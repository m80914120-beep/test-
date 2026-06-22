from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional
import os
import shutil

from app.core.database import get_write_db, get_read_db
from app.services.face_rec import FaceRecognitionService

router = APIRouter(prefix="/blacklist", tags=["Face Blacklist & Auth Rules"])
face_service = FaceRecognitionService()

class AuthRuleCreate(BaseModel):
    tenant_id: str
    branch_id: str
    camera_id: str
    face_id: str
    zone_name: str
    is_allowed: bool = True

class BlacklistFaceResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    image_url: Optional[str]

@router.post("/faces", response_model=BlacklistFaceResponse, status_code=status.HTTP_201_CREATED)
async def add_blacklist_face(
    tenant_id: str = Form(...),
    name: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_write_db)
):
    """
    إضافة وجه جديد للقائمة السوداء واستخراج البصمة (Embedding) وحفظها بـ pgvector
    """
    # 1. حفظ الصورة مؤقتاً لمعالجتها
    temp_dir = "/tmp/blacklist_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{tenant_id}_{file.filename}")
    
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # 2. استخراج ناقل الميزات (Embedding)
    embedding = face_service.extract_face_embedding(temp_path)
    if not embedding:
        raise HTTPException(status_code=400, detail="Could not detect or extract face from image.")

    # 3. حفظ بصمة الوجه في قاعدة البيانات بـ pgvector
    # نقوم بتحويل الناقل لصيغة pgvector النصية: '[v1, v2, ...]'
    vector_str = f"[{','.join(map(str, embedding))}]"
    
    # محاكاة حفظ مسار الصورة النهائي
    image_url = f"/var/eye_of_ai/blacklist/{tenant_id}/{file.filename}"
    
    insert_query = text("""
        INSERT INTO blacklist_faces (tenant_id, name, face_embedding, image_url)
        VALUES (:tenant_id, :name, :vector_str, :image_url)
        RETURNING id, tenant_id, name, image_url
    """)
    
    try:
        result = await db.execute(insert_query, {
            "tenant_id": tenant_id,
            "name": name,
            "vector_str": vector_str,
            "image_url": image_url
        })
        row = result.fetchone()
        
        # تنظيف الملف المؤقت
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        return BlacklistFaceResponse(
            id=str(row[0]),
            tenant_id=str(row[1]),
            name=row[2],
            image_url=row[3]
        )
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/authorize")
async def create_authorization_rule(rule: AuthRuleCreate, db: AsyncSession = Depends(get_write_db)):
    """
    تحديد قواعد تفويض حركة الأشخاص (مثال: فلان مصرح له دخول الكاشير، بينما غيره يطلق إنذاراً)
    """
    # 1. التحقق من وجود الوجه
    check_face = text("SELECT id FROM blacklist_faces WHERE id = :face_id")
    res = await db.execute(check_face, {"face_id": rule.face_id})
    if not res.fetchone():
        raise HTTPException(status_code=404, detail="Face record not found in database.")

    insert_query = text("""
        INSERT INTO authorized_rules (tenant_id, branch_id, camera_id, face_id, zone_name, is_allowed)
        VALUES (:tenant_id, :branch_id, :camera_id, :face_id, :zone_name, :is_allowed)
        RETURNING id
    """)
    
    try:
        result = await db.execute(insert_query, {
            "tenant_id": rule.tenant_id,
            "branch_id": rule.branch_id,
            "camera_id": rule.camera_id,
            "face_id": rule.face_id,
            "zone_name": rule.zone_name,
            "is_allowed": rule.is_allowed
        })
        row = result.fetchone()
        return {"status": "success", "rule_id": str(row[0]), "message": "Authorization rule saved successfully."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
