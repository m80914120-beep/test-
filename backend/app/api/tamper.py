from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Dict, Any

from app.core.database import get_write_db
from app.services.tamper import CameraTamperDetector

router = APIRouter(prefix="/tamper", tags=["Tamper & Blackout Detection"])
tamper_detector = CameraTamperDetector()

@router.post("/camera/{camera_id}/check")
async def check_camera_tamper(camera_id: str, db: AsyncSession = Depends(get_write_db)):
    """
    فحص التلاعب بالكاميرا برمجياً وكشف هوية الفاعل في حال انقطاع البث
    """
    # 1. جلب بيانات الكاميرا والفرع والمستأجر
    query = text("""
        SELECT c.name, c.rtsp_url, b.id, b.tenant_id
        FROM cameras c
        JOIN branches b ON c.branch_id = b.id
        WHERE c.id = :camera_id
    """)
    res = await db.execute(query, {"camera_id": camera_id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Camera not found.")
        
    camera_name, rtsp_url, branch_id, tenant_id = row[0], row[1], row[2], row[3]
    
    # 2. تشغيل خدمة فحص التلاعب
    tamper_result = await tamper_detector.detect_tampering_event(
        str(tenant_id), str(branch_id), camera_id, camera_name, rtsp_url, db
    )
    
    # تحديث حالة الكاميرا في الداتابيس في حال انقطاعها
    if tamper_result["tampered"]:
        update_query = text("""
            UPDATE cameras SET status = 'offline', updated_at = CURRENT_TIMESTAMP
            WHERE id = :camera_id
        """)
        await db.execute(update_query, {"camera_id": camera_id})
        
    return tamper_result

@router.post("/branch/{branch_id}/check-blackout")
async def check_site_blackout(branch_id: str, db: AsyncSession = Depends(get_write_db)):
    """
    التحقق من حدوث تعتيم كلي (Blackout) وانقطاع الطاقة بالكامل عن الفرع
    """
    # 1. تشغيل الفحص التراكمي
    blackout_result = await tamper_detector.detect_site_blackout(
        "", branch_id, db # يتم جلب المستأجر داخلياً من الفرع
    )
    
    # تحديث حالة الفرع كـ offline في قاعدة البيانات في حال حدوث التعتيم الكامل
    if blackout_result.get("blackout"):
        update_branch = text("""
            UPDATE branches SET status = 'offline', updated_at = CURRENT_TIMESTAMP
            WHERE id = :branch_id
        """)
        update_cams = text("""
            UPDATE cameras SET status = 'offline', updated_at = CURRENT_TIMESTAMP
            WHERE branch_id = :branch_id
        """)
        await db.execute(update_branch, {"branch_id": branch_id})
        await db.execute(update_cams, {"branch_id": branch_id})
        
    return blackout_result
