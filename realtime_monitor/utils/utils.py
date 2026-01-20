import logging
from datetime import datetime, timezone
from typing import Optional

from django.db.models import Q

logger = logging.getLogger(__name__)

def _normalize_timestamp_to_utc(timestamp: Optional[int]) -> Optional[int]:
    """
    将时间戳规范化为 UTC+0 时间戳（毫秒级）

    Unix 时间戳本身就是 UTC 时间，此函数确保时间戳格式统一为毫秒级 UTC+0 时间戳。

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
            # 毫秒级时间戳，直接返回（LinkedIn API 返回的通常是 UTC 毫秒级时间戳）
            return int(timestamp)
        else:
            # 秒级时间戳，转换为毫秒级
            return int(timestamp * 1000)
    except (ValueError, TypeError, OverflowError):
        return None


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
        normalized = _normalize_timestamp_to_utc(timestamp)
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


def _handle_conversations(elements: list, sender_hash_id: str):
    all_messages = []
    # 批量查询参与者信息（优化性能）
    participant_hash_ids = []
    participant_public_ids = []
    for item in elements:
        if not isinstance(item, dict):
            continue
        participants = item.get('conversationParticipants', [])
        for participant in participants:
            host_identity_urn = participant.get('hostIdentityUrn', '')
            if 'urn:li:fsd_profile:' in host_identity_urn:
                participant_hash_id = host_identity_urn.split('urn:li:fsd_profile:')[-1].split(')')[0].split(',')[0]
                if participant_hash_id != sender_hash_id:
                    participant_hash_ids.append(participant_hash_id)
                    # 从 participant 中提取 public_id（如果有）
                    public_id = participant.get('publicIdentifier', '')
                    if not public_id:
                        # 尝试从 participantType.member.profileUrl 中提取
                        participant_type = participant.get('participantType', {})
                        member_info = participant_type.get('member', {})
                        profile_url = member_info.get('profileUrl', '')
                        if profile_url and '/in/' in profile_url:
                            public_id = profile_url.split('/in/')[-1].split('/')[0].split('?')[0]
                    if public_id:
                        participant_public_ids.append(public_id)

    for item in elements:
        if not item:
            continue
        conversation_urn = item.get('entityUrn', '')
        # 将时间戳转换为 ISO 8601 格式的 UTC+0 时间字符串
        last_activity_at_value = _timestamp_to_iso_utc(item.get('lastActivityAt'))
        unread_count = item.get('unreadCount', 0)
        created_at = _timestamp_to_iso_utc(item.get('createdAt'))
        last_read_at = _timestamp_to_iso_utc(item.get('lastReadAt'))
        is_group_chat = item.get('groupChat', False)
        conversation_url = item.get('conversationUrl', '')

        # 提取最后一条消息（从 messages.elements 中获取）
        messages_data = item.get('messages', {})
        messages_elements = messages_data.get('elements', []) if messages_data else []
        last_message_text = ''
        last_message_delivered_at = None
        last_message_sender = 'You'

        if messages_elements:
            # 获取最后一条消息（通常是第一条，因为可能按时间倒序）
            last_msg = messages_elements[0] if messages_elements else {}
            last_message_text = last_msg.get('body', {}).get('text', '') if last_msg.get('body') else ''
            last_message_delivered_at = _timestamp_to_iso_utc(last_msg.get('deliveredAt'))

            # 判断发送者：优先使用 actor，如果没有则使用 sender
            try:
                actor = last_msg.get('actor', {})
                if not actor:
                    # 如果 actor 不存在，尝试使用 sender
                    actor = last_msg.get('sender', {})

                actor_urn = actor.get('hostIdentityUrn', '') if actor else ''
                if 'urn:li:fsd_profile:' in actor_urn:
                    actor_hash_id = actor_urn.split('urn:li:fsd_profile:')[-1].split(')')[0].split(',')[0]
                    if actor_hash_id != sender_hash_id:
                        # 不是发送者，获取对方全名
                        participant_type = actor.get('participantType', {})
                        member_info = participant_type.get('member', {}) if participant_type else {}
                        actor_first_name_obj = member_info.get('firstName', {})
                        actor_last_name_obj = member_info.get('lastName', {})
                        actor_first_name = actor_first_name_obj.get('text', '') if isinstance(
                            actor_first_name_obj, dict) else ''
                        actor_last_name = actor_last_name_obj.get('text', '') if isinstance(actor_last_name_obj,
                                                                                            dict) else ''
                        last_message_sender = f"{actor_first_name} {actor_last_name}".strip() or 'Unknown'
            except Exception as e:
                logger.warning(f"解析消息发送者失败: {str(e)}")
                # 如果解析失败，保持默认值 'You'

        # 提取参与者信息（非发送方）
        participants = item.get('conversationParticipants', [])
        first_name = ''
        last_name = ''
        headline = ''
        distance = ''
        participant_hash_id = None
        participant_public_id = ''
        source = 'original'
        participant_member_id = None
        if participants:
            # 获取非发送方的参与者
            for participant in participants:
                host_identity_urn = participant.get('hostIdentityUrn', '')
                backend_urn = participant.get('backendUrn', '')

                # 从 backendUrn 提取 member_id
                if backend_urn and 'urn:li:member:' in backend_urn:
                    participant_member_id = backend_urn.split('urn:li:member:')[-1].split(',')[0]

                if 'urn:li:fsd_profile:' in host_identity_urn:
                    participant_hash_id = host_identity_urn.split('urn:li:fsd_profile:')[-1].split(')')[0].split(',')[0]
                    if participant_hash_id != sender_hash_id:
                        # 提取参与者基本信息
                        participant_type = participant.get('participantType', {})
                        member_info = participant_type.get('member', {}) if participant_type else {}

                        # 提取姓名
                        first_name_obj = member_info.get('firstName', {})
                        last_name_obj = member_info.get('lastName', {})
                        first_name = first_name_obj.get('text', '') if isinstance(first_name_obj, dict) else ''
                        last_name = last_name_obj.get('text', '') if isinstance(last_name_obj, dict) else ''

                        # 提取 headline
                        headline_obj = member_info.get('headline', {})
                        headline = headline_obj.get('text', '') if isinstance(headline_obj, dict) else ''

                        # 提取 distance
                        distance = member_info.get('distance', '')

                        # 提取 public_id：优先从 participant 中获取，其次从数据库查询
                        participant_public_id = participant.get('publicIdentifier', '')
                        if not participant_public_id:
                            # 尝试从 profileUrl 中提取
                            profile_url = member_info.get('profileUrl', '')
                            if profile_url and '/in/' in profile_url:
                                participant_public_id = profile_url.split('/in/')[-1].split('/')[0].split('?')[0]
                        break

        message_item = {
            'first_name': first_name,
            'last_name': last_name,
            'headline': headline,
            'distance': distance,
            'hash_id': participant_hash_id,  # 参与者的 hash_id（用于查询数据库）
            'public_id': participant_public_id,
            'member_id': participant_member_id,
            'unread_count': unread_count,
            'created_at': created_at,
            'last_activity_at': last_activity_at_value,
            'last_read_at': last_read_at,
            'is_group_chat': is_group_chat,
            'conversation_url': conversation_url,
            'conversation_urn': conversation_urn,
            'last_message': {
                'text': last_message_text,
                'delivered_at': last_message_delivered_at,
                'sender': last_message_sender,
            }
        }
        all_messages.append(message_item)

    return all_messages
