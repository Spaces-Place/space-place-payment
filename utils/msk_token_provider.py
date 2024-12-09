import os
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

from utils.aws_ssm import ParameterStore
from utils.env_config import get_env_config


class MSKTokenProvider:

    def __init__(self):
        if not hasattr(self, "producer"):  # 인스턴스가 이미 초기화되었는지 확인
            self._env_config = get_env_config()
            self._parameter_store = ParameterStore()

    # TODO: 이거도 뭔가 오류 날 것 같아서 TOOD 해놓음
    def token(self):
        if self._env_config.is_development:
            token, _ = MSKAuthTokenProvider.generate_auth_token(
                os.getenv("REGION_NAME", "ap-northeast-2")
            )
        else:
            token, _ = MSKAuthTokenProvider.generate_auth_token(
                os.getenv("REGION_NAME", "ap-northeast-2"),
                self._parameter_store.get_parameter("KAFKA_ROLE_ARN"),
            )
        return token
