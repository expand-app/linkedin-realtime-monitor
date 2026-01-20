
import os
import sys
import time
import django
import shutil
import asyncio
import logging
import multiprocessing
import threading
from datetime import datetime
from typing import Dict, Optional
from asgiref.sync import sync_to_async


# 项目根目录路径（根据你的实际结构调整）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin_realtime_monitor.settings")  # 替换成你的 settings 路径
django.setup()


from django.db import connection
from realtime_monitor.models import MonitorAccount
from realtime_monitor.core.account_monitor import AccountMonitor
from realtime_monitor.core.db_health_check import db_health_checker, periodic_db_health_check
from common.aws_cli.file_backend import FileBackend, FilePrefix
from middlewares.trace_id import set_trace_id, generate_trace_id
from django.utils import timezone


class MonitorManager:
    """监听进程管理器 - 主进程"""

    def __init__(self):
        self.processes: Dict[str, multiprocessing.Process] = {}
        self.should_stop = False
        self._start_lock = threading.Lock()  # 用于防止并发启动同一账号

    def start(self):
        """启动管理器"""
        logging.info("MonitorManager starting...")

        # 检查数据库连接
        if not db_health_checker.ensure_connection():
            logging.error("Failed to establish database connection, exiting...")
            return

        # 加载需要监听的账号
        self.load_accounts()

        # 启动健康检查循环（包括数据库健康检查）
        asyncio.run(self.health_check_loop())

    def load_accounts(self):
        """从数据库加载需要监听的账号（只在启动时调用）"""
        try:
            # 关闭 Django 连接，避免跨进程共享
            connection.close()
            
            # 确保数据库连接可用
            if not db_health_checker.ensure_connection():
                logging.error("Database connection not available, cannot load accounts")
                return

            accounts = list(MonitorAccount.objects.filter(
                monitor_enabled=True,
                status='active'
            ))

            logging.info(f"Loading {len(accounts)} accounts to monitor")
            for account in accounts:
                account_id = str(account.id)
                # 避免重复启动
                if account_id not in self.processes:
                    self.start_account_monitor(account_id)
                else:
                    logging.info(f"Account {account_id} already running, skipping")
        except Exception as e:
            logging.error(f"Error loading accounts: {e}", exc_info=True)

    def start_account_monitor(self, account_id: str):
        """启动单个账号监听进程"""
        # 使用锁保护，防止并发启动同一账号
        with self._start_lock:
            # 双重检查：锁内再次检查，防止竞态条件
            if account_id in self.processes:
                logging.warning(f"Monitor for {account_id} already running")
                return

            # 检查 monitor_enabled 和 status 状态
            try:
                # 在当前线程中关闭并重新创建连接
                connection.close()
                account = MonitorAccount.objects.get(id=int(account_id))
                if not account.monitor_enabled:
                    logging.info(f"Account {account_id} monitor_enabled is False, skipping start")
                    return
                if account.status == 'error':
                    logging.warning(
                        f"Account {account_id} status is 'error', skipping start. "
                        f"Please manually fix the issue and set status to 'active'."
                    )
                    return
            except MonitorAccount.DoesNotExist:
                logging.warning(f"Account {account_id} not found, skipping start")
                return
            except Exception as e:
                logging.error(f"Error checking account {account_id}: {e}", exc_info=True)
                return

            # 创建子进程
            process = multiprocessing.Process(
                target=self._run_account_monitor,
                args=(account_id,),
                name=f"monitor_{account_id}"
            )
            process.start()

            # 注册到进程字典（在锁保护下）
            self.processes[account_id] = process
            logging.info(f"Started monitor for account {account_id}, PID: {process.pid}")

    def _remove_process_only(self, account_id: str):
        """仅从进程列表中移除，不执行停止和上传操作（用于 error 状态的账号）"""
        with self._start_lock:
            if account_id in self.processes:
                del self.processes[account_id]
                logging.info(f"Removed process {account_id} from process list (account in error state)")

    def stop_account_monitor(self, account_id: str):
        """停止单个账号监听进程，然后由主进程上传 profile 到 S3"""
        # 使用锁保护，获取进程引用
        with self._start_lock:
            if account_id not in self.processes:
                logging.warning(f"Monitor for {account_id} not found")
                return
            process = self.processes[account_id]
        
        # 关闭进程（不在锁内执行，避免长时间持有锁）
        logging.info(f"Sending terminate signal to process {account_id}...")
        process.terminate()
        process.join(timeout=30)  # 等待进程关闭

        if process.is_alive():
            logging.warning(f"Process {account_id} didn't terminate gracefully, killing...")
            process.kill()
            process.join(timeout=5)

        # 进程已关闭，从进程列表中移除（需要锁保护）
        with self._start_lock:
            if account_id in self.processes:
                del self.processes[account_id]
        
        logging.info(f"Process {account_id} stopped")

        # 主进程上传 profile 到 S3
        try:
            connection.close()
            account = MonitorAccount.objects.get(id=int(account_id))
            self.upload_profile_to_s3(account)
        except MonitorAccount.DoesNotExist:
            logging.warning(f"Account {account_id} not found, skipping profile upload")
        except Exception as e:
            logging.error(f"Failed to upload profile for {account_id}: {e}", exc_info=True)
        
        logging.info(f"Stopped monitor for account {account_id}")

    def upload_profile_to_s3(self, account: MonitorAccount):
        """上传 Chrome profile 到 S3（主进程执行）"""
        try:
            profile_dir = f'./chrome_profile_dir/{account.email}'

            if not os.path.exists(profile_dir):
                logging.warning(f"Profile directory not found: {profile_dir}, skipping upload")
                return

            logging.info(f"Uploading profile to S3 for account {account.id} ({account.email})")

            # 清理锁文件和临时文件
            lock_files = ['SingletonLock', 'lockfile']
            temp_files = ['SingletonSocket', 'SingletonCookie']

            for lock_file in lock_files:
                lock_path = os.path.join(profile_dir, lock_file)
                if os.path.exists(lock_path):
                    try:
                        os.remove(lock_path)
                        logging.info(f'Cleaned lock file: {lock_file}')
                    except Exception as e:
                        logging.warning(f'Failed to clean lock file {lock_file}: {str(e)}')

            for temp_file in temp_files:
                temp_path = os.path.join(profile_dir, temp_file)
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                        logging.info(f'Cleaned temp file: {temp_file}')
                    except Exception as e:
                        logging.warning(f'Failed to clean temp file {temp_file}: {str(e)}')

            # 打包并上传
            logging.info(f'Packing profile: {profile_dir}')
            zip_file_path = shutil.make_archive(profile_dir, 'zip', profile_dir)
            online_file_name = f'{account.email}.zip'

            logging.info(f'Uploading profile to S3: {online_file_name}')
            fb = FileBackend()
            fb.upload_file(zip_file_path, online_file_name, FilePrefix.CHROME_PROFILE_PREFIX)
            logging.info(f'Profile uploaded successfully: {online_file_name}')

            # 清理临时 zip 文件
            os.remove(zip_file_path)
            logging.info(f'Cleaned temporary zip file')

        except Exception as e:
            logging.error(f"Failed to upload profile to S3 for account {account.id}: {e}", exc_info=True)

    def restart_account_monitor(self, account_id: str):
        """重启单个账号监听进程"""
        logging.info(f"Restarting monitor for account {account_id}")
        self.stop_account_monitor(account_id)
        time.sleep(2)
        self.start_account_monitor(account_id)

    async def health_check_loop(self):
        """健康检查循环 - 每分钟检查一次（包括数据库健康检查）"""
        # 启动数据库健康检查任务
        db_check_task = asyncio.create_task(periodic_db_health_check(interval=120))
        
        try:
            while not self.should_stop:
                try:
                    await self.check_all_monitors()
                    await asyncio.sleep(60)
                except Exception as e:
                    logging.error(f"Health check error: {e}", exc_info=True)
        finally:
            # 取消数据库健康检查任务
            db_check_task.cancel()
            try:
                await db_check_task
            except asyncio.CancelledError:
                pass

    async def check_all_monitors(self):
        """检查所有监听进程的健康状态和 monitor_enabled 状态"""
        # 获取所有需要监听的账号（monitor_enabled=True）
        @sync_to_async
        def get_enabled_accounts():
            # 在线程内关闭连接，让 Django 创建新连接
            connection.close()
            
            # 确保数据库连接可用
            if not db_health_checker.ensure_connection():
                logging.error("Database connection not available in health check")
                return set()
            
            return set(
                str(acc.id) for acc in MonitorAccount.objects.filter(
                    monitor_enabled=True,
                    status='active'
                )
            )
        
        enabled_accounts = await get_enabled_accounts()

        # 检查当前运行的进程
        for account_id, process in list(self.processes.items()):
            try:
                # 如果账号的 monitor_enabled 为 False，停止进程
                if account_id not in enabled_accounts:
                    logging.info(f"Account {account_id} monitor_enabled is False, stopping monitor...")
                    await sync_to_async(self.stop_account_monitor)(account_id)
                    continue

                # 检查进程是否存活
                if not process.is_alive():
                    # 检查账号状态，如果是 error 状态，不重启
                    @sync_to_async
                    def check_account_status():
                        connection.close()
                        try:
                            account = MonitorAccount.objects.get(id=int(account_id))
                            return account.status
                        except MonitorAccount.DoesNotExist:
                            return None
                    
                    account_status = await check_account_status()
                    if account_status == 'error':
                        logging.warning(
                            f"Monitor {account_id} is dead, but account status is 'error', "
                            f"skipping restart. Please manually fix the issue and set status to 'active'."
                        )
                        # 从进程列表中移除，但不重启
                        await sync_to_async(self._remove_process_only)(account_id)
                    else:
                        logging.error(f"Monitor {account_id} is dead, restarting...")
                        await sync_to_async(self.restart_account_monitor)(account_id)
                    continue

                # 检查心跳时间（通过数据库）
                last_heartbeat = await self._get_last_heartbeat(account_id)
                if last_heartbeat:
                    time_since_heartbeat = (timezone.now() - last_heartbeat).total_seconds()

                    if time_since_heartbeat > 300:  # 5分钟无心跳
                        # 检查账号状态，如果是 error 状态，不重启
                        @sync_to_async
                        def check_account_status():
                            connection.close()
                            try:
                                account = MonitorAccount.objects.get(id=int(account_id))
                                return account.status
                            except MonitorAccount.DoesNotExist:
                                return None
                        
                        account_status = await check_account_status()
                        if account_status == 'error':
                            logging.warning(
                                f"Monitor {account_id} heartbeat timeout ({time_since_heartbeat:.0f}s), "
                                f"but account status is 'error', skipping restart. "
                                f"Please manually fix the issue and set status to 'active'."
                            )
                            # 从进程列表中移除，但不重启
                            await sync_to_async(self._remove_process_only)(account_id)
                        else:
                            logging.error(f"Monitor {account_id} heartbeat timeout ({time_since_heartbeat:.0f}s), restarting...")
                            await sync_to_async(self.restart_account_monitor)(account_id)
            except Exception as e:
                logging.error(f"Error checking monitor {account_id}: {e}", exc_info=True)

        # 检查是否有新的账号需要启动
        for account_id in enabled_accounts:
            try:
                if account_id not in self.processes:
                    logging.info(f"New account {account_id} enabled, starting monitor...")
                    await sync_to_async(self.start_account_monitor)(account_id)
            except Exception as e:
                logging.error(f"Error starting monitor {account_id}: {e}", exc_info=True)

    async def _get_last_heartbeat(self, account_id: str) -> Optional[datetime]:
        """获取进程的最后心跳时间"""
        try:
            # 使用异步 ORM 方法，Django 会自动管理连接
            account = await MonitorAccount.objects.aget(id=int(account_id))
            return account.last_heartbeat_at
        except MonitorAccount.DoesNotExist:
            return None
        except Exception as e:
            logging.error(f"Error getting heartbeat for {account_id}: {e}", exc_info=True)
            return None

    @staticmethod
    def _run_account_monitor(account_id: str):
        """子进程入口点"""
        # 重要：关闭继承的数据库连接
        connection.close()

        # 重新设置 Django
        import django
        django.setup()

        # 为子进程设置独立的 trace_id
        child_trace_id = generate_trace_id()
        set_trace_id(child_trace_id)
        logging.info(f"AccountMonitor subprocess started for account {account_id} with trace_id: {child_trace_id}")

        # 创建并运行监听器
        monitor = AccountMonitor(account_id)
        asyncio.run(monitor.run())

    def shutdown(self):
        """关闭所有监听进程"""
        logging.info("Shutting down MonitorManager...")
        self.should_stop = True

        # 停止所有监听进程
        account_ids = list(self.processes.keys())
        logging.info(f"Stopping {len(account_ids)} monitor processes...")
        
        for account_id in account_ids:
            try:
                self.stop_account_monitor(account_id)
            except Exception as e:
                logging.error(f"Error stopping monitor {account_id}: {e}", exc_info=True)

        logging.info("MonitorManager shutdown complete")


def main():
    """主函数 - 作为独立服务运行"""
    # 为主进程设置 trace_id
    main_trace_id = generate_trace_id()
    set_trace_id(main_trace_id)
    
    # 调试：打印系统时间信息
    import datetime
    current_ts = time.time()
    logging.info(
        f"[System Time Check] time.time()={current_ts}, "
        f"UTC={datetime.datetime.utcfromtimestamp(current_ts)}, "
        f"Local={datetime.datetime.fromtimestamp(current_ts)}"
    )
    
    logging.info(f"MonitorManager main process started with trace_id: {main_trace_id}")
    
    # 配置基本日志（Django setup 后会使用 Django 的日志配置）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(threadName)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    manager = MonitorManager()

    # 注册信号处理
    import signal
    
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down...")
        manager.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        manager.start()
    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt received, shutting down...")
        manager.shutdown()
    except Exception as e:
        logging.error(f"Unexpected error in main: {e}", exc_info=True)
        manager.shutdown()
        sys.exit(1)


if __name__ == '__main__':
    main()