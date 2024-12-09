import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import socket
from typing import Callable, Dict
from confluent_kafka import Producer, Consumer, KafkaException
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

from utils.aws_ssm import ParameterStore
from utils.env_config import get_env_config
from utils.logger import Logger
from utils.msk_token_provider import MSKTokenProvider


class KafkaConfig:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KafkaConfig, cls).__new__(cls)
            cls._instance.__init__(*args, **kwargs)

        return cls._instance

    def __init__(self):
        if not hasattr(self, "producer"):  # 인스턴스가 이미 초기화되었는지 확인
            self._logger = Logger.setup_logger()
            self._env_config = get_env_config()
            self._parameter_store = ParameterStore()
            self.bootstrap_servers = self._get_kafka_server()
            self.producer = self._get_kafka_producer()
            self.consumers = {}
            self.executor = ThreadPoolExecutor()
            self._running = False
            self.message_handlers: Dict[str, Callable] = {}

    # 환경별 카프카 서버 반환
    def _get_kafka_server(self) -> str:
        if self._env_config.is_development:
            return os.getenv("KAFKA_SERVER")
        else:
            return self._parameter_store.get_parameter("KAFKA_SERVER")

    # 환경별 프로듀서 반환
    def _get_kafka_producer(self) -> Producer:
        if self._env_config.is_development:
            return Producer({"bootstrap.servers": self.bootstrap_servers})
        else:
            tp = MSKTokenProvider()
            return Producer(
                {
                    "bootstrap.servers": self.bootstrap_servers,
                    "security_protocol": "SASL_SSL",
                    "sasl_mechanism": "OAUTHBEARER",
                    "sasl_oauth_token_provider": tp,
                    "client_id": socket.gethostname(),
                }
            )

    # 메세지 실체 전송 로직
    def _produce_message(self, topic: str, message: str):
        self.producer.produce(topic, json.dumps(message).encode("utf-8"))
        self.producer.flush()

    # 메세지 비동기 전송(실제 처리 로직 있어야함 (_produce_message()))
    async def produce_message(self, topic: str, message: str):
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                self.executor, self._produce_message, topic, str(message)
            )
        except KafkaException as e:
            self._logger.error(f"메세지 발행 에러: {e}")

    def _oauth_cb(oauth_config):
        # TODO: access denied 뜰 가능성 높음!!
        # 자격 증명을 ARN이나 EC2 인스턴스에서 가져온다고 함
        # 로그 레벨 DEBUG로 설정하고 (aws_debug_creds: True) 설정하면 아래처럼 나온다 함
        # Credentials Identity: {UserId: ABCD:test124, Account: 1234567890, Arn: arn:aws:sts::1234567890:assumed-role/abc/test124}

        auth_token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(
            os.getenv("REGION_NAME"), aws_debug_creds=True
        )
        return auth_token, expiry_ms / 1000

    # 환경별 컨슈머 반환
    def _get_kafka_consumer(self, group_id: str) -> Consumer:
        if self._env_config.is_development:
            return Consumer(
                {
                    "bootstrap.servers": self.bootstrap_servers,
                    "group.id": group_id,
                    "auto.offset.reset": "earliest",
                }
            )
        else:
            return Consumer(
                {
                    "bootstrap.servers": self.bootstrap_servers,
                    "client.id": socket.gethostname(),
                    "security.protocol": "SASL_SSL",
                    "sasl.mechanisms": "OAUTHBEARER",
                    "oauth_cb": self._oauth_cb,
                    "group.id": group_id,
                    "auto.offset.reset": "earliest",
                }
            )

    # 컨슈머 시작, 메세지 핸들러 등록
    def start_consumer(self, topic: str, group_id: str, message_handler: Callable):
        consumer = self._get_kafka_consumer(group_id)
        consumer.subscribe([topic])
        self.consumers[topic] = consumer
        self.message_handlers[topic] = message_handler

    # 전체 컨슈머 메세지 소비
    async def start_consuming(self):
        self._running = True
        self._logger.info("Starting Kafka consumers...")

        while self._running:
            for topic, consumer in self.consumers.items():
                try:
                    msg = consumer.poll(1.0)
                    if msg is None:
                        continue
                    if msg.error():
                        self._logger.error(f"메세지 소비 에러: {msg.error()}")
                        continue

                    # 처리 로직
                    value = json.loads(msg.value().decode("utf-8"))
                    handler = self.message_handlers.get(topic)
                    if handler:
                        await handler(value)

                except Exception as e:
                    self._logger.error(f"메세지 처리 중 오류 발생: {e}")
            await asyncio.sleep(0.1)

    def close_consumers(self):
        self._running = False
        for consumer in self.consumers.values():
            consumer.close()
        self.consumers.clear()
        self.executor.shutdown()


def get_kafka() -> KafkaConfig:
    return KafkaConfig()
