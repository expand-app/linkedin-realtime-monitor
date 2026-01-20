import subprocess
import json


class AWSCLI:
    def __init__(self, aws_account_id=None, aws_region=None, aws_credential_profile=None) -> None:
        self.aws_account_id = aws_account_id
        self.aws_region = aws_region
        self.aws_credential_profile = aws_credential_profile

    @staticmethod
    def run_command(params: list[str], parse_stdout_response=False):
        response = subprocess.run(params, stdout=subprocess.PIPE)

        if b'ERROR:' in response.stdout:
            raise Exception(response.stdout)

        if parse_stdout_response:
            return json.loads(response.stdout)

        return response

    def get_elasticbeanstalk_s3_bucket_name(self, aws_account_id=None, aws_region=None):
        final_aws_region = aws_region if aws_region else self.aws_region
        if not final_aws_region:
            raise Exception('AWS region must be specified')

        final_aws_account_id = aws_account_id if aws_account_id else self.aws_account_id
        if not final_aws_account_id:
            raise Exception('AWS account id must be specified')

        return f"elasticbeanstalk-{final_aws_region}-{final_aws_account_id}"

    def list_s3_file_paths(self, bucket_name, path, aws_credential_profile=None, verbose=True):
        list_s3_file_paths_cli_params = ['aws', 's3api', 'list-objects-v2',
                                         '--bucket', bucket_name,
                                         '--prefix', path,
                                         '--query', 'Contents[].{Key: Key, LastModified: LastModified}',
                                         '--profile', aws_credential_profile if aws_credential_profile else self.aws_credential_profile]
        if verbose:
            print(
                f"Retrieving file paths from bucket {bucket_name} with path {path}")

        file_list = AWSCLI.run_command(
            list_s3_file_paths_cli_params, parse_stdout_response=True)

        if verbose:
            print(
                f"Retrieved {len(file_list)} file paths from bucket {bucket_name} with path {path}")

        return file_list

    def list_elasticbeanstalk_s3_file_paths(self, aws_account_id=None, aws_region=None, aws_credential_profile=None,
                                            eb_env_id=None, eb_instance_id=None, verbose=True):

        bucket_name = self.get_elasticbeanstalk_s3_bucket_name(
            aws_account_id, aws_region)
        path = f"resources/environments/logs/publish/"

        if eb_env_id:
            path += f"{eb_env_id}/"

        if eb_instance_id:
            path += f"{eb_instance_id}/"

        return self.list_s3_file_paths(bucket_name=bucket_name, path=path, aws_credential_profile=aws_credential_profile, verbose=verbose)

    def downlaod_s3_file(self, bucket_name, path, destination, aws_credential_profile=None, verbose=True):
        downlaod_s3_file_params = ['aws', 's3', 'cp',
                                   f"s3://{bucket_name}/{path}",
                                   destination,
                                   '--profile', aws_credential_profile if aws_credential_profile else self.aws_credential_profile]

        if verbose:
            print(
                f"Downloading file from bucket {bucket_name} with path {path} to destination {destination}")

        response = AWSCLI.run_command(downlaod_s3_file_params)

        if verbose:
            print(
                f"Downloaded file from bucket {bucket_name} with path {path} to destination {destination}")

        return response

    def downlaod_elasticbeanstalk_s3_file(self, path, destination, aws_account_id=None, aws_region=None, aws_credential_profile=None, verbose=True):
        bucket_name = self.get_elasticbeanstalk_s3_bucket_name(
            aws_account_id, aws_region)

        return self.downlaod_s3_file(bucket_name=bucket_name, path=path, destination=destination, aws_credential_profile=aws_credential_profile, verbose=verbose)

    def download_elasticbeanstalk_native_log_files(self, verbose=True):
        if verbose:
            print(
                f"Downloading EB native log files")

        response = AWSCLI.run_command(['eb', 'logs', '-a'])

        if verbose:
            print(
                f"Downloaded EB native log files")

        return response
