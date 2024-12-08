import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from typing import Callable, Dict
from confluent_kafka import Producer, Consumer, KafkaException

from utils.aws_ssm import ParameterStore
from utils.env_config import get_env_config
from utils.logger import Logger


class KafkaConfig:
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(KafkaConfig, cls).__new__(cls)
            cls._instance.__init__(*args, **kwargs)
            
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'producer'):  # 인스턴스가 이미 초기화되었는지 확인
            self._logger = Logger.setup_logger()
            self._env_config = get_env_config()
            self._parameter_store = ParameterStore()
            self.bootstrap_servers = self._get_kafka_server()
            self.producer = Producer({'bootstrap.servers': self.bootstrap_servers})
            self.consumers = {}
            self.executor = ThreadPoolExecutor()
            self._running = False
            self.message_handlers: Dict[str, Callable] = {}

    def _get_kafka_server(self) -> str:
        if self._env_config.is_development:
            return os.getenv('KAFKA_SERVER')
        else:
            return self._parameter_store.get_parameter("KAFKA_SERVER")

    def _produce_message(self, topic: str, message: str):
        self.producer.produce(topic, json.dumps(message).encode('utf-8'))
        self.producer.flush()

    async def produce_message(self, topic: str, message: str):
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(self.executor, self._produce_message, topic, str(message))
        except KafkaException as e:
            self._logger.error(f"메세지 발행 에러: {e}")
            
    # 컨슈머 시작, 메세지 핸들러 등록
    def start_consumer(self, topic: str, group_id: str, message_handler: Callable):
        consumer = Consumer({
            'bootstrap.servers': self.bootstrap_servers,
            'group.id': group_id,
            'auto.offset.reset': 'earliest'
        })
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
                    value = json.loads(msg.value().decode('utf-8'))
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