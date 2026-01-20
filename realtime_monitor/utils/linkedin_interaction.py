import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Pattern

from datetime import datetime, timezone
from uuid import uuid4

import requests
from django.conf import settings
from django.db.models import Q
from rest_framework import status

from linkedin_realtime_monitor.settings import ENV
from lkp_client_base_utils.lkp_client_base import LKPClientBase

# TODO 测试期间 prod， 正式上线使用 env 变量
lkpc = LKPClientBase('prod')

logger = logging.getLogger(__name__)

LOOKUP_USERNAME_ENDPOINT = f"https://api.tuilink.io/account/linkedin_api/lookup-username"


class LinkedInInteractionError(Exception):
    """业务层自定义异常，包含错误码与 HTTP 状态码。"""

    def __init__(self, error_code: str, http_status: int, message: Optional[str] = None):
        super().__init__(message or error_code)
        self.error_code = error_code
        self.http_status = http_status


@dataclass
class SenderAccount:
    email: str
    hash_id: str


def resolve_sender_account(profile_id: str) -> SenderAccount:
    """
    根据传入的 profile_id 获取发送端账号信息。
    profile_id 可以是 hash_id、public_id 或 member_id。
    """
    if not profile_id:
        raise LinkedInInteractionError("missing_sender_profile_id", status.HTTP_400_BAD_REQUEST)

    lookup = _lookup_account_from_api(profile_id)
    if not lookup:
        raise LinkedInInteractionError("sender_not_found", status.HTTP_400_BAD_REQUEST)

    email = lookup.get("username")
    sender_hash_id = lookup.get("hash_id")

    if not email:
        raise LinkedInInteractionError("sender_email_missing", status.HTTP_400_BAD_REQUEST)
    if not sender_hash_id:
        raise LinkedInInteractionError("sender_hash_id_missing", status.HTTP_400_BAD_REQUEST)

    return SenderAccount(
        email=email,
        hash_id=sender_hash_id,
    )


def _lookup_account_from_api(profile_id: str) -> Optional[Dict[str, Optional[str]]]:
    if not LOOKUP_USERNAME_ENDPOINT or not profile_id:
        return None
    params_candidates = {'identifier': profile_id}
    resp = requests.get(LOOKUP_USERNAME_ENDPOINT, params=params_candidates, timeout=10)
    if resp.status_code != 200:
        logger.debug("lookup-username non-200 response: %s %s", resp.status_code, resp.text[:200])
        return None
    payload = resp.json()

    data = payload.get("data")
    username = data.get("username")
    hash_id = data.get("hash_id")

    if username:
        return {
            "username": username,
            "hash_id": hash_id
        }

    return None


