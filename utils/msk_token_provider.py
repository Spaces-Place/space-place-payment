import os
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider


class MSKTokenProvider:
    # TODO: 이거도 뭔가 오류 날 것 같아서 TOOD 해놓음
    def token(self):
        token, _ = MSKAuthTokenProvider.generate_auth_token(
            os.getenv("REGION_NAME", "ap-northeast-2")
        )
        return token
