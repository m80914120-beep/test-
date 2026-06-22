import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# جلب روابط الاتصال بقاعدة البيانات من متغيرات البيئة
# الرابط المخصص للكتابة والتعديل (Primary/Master Node)
WRITE_DB_URL = os.getenv(
    "WRITE_DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/eye_of_ai"
)

# الرابط المخصص للقراءة فقط (Read Replica)
# في حال عدم وجود خادم قراءة منفصل، نعتمد على خادم الكتابة كخيار احتياطي
READ_DB_URL = os.getenv("READ_DATABASE_URL", WRITE_DB_URL)

# إنشاء محركات الاتصال (Engines) مع تفعيل فحص الاتصال التلقائي (pool_pre_ping)
write_engine = create_async_engine(
    WRITE_DB_URL, 
    pool_pre_ping=True, 
    echo=False
)

read_engine = create_async_engine(
    READ_DB_URL, 
    pool_pre_ping=True, 
    echo=False
)

# إنشاء صانع الجلسات (Session Makers) لكل محرك
async_session_write = async_sessionmaker(
    write_engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

async_session_read = async_sessionmaker(
    read_engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

Base = declarative_base()

# 1. تابع حقن الاعتمادية لعمليات الكتابة والتعديل (FastAPI Dependency for Writes)
async def get_write_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_write() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 2. تابع حقن الاعتمادية لعمليات الاستعلام والقراءة (FastAPI Dependency for Reads)
async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_read() as session:
        try:
            yield session
        finally:
            await session.close()
