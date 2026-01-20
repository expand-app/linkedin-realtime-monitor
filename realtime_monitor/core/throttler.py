import os
import sys
import time
import asyncio
from asgiref.sync import sync_to_async

import django

# 项目根目录路径（根据你的实际结构调整）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin_realtime_monitor.settings")  # 替换成你的 settings 路径
django.setup()

from linkedin_realtime_monitor.settings import redis_client


class Throttler:
    """节流控制器 - 基于 Redis 的令牌桶"""

    # 节流配置
    HIGH_PRIORITY_INTERVAL = 60  # 高优先级：1次/分钟
    LOW_PRIORITY_INTERVAL = 3600  # 低优先级：1次/小时
    GLOBAL_LIMIT = 60  # 全局限制：60次/小时

    def __init__(self, account_id: str):
        self.account_id = account_id

    async def can_proceed(self, priority: str) -> bool:
        """检查是否可以继续执行"""

        # 1. 检查全局限制
        if not await self._check_global_limit():
            return False

        # 2. 检查优先级限制
        if priority == 'high':
            return await self._check_high_priority()
        else:
            return await self._check_low_priority()

    async def _check_global_limit(self) -> bool:
        """检查全局限制 - 滑动窗口"""
        key = f'throttle:global:{self.account_id}'

        now = int(time.time())
        window_start = now - 3600  # 1小时窗口

        try:
            # 使用 Redis ZSET 实现滑动窗口
            # 使用 sync_to_async 包装同步的 Redis 操作
            @sync_to_async
            def execute_pipeline():
                pipe = redis_client.pipeline()
                # 移除过期的记录
                pipe.zremrangebyscore(key, 0, window_start)
                # 计数
                pipe.zcard(key)
                # 添加当前时间戳
                pipe.zadd(key, {now: now})
                # 设置过期时间
                pipe.expire(key, 3600)
                return pipe.execute()

            results = await execute_pipeline()
            count = results[1]

            return count < self.GLOBAL_LIMIT
        except Exception as e:
            # 如果 Redis 操作失败，记录错误但允许继续执行（降级策略）
            import logging
            logging.error(f"Throttler global limit check failed for account {self.account_id}: {e}", exc_info=True)
            return True  # 降级：允许继续执行

    async def _check_high_priority(self) -> bool:
        """检查高优先级限制"""
        key = f'throttle:high:{self.account_id}'

        try:
            # 使用 sync_to_async 包装同步的 Redis 操作
            @sync_to_async
            def get_last_time():
                value = redis_client.get(key)
                if value is None:
                    return None
                # Redis 返回的是 bytes，需要解码并转换为 float
                try:
                    return float(value.decode('utf-8'))
                except (ValueError, AttributeError):
                    return None

            @sync_to_async
            def set_current_time():
                current_ts = time.time()
                redis_client.set(key, current_ts, ex=self.HIGH_PRIORITY_INTERVAL)
                return current_ts

            last_time = await get_last_time()
            now = time.time()
            
            # 添加调试日志
            import logging
            import datetime
            logging.info(
                f"[Throttler High] account={self.account_id}, "
                f"last_time={last_time}, now={now}, "
                f"now_utc={datetime.datetime.utcfromtimestamp(now)}, "
                f"interval={self.HIGH_PRIORITY_INTERVAL}, "
                f"diff={now - last_time if last_time else 'N/A'}"
            )

            if last_time is None or (now - last_time) >= self.HIGH_PRIORITY_INTERVAL:
                written_ts = await set_current_time()
                logging.info(
                    f"[Throttler High] account={self.account_id}, ALLOWED, written_ts={written_ts}, "
                    f"written_utc={datetime.datetime.utcfromtimestamp(written_ts)}"
                )
                return True

            logging.info(f"[Throttler High] account={self.account_id}, BLOCKED")
            return False
        except Exception as e:
            # 如果 Redis 操作失败，记录错误但允许继续执行（降级策略）
            import logging
            logging.error(f"Throttler high priority check failed for account {self.account_id}: {e}", exc_info=True)
            return True  # 降级：允许继续执行

    async def _check_low_priority(self) -> bool:
        """检查低优先级限制"""
        key = f'throttle:low:{self.account_id}'

        try:
            # 使用 sync_to_async 包装同步的 Redis 操作
            @sync_to_async
            def get_last_time():
                value = redis_client.get(key)
                if value is None:
                    return None
                # Redis 返回的是 bytes，需要解码并转换为 float
                try:
                    return float(value.decode('utf-8'))
                except (ValueError, AttributeError):
                    return None

            @sync_to_async
            def set_current_time():
                current_ts = time.time()
                redis_client.set(key, current_ts, ex=self.LOW_PRIORITY_INTERVAL)
                return current_ts

            last_time = await get_last_time()
            now = time.time()
            
            # 添加调试日志
            import logging
            import datetime
            logging.info(
                f"[Throttler Low] account={self.account_id}, "
                f"last_time={last_time}, now={now}, "
                f"now_utc={datetime.datetime.utcfromtimestamp(now)}, "
                f"interval={self.LOW_PRIORITY_INTERVAL}, "
                f"diff={now - last_time if last_time else 'N/A'}"
            )

            if last_time is None or (now - last_time) >= self.LOW_PRIORITY_INTERVAL:
                written_ts = await set_current_time()
                logging.info(
                    f"[Throttler Low] account={self.account_id}, ALLOWED, written_ts={written_ts}, "
                    f"written_utc={datetime.datetime.utcfromtimestamp(written_ts)}"
                )
                return True

            logging.info(f"[Throttler Low] account={self.account_id}, BLOCKED")
            return False
        except Exception as e:
            # 如果 Redis 操作失败，记录错误但允许继续执行（降级策略）
            import logging
            logging.error(f"Throttler low priority check failed for account {self.account_id}: {e}", exc_info=True)
            return True  # 降级：允许继续执行