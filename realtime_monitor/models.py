from django.db import models


# Create your models here.
class MonitorAccount(models.Model):
    """监听账号配置"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    id = models.AutoField(primary_key=True)
    email = models.CharField(max_length=255, unique=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    proxy_ip = models.CharField(max_length=100, null=True, blank=True)
    proxy_port = models.CharField(max_length=100, null=True, blank=True)
    proxy_username = models.CharField(max_length=100, null=True, blank=True)
    proxy_password = models.CharField(max_length=100, null=True, blank=True)
    monitor_enabled = models.BooleanField(default=False)  # 是否启用监听
    # 监控信息
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    hash_id = models.CharField(max_length=255, null=True, blank=True)

    # callback url
    callback_url = models.CharField(max_length=2048, null=True, blank=True)
    callback_token = models.CharField(max_length=2048, null=True, blank=True)


    # 状态
    status = models.CharField(
        max_length=20,
        choices=[
            ('active', 'Active'),
            ('inactive', 'Inactive'),
            ('error', 'Error')
        ],
        default='inactive'
    )

    class Meta:
        db_table = 'monitor_accounts'
        verbose_name = 'Monitor Account'
        verbose_name_plural = 'Monitor Accounts'


class RealtimeConnection(models.Model):
    """实时抓取的好友列表"""

    ORIGINAL = 'original'
    SEARCHED = 'searched'
    SourceStatus = {
        ORIGINAL: 'original',
        SEARCHED: 'searched'
    }

    id = models.AutoField(primary_key=True)

    # 外键关联到 monitor_accounts
    account = models.ForeignKey(
        MonitorAccount,
        on_delete=models.CASCADE,
        db_column='account_id',
        related_name='connections'
    )

    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    public_id = models.CharField(max_length=255, null=True, blank=True)
    hash_id = models.CharField(max_length=255, null=True, blank=True)
    member_id = models.CharField(max_length=255, null=True, blank=True)
    headline = models.TextField(null=True, blank=True)
    connected_at = models.DateTimeField()  # 成为好友的时间
    source = models.CharField(max_length=20, choices=SourceStatus.items(), default=SEARCHED)

    class Meta:
        db_table = 'realtime_connections'
        unique_together = [['account', 'member_id']]
        indexes = [
            models.Index(fields=['account', '-connected_at']),
        ]

    @property
    def account_id(self):
        """向后兼容的属性"""
        return self.account.id


class RealtimeConversation(models.Model):
    """实时抓取的对话列表（仅对话列表，不包含消息详情）"""

    ORIGINAL = 'original'
    SEARCHED = 'searched'
    SourceStatus = {
        ORIGINAL: 'original',
        SEARCHED: 'searched'
    }

    id = models.AutoField(primary_key=True)

    # 外键关联到 monitor_accounts
    account = models.ForeignKey(
        MonitorAccount,
        on_delete=models.CASCADE,
        db_column='account_id',
        related_name='conversations'
    )

    # 唯一标识（与 account 一起做唯一性约束，用于去重和更新）
    hash_id = models.CharField(max_length=200, db_index=True)

    # LinkedIn 原始标识
    public_id = models.CharField(max_length=100, blank=True, null=True)
    member_id = models.CharField(max_length=100, blank=True, null=True)
    conversation_id = models.CharField(max_length=100, db_index=True)
    conversation_url = models.CharField(max_length=2048, null=True, blank=True)

    # 对话对方信息（单聊情况下）
    first_name = models.CharField(max_length=200, blank=True, null=True)
    last_name = models.CharField(max_length=200, blank=True, null=True)
    distance = models.CharField(max_length=50, blank=True, null=True)
    unread_count = models.IntegerField(default=0)
    dialogue_created_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    # 对话类型
    is_group_chat = models.BooleanField(default=False)

    # 最后一条消息信息
    last_message_text = models.TextField(blank=True, null=True)
    last_message_sender = models.CharField(max_length=200, blank=True, null=True)
    last_message_delivered_at = models.DateTimeField(null=True, blank=True)

    # 数据来源
    source = models.CharField(max_length=20, choices=SourceStatus.items(), default=SEARCHED)

    class Meta:
        db_table = 'realtime_conversations'
        unique_together = [('account', 'hash_id')]  # account 和 hash_id 一起做唯一性约束
        indexes = [
            models.Index(fields=['account', '-last_activity_at']),
            models.Index(fields=['hash_id']),
            models.Index(fields=['-last_message_delivered_at']),
            models.Index(fields=['is_group_chat']),
        ]

    @property
    def account_id(self):
        """向后兼容的属性"""
        return self.account.id

    def __str__(self):
        return f"{self.first_name or 'Group'} - {self.hash_id}"
