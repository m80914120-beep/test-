from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import logging

from app.core.database import get_read_db, get_write_db
from app.api.tenants import router as tenants_router
from app.api.branches import router as branches_router
from app.api.cameras import router as cameras_router
from app.api.payments import router as payments_router

# إعداد السجلات (Logging)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eye_of_ai")

app = FastAPI(
    title="عين الذكاء (Eye of AI) API",
    description="البوابة الخلفية لمنصة SaaS لمراقبة المنشآت بالذكاء الاصطناعي",
    version="1.0.0"
)

# تفعيل CORS للسماح للوحة التحكم (React/Next.js) بالاتصال بالـ API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # يفضل تخصيصه في الإنتاج
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# تضمين مسارات النظام الفرعية (API Routers)
app.include_router(tenants_router)
app.include_router(branches_router)
app.include_router(cameras_router)
app.include_router(payments_router)

@app.get("/")
async def root():
    return {
        "app": "Eye of AI Central API",
        "status": "running",
        "version": "1.0.0"
    }

# 1. اختبار اتصال خادم القراءة (Read Database Connection)
@app.get("/health/read-db")
async def health_read_db(db: AsyncSession = Depends(get_read_db)):
    try:
        result = await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "read_replica_connected", "data": result.scalar()}
    except Exception as e:
        logger.error(f"Read DB connection error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Read DB Connection failed: {str(e)}")

# 2. اختبار اتصال خادم الكتابة (Write Database Connection)
@app.post("/health/write-db")
async def health_write_db(db: AsyncSession = Depends(get_write_db)):
    try:
        result = await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "write_master_connected", "data": result.scalar()}
    except Exception as e:
        logger.error(f"Write DB connection error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Write DB Connection failed: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
