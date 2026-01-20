import asyncio
import logging
import os
import sys
import time
# import aiohttp
from datetime import datetime, timezone
from typing import List, Dict, Optional

import requests
from asgiref.sync import sync_to_async

import django
from django.utils import timezone as django_timezone

from realtime_monitor.utils.utils import _handle_conversations
from common.wechat_bot import send_wechat_message
from linkedin_realtime_monitor.settings import WechatRobotKey

# 项目根目录路径（根据你的实际结构调整）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin_realtime_monitor.settings")  # 替换成你的 settings 路径
django.setup()

from lkp_client_base_utils.lkp_client_base import LKPClientBase
from realtime_monitor.models import RealtimeConnection, RealtimeConversation, MonitorAccount
from realtime_monitor.core.db_health_check import db_health_checker


class DataCrawler:
    """数据抓取器"""

    def __init__(self, account_id: str):
        self.account_id = account_id

    async def crawl_connections(self, page, max_pages: Optional[int] = None) -> int:
        """抓取好友列表（使用 get_connections_v2 接口）

        Args:
            page: Playwright page 对象
            max_pages: 最大翻页次数，None 表示不限制（保持原有逻辑）

        Returns:
            int: 新增好友数量
        """
        logging.info(f"Crawling connections for {self.account_id}, max_pages={max_pages}")

        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            logging.error(f"Database connection not available for crawl_connections")
            return 0

        # 获取账号信息
        account = await MonitorAccount.objects.aget(id=int(self.account_id))
        sender_email = account.email

        # 初始化 LKPClient
        lkpc = LKPClientBase('prod')

        # 获取数据库中最新的好友 hash_id（用于去重）
        latest_hash_id = await self._get_latest_connection_profile_id()

        start = 0
        count = 40
        raw_connections_data = []
        should_stop = False
        current_page = 0

        # 循环获取所有新好友
        while not should_stop:
            try:

                # 调用 LinkedIn get_connections_v2 API
                lk_connections_data = lkpc.make_a_linked_in_request(
                    sender_email,
                    category='extended',
                    method_name='get_connections_v2',
                    params={"start": start, 'count': count}
                )

                if not lk_connections_data:
                    logging.warning(f"API 返回空数据: start={start}, count={count}")
                    break

                connections_data = lk_connections_data.get('elements', [])

                if not connections_data:
                    logging.info(f"没有更多连接数据，停止请求")
                    break

                # 检查去重：如果遇到已存在的好友，停止
                for conn_info in connections_data:
                    profile_dict = conn_info.get('connectedMemberResolutionResult', {})
                    if profile_dict:
                        entity_urn = profile_dict.get('entityUrn', '')
                        hash_id = entity_urn.split(':')[-1] if entity_urn else None

                        # 遇到已存在的好友，停止
                        if hash_id == latest_hash_id:
                            should_stop = True
                            break

                        raw_connections_data.append(conn_info)

                if should_stop:
                    break

                # 如果返回的数据少于请求的数量，说明没有更多数据了
                if len(connections_data) < count:
                    logging.info(f"返回数据少于请求数量 ({len(connections_data)} < {count})，停止请求")
                    break

                # 检查是否达到最大翻页次数限制
                current_page += 1
                if max_pages is not None and current_page >= max_pages:
                    logging.info(f"达到最大翻页次数限制 ({current_page} >= {max_pages})，停止请求")
                    break

                start += count
                await asyncio.sleep(2)  # 分页间隔

            except Exception as e:
                logging.error(f"获取连接数据失败: {e}", exc_info=True)
                break

        if raw_connections_data:
            # 批量查询 member_id（优化性能）

            # 解析 connections 数据
            parsed_connections = []

            for connection_info in raw_connections_data:
                try:
                    conn_data = self._parse_connection_data(connection_info)
                    if conn_data:
                        parsed_connections.append(conn_data)
                except Exception as e:
                    logging.warning(f"解析连接数据失败: {str(e)}")
                    continue

            # 保存到数据库
            if parsed_connections:
                saved_connections = await self._save_connections_v2(parsed_connections)
                logging.info(f"Saved {len(saved_connections)} new connections")

                # 通知 Business 方
                notification_success = await self._notify_business_conversations(saved_connections, 'my_network')

                # 如果通知成功，清除 My Network 红点
                if notification_success:
                    await self._clear_notification(page, notification_source='my_network')
            else:
                logging.info(f"No new connections found after parsing")
        else:
            logging.info(f"No new connections data retrieved from API")
            await self._clear_notification(page, notification_source='my_network')
            parsed_connections = []
        return len(parsed_connections)

    async def crawl_conversations(self, page) -> int:
        """抓取对话列表

        优化策略：
        1. 先获取DB中当前账号的最大消息时间作为基准
        2. 请求第一页后，检查最后一条的时间
        3. 只处理和保存时间 > DB基准时间的对话
        4. 如果最后一条时间 ≤ DB基准时间，停止翻页

        使用 conversations_by_sync_token（第一页）和 conversations_by_category（翻页）接口
        LinkedIn 按 last_message_delivered_at 从大到小（降序）返回对话

        Returns:
            int: 更新的对话数量
        """
        logging.info(f"Crawling conversations for {self.account_id}")

        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            logging.error(f"Database connection not available for crawl_conversations")
            return 0

        # 获取账号信息，用于调用 LKP 接口
        account = await MonitorAccount.objects.aget(id=int(self.account_id))
        sender_email = account.email
        hash_id = account.hash_id

        lkpc = LKPClientBase('prod')

        # ⚡ 关键优化：先获取DB中当前账号的最大消息时间
        db_max_time = await self._get_max_message_time()
        logging.info(f"DB max message time: {db_max_time}")

        if not hash_id:
            try:
                connection_response = lkpc.make_a_linked_in_request(sender_email, 'extended', 'connection_summary', {})
                entity_urn = connection_response.get('entityUrn', "") if connection_response else ""
                hash_id = entity_urn.split(":")[-1] if entity_urn else ""
                if hash_id:
                    account.hash_id = hash_id
                    await sync_to_async(account.save)()
            except Exception as e:
                logging.error(f"Failed to fetch hash_id for account {self.account_id}: {e}", exc_info=True)
                # 如果获取 hash_id 失败，继续尝试使用空的 hash_id（可能会在后续失败）

        if not hash_id:
            logging.warning(f"Account {self.account_id} has no hash_id, skipping conversation crawl")
            return 0

        all_messages = []

        # 循环请求多页数据, 每页20条， 最多10页
        for page_num in range(10):
            try:
                if page_num == 0:
                    # 第一页：使用 conversations_by_sync_token
                    response = lkpc.make_a_linked_in_request(
                        sender_email,
                        category='extended',
                        method_name='conversations_by_sync_token',
                        params={'fsd_profile': hash_id}
                    )
                else:
                    # 翻页：使用 conversations_by_category
                    # 从上一页最后一条消息获取 last_activity_at
                    if not all_messages:
                        break  # 如果上一页没有数据，停止翻页

                    last_message = all_messages[-1]
                    last_activity_at_iso = last_message.get('last_activity_at')

                    if not last_activity_at_iso:
                        break  # 如果没有 last_activity_at，无法翻页

                    # 将 ISO 格式字符串转换回时间戳（毫秒级）用于 API 请求
                    try:
                        # 解析 ISO 格式字符串为 datetime 对象
                        dt = datetime.fromisoformat(last_activity_at_iso.replace('Z', '+00:00'))
                        # 确保有时区信息
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)

                        # 如果数据库中的最大时间不为空，且当前时间小于等于最大时间，停止翻页
                        # 确保 db_max_time 也有时区信息进行比较
                        if db_max_time:
                            # 如果 db_max_time 没有时区信息，添加 UTC 时区
                            if db_max_time.tzinfo is None:
                                db_max_time_utc = db_max_time.replace(tzinfo=timezone.utc)
                            else:
                                db_max_time_utc = db_max_time
                            
                            if dt <= db_max_time_utc:
                                logging.info(
                                    f"🛑 Last conversation time ({dt}) ≤ DB max time ({db_max_time_utc}), "
                                    f"stopping pagination at page {page_num}"
                                )
                                break

                        # 转换为毫秒级时间戳
                        last_activity_at_timestamp = int(dt.timestamp() * 1000)
                    except (ValueError, AttributeError) as e:
                        logging.warning(f"Failed to parse last_activity_at for pagination: {e}")
                        break  # 如果解析失败，停止翻页

                    response = lkpc.make_a_linked_in_request(
                        sender_email,
                        category='extended',
                        method_name='conversations_by_category',
                        params={
                            'fsd_profile': hash_id,
                            'last_activity_at': last_activity_at_timestamp
                        }
                    )
            except Exception as e:
                logging.error(f"Failed to fetch conversations page {page_num}: {e}", exc_info=True)
                break  # API 调用失败，停止翻页

            # 解析响应数据
            if not response:
                break  # 如果响应为空，停止翻页

            # 提取对话列表
            # 处理不同的响应结构：可能是 {'json': {...}} 或 {'data': {...}}
            conversation_data = response.get('json', {}) or response.get('data', {})
            data_section = conversation_data.get('data', conversation_data)

            # 尝试从不同的字段获取 elements
            if page_num == 0:
                # 第一页使用 messengerConversationsBySyncToken
                data_node = data_section.get('messengerConversationsBySyncToken', {})
                elements = data_node.get('elements', [])
            else:
                # 翻页使用 conversations_by_category
                # 翻页后的响应结构可能不同，尝试多种可能的路径
                data_node = data_section.get('messengerConversationsByCategory', {}) or \
                            data_section.get('messengerConversationsBySyncToken', {})
                elements = data_node.get('elements', [])

                # 如果 elements 为空，可能是直接返回对话项列表
                if not elements and isinstance(data_section, list):
                    elements = data_section
                elif not elements and isinstance(data_node, list):
                    elements = data_node

            if not elements:
                break  # 如果当前页没有数据，停止翻页

            # 使用 sync_to_async 包装同步函数调用，避免在异步上下文中直接调用同步数据库操作
            current_messages = await sync_to_async(_handle_conversations)(elements, hash_id)
            all_messages += current_messages

        logging.info('all_messages: {}'.format(len(all_messages)))
        # 处理 all_messages，获取最新的对话消息，只新增或更新 last_activity_at > db_max_time 的对话
        # 保存到数据库
        updated_count, updated_convs = await self._save_conversations_from_all_messages(
            all_messages,
            db_max_time
        )
        total_updated = updated_count
        all_updated_conversations = updated_convs

        # 通知 Business 方
        if all_updated_conversations:
            notification_success = await self._notify_business_conversations(all_updated_conversations, 'message')

            # 如果通知成功，清除 message 红点
            if notification_success:
                await self._clear_notification(page, notification_source='message')
        else:
            logging.info(f"No new or updated conversations to notify")
            await self._clear_notification(page, notification_source='message')

        logging.info(f"Processed {total_updated} conversations for {self.account_id}")
        return total_updated

    async def _save_conversations_from_all_messages(
            self,
            all_messages: List[dict],
            db_max_time: Optional[datetime]
    ) -> tuple[int, List[dict]]:
        """从 all_messages 中保存对话数据到数据库

        根据注释中的数据结构，处理 _handle_conversations 返回的格式化数据

        Args:
            all_messages: _handle_conversations 返回的格式化对话列表
            db_max_time: 数据库中当前账号的最大 last_activity_at 时间（基准时间）

        Returns:
            tuple[int, List[dict]]: (更新的对话数量, 更新的对话数据列表)
        """
        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            logging.error(f"Database connection not available for saving conversations")
            return 0, []
        
        updated_count = 0
        updated_conversations: List[dict] = []
        account = await MonitorAccount.objects.aget(id=int(self.account_id))

        for msg in all_messages:
            try:

                hash_id = msg.get('hash_id', '')

                # 解析时间字段（ISO 格式字符串 -> datetime）
                last_activity_at_str = msg.get('last_activity_at')
                if not last_activity_at_str:
                    logging.warning(f"Conversation {hash_id} missing last_activity_at, skipping")
                    continue

                # 将 ISO 格式字符串转换为 datetime 对象
                try:
                    last_activity_at = datetime.fromisoformat(
                        last_activity_at_str.replace('Z', '+00:00')
                    )
                    # 确保有时区信息
                    if last_activity_at.tzinfo is None:
                        last_activity_at = last_activity_at.replace(tzinfo=timezone.utc)
                except (ValueError, AttributeError) as e:
                    logging.warning(f"Failed to parse last_activity_at for {hash_id}: {e}")
                    continue

                # 关键过滤：只处理时间 > db_max_time 的对话
                if db_max_time and last_activity_at <= db_max_time:
                    logging.debug(
                        f"⏭️ Skipping old conversation: {hash_id} "
                        f"(API: {last_activity_at} ≤ DB: {db_max_time})"
                    )
                    continue  # 跳过旧对话

                # 解析其他时间字段
                created_at = None
                if msg.get('created_at'):
                    try:
                        created_at = datetime.fromisoformat(
                            msg['created_at'].replace('Z', '+00:00')
                        )
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        pass

                last_read_at = None
                if msg.get('last_read_at'):
                    try:
                        last_read_at = datetime.fromisoformat(
                            msg['last_read_at'].replace('Z', '+00:00')
                        )
                        if last_read_at.tzinfo is None:
                            last_read_at = last_read_at.replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        pass

                # 解析最后一条消息的时间
                last_message = msg.get('last_message', {})
                last_message_delivered_at = None
                if last_message.get('delivered_at'):
                    try:
                        last_message_delivered_at = datetime.fromisoformat(
                            last_message['delivered_at'].replace('Z', '+00:00')
                        )
                        if last_message_delivered_at.tzinfo is None:
                            last_message_delivered_at = last_message_delivered_at.replace(tzinfo=timezone.utc)
                    except (ValueError, AttributeError):
                        pass
                # 查询数据库中是否已存在该对话（基于 account 和 hash_id 一起做唯一性判断）
                existing_conv = await RealtimeConversation.objects.filter(
                    account=account,
                    hash_id=hash_id
                ).afirst()

                # 准备对话数据
                conv_data = {
                    'hash_id': hash_id,
                    'conversation_id': msg.get('conversation_id', ''),
                    'public_id': msg.get('public_id', ''),
                    'member_id': msg.get('member_id', ''),
                    'conversation_url': msg.get('conversation_url', ''),
                    'first_name': msg.get('first_name', ''),
                    'last_name': msg.get('last_name', ''),
                    'distance': msg.get('distance', ''),
                    'unread_count': msg.get('unread_count', 0),
                    'dialogue_created_at': created_at,
                    'last_activity_at': last_activity_at,
                    'last_read_at': last_read_at,
                    'is_group_chat': msg.get('is_group_chat', False),
                    'last_message_text': last_message.get('text', ''),
                    'last_message_sender': last_message.get('sender', ''),
                    'last_message_delivered_at': last_message_delivered_at,
                    'source': msg.get('source', 'original'),
                }

                if existing_conv is None:
                    # 不存在，创建新对话
                    # 注意：hash_id 已经在 conv_data 中，不需要单独传递
                    await RealtimeConversation.objects.acreate(
                        account=account,
                        **conv_data
                    )
                    logging.info(f"✅ Created new conversation: {hash_id}")
                    updated_count += 1
                    updated_conversations.append(conv_data)
                else:
                    # 已存在，更新对话信息
                    existing_conv.conversation_id = conv_data['conversation_id']
                    existing_conv.public_id = conv_data['public_id']
                    existing_conv.member_id = conv_data['member_id']
                    existing_conv.conversation_url = conv_data['conversation_url']
                    existing_conv.first_name = conv_data['first_name']
                    existing_conv.last_name = conv_data['last_name']
                    existing_conv.distance = conv_data['distance']
                    existing_conv.unread_count = conv_data['unread_count']
                    existing_conv.dialogue_created_at = conv_data['dialogue_created_at']
                    existing_conv.last_activity_at = conv_data['last_activity_at']
                    existing_conv.last_read_at = conv_data['last_read_at']
                    existing_conv.is_group_chat = conv_data['is_group_chat']
                    existing_conv.last_message_text = conv_data['last_message_text']
                    existing_conv.last_message_sender = conv_data['last_message_sender']
                    existing_conv.last_message_delivered_at = conv_data['last_message_delivered_at']
                    existing_conv.source = conv_data['source']

                    # 使用 sync_to_async 包装同步的 save() 方法
                    await sync_to_async(existing_conv.save)()
                    logging.info(
                        f"✅ Updated conversation: {hash_id} "
                        f"(last_activity_at: {last_activity_at})"
                    )
                    updated_count += 1
                    updated_conversations.append(conv_data)

            except Exception as e:
                logging.error(f"Error processing conversation: {e}", exc_info=True)
                continue

        return updated_count, updated_conversations

    async def _get_max_message_time(self) -> Optional[datetime]:
        """获取当前账号在数据库中的最大消息时间

        用作基准时间，只处理比这个时间更新的对话

        Returns:
            Optional[datetime]: 最大消息时间，如果没有记录则返回 None
        """
        from django.db.models import Max

        # 注意：RealtimeConversation 中的外键字段名为 account（db_column='account_id'），
        # 查询时应使用 account_id 或 account__id，而不是 account__account_id
        try:
            account_id = int(self.account_id)
        except (TypeError, ValueError):
            account_id = self.account_id

        result = await RealtimeConversation.objects.filter(
            account_id=account_id
        ).aaggregate(max_time=Max('last_activity_at'))

        max_time = result.get('max_time')
        return max_time

    async def _fetch_api(self, page, url: str, max_retries: int = 3) -> dict:
        """调用 LinkedIn API（带重试）"""
        for attempt in range(max_retries):
            try:
                response = await page.evaluate(
                    f"""
                    async () => {{
                        const response = await fetch('{url}', {{
                            credentials: 'include'
                        }});
                        return await response.json();
                    }}
                    """
                )
                return response

            except Exception as e:
                wait_time = (2 ** attempt) * 1
                logging.error(f"API fetch error (attempt {attempt + 1}): {e}")

                if attempt < max_retries - 1:
                    await asyncio.sleep(wait_time)
                    return {}
                else:
                    raise
        return {}

    async def _get_latest_connection_profile_id(self) -> Optional[str]:
        """获取最新的好友 Profile ID（基于 hash_id 去重）"""
        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            logging.warning(f"Database connection not available for getting latest connection")
            return None
        
        account = await MonitorAccount.objects.aget(id=int(self.account_id))
        latest = await RealtimeConnection.objects.filter(
            account=account
        ).order_by('-connected_at').afirst()

        return latest.hash_id if latest else None

    async def _save_connections(self, connections: List[dict]) -> List[dict]:
        """批量保存好友数据

        Returns:
            List[dict]: 保存的好友数据列表
        """
        objects = []
        saved_data = []

        for conn in connections:
            conn_data = {
                'account_id': self.account_id,
                'profile_id': self._extract_profile_id(conn),
                'profile_urn': conn.get('entityUrn'),
                'full_name': self._extract_name(conn),
                'headline': self._extract_headline(conn),
                'connected_at': self._parse_timestamp(conn.get('createdAt'))
            }

            objects.append(RealtimeConnection(**conn_data))
            saved_data.append(conn_data)  # 收集保存的数据

        await RealtimeConnection.objects.abulk_create(
            objects,
            ignore_conflicts=True
        )

        return saved_data

    @staticmethod
    def _extract_profile_id(conn: dict) -> str:
        """提取 Profile ID"""
        return conn.get('entityUrn', '').split(':')[-1]

    @staticmethod
    def _extract_name(conn: dict) -> str:
        """提取姓名"""
        # 根据实际 API 响应结构提取
        return conn.get('connectedMember', {}).get('firstName', '') + ' ' + \
            conn.get('connectedMember', {}).get('lastName', '')

    @staticmethod
    def _extract_headline(conn: dict) -> str:
        """提取标题"""
        return conn.get('connectedMember', {}).get('headline', '')

    @staticmethod
    def _parse_timestamp(ts) -> Optional[datetime]:
        """解析时间戳"""
        if not ts:
            return None
        return datetime.fromtimestamp(ts / 1000)  # LinkedIn 使用毫秒时间戳

    @staticmethod
    def _normalize_timestamp_to_utc(timestamp: Optional[int]) -> Optional[int]:
        """
        将时间戳规范化为 UTC+0 时间戳（毫秒级）

        Args:
            timestamp: 时间戳（可能是秒级或毫秒级，必须是 UTC 时间戳）

        Returns:
            UTC+0 的毫秒级时间戳，如果输入无效返回 None
        """
        if timestamp is None or timestamp == 0:
            return None

        try:
            # 判断是毫秒级还是秒级时间戳
            if timestamp > 1e10:
                # 毫秒级时间戳，直接返回
                return int(timestamp)
            else:
                # 秒级时间戳，转换为毫秒级
                return int(timestamp * 1000)
        except (ValueError, TypeError, OverflowError):
            return None

    @staticmethod
    def _timestamp_to_iso_utc(timestamp: Optional[int]) -> Optional[str]:
        """
        将时间戳转换为 ISO 8601 格式的 UTC+0 时间字符串

        Args:
            timestamp: 时间戳（可能是秒级或毫秒级，必须是 UTC 时间戳）

        Returns:
            ISO 8601 格式的时间字符串，例如：'2025-09-24T06:44:22+00:00'
            如果输入无效返回 None
        """
        if timestamp is None or timestamp == 0:
            return None

        try:
            # 规范化时间戳为毫秒级
            normalized = DataCrawler._normalize_timestamp_to_utc(timestamp)
            if normalized is None:
                return None

            # 转换为秒级时间戳
            time_int = normalized / 1000

            # 转换为 UTC 时间的 datetime 对象
            dt = datetime.fromtimestamp(time_int, tz=timezone.utc)

            # 格式化为 ISO 8601 格式，确保使用 +00:00 而不是 Z
            iso_str = dt.isoformat()
            # 将 Z 替换为 +00:00 以确保格式统一
            if iso_str.endswith('Z'):
                iso_str = iso_str[:-1] + '+00:00'
            # 如果没有时区信息，添加 +00:00
            elif '+' not in iso_str and '-' not in iso_str[-6:]:
                iso_str = iso_str + '+00:00'

            return iso_str
        except (ValueError, TypeError, OverflowError, OSError):
            return None

    def _parse_connection_data(self, connection_info: Dict) -> Optional[Dict]:
        """
        解析单个连接数据（与 linkedin_interaction.py 保持一致）

        Args:
            connection_info: LinkedIn API 返回的连接信息

        Returns:
            格式化的连接数据字典，如果解析失败返回 None
        """
        profile_dict = connection_info.get('connectedMemberResolutionResult', {})
        if not profile_dict:
            return None

        # 提取基本信息
        public_id = profile_dict.get('publicIdentifier')
        first_name = profile_dict.get('firstName')
        last_name = profile_dict.get('lastName')
        headline = profile_dict.get('headline')

        # 提取 hash_id
        entity_urn = profile_dict.get('entityUrn', '')
        hash_id = entity_urn.split(':')[-1] if entity_urn else None

        # 提取连接时间
        created_at = connection_info.get('createdAt')
        connected_at = None
        if created_at:
            if isinstance(created_at, int):
                # 将时间戳转换为 ISO 8601 格式的 UTC+0 时间字符串
                connected_at = self._timestamp_to_iso_utc(created_at)
            elif isinstance(created_at, str):
                # 如果已经是字符串，尝试解析并确保是 UTC+0 格式
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    if dt.tzinfo is None:
                        # 如果没有时区信息，假设是 UTC
                        dt = dt.replace(tzinfo=timezone.utc)
                    connected_at = dt.isoformat()
                except (ValueError, AttributeError):
                    connected_at = created_at

        # 构建返回数据
        return {
            'first_name': first_name,
            'last_name': last_name,
            'headline': headline,
            'public_id': public_id,
            'hash_id': hash_id,
            'connected_at': connected_at,
        }

    async def _save_connections_v2(self, connections: List[dict]) -> List[dict]:
        """批量保存好友数据（使用新的数据结构）

        Returns:
            List[dict]: 保存的好友数据列表
        """
        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            logging.error(f"Database connection not available for saving connections")
            return []
        
        # 获取 account 对象
        account = await MonitorAccount.objects.aget(id=int(self.account_id))

        objects = []
        saved_data = []

        for conn_data in connections:
            # 转换 connected_at 字符串为 datetime 对象
            connected_at = None
            if conn_data.get('connected_at'):
                try:
                    connected_at_str = conn_data['connected_at']
                    if isinstance(connected_at_str, str):
                        # 解析 ISO 8601 格式的字符串
                        connected_at = datetime.fromisoformat(
                            connected_at_str.replace('Z', '+00:00'))
                    elif isinstance(connected_at_str, datetime):
                        connected_at = connected_at_str
                except (ValueError, AttributeError):
                    logging.warning(
                        f"Failed to parse connected_at: {conn_data.get('connected_at')}")

            conn_obj = RealtimeConnection(
                account=account,
                first_name=conn_data.get('first_name'),
                last_name=conn_data.get('last_name'),
                headline=conn_data.get('headline'),
                public_id=conn_data.get('public_id'),
                hash_id=conn_data.get('hash_id'),
                member_id=conn_data.get('member_id'),
                source=conn_data.get('source', 'original'),
                connected_at=connected_at or django_timezone.now()
            )
            objects.append(conn_obj)
            saved_data.append(conn_data)

        # 使用 bulk_create 批量保存，忽略冲突（基于 unique_together: account + member_id）
        await sync_to_async(RealtimeConnection.objects.bulk_create)(
            objects,
            ignore_conflicts=True
        )

        return saved_data

    async def _clear_notification(self, page, notification_source: str):
        """清除红点（通过导航到目标页面）

        Args:
            page: Playwright page 对象
            notification_source: 'my_network' 或 'message'，决定跳转到哪个页面
        """
        try:
            logging.info(f'开始清除红点: {notification_source}')
            
            # 确定目标 URL（直接导航，避免重定向问题）
            if notification_source == 'my_network':
                target_url = 'https://www.linkedin.com/mynetwork/grow/'
                wait_selector = 'button[aria-label*="Connect"]'  # Grow 页面的特征元素
                wait_description = "Connect button on Grow page"
            else:
                target_url = 'https://www.linkedin.com/messaging/'
                wait_selector = 'div[class*="msg-conversations-container"]'
                wait_description = "Messaging conversations container"
            
            # 直接导航到目标页面
            try:
                logging.info(f"Navigating to {target_url}")
                await page.goto(target_url, timeout=60000)
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                logging.info(f"✅ Navigated to {target_url}")
            except Exception as nav_err:
                logging.error(f"❌ Failed to navigate to {target_url}: {nav_err}")
                pass
            
            # 等待页面特征元素加载（确认页面加载成功）
            try:
                await page.wait_for_selector(wait_selector, timeout=10000)
                logging.info(f"✅ Page loaded successfully (found {wait_description})")
            except Exception as wait_err:
                # 即使找不到特征元素，也继续（页面可能已加载，只是元素结构变了）
                logging.warning(
                    f"⚠️ Timeout waiting for {wait_description}: {wait_err}. "
                    f"Page might still be loaded, continuing..."
                )
            
            # 等待一下，确保红点被清除
            await asyncio.sleep(2)
            
            # 验证当前 URL（调试用）
            current_url = page.url
            logging.info(f"Current URL after navigation: {current_url}")
            
            # 返回 Feed 页面
            try:
                logging.info("Navigating back to Feed page")
                await page.goto("https://www.linkedin.com/feed/", timeout=60000)
                await page.wait_for_load_state('domcontentloaded', timeout=10000)
                logging.info("✅ Navigated back to Feed page after clearing notification")
            except Exception as nav_err:
                logging.error(f"❌ Failed to navigate back to Feed page: {nav_err}")

        except Exception as e:
            logging.error(
                f"❌ Error clearing {notification_source} notification: {e}",
                exc_info=True
            )

    async def _notify_business_conversations(self, data: List[dict], source: str):
        """通知使用方：对话更新数据

        Args:
            data: 更新的对话/好友数据列表
            source: 数据源类型 ('message' 或其他)
        """
        if not data:
            return False

        # 从配置中获取 Callback 接口 URL（使用 sync_to_async 避免阻塞事件循环）
        try:
            account_model = await MonitorAccount.objects.aget(id=int(self.account_id))
            callback_url = account_model.callback_url
            callback_token = account_model.callback_token
            hash_id = account_model.hash_id
            
            # 构建请求头
            callback_headers = {
                "Content-Type": "application/json"
            }
            if callback_token:
                callback_headers["X-Callback-Token"] = callback_token
        except MonitorAccount.DoesNotExist:
            logging.error(f"账号ID：{self.account_id} 不存在")
            return False
        
        # 准备通知数据（需要序列化 datetime 对象）
        def serialize_value(value):
            """递归序列化值，将 datetime 对象转换为 ISO 格式字符串"""
            if isinstance(value, datetime):
                return value.isoformat()
            elif isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                return [serialize_value(item) for item in value]
            else:
                return value
        
        def serialize_data(data_list):
            """序列化数据列表，处理所有层级的 datetime 对象"""
            return [serialize_value(item) for item in data_list]
        
        serialized_data = serialize_data(data)
        
        if source == 'message':
            json_data = {'conversations': serialized_data, 'profile_id': hash_id, 'type':'conversations'}
            notify_type = '消息列表'
        else:
            json_data = {'connections': serialized_data, 'profile_id': hash_id, 'type':'connections'}
            notify_type = '好友列表'
        
        # 数据量检查（如果数据量很大，记录警告）
        if len(data) > 100:
            logging.warning(
                f"准备发送大量数据到 Callback URL，"
                f"数据量：{len(data)} 条，可能导致请求超时或失败"
            )
        
        # 如果配置了回调 URL，尝试通知
        if callback_url:
            # 记录请求信息（用于调试）
            logging.info(
                f"准备通知 Business 方{notify_type}数据，"
                f"URL: {callback_url}，"
                f"数据量: {len(data)} 条，"
                f"是否包含 Token: {bool(callback_token)}"
            )
            
            for retry in range(5):
                try:
                    # 使用异步 HTTP 请求（避免阻塞事件循环）
                    loop = asyncio.get_running_loop()
                    
                    # 在 executor 中执行请求（包含 JSON 序列化）
                    def make_request():
                        try:
                            return requests.post(
                                callback_url, 
                                json=json_data, 
                                headers=callback_headers,
                                timeout=10
                            )
                        except (TypeError, ValueError) as json_err:
                            # 捕获 JSON 序列化错误
                            logging.error(
                                f"JSON 序列化失败: {json_err}，"
                                f"数据类型检查：{type(json_data)}",
                                exc_info=True
                            )
                            raise
                    
                    response = await loop.run_in_executor(None, make_request)
                    
                    if 200 <= response.status_code < 300:
                        logging.info(
                            f"通知 Business 方{notify_type}数据更新成功，"
                            f"账号ID：{self.account_id}，更新数量：{len(data)}"
                        )
                        return True
                    else:
                        # 尝试获取响应内容用于调试
                        try:
                            response_text = response.text[:500]  # 只记录前500字符
                        except Exception as text_err:
                            response_text = f"无法获取响应内容: {text_err}"
                        
                        logging.warning(
                            f"通知 Business 方失败，状态码：{response.status_code}，"
                            f"响应内容：{response_text}，"
                            f"重试次数：{retry + 1}/5"
                        )
                except requests.exceptions.Timeout as e:
                    logging.error(
                        f"通知 Business 方超时：{e}，重试次数：{retry + 1}/5",
                        exc_info=True
                    )
                except requests.exceptions.ConnectionError as e:
                    logging.error(
                        f"通知 Business 方连接错误：{e}，重试次数：{retry + 1}/5",
                        exc_info=True
                    )
                except requests.exceptions.RequestException as e:
                    logging.error(
                        f"通知 Business 方请求异常：{e}，重试次数：{retry + 1}/5",
                        exc_info=True
                    )
                except Exception as e:
                    logging.error(
                        f"通知 Business 方未知异常：{e}，重试次数：{retry + 1}/5",
                        exc_info=True
                    )
                
                # 如果不是最后一次重试，等待后重试
                if retry < 4:
                    await asyncio.sleep(5)  # 使用异步 sleep
            
            # 所有重试失败，发送告警
            logging.error(
                f"通知 Business 方{notify_type}数据更新失败（5次重试均失败），"
                f"账号ID：{self.account_id}，更新数量：{len(data)}"
            )
            await sync_to_async(send_wechat_message)(
                f'数据监控-{notify_type}数据更新通知失败，'
                f'账号ID：{self.account_id}，更新数量：{len(data)}',
                key=WechatRobotKey.TEST_WECHAT_ROBOT_KEY.value
            )
            return False
        else:
            # 未配置回调 URL，发送微信通知
            logging.warning(f"账号ID：{self.account_id} 未配置 callback_url")
            await sync_to_async(send_wechat_message)(
                f'数据监控-{notify_type}数据更新通知（未配置回调URL），'
                f'账号ID：{self.account_id}，更新数量：{len(data)}',
                key=WechatRobotKey.TEST_WECHAT_ROBOT_KEY.value
            )
            return False
