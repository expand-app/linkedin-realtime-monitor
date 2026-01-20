import asyncio
import logging
import os
import random
import sys
import re
import time
from typing import Optional
from asgiref.sync import sync_to_async

import django

# 项目根目录路径（根据你的实际结构调整）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "linkedin_realtime_monitor.settings")  # 替换成你的 settings 路径
django.setup()

from django.utils import timezone
from playwright.async_api import async_playwright, Browser, Page
from realtime_monitor.core.event_handler import EventHandler
from realtime_monitor.core.db_health_check import db_health_checker
from realtime_monitor.models import MonitorAccount
from middlewares.trace_id import get_current_trace_id


class AccountMonitor:
    """单个账号的监听器 - 运行在独立子进程中"""

    # XPath 配置
    XPATHS = {
        'my_network': '//*[@href="https://www.linkedin.com/mynetwork/?"]/div/span/span[1]',
        'messaging': '//*[@id="msg-overlay"]/div[1]/header/div[2]/mark'
    }

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.is_running = False
        self.event_handler = EventHandler(account_id)

    async def run(self):
        """运行监听器"""
        # 获取当前 trace_id（已在子进程启动时设置）
        trace_id = get_current_trace_id()
        logging.info(f"AccountMonitor starting for account {self.account_id} with trace_id: {trace_id}")

        try:
            # 1. 初始化浏览器
            await self.init_browser()

            # 2. 检查登录状态
            if not await self.check_login():
                logging.error(f"Account {self.account_id} not logged in")
                await self._mark_account_error("Login check failed")
                return

            # 3. 启动监听循环
            self.is_running = True

            # 并发运行五个任务（包括浏览器健康检查）
            await asyncio.gather(
                self.dom_monitor_loop(),
                self.fallback_polling_loop(),
                self.heartbeat_loop(),
                self.monitor_enabled_check_loop()
            )

        except Exception as e:
            error_msg = f"AccountMonitor fatal error: {str(e)}"
            logging.error(f"AccountMonitor error for account {self.account_id}: {error_msg}", exc_info=True)
            await self._mark_account_error(error_msg)
        finally:
            await self.cleanup()

    async def init_browser(self):
        """初始化浏览器"""
        # 确保数据库连接可用
        if not await db_health_checker.ensure_connection_async():
            raise Exception("Database connection not available")
        
        # 获取账号配置
        account = await MonitorAccount.objects.aget(id=int(self.account_id))

        self.playwright = await async_playwright().start()

        # 启动浏览器（使用持久化 Profile）
        user_data_dir = f'./chrome_profile_dir/{account.email}'
        self.browser = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,  # 生产环境使用无头模式
            channel="chrome",
            args=[
                "--disable-gpu",
                "--disable-infobars",
                "--start-maximized",
                "--disable-extensions",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        # 创建或获取页面
        if len(self.browser.pages) > 0:
            self.page = self.browser.pages[0]
        else:
            self.page = await self.browser.new_page()

        # 导航到 LinkedIn Feed 页面
        await self.page.goto('https://www.linkedin.com/feed/', timeout=60000)

        logging.info(f"Browser initialized for {self.account_id}")

    async def check_login(self) -> bool:
        """检查是否已登录

        Returns:
            bool: 如果已登录返回 True，否则返回 False
        """
        try:
            # 1. 等待页面加载完成
            await self.page.wait_for_load_state('domcontentloaded', timeout=10000)

            # 2. 再等待一点时间，确保 JavaScript 执行完成
            await asyncio.sleep(5)

            # 3. 检查是否在登录页面
            current_url = self.page.url
            if 'login' in current_url or 'challenge' in current_url:
                logging.info(f"Currently on login page: {current_url}")
                return False
            return True

        except asyncio.TimeoutError:
            logging.error("Login check timeout - page load took too long")
            return False
        except Exception as e:
            logging.error(f"Login check error: {type(e).__name__}: {e}")
            return False

    async def dom_monitor_loop(self):
        """DOM 红点监听循环"""
        logging.info(f"DOM monitor loop started for {self.account_id}")

        last_states = {key: False for key in self.XPATHS}
        loop_count = 0  # 循环计数器，用于控制页面刷新

        while self.is_running:
            try:
                for key in self.XPATHS.keys():
                    current_state, badge_count = await self.check_red_badge(key)
                    logging.info(
                        f"Account {self.account_id}: {key} state: {current_state} last_state: {last_states[key]} badge_count: {badge_count}")
                    # 从无到有：触发高优先级事件
                    if current_state and not last_states[key]:
                        await self.trigger_event(
                            event_type=key,
                            source='dom_monitor',
                            priority='high',
                            badge_count=badge_count
                        )
                    last_states[key] = current_state
                    await asyncio.sleep(1)  # 每秒检查一次

            except Exception as e:
                # 检查是否是浏览器关闭导致的异常
                if "Target closed" in str(e) or "Browser closed" in str(e) or "Connection closed" in str(e):
                    logging.error(f"Account {self.account_id}: Browser closed unexpectedly in DOM monitor: {e}")
                    await self._mark_account_error(f"Browser closed in DOM monitor: {str(e)}")
                    self.is_running = False
                    break
                logging.error(f"DOM monitor error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def fallback_polling_loop(self):
        """Fallback 轮训循环"""
        logging.info(f"Fallback polling loop started for {self.account_id}")

        while self.is_running:
            try:
                await asyncio.sleep(300)  # 5分钟

                # 触发低优先级事件
                try:
                    await self.trigger_event(
                        event_type='my_network',
                        source='fallback_polling',
                        priority='low',
                        badge_count=1  # fallback 流程不基于红点数量
                    )

                    await self.trigger_event(
                        event_type='messaging',
                        source='fallback_polling',
                        priority='low'
                    )
                except Exception as e:
                    # Fallback 流程中的错误不应该导致循环停止
                    # 只记录日志，继续运行
                    logging.warning(
                        f"Account {self.account_id}: Error in fallback polling event trigger: {e}. "
                        f"Fallback loop will continue."
                    )

            except Exception as e:
                # 检查是否是浏览器关闭导致的异常
                if "Target closed" in str(e) or "Browser closed" in str(e) or "Connection closed" in str(e):
                    logging.error(f"Account {self.account_id}: Browser closed unexpectedly in fallback polling: {e}")
                    await self._mark_account_error(f"Browser closed in fallback polling: {str(e)}")
                    self.is_running = False
                    break
                logging.error(f"Fallback polling error: {e}", exc_info=True)

    async def heartbeat_loop(self):
        """心跳循环 - 每30秒更新一次"""
        while self.is_running:
            try:
                await asyncio.sleep(30)

                # 确保数据库连接可用
                if not await db_health_checker.ensure_connection_async():
                    logging.error(f"Account {self.account_id}: Database connection lost in heartbeat")
                    continue

                # 更新数据库中的心跳时间
                account = await MonitorAccount.objects.aget(id=int(self.account_id))
                account.last_heartbeat_at = timezone.now()
                # 使用 sync_to_async 包装同步的 save() 方法
                await sync_to_async(account.save)()

            except Exception as e:
                # 检查是否是浏览器关闭导致的异常
                if "Target closed" in str(e) or "Browser closed" in str(e) or "Connection closed" in str(e):
                    logging.error(f"Account {self.account_id}: Browser closed unexpectedly in heartbeat: {e}")
                    await self._mark_account_error(f"Browser closed in heartbeat: {str(e)}")
                    self.is_running = False
                    break
                logging.error(f"Heartbeat error: {e}", exc_info=True)

    async def monitor_enabled_check_loop(self):
        """监控 enable 状态检查循环 - 每10秒检查一次"""
        logging.info(f"Monitor enabled check loop started for {self.account_id}")

        while self.is_running:
            try:
                await asyncio.sleep(10)

                # 确保数据库连接可用
                if not await db_health_checker.ensure_connection_async():
                    logging.warning(f"Account {self.account_id}: Database connection lost in monitor check")
                    continue

                # 检查 monitor_enabled 状态
                account = await MonitorAccount.objects.aget(id=int(self.account_id))
                if not account.monitor_enabled:
                    logging.info(f"Account {self.account_id} monitor_enabled is False, stopping monitor...")
                    # 停止所有循环
                    self.is_running = False
                    # 退出循环，触发 cleanup（主进程会上传 profile）
                    break

            except MonitorAccount.DoesNotExist:
                logging.error(f"Account {self.account_id} not found, stopping monitor...")
                self.is_running = False
                break
            except Exception as e:
                logging.error(f"Monitor enabled check error: {e}")

    async def _mark_account_error(self, error_message: str):
        """标记账号为错误状态，并禁用监听"""
        try:
            # 确保数据库连接可用
            if not await db_health_checker.ensure_connection_async():
                logging.error(f"Account {self.account_id}: Cannot mark as error - database connection lost")
                return
            
            account = await MonitorAccount.objects.aget(id=int(self.account_id))
            account.status = 'error'
            account.monitor_enabled = False
            # 使用 sync_to_async 包装同步的 save() 方法
            await sync_to_async(account.save)()

            # 记录详细的错误日志
            logging.error(
                f"Account {self.account_id} ({account.email}) marked as ERROR. "
                f"Reason: {error_message}. "
                f"Monitor disabled. Status set to 'error'."
            )
        except Exception as e:
            logging.error(
                f"Failed to mark account {self.account_id} as error: {e}",
                exc_info=True
            )

    async def check_red_badge(self, link_type: str) -> tuple[bool, int]:
        """检查红点是否存在，并返回红点上的数量

        Args:
            link_type: 'my_network' 或 'messaging'

        Returns:
            tuple[bool, int]: (是否存在红点, 红点上的数量，如果不存在则返回0)
        """
        try:
            # 使用原始 XPath 方法
            xpath = self.XPATHS.get(link_type)
            if not xpath:
                logging.error(f"No XPath found for link_type: {link_type}")
                return False, 0

            if link_type == 'messaging':
                try:
                    # 等待元素出现，如果超时或找不到则返回 False
                    await self.page.wait_for_selector(f'xpath={xpath}', timeout=10000)
                    
                    locator = self.page.locator(f'xpath={xpath}')
                    
                    # 使用 await 获取文本（inner_text 是异步方法）
                    text = await locator.inner_text()
                    
                    # 提取数字
                    match = re.search(r'\d+', text) if text else None
                    count = int(match.group()) if match else 0
                    
                    # 根据 count 判断是否找到红点
                    result = {
                        'found': count > 0,
                        'count': count,
                        'method': 'messaging_xpath'
                    }
                except Exception as e:
                    # 如果等待超时或元素不存在，返回未找到
                    logging.debug(f"Messaging badge check failed: {e}")
                    result = {
                        'found': False,
                        'count': 0,
                        'reason': f'wait_selector_failed: {str(e)}'
                    }
            else:
                # 使用 JavaScript 通过 XPath 查找红点元素
                find_badge_script = """
                (xpath) => {
                    // 辅助函数：检查元素是否可见（宽松检查）
                    function isElementVisible(element) {
                        if (!element) return false;
                        
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        
                        // 只检查最基本的隐藏方式
                        if (style.display === 'none') return false;
                        if (style.visibility === 'hidden') return false;
                        
                        // 检查尺寸（宽松一点，只要有一点尺寸就认为可见）
                        if (rect.width < 1 && rect.height < 1) return false;
                        
                        return true;
                    }
                    
                    // 辅助函数：提取数字（宽松版本）
                    function extractNumber(text) {
                        if (!text) return null;
                        
                        const cleaned = text.trim();
                        if (!cleaned) return null;
                        
                        // 尝试多种匹配方式
                        // 1. 纯数字: "3", " 5 "
                        let pureMatch = cleaned.match(/^\\s*(\\d+)\\s*$/);
                        if (pureMatch) {
                            return parseInt(pureMatch[1]);
                        }
                        
                        // 2. 数字在开头: "5 new", "3+"
                        let startMatch = cleaned.match(/^(\\d+)/);
                        if (startMatch) {
                            return parseInt(startMatch[1]);
                        }
                        
                        // 3. 提取任何数字
                        let anyMatch = cleaned.match(/\\d+/);
                        if (anyMatch) {
                            return parseInt(anyMatch[0]);
                        }
                        
                        return null;
                    }
                    
                    try {
                        // 方法1: 使用 XPath 查找（主要方法）
                        const xpathResult = document.evaluate(
                            xpath,
                            document,
                            null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE,
                            null
                        );
                        
                        const xpathElement = xpathResult.singleNodeValue;
                        
                        if (xpathElement && isElementVisible(xpathElement)) {
                            const text = xpathElement.textContent || xpathElement.innerText || '';
                            const number = extractNumber(text);
                            
                            if (number !== null && number > 0) {
                                const style = window.getComputedStyle(xpathElement);
                                const rect = xpathElement.getBoundingClientRect();
                                
                                return {
                                    found: true,
                                    count: number,
                                    method: 'xpath',
                                    debug: {
                                        tagName: xpathElement.tagName,
                                        className: xpathElement.className,
                                        textContent: text.trim().substring(0, 100),
                                        display: style.display,
                                        visibility: style.visibility,
                                        opacity: style.opacity,
                                        width: rect.width,
                                        height: rect.height
                                    }
                                };
                            } else {
                                // XPath 找到了元素，但没有有效数字
                                return {
                                    found: false,
                                    count: 0,
                                    reason: 'xpath_found_but_no_number',
                                    debug: {
                                        textContent: text.substring(0, 100),
                                        extractedNumber: number
                                    }
                                };
                            }
                        }
                        
                        // 方法2: XPath 失败，尝试备用方案（查找包含特定 href 的链接下的数字）
                        const hrefPattern = xpath.includes('mynetwork') ? 'mynetwork' : 'messaging';
                        const links = Array.from(document.querySelectorAll('a')).filter(a => {
                            const href = a.getAttribute('href') || '';
                            return href.includes(hrefPattern);
                        });
                        
                        for (const link of links) {
                            // 在链接中查找包含数字的可见子元素
                            const allSpans = link.querySelectorAll('span');
                            
                            for (const span of allSpans) {
                                if (!isElementVisible(span)) continue;
                                
                                const text = span.textContent || span.innerText || '';
                                const number = extractNumber(text);
                                
                                if (number !== null && number > 0) {
                                    // 额外验证：这个 span 应该比较小（红点通常很小）
                                    const rect = span.getBoundingClientRect();
                                    // 如果宽度或高度在 10-100px 之间，更可能是红点
                                    const style = window.getComputedStyle(span);
                                    
                                    return {
                                        found: true,
                                        count: number,
                                        method: 'fallback_span',
                                        debug: {
                                            tagName: span.tagName,
                                            className: span.className,
                                            textContent: text.trim().substring(0, 100),
                                            width: rect.width,
                                            height: rect.height,
                                            backgroundColor: style.backgroundColor
                                        }
                                    };
                                }
                            }
                        }
                        
                        // 都没找到
                        return {
                            found: false,
                            count: 0,
                            reason: 'all_methods_failed',
                            debug: {
                                xpath: xpath,
                                xpathElementFound: xpathElement !== null,
                                linksFound: links.length
                            }
                        };
                        
                    } catch (error) {
                        return { 
                            found: false, 
                            count: 0, 
                            reason: 'exception',
                            error: error.message 
                        };
                    }
                }
                """

                # 执行 JavaScript
                result = await self.page.evaluate(find_badge_script, xpath)

            if result.get('found'):
                # 改为 info 级别，方便查看
                logging.info(
                    f"✓ Badge found for {link_type}: count={result['count']}, "
                    f"method={result.get('method')}, debug={result.get('debug', {})}"
                )
                return True, result['count']
            else:
                # 改为 info 级别，方便调试
                logging.info(
                    f"✗ No badge for {link_type}: reason={result.get('reason')}, "
                    f"debug={result.get('debug', {})}"
                )
                return False, 0

        except Exception as e:
            logging.error(f"check_red_badge error for {link_type}: {e}", exc_info=True)
            return False, 0

    async def trigger_event(self, event_type: str, source: str, priority: str, badge_count: int = 0):
        """触发事件处理

        Args:
            event_type: 事件类型
            source: 事件来源
            priority: 优先级
            badge_count: 红点上的数量（仅对 DOM 监听有效）
        """
        logging.info(f"Event triggered: {event_type}, source={source}, priority={priority}, badge_count={badge_count}")

        # 交给事件处理器处理
        await self.event_handler.handle_event(
            page=self.page,
            event_type=event_type,
            source=source,
            priority=priority,
            badge_count=badge_count
        )

    async def cleanup(self):
        """清理资源"""
        logging.info(f"Cleaning up AccountMonitor for {self.account_id}")

        if self.browser:
            await self.browser.close()

        if self.playwright:
            await self.playwright.stop()