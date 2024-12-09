import json

from sqlmodel import select
from fastapi import HTTPException, status, Depends
from enums.payment_type import PaymentStatus
from models.payment import Payment
from utils.mysqldb import get_mysql_session
from utils.kafka_config import KafkaConfig, get_kafka
from utils.logger import Logger


class PaymentService:
    
    def __init__(self, kafka_config: KafkaConfig , logger: Logger):
        self.kafka_config = kafka_config
        self._logger = logger
        self._ready_approval_topic = "reservation.ready.approval"
        self._ready_fail_topic = "reservation.ready.fail"
        self._payment_approval_topic = "reservation.payment.approval"

        self.topic_handlers = {
            self._payment_approval_topic: self.start_payment_approval
        }
        self.consumer_groups = {
            self._payment_approval_topic: "payment_group"
        }

    async def initialize_consumers(self):
        # 토픽별 컨슈머 초기화
        for topic, group_id in self.consumer_groups.items():
            self.kafka_config.start_consumer(
                topic=topic,
                group_id=group_id,
                message_handler=self.topic_handlers[topic]
            )

        self._logger.info(f"컨슈머 초기화 토픽: {topic}, 그룹: {group_id}")
        
        # 메세지 소비 시작
        await self.kafka_config.start_consuming()

    # pub: 결제 준비 성공
    async def ready_approval(self, data: str):
        await self.kafka_config.produce_message(self._ready_approval_topic, data)

    # pub: 결제 실패
    async def ready_fail(self, data: str):
        await self.kafka_config.produce_message(self._ready_fail_topic, data)

    # pub: 결제 성공
    async def payment_approval(self, data: str):
        await self.kafka_config.produce_message(self._payment_approval_topic, data)

    # sub: 결제 성공 처리
    async def start_payment_approval(self, message: str):
        self._logger.info("테스트 성공")
        self._logger.info(message)
        try:
            data = json.loads(message)

            async for session in get_mysql_session():
                statement = select(Payment).filter(Payment.order_number == data.get("order_number"))
                result = await session.execute(statement)
                payment = result.scalars().first()

                if not payment:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="잘못된 접근입니다.",
                    )
                payment.p_status = PaymentStatus.COMPLETED
                await session.commit()
                self._logger.info("결제 성공 처리 완료")

        except Exception as e:
            self._logger.error(f"결제 정보 업데이트 중 오류가 발생했습니다: {e}")

async def get_payment_service(kafka_config: KafkaConfig = Depends(get_kafka), logger: Logger = Depends(Logger.setup_logger)):
    return PaymentService(kafka_config, logger)