from django.shortcuts import render
from rest_framework import status
from rest_framework.views import APIView

from common.lkp_client import LKPClient
from realtime_monitor.models import MonitorAccount
from rest_framework.response import Response

from realtime_monitor.utils.linkedin_interaction import resolve_sender_account, LinkedInInteractionError


# Create your views here.


class MonitorView(APIView):
    """账号托管 API"""

    def post(self, request):
        data = request.data
        profile_id = data.get('profile_id')

        if not profile_id:
            return Response({
                "message": "Missing required parameter: profile_id",
                "error": {"code": "missing_profile_id"}
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            account_obj = resolve_sender_account(profile_id)
        except LinkedInInteractionError as exc:
            return Response({
                "message": str(exc),
                "error": {"code": exc.error_code}
            }, status=exc.http_status)

        email = account_obj.email
        hash_id = account_obj.hash_id

        lkp_client = LKPClient()
        is_success, cookie, proxy, account_data, user_agent = lkp_client.get_cookie(email)
        if is_success and cookie:
            self._upsert_monitor_account(
                email=email,
                monitor_enabled=True,
                account_data=account_data,
                proxy=proxy,
            )
        else:
            return Response({
                "message": f"Tuilink {profile_id} binding has expired",
                "error": {'code': "bind_expired"}
            }, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'message': "Successfully completed account hosting",
            'data': {
                'email': email,
                'hash_id': hash_id,
                'monitor_enabled': True
            }
        })

    def put(self, request):
        data = request.data
        profile_id = data.get('profile_id')
        monitor = data.get('monitor')

        if not profile_id:
            return Response({
                "message": "Missing required parameter: profile_id",
                "error": {"code": "missing_profile_id"}
            }, status=status.HTTP_400_BAD_REQUEST)

        if monitor is None:
            return Response({
                "message": "Missing required parameter: monitor",
                "error": {"code": "missing_monitor"}
            }, status=status.HTTP_400_BAD_REQUEST)

        if isinstance(monitor, bool):
            monitor_enabled = monitor
        else:
            return Response({
                "message": "Invalid monitor value, must be boolean",
                "error": {"code": "invalid_monitor"}
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            account_obj = resolve_sender_account(profile_id)
        except LinkedInInteractionError as exc:
            return Response({
                "message": str(exc),
                "error": {"code": exc.error_code}
            }, status=exc.http_status)

        email = account_obj.email
        hash_id = account_obj.hash_id

        lkp_client = LKPClient()
        is_success, cookie, proxy, account_data, user_agent = lkp_client.get_cookie(email)
        if is_success and cookie:
            self._upsert_monitor_account(
                email=email,
                monitor_enabled=monitor_enabled,
                account_data=account_data,
                proxy=proxy,
            )
        else:
            return Response({
                "message": f"Tuilink {profile_id} binding has expired",
                "error": {'code': "bind_expired"}
            }, status=status.HTTP_400_BAD_REQUEST)

        message = 'restarted' if monitor_enabled else 'closed'
        return Response({
            'message': f"Successfully {message} account hosting",
            'data': {
                'email': email,
                'hash_id': hash_id,
                'monitor_enabled': monitor_enabled
            }
        })

    @staticmethod
    def _upsert_monitor_account(email: str, monitor_enabled: bool, account_data=None, proxy=None):
        """创建或更新 MonitorAccount 记录"""
        defaults = {
            'monitor_enabled': monitor_enabled,
            'status': 'inactive',
        }

        if account_data:
            defaults['password'] = account_data.get('password')

        if proxy:
            defaults.update({
                'proxy_ip': proxy.get('ip'),
                'proxy_port': proxy.get('port'),
                'proxy_username': proxy.get('account'),
                'proxy_password': proxy.get('password'),
            })

        MonitorAccount.objects.update_or_create(
            email=email,
            defaults=defaults
        )