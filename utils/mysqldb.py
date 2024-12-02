
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from utils.type.db_config_type import DBConfig


class MySQLDatabase:
    """
    DB 연결 및 세션 관리
    """
    _logger = logging.getLogger("")
    _instance = None
    _engine = None
    _session_maker = None

    def __new__(cls, *args):
        if cls._instance is None:
            cls._instance = super(MySQLDatabase, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, db_config: DBConfig = None):
        if not hasattr(self, '_db_config'):
            self._logger.info('데이터 베이스가 초기화 되었습니다.')
            self._logger.info(db_config)
            self._db_config = db_config

    async def initialize(self):
        if not self._engine:
            connection_string = self._build_connection_string()
            self._engine = create_async_engine(
                connection_string,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20
            )
            self._session_maker = sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False
            )

            await self.create_tables()  
            self._logger.info(connection_string)

    async def create_tables(self):
        async with self.session() as session:
            with open('setup.sql', 'r', encoding='utf-8') as file:
                sql_commands = file.read().split(';')
                
            for command in sql_commands:
                if command.strip():
                    await session.execute(text(command.strip()))

            self._logger.info('테이블이 초기화 되었습니다.')
    
    def _build_connection_string(self) -> str:
        host = self._db_config.host
        dbname = self._db_config.dbname
        username = self._db_config.username
        password = self._db_config.password
        return f"mysql+aiomysql://{username}:{password}@{host}/{dbname}"
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        if not self._session_maker:
            await self.initialize()
            
        async with self._session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def close(self):
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_maker = None
            self._logger.info('DB 커넥션 해제')

async def get_mysql_session() -> AsyncGenerator[AsyncSession, None]:
    from utils.database_config import DatabaseConfig
    
    db = MySQLDatabase(DatabaseConfig().get_db_config())
    async with db.session() as session:
        yield session