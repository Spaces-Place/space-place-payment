from contextlib import asynccontextmanager
import logging.config
import os
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from routers.payment import payment_router
from utils.database_config import DatabaseConfig
from utils.logger import Logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 애플리케이션 시작될 때 실행할 코드
    env_type = '.env.development' if os.getenv('APP_ENV') == 'development' else '.env.production'
    load_dotenv(env_type)

    database = DatabaseConfig().create_database()
    await database.initialize()

    yield

    # 애플리케이션 종료될 때 실행할 코드 (필요 시 추가)
    await database.close()


app = FastAPI(lifespan=lifespan, title="결제 API", version="ver.1")

app.include_router(payment_router, prefix="/api/v1/payments")

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check(logger: Logger = Depends(Logger.setup_logger)) -> dict:
    logger.info('health check')
    return {"status" : "ok"}

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
