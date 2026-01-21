# LinkedIn 实时监控系统

一个基于 Django 的 LinkedIn 账号实时监控系统，支持多账号并发监控、好友列表抓取、对话列表抓取等功能。

## 功能特性

- 🔍 **多账号监控**: 支持同时监控多个 LinkedIn 账号
- 👥 **好友列表抓取**: 实时抓取和更新账号的好友列表
- 💬 **对话列表抓取**: 实时抓取对话列表和消息更新
- 🔄 **自动重启**: 支持进程健康检查和自动重启
- 💓 **心跳检测**: 实时监控进程状态，确保服务稳定运行
- 🔔 **微信通知**: 集成企业微信机器人，支持消息通知
- ☁️ **云存储**: 支持将浏览器 Profile 上传到 AWS S3
- 🚀 **多进程架构**: 采用多进程架构，每个账号独立进程监控

## 技术栈

- **Web 框架**: Django 4.1 + Django REST Framework
- **数据库**: PostgreSQL
- **缓存**: Redis
- **异步任务**: Celery + Celery Redbeat
- **浏览器自动化**: Playwright + Selenium
- **云存储**: AWS S3 (boto3)
- **消息通知**: 企业微信机器人
- **其他**: LangChain, OpenAI API 等

## 项目结构

```
linkedin-realtime-monitor/
├── linkedin_realtime_monitor/      # Django 项目主配置
│   ├── settings.py                 # Django 配置
│   ├── urls.py                     # URL 路由配置
│   └── wsgi.py                     # WSGI 入口
├── realtime_monitor/               # 核心监控应用
│   ├── models.py                   # 数据模型 (MonitorAccount, RealtimeConnection, RealtimeConversation)
│   ├── views.py                    # API 视图
│   ├── core/                       # 核心功能模块
│   │   ├── manager.py              # 监控管理器（主进程）
│   │   ├── account_monitor.py      # 账号监听器（子进程）
│   │   ├── event_handler.py        # 事件处理器
│   │   ├── data_crawler.py         # 数据抓取器
│   │   └── db_health_check.py      # 数据库健康检查
│   └── utils/                      # 工具函数
├── common/                         # 通用功能模块
│   ├── aws_cli/                    # AWS S3 文件存储
│   ├── wechat_bot.py               # 微信机器人
│   └── lkp_client.py               # LKP 客户端
├── middlewares/                    # Django 中间件
│   ├── trace_id.py                 # 请求追踪 ID
│   ├── request.py                  # 请求中间件
│   └── response_wrapper.py         # 响应包装器
├── lkp_client_base_utils/          # LKP 客户端基础工具
├── manage.py                       # Django 管理脚本
└── requirements.txt                # Python 依赖

```

## 数据模型

### MonitorAccount
监听账号配置表，存储需要监控的 LinkedIn 账号信息：
- `email`: 账号邮箱（唯一）
- `password`: 账号密码
- `proxy_ip/port/username/password`: 代理配置
- `monitor_enabled`: 是否启用监控
- `status`: 账号状态 (active/inactive/error)
- `last_heartbeat_at`: 最后心跳时间
- `hash_id`: 账号哈希 ID
- `callback_url/token`: 回调配置

### RealtimeConnection
实时抓取的好友列表：
- `account`: 关联的监控账号
- `first_name/last_name`: 好友姓名
- `public_id/hash_id/member_id`: 唯一标识
- `headline`: 个人简介
- `connected_at`: 成为好友的时间
- `source`: 数据来源 (original/searched)

### RealtimeConversation
实时抓取的对话列表：
- `account`: 关联的监控账号
- `hash_id/conversation_id`: 对话唯一标识
- `first_name/last_name`: 对方姓名
- `unread_count`: 未读消息数
- `is_group_chat`: 是否为群聊
- `last_message_text/sender/delivered_at`: 最后一条消息信息
- `last_activity_at`: 最后活动时间

## 安装与配置

### 环境要求

- Python 3.8+
- PostgreSQL
- Redis
- Chrome/Chromium 浏览器

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd linkedin-realtime-monitor
```

2. **创建虚拟环境**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **配置环境变量**
```bash
# 设置环境变量（或使用 .env 文件）
export Env=staging  # 或 prod
export CACHE_HOST=localhost  # Redis 主机
export S3_AWS_ACCESS_KEY_ID=your_key
export S3_AWS_SECRET_ACCESS_KEY=your_secret
export S3_REGION_NAME=us-east-1
export S3_BUCKET_NAME=your_bucket
```

5. **数据库迁移**
```bash
python manage.py makemigrations
python manage.py migrate
```

6. **创建超级用户（可选）**
```bash
python manage.py createsuperuser
```

## 使用说明

### 启动 Django 服务

```bash
python manage.py runserver
# 或使用 gunicorn（生产环境）
gunicorn linkedin_realtime_monitor.wsgi:application
```

### 启动监控管理器

监控管理器是独立服务，负责管理和监控所有账号：

```bash
python realtime_monitor/core/manager.py
```

### API 接口

#### 1. 托管账号（启用监控）

```http
POST /api/monitor/
Content-Type: application/json

{
  "profile_id": "your_profile_id"
}
```

#### 2. 更新监控状态

```http
PUT /api/monitor/
Content-Type: application/json

{
  "profile_id": "your_profile_id",
  "monitor": true  # 或 false
}
```

#### 3. 健康检查

```http
GET /healthz
```

#### 4. 关闭检查

```http
GET /shutdownz
```

### 管理后台

访问 `http://localhost:8000/admin/` 使用 Django 管理后台管理账号配置。

## 架构说明

### 多进程架构

系统采用主进程 + 子进程的架构：

- **主进程 (MonitorManager)**: 
  - 管理所有监控账号的进程
  - 定期健康检查（每分钟）
  - 自动启动/停止账号监控进程
  - 检测进程死亡并自动重启
  - 心跳超时检测（5分钟无心跳则重启）

- **子进程 (AccountMonitor)**:
  - 每个账号独立运行在一个子进程中
  - 使用 Playwright 自动化浏览器
  - DOM 监控 + 轮询抓取双重保障
  - 定期发送心跳到数据库
  - 检查监控状态，如果被禁用则自动退出

### 监控流程

1. **初始化**: 从数据库加载所有 `monitor_enabled=True` 且 `status='active'` 的账号
2. **启动**: 为每个账号创建独立的子进程进行监控
3. **运行**: 子进程使用 Playwright 自动化浏览器，实时抓取数据
4. **健康检查**: 主进程每分钟检查：
   - 进程是否存活
   - 心跳是否超时（5分钟）
   - 账号是否被禁用
   - 是否有新账号需要启动
5. **异常处理**: 进程死亡或心跳超时时自动重启（除非账号状态为 `error`）

### 数据抓取策略

- **DOM 监控**: 监听页面 DOM 变化，实时捕获新数据
- **轮询抓取**: 定期轮询抓取，作为 DOM 监控的补充
- **事件处理**: 捕获到新数据后，通过 EventHandler 处理并存储到数据库

## 配置说明

### 数据库配置

在 `settings.py` 中配置 PostgreSQL 连接：

```python
DATABASES = {
    'default': {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "postgres",
        "PASSWORD": "your_password",
        "HOST": "your_host",
        "PORT": "5432",
    }
}
```

### Redis 配置

在 `settings.py` 中配置 Redis 连接：

```python
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',
    }
}
```

### 微信机器人配置

在 `settings.py` 中的 `WechatRobotKey` 类中配置各个功能的微信机器人 Webhook Key。

### AWS S3 配置

通过环境变量配置：

```bash
export S3_AWS_ACCESS_KEY_ID=your_key
export S3_AWS_SECRET_ACCESS_KEY=your_secret
export S3_REGION_NAME=us-east-1
export S3_BUCKET_NAME=your_bucket
```

## 开发说明

### 代码风格

- 遵循 PEP 8 Python 代码规范
- 使用类型提示（Type Hints）
- 编写清晰的注释和文档字符串

### 日志

系统使用 Django 的日志配置，所有日志都包含：
- 时间戳
- 线程名
- 日志级别
- Trace ID（用于追踪请求）
- 消息内容

### 测试

```bash
python manage.py test
```

## 常见问题

### Q: 进程启动失败怎么办？

A: 检查以下几点：
1. 数据库连接是否正常
2. Redis 连接是否正常
3. 账号的 `monitor_enabled` 是否为 `True`
4. 账号的 `status` 是否为 `active`
5. 查看日志获取详细错误信息

### Q: 心跳超时怎么办？

A: 系统会自动重启进程。如果频繁超时，可能是：
1. 浏览器自动化出现问题
2. 网络连接不稳定
3. LinkedIn 页面加载慢

可以查看账号的 `status` 字段，如果变为 `error`，需要手动检查和修复。

### Q: 如何查看监控状态？

A: 可以通过以下方式：
1. Django 管理后台查看 `MonitorAccount` 模型
2. 查看 `last_heartbeat_at` 字段确认最后心跳时间
3. 查看进程日志

## 许可证

[在此添加许可证信息]

## 联系方式

[在此添加联系方式]
