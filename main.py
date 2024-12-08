import asyncio
from random import randint
from contextlib import asynccontextmanager
import os
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from routers.payment_kafka import payment_kafka_router
from services.payment_service import PaymentService
from utils.database_config import DatabaseConfig
from utils.kafka_config import get_kafka
from utils.logger import Logger


async def start_payment_consumers():
    kafka_config = get_kafka()
    logger = Logger.setup_logger()
    payment_service = PaymentService(kafka_config, logger)
    await payment_service.initialize_consumers()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작될 때 실행할 코드"""
    
    # 환경 설정
    env_type = '.env.development' if os.getenv('APP_ENV') == 'development' else '.env.production'
    load_dotenv(env_type)

    # DB 설정
    database = DatabaseConfig().create_database()
    await database.initialize()

    consumer_task = asyncio.create_task(start_payment_consumers())

    yield
    
    """애플리케이션 종료될 때 실행할 코드 (필요 시 추가)"""
    consumer_task.cancel()
    await asyncio.gather(consumer_task, return_exceptions=True)
    await database.close()


app = FastAPI(lifespan=lifespan, title="결제 API", version="ver.1")

app.include_router(payment_kafka_router, prefix="/api/v1/payments")

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check(logger: Logger = Depends(Logger.setup_logger)) -> dict:
    logger.info('health check')
    return {"status" : "ok"}

# @app.get("/rolldice")
# async def roll_dice(player: str = None, logger: Logger = Depends(Logger.setup_logger)):
#     result = str(randint(1, 6))
#     if player:
#         logger.warning("%s is rolling the dice: %s", player, result)
#     else:
#         logger.warning("Anonymous player is rolling the dice: %s", result)
#     return {"result": result}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 허용하는 URL 넣어야함
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FastAPIInstrumentor.instrument_app(app)

instrumentator = Instrumentator()
instrumentator.instrument(app).expose(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=80, reload=True)
