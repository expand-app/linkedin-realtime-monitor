import logging
import os
import subprocess
from enum import Enum, unique


@unique
class Environment(Enum):
    DEV = 'dev'
    STAGING = 'staging'
    PROD = 'prod'


value_to_environment = {
    env.value: env for env in Environment
}


def get_env() -> Environment:
    env_value = os.environ.get('Env', Environment.STAGING.value)
    logging.info('Read Env from sys environment, got {}'.format(env_value))
    return value_to_environment[env_value]


def is_prod_env():
    return get_env() == Environment.PROD


def is_staging_env():
    return get_env() == Environment.STAGING


def is_local_dev():
    return os.environ.get('LocalDev', 'False') == 'True'
