import boto3
from linkedin_realtime_monitor.settings import S3_REGION_NAME, S3_AWS_SECRET_ACCESS_KEY, S3_AWS_ACCESS_KEY_ID, S3_BUCKET_NAME
import logging


class FilePrefix:
    FIREFOX_PROFILE_PREFIX = 'firefox_profile'
    CHROME_PROFILE_PREFIX = 'chrome_profile'
    SCREENSHOT_PREFIX = 'screenshot'
    CRAWL_FRIEND_SCREENSHOT_PREFIX = 'crawl_friend_screenshot'


class FileBackend(object):
    def __init__(self):
        session = boto3.Session(
            aws_access_key_id=S3_AWS_ACCESS_KEY_ID,
            aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY,
            region_name=S3_REGION_NAME,
        )
        self.s3_client = session.client('s3')
        pass

    def upload_file(self, local_file_path, online_file_name, prefix):
        online_file_path = f'{prefix}/{online_file_name}'
        bucket_name = S3_BUCKET_NAME
        logging.info(f"Uploading {local_file_path} to s3://{bucket_name}/{online_file_path}")
        self.s3_client.upload_file(Filename=local_file_path, Bucket=bucket_name, Key=online_file_path)
        logging.info(f"Upload completed: s3://{bucket_name}/{online_file_path}")

    def download_file(self, local_file_path, online_file_name, prefix):
        online_file_path = f'{prefix}/{online_file_name}'
        bucket_name = S3_BUCKET_NAME
        logging.info(f"Downloading {local_file_path} to s3://{bucket_name}/{online_file_path}")
        self.s3_client.download_file(bucket_name, online_file_path, local_file_path)
        logging.info(f"Download completed: s3://{bucket_name}/{online_file_path}")


def upload_file_to_s3(local_file_path, online_file_path, verbose=False):

    session = boto3.Session(
        aws_access_key_id=S3_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=S3_AWS_SECRET_ACCESS_KEY,
        region_name=S3_REGION_NAME,
    )
    s3 = session.client('s3')
    bucket_name = S3_BUCKET_NAME

    if verbose:
        logging.info(f"Uploading {local_file_path} to s3://{bucket_name}/{online_file_path}")

    s3.upload_file(Filename=local_file_path, Bucket=bucket_name, Key=online_file_path)

    if verbose:
        logging.info(f"Upload completed: s3://{bucket_name}/{online_file_path}")
