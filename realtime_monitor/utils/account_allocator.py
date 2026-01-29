import os
from dataclasses import dataclass
from typing import Tuple

from realtime_monitor.models import MonitorAccount


@dataclass
class PodShardInfo:
    pod_name: str
    pod_index: int
    accounts_per_pod: int
    start_index: int
    end_index: int


def get_pod_index_from_env() -> int:
    """
    从 POD_NAME 环境变量解析当前 Pod 的 index。

    例如：
    - POD_NAME=lkrm-prod-0 -> index=0
    - POD_NAME=lkrm-prod-7 -> index=7
    """
    pod_name = os.environ.get("POD_NAME", "")
    if not pod_name or "-" not in pod_name:
        return 0
    try:
        return int(pod_name.split("-")[-1])
    except ValueError:
        return 0


def get_accounts_per_pod_from_env(default: int = 8) -> int:
    raw = os.environ.get("ACCOUNTS_PER_POD")
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


def get_pod_shard_info() -> PodShardInfo:
    pod_name = os.environ.get("POD_NAME", "unknown-0")
    pod_index = get_pod_index_from_env()
    accounts_per_pod = get_accounts_per_pod_from_env()
    start = pod_index * accounts_per_pod
    end = start + accounts_per_pod - 1
    return PodShardInfo(
        pod_name=pod_name,
        pod_index=pod_index,
        accounts_per_pod=accounts_per_pod,
        start_index=start,
        end_index=end,
    )


def get_account_id_range_for_current_pod() -> Tuple[int, int]:
    """
    返回当前 Pod 负责的账号索引区间（基于排序后的账号列表下标）。
    """
    shard = get_pod_shard_info()
    return shard.start_index, shard.end_index


def get_accounts_for_current_pod():
    """
    根据当前 Pod 的 shard 信息，从数据库中取出对应区间的账号列表。

    排序规则：
    - 以 id 升序排序
    - 只取 monitor_enabled=True 且 status='active' 的账号
    """
    shard = get_pod_shard_info()
    qs = (
        MonitorAccount.objects.filter(
            monitor_enabled=True,
            status="active",
        )
        .order_by("id")
    )
    accounts = list(qs)
    return accounts[shard.start_index : shard.end_index + 1]

