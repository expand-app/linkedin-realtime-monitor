"""纯粹的lkp-client"""
import datetime
import json
import logging
import time

import requests
from urllib.parse import urljoin

from middlewares.trace_id import generate_trace_id
from .lkp_responses import GetCookieResponse, EscrowAccountResponse, RefreshCookieResponse, ReportActionResponse, \
    AccountInfoResponse, SubmitAuthCodeResponse, RefreshCookieTaskResponse, DeleteAccountResponse


class Account:
    def __init__(self, account, password):
        self.account = account
        self.password = password


class ProxyConfig:
    def __init__(self, ip, port, account, password):
        self.ip = ip
        self.port = port
        self.account = account
        self.password = password

    @property
    def proxy_url(self):
        if self.account and self.password:
            return f'http://{self.account}:{self.password}@{self.ip}:{self.port}'
        else:
            return f'http://{self.ip}:{self.port}'


class Env(object):
    STAGING = 'staging'
    PROD = 'prod'
    LOCAL = 'local'


class LKPClientBase:

    def __init__(self, env=Env.STAGING):
        self.env = env
        if self.env == Env.PROD:
            self.base_url = 'https://lkp-v2.tuilink.io'
        elif self.env == Env.STAGING:
            self.base_url = 'https://lkp-v2.staging.tuilink.io'
        elif self.env == Env.LOCAL:
            self.base_url = 'http://192.168.163.49:8001/'
        else:
            raise ValueError('Invalid env')

    def create_account(self, account: Account, strict=False, source='lkrm'):
        # TODO:为了方便tuilink使用，设置里source的默认值，后续发展上， 不应该这么做
        url = urljoin(self.base_url, '/api/linkedin-account/')
        response = requests.post(url=url, json=dict(
            account=account.account,
            password=account.password,
            source=source,
            timeout=3 * 60
        ))
        logging.info('linkedin create account status code:{}'.format(response.status_code))
        logging.info('linkedin create account status:{}'.format(response.json()))
        if not strict:
            # 已存在的情况也会本认定成成功
            if response.status_code in (200, 400):
                return True, response.json()
        else:
            if response.status_code != 200:
                return False, response.json()

    def get_cookie(self, account: str) -> GetCookieResponse:
        """
        获取cookie
        """
        uri = '/api/linkedin-account/cookie/'
        url = urljoin(self.base_url, uri)
        response = requests.get(url, params=dict(
            linkedin_account=account,
        ), timeout=3*60)
        return GetCookieResponse(response)

    def update_account(self, account_id, account, password):
        url = urljoin(self.base_url, '/api/linkedin-account/{}/'.format(account_id))
        response = requests.put(url=url, json=dict(
            account=account,
            password=password,
        ), timeout=3*60)
        if response.status_code != 200:
            return False, response.json()
        else:
            return True, response.json()

    def escrow_account(self, account: Account, member_id=None):
        """托管账户"""
        try:
            account_info = self.get_account_info(account=account.account, member_id=member_id)
            is_success, data = self.update_account(account_id=account_info.account_id,
                                                   account=account.account,
                                                   password=account.password)
            if not is_success:
                logging.error('修改账号信息失败')
                return
            ret = self.create_refresh_cookie_task(account.account)
            task_id = ret.task_id
            return EscrowAccountResponse(task_id)
        except Exception as e:
            logging.error("escrow account error: {}".format(str(e)))
            self.create_account(account)

    def get_account_info(self, account=None, member_id=None) -> AccountInfoResponse:
        uri = '/api/linkedin-account/'
        if account:
            member_id = None
        response = requests.get(urljoin(self.base_url, uri), params=dict(account=account, linkedin_member_id=member_id), timeout=3*60)
        data = response.json().get('data')
        logging.info(f'获取账号 {account} 信息, LKP 接口状态: {response.status_code}, data: {data}')
        if len(data) == 0:
            raise Exception('Please bind linkedin')
        return AccountInfoResponse(response)

    def report_action(self) -> ReportActionResponse:
        return ReportActionResponse({})

    def create_refresh_cookie_task(self, account) -> RefreshCookieResponse:
        uri = '/api/refresh-cookie-task/'
        url = urljoin(self.base_url, uri)
        print('request {}'.format(url))
        response = requests.post(url, json=dict(linkedin_account=account), timeout=3*60)
        return RefreshCookieResponse(response)

    def submit_auth_code(self, task_id, auth_code) -> SubmitAuthCodeResponse:
        uri = '/api/refresh-cookie-task/{}/'.format(task_id)
        url = urljoin(self.base_url, uri)
        response = requests.put(url, json=dict(auth_code=auth_code, status='auth code submitted'), timeout=3*60)
        return SubmitAuthCodeResponse(response)

    def submit_app_confirm(self, task_id) -> SubmitAuthCodeResponse:
        uri = '/api/refresh-cookie-task/{}/'.format(task_id)
        url = urljoin(self.base_url, uri)
        response = requests.put(url, json=dict(status='app confirmed'), timeout=3*60)
        return SubmitAuthCodeResponse(response)

    def get_refresh_task_info(self, task_id):
        uri = '/api/refresh-cookie-task/{}/'.format(task_id)
        response = requests.get(urljoin(self.base_url, uri), timeout=3*60)
        return RefreshCookieTaskResponse(response)

    def delete_account(self, account=None, member_id=None):
        try:
            account_info = self.get_account_info(account=account, member_id=member_id)
            account_id = account_info.account_id

            uri = '/api/linkedin-account/{}/'.format(account_id)
            url = urljoin(self.base_url, uri)
            response = requests.delete(url, timeout=3*60)
            return DeleteAccountResponse(response)
        except Exception as e:
            raise e

    def make_a_linked_in_request(self, account, category, method_name, params, member_id=None):
        only_id = generate_trace_id()
        logging.info(f'request lkp {only_id} 请求参数: {params}, method_name: {method_name}, account: {account}, category: {category}')
        try:
            logging.info(f'request lkp {only_id} get account info start here')
            account_info = self.get_account_info(account=account, member_id=member_id)
            logging.info(f'request lkp {only_id} get account info end here')
        except Exception as e:
            logging.info(f'request lkp {only_id} get account info error here, error msg: {str(e)}')
            raise Exception('Get linkedin account info failed')

        if category == 'extended':
            uri = '/api/action/proxy-extended-requests/'
            url = urljoin(self.base_url, uri)
        elif category == 'third_party':
            uri = '/api/action/proxy-third-party-requests/'
            url = urljoin(self.base_url, uri)
        else:
            raise Exception('invalid category')
        logging.info(f'request lkp {only_id} proxy request start here')
        response = requests.post(url=url, json=dict(
            linkedin_account=account_info.account_id,
            method_name=method_name,
            params=params,
            enable_login=True,
            source='LKRM',
            description=f'{category} request {method_name}'
        ), timeout=3*60)
        if response.status_code != 201:
            logging.info(f'request lkp {only_id} proxy request error here')
            raise Exception('Request lkp proxy failed， status code {}'.format(response.status_code))
        data = response.json()
        status = data.get('response_status')
        if status == ProxyRequestRecordStatus.SUCCESS:
            result = data.get('response')
            ret = eval(result)
            if method_name == 'conversation_file':
                ret = ret.get('content', None)
                origin_ret = None
                message = None
            else:
                ret = json.loads(ret.get('text'))
                origin_ret = ret.get('origin_ret')
                message = ret.get('message')
            if origin_ret:
                ret = eval(origin_ret)
            if message == ProxyRequestRecordStatus.PROFILE_NOT_ACCESSED:
                logging.info(f'request lkp {only_id} proxy request error here')
                raise Exception(ProxyRequestRecordStatus.PROFILE_NOT_ACCESSED)
            logging.info(f'request lkp {only_id} proxy request end here')
            return ret
        elif status == ProxyRequestRecordStatus.COOKIE_EXPIRED:
            logging.info(f'request lkp {only_id} proxy request error here')
            logging.info(f'{only_id}: {account} 账号绑定失效, 请重新托管')
            raise Exception('Please bind LKP')
        else:
            logging.info(f'request lkp {only_id} proxy request error here')
            raise Exception('something unexpected happened, data {}'.format(data))


class ProxyRequestRecordStatus:
    COOKIE_EXPIRED = 'cookie expired'
    SUCCESS = 'success'
    PROFILE_NOT_ACCESSED = 'Profile cannot be accessed'
