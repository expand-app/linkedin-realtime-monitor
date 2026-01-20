import asyncio
import os
import sys
import time
import logging
import math

import django

# 项目根目录路径（根据你的实际结构调整）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin_realtime_monitor.settings")  # 替换成你的 settings 路径
django.setup()

from realtime_monitor.core.throttler import Throttler
from realtime_monitor.core.data_crawler import DataCrawler

logger = logging.getLogger('realtime_monitor')


class EventHandler:
    """事件处理器"""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.throttler = Throttler(account_id)
        self.crawler = DataCrawler(account_id)

    async def handle_event(
            self,
            page,
            event_type: str,
            source: str,
            priority: str,
            badge_count: int = 0
    ):
        """处理事件
        
        Args:
            page: Playwright page 对象
            event_type: 事件类型
            source: 事件来源
            priority: 优先级
            badge_count: 红点上的数量（仅对 DOM 监听有效）
        """

        # 日志打印：事件触发
        logger.info(
            f"[Event Triggered] account={self.account_id}, "
            f"type={event_type}, source={source}, priority={priority}, badge_count={badge_count}"
        )

        try:
            # 节流检查
            if not await self.throttler.can_proceed(priority):
                logger.info(
                    f"[Event Throttled] account={self.account_id}, "
                    f"type={event_type}, priority={priority}"
                )
                return

            # 执行抓取
            start_time = time.time()

            if event_type == 'my_network':
                # 根据来源决定翻页次数
                if source == 'dom_monitor' and badge_count > 0:
                    # DOM 监听：根据红点数量计算翻页次数
                    # 每页40条，计算需要的页数（向上取整）
                    max_pages = math.ceil(badge_count / 40)
                    logger.info(
                        f"[DOM Monitor] badge_count={badge_count}, calculated max_pages={max_pages}"
                    )
                elif source == 'fallback_polling':
                    # Fallback 流程：最多2页
                    max_pages = 2
                    logger.info(f"[Fallback Polling] max_pages limited to 2")
                else:
                    # 其他情况：不限制翻页（保持原有逻辑）
                    max_pages = 5
                    logger.info(f"[Other Source] no page limit")
                
                result_count = await self.crawler.crawl_connections(page, max_pages=max_pages)
                logger.info(
                    f"[Event Success] account={self.account_id}, "
                    f"type={event_type}, fetched={result_count} connections, "
                    f"duration={time.time() - start_time:.2f}s"
                )
            elif event_type == 'messaging':
                result_count = await self.crawler.crawl_conversations(page)
                logger.info(
                    f"[Event Success] account={self.account_id}, "
                    f"type={event_type}, updated={result_count} conversations, "
                    f"duration={time.time() - start_time:.2f}s"
                )

        except Exception as e:
            logger.error(
                f"[Event Failed] account={self.account_id}, "
                f"type={event_type}, error={str(e)}",
                exc_info=True
            )