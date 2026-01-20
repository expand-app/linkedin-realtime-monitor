import logging
import traceback

import requests


def send_wechat_message(content, key='a09786d5-604f-4f30-9fd6-63ea405279dd'):
    try:
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        offline_job_url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={}'.format(key)

        requests.post(url=offline_job_url, json=data)
    except Exception as e:
        logging.error(f'发送企业微信机器人报错:{str(e)}')
        logging.info(traceback.format_exc())


