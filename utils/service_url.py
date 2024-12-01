import os
from utils.aws_ssm import ParameterStore
from utils.env_config import get_env_config


class ServiceUrlConfig:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ServiceUrlConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        self._env_config = get_env_config()
        self._parameter_store = ParameterStore()
        self._urls = {}
        self._initialize_urls()

    def _initialize_urls(self):
        if self._env_config.is_development:
            self._urls = {
                'reservation': os.getenv('RESERVATION_URL'),
                'payment': os.getenv('PAYMENT_URL'),
                'space': os.getenv('SPACE_URL'),
            }
        else:
            self._urls = {
                'reservation': self._parameter_store.get_parameter('RESERVATION_URL'),
                'payment': self._parameter_store.get_parameter('PAYMENT_URL'),
                'space': self._parameter_store.get_parameter('SPACE_URL'),
            }

    @property
    def reservation_url(self) -> str:
        return self._urls.get('reservation')

    @property
    def payment_url(self) -> str:
        return self._urls.get('payment')

    @property
    def space_url(self) -> str:
        return self._urls.get('space')