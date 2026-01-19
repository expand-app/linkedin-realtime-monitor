"""
数据库连接健康检查模块

提供数据库连接检测、恢复和装饰器功能，避免因连接中断导致程序报错
"""

import logging
import asyncio
from functools import wraps
from typing import Optional, Callable, Any
from asgiref.sync import sync_to_async
from django.db import connection, OperationalError, InterfaceError
from django.db.utils import DatabaseError


class DatabaseHealthChecker:
    """数据库健康检查器"""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """
        初始化数据库健康检查器
        
        Args:
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    def check_connection(self) -> bool:
        """
        检查数据库连接是否正常（同步版本，仅用于同步上下文）
        
        Returns:
            bool: 连接正常返回 True，否则返回 False
        """
        try:
            # 尝试执行一个简单的查询
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return True
        except (OperationalError, InterfaceError, DatabaseError) as e:
            logging.warning(f"Database connection check failed: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error during database connection check: {e}", exc_info=True)
            return False
    
    async def check_connection_async(self) -> bool:
        """
        检查数据库连接是否正常（异步版本）
        
        Returns:
            bool: 连接正常返回 True，否则返回 False
        """
        @sync_to_async
        def _check():
            try:
                # 尝试执行一个简单的查询
                connection.ensure_connection()
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                return True
            except (OperationalError, InterfaceError, DatabaseError) as e:
                logging.warning(f"Database connection check failed: {e}")
                return False
            except Exception as e:
                logging.error(f"Unexpected error during database connection check: {e}", exc_info=True)
                return False
        
        return await _check()
    
    def reconnect(self) -> bool:
        """
        尝试重新连接数据库（同步版本，仅用于同步上下文）
        
        Returns:
            bool: 重连成功返回 True，否则返回 False
        """
        try:
            logging.info("Attempting to reconnect to database...")
            # 关闭现有连接
            connection.close()
            # 尝试建立新连接
            connection.ensure_connection()
            logging.info("Database reconnection successful")
            return True
        except (OperationalError, InterfaceError, DatabaseError) as e:
            logging.error(f"Database reconnection failed: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error during database reconnection: {e}", exc_info=True)
            return False
    
    async def reconnect_async(self) -> bool:
        """
        尝试重新连接数据库（异步版本）
        
        Returns:
            bool: 重连成功返回 True，否则返回 False
        """
        @sync_to_async
        def _reconnect():
            try:
                logging.info("Attempting to reconnect to database...")
                # 关闭现有连接
                connection.close()
                # 尝试建立新连接
                connection.ensure_connection()
                logging.info("Database reconnection successful")
                return True
            except (OperationalError, InterfaceError, DatabaseError) as e:
                logging.error(f"Database reconnection failed: {e}")
                return False
            except Exception as e:
                logging.error(f"Unexpected error during database reconnection: {e}", exc_info=True)
                return False
        
        return await _reconnect()
    
    def ensure_connection(self) -> bool:
        """
        确保数据库连接可用，如果连接断开则尝试重连
        
        Returns:
            bool: 连接可用返回 True，否则返回 False
        """
        # 先检查连接
        if self.check_connection():
            return True
        
        # 连接失败，尝试重连
        for attempt in range(self.max_retries):
            logging.warning(f"Database connection lost, attempting reconnect ({attempt + 1}/{self.max_retries})...")
            
            if self.reconnect():
                return True
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries - 1:
                import time
                time.sleep(self.retry_delay)
        
        logging.error(f"Failed to reconnect to database after {self.max_retries} attempts")
        return False
    
    async def ensure_connection_async(self) -> bool:
        """
        异步版本：确保数据库连接可用，如果连接断开则尝试重连
        
        Returns:
            bool: 连接可用返回 True，否则返回 False
        """
        # 先检查连接（使用异步版本）
        if await self.check_connection_async():
            return True
        
        # 连接失败，尝试重连
        for attempt in range(self.max_retries):
            logging.warning(f"Database connection lost, attempting reconnect ({attempt + 1}/{self.max_retries})...")
            
            if await self.reconnect_async():
                return True
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay)
        
        logging.error(f"Failed to reconnect to database after {self.max_retries} attempts")
        return False


# 全局数据库健康检查器实例
db_health_checker = DatabaseHealthChecker(max_retries=3, retry_delay=2.0)


def with_db_reconnect(max_retries: int = 3, retry_delay: float = 1.0):
    """
    装饰器：为同步函数添加数据库连接检测和自动重连功能
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            checker = DatabaseHealthChecker(max_retries=max_retries, retry_delay=retry_delay)
            
            for attempt in range(max_retries):
                try:
                    # 确保连接可用
                    if not checker.ensure_connection():
                        raise DatabaseError("Database connection is not available")
                    
                    # 执行原函数
                    return func(*args, **kwargs)
                    
                except (OperationalError, InterfaceError, DatabaseError) as e:
                    logging.warning(
                        f"Database error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    
                    # 如果不是最后一次尝试，等待后重试
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(retry_delay)
                        continue
                    else:
                        # 最后一次尝试失败，抛出异常
                        logging.error(
                            f"Database operation failed in {func.__name__} after {max_retries} attempts"
                        )
                        raise
                except Exception as e:
                    # 其他异常直接抛出，不重试
                    logging.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
                    raise
        
        return wrapper
    return decorator


def with_db_reconnect_async(max_retries: int = 3, retry_delay: float = 1.0):
    """
    装饰器：为异步函数添加数据库连接检测和自动重连功能
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 重试间隔（秒）
    
    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            checker = DatabaseHealthChecker(max_retries=max_retries, retry_delay=retry_delay)
            
            for attempt in range(max_retries):
                try:
                    # 确保连接可用
                    if not await checker.ensure_connection_async():
                        raise DatabaseError("Database connection is not available")
                    
                    # 执行原函数
                    return await func(*args, **kwargs)
                    
                except (OperationalError, InterfaceError, DatabaseError) as e:
                    logging.warning(
                        f"Database error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}"
                    )
                    
                    # 如果不是最后一次尝试，等待后重试
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    else:
                        # 最后一次尝试失败，抛出异常
                        logging.error(
                            f"Database operation failed in {func.__name__} after {max_retries} attempts"
                        )
                        raise
                except Exception as e:
                    # 其他异常直接抛出，不重试
                    logging.error(f"Unexpected error in {func.__name__}: {e}", exc_info=True)
                    raise
        
        return wrapper
    return decorator


async def periodic_db_health_check(interval: int = 60):
    """
    定期检查数据库连接健康状态
    
    Args:
        interval: 检查间隔（秒）
    """
    while True:
        try:
            # 使用异步版本的检查方法
            if not await db_health_checker.check_connection_async():
                logging.warning("Periodic health check: Database connection is unhealthy")
                await db_health_checker.ensure_connection_async()
            else:
                logging.debug("Periodic health check: Database connection is healthy")
        except Exception as e:
            logging.error(f"Error during periodic database health check: {e}", exc_info=True)
        
        await asyncio.sleep(interval)
