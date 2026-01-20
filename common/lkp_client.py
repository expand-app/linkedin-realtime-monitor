import json
import logging
import time

from urllib.parse import urljoin
import requests

from common.env import is_prod_env


class LKPClient(object):
    def __init__(self):
        self.base_url = 'https://lkp-v2.tuilink.io/'

    def get_cookie(self, account=None, member_id=None):
        """获取指定账户的cookie"""
        uri = '/api/linkedin-account/cookie/'
        url = urljoin(self.base_url, uri)
        params = {}
        if account:
            params['linkedin_account'] = account
        if member_id:
            params['linkedin_member_id'] = member_id
        response = requests.get(url, params=params, timeout=3*60).json()
        status = response.get('status')
        if status == 'success':
            data = response.get('data')
            cookie = data.get('cookie', None)
            proxy = data.get('proxy_config', None)
            account_data = data.get('account_data', None)
            user_agent = data.get('user_agent', None)
            is_success = True
        else:
            is_success = False
            cookie = None
            proxy = None
            account_data = None
            user_agent = None

        return is_success, cookie, proxy, account_data, user_agent

    def get_proxy_config(self, account):
        uri = '/api/linkedin-account/'
        response = requests.get(urljoin(self.base_url, uri), params=dict(account=account), timeout=3*60)
        response_data = response.json()
        return response_data[0] if response_data else []

    def get_account_id(self, account):
        uri = '/api/linkedin-account/'
        response = requests.get(urljoin(self.base_url, uri), params=dict(account=account), timeout=3*60)
        response_data = response.json()
        return response_data[0] if response_data else []

    def create_cookie(self, account, cookie_content):
        uri = '/api/linkedin-account/'
        account_response = requests.get(urljoin(self.base_url, uri), params=dict(account=account), timeout=3*60)
        account_data = account_response.json().get('data')[0]
        account_id = account_data.get('id')
        uri = '/api/linkedin-cookies/'
        url = urljoin(self.base_url, uri)
        response = requests.post(url, json=dict(
            account=account_id,
            cookie_content=cookie_content
        ))
        return response


if __name__ == '__main__':
    lkp_client = LKPClient()
    is_success, cookie, proxy, account_data, user_agent = lkp_client.get_cookie('wilsonleechen@gmail.com')

    print(type(cookie), proxy, account_data, user_agent)
    # print(lkp_client.get_proxy_config('shuo.feng@rexpandco.com'))
    # print(lkp_client.get_proxy_config('shuo.feng@rexpandco.com'))
