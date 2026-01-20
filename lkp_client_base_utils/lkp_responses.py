import json


class LKPResponse(object):
    class STATUS:
        SUCCESS = 'success'
        FAIL = 'fail'

    def __init__(self, http_response):
        self.http_response = http_response
        try:
            self.data = json.loads(http_response.text)
        except json.JSONDecodeError:
            self.data = {}


class GetCookieResponse(LKPResponse):

    @property
    def status(self):
        if not self.cookie:
            return LKPResponse.STATUS.FAIL
        status = self.data.get('status')
        return status

    @property
    def cookie(self):
        cookie = self.data.get('data', {}).get('cookie')
        return cookie


class EscrowAccountResponse():
    def __init__(self, task_id):
        self.task_id = task_id


class RefreshCookieResponse(LKPResponse):

    @property
    def task_id(self):
        task_id = self.data.get('data', {}).get('id')
        return task_id

    @property
    def status(self):
        status = self.data.get('status')
        return status


class ReportActionResponse(LKPResponse):
    class STATUS:
        SUCCESS = 'success'
        FAIL = 'fail'

    ALL_STATUS = [STATUS.SUCCESS, STATUS.FAIL]

    @property
    def status(self):
        status = self.data.get('status')
        # 做一些对于服务端的强制校验，防止一些意外情况发生， 对其他子系统造成影响
        if status not in self.ALL_STATUS:
            raise ValueError(f'Invalid status: {status}')
        return status


class SubmitAuthCodeResponse(LKPResponse):
    class STATUS:
        SUCCESS = 'success'
        FAIL = 'fail'

    ALL_STATUS = [STATUS.SUCCESS, STATUS.FAIL]

    @property
    def status(self):
        status = self.data.get('status')
        # 做一些对于服务端的强制校验，防止一些意外情况发生， 对其他子系统造成影响
        if status not in self.ALL_STATUS:
            raise ValueError(f'Invalid status: {status}')
        return status


class AccountInfoResponse(LKPResponse):
    class STATUS:
        SUCCESS = 'success'
        FAIL = 'fail'

    ALL_STATUS = [STATUS.SUCCESS, STATUS.FAIL]

    @property
    def proxy_url(self):
        data = self.data.get('data', [])
        if len(data) == 0:
            return None
        d = data[0]
        return d.get('proxy_url', False)

    @property
    def is_cookie_valid(self):
        data = self.data.get('data', [])
        if len(data) == 0:
            return None
        d = data[0]
        return d.get('is_cookie_valid', False)

    @property
    def status(self):
        status = self.data.get('status')
        # 做一些对于服务端的强制校验，防止一些意外情况发生， 对其他子系统造成影响
        if status not in self.ALL_STATUS:
            raise ValueError(f'Invalid status: {status}')
        return status

    @property
    def two_step_auth_enabled(self):
        data = self.data.get('data', [])
        if len(data) == 0:
            return None
        d = data[0]
        return d.get('two_step_auth_enabled', False)

    @property
    def account_id(self):
        data = self.data.get('data', [])
        if len(data) == 0:
            return None
        d = data[0]
        account_id = d.get('id')
        return account_id

    @property
    def authenticator_secret_key(self):
        data = self.data.get('data', [])
        if len(data) == 0:
            return None
        d = data[0]
        authenticator_secret_key = d.get('authenticator_secret_key')
        return authenticator_secret_key


class RefreshCookieTaskResponse(LKPResponse):
    class STATUS:
        SUCCESS = 'success'
        FAIL = 'fail'
        SYSTEM_OVERLOAD = 'system overload'
        ACCOUNT_OR_PASSWORD_ERROR = 'account or password error'
        AUTH_CODE_ERROR = 'auth code error'
        RUNNING = 'running'
        AUTH_CODE_SUBMITTED = 'auth code submitted'
        # 当处于这种状态的时候，需要调用LKPClientBase.submit_auth_code
        WAITING_FOR_SUBMIT_AUTH_FOR_SMS = 'waiting for submit auth for sms'
        WAITING_FOR_SUBMIT_AUTH_FOR_EMAIL = 'waiting for submit auth for email'
        WAITING_FOR_SUBMIT_AUTH_FOR_AUTHENTICATOR = 'waiting for submit auth for authenticator'
        WAITING_FOR_SUBMIT_AUTH_FOR_APP = 'waiting for submit auth for app'
        APP_CONFIRMED = 'app confirmed'
        TIMEOUT_ERROR = 'timeout error'
        ACCOUNT_CHALLENGED = 'account challenged'
        INTERRUPTED = 'interrupted'

    @property
    def status(self):
        two_step_auth_type = self.data.get('data', {}).get('two_step_auth_type')
        raw_status = self.data.get('data', {}).get('status')
        # 这里相当于是根据状态和二步验证类型映射到对应的状态
        if raw_status == 'waiting for submitting auth code' and two_step_auth_type:
            if two_step_auth_type == 'sms':
                return self.STATUS.WAITING_FOR_SUBMIT_AUTH_FOR_SMS
            elif two_step_auth_type == 'email':
                return self.STATUS.WAITING_FOR_SUBMIT_AUTH_FOR_EMAIL
            elif two_step_auth_type == 'authenticator':
                return self.STATUS.WAITING_FOR_SUBMIT_AUTH_FOR_AUTHENTICATOR
            elif two_step_auth_type == 'linkedin app':
                return self.STATUS.WAITING_FOR_SUBMIT_AUTH_FOR_APP
            else:
                raise ValueError(f'Invalid two_step_auth_type: {two_step_auth_type}')
        elif raw_status == 'account challenged':
            return self.STATUS.ACCOUNT_CHALLENGED
        elif raw_status == 'auth code submitted':
            return self.STATUS.AUTH_CODE_SUBMITTED
        elif raw_status == 'app confirmed':
            return self.STATUS.APP_CONFIRMED
        elif raw_status == 'success':
            return self.STATUS.SUCCESS
        elif raw_status == 'auth code error':
            return self.STATUS.AUTH_CODE_ERROR
        elif raw_status == 'account or password error':
            return self.STATUS.ACCOUNT_OR_PASSWORD_ERROR
        elif raw_status == 'timeout error':
            return self.STATUS.TIMEOUT_ERROR
        elif raw_status == 'failed':
            return self.STATUS.FAIL
        elif raw_status == 'system overload':
            return self.STATUS.SYSTEM_OVERLOAD
        elif raw_status == 'created':
            return self.STATUS.RUNNING
        elif raw_status == 'interrupted':
            return self.STATUS.INTERRUPTED
        else:
            raise ValueError(f'Invalid raw_status: {raw_status} or two_step_auth_type: {two_step_auth_type}')

    def task_id(self):
        return self.data.get('data', {}).get('id')


class DeleteAccountResponse(LKPResponse):

    @property
    def status(self):
        if self.http_response.status_code == 200:
            return self.STATUS.SUCCESS
        else:
            return self.STATUS.FAIL
