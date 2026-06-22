from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional

from app.core.database import get_write_db, get_read_db
from app.services.ai_service import AIServiceManager

router = APIRouter(prefix="/rules", tags=["Smart AI Rules Engine"])
ai_manager = AIServiceManager()

class RuleCreate(BaseModel):
    branch_id: str
    camera_id: str
    name: str
    raw_text_command: str # الأمر النصي العراقي/العربي (مثل: نبهني إذا دخل شخص للكاشير بالليل)

class RuleResponse(BaseModel):
    id: str
    branch_id: str
    camera_id: str
    name: str
    raw_text_command: str
    parsed_rule_json: dict
    is_active: bool

@router.post("/", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_smart_rule(rule: RuleCreate, db: AsyncSession = Depends(get_write_db)):
    """
    تحويل أمر نصي حر (عربي/لهجة عراقية) إلى قاعدة مراقبة بصيغة JSON وحفظها في قاعدة البيانات
    """
    # 1. التحقق من وجود الكاميرا والفرع
    check_query = text("""
        SELECT id FROM cameras WHERE id = :camera_id AND branch_id = :branch_id
    """)
    res = await db.execute(check_query, {"camera_id": rule.camera_id, "branch_id": rule.branch_id})
    if not res.fetchone():
        raise HTTPException(status_code=404, detail="Camera or Branch not found.")

    # 2. إرسال الأمر للذكاء الاصطناعي Ollama/Claude لاستخلاص القاعدة
    parsed_json = ai_manager.parse_text_command_to_rule(rule.raw_text_command)
    
    # 3. حفظ القاعدة في قاعدة البيانات
    insert_query = text("""
        INSERT INTO rules (branch_id, camera_id, name, raw_text_command, parsed_rule_json, is_active)
        VALUES (:branch_id, :camera_id, :name, :raw_text_command, :parsed_json, TRUE)
        RETURNING id, branch_id, camera_id, name, raw_text_command, parsed_rule_json, is_active
    """)
    
    try:
        result = await db.execute(insert_query, {
            "branch_id": rule.branch_id,
            "camera_id": rule.camera_id,
            "name": rule.name,
            "raw_text_command": rule.raw_text_command,
            "parsed_json": json.dumps(parsed_json) # حفظ الـ JSONB في Postgres
        })
        row = result.fetchone()
        return RuleResponse(
            id=str(row[0]),
            branch_id=str(row[1]),
            camera_id=str(row[2]),
            name=row[3],
            raw_text_command=row[4],
            parsed_rule_json=row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            is_active=row[6]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/camera/{camera_id}", response_model=List[RuleResponse])
async def list_camera_rules(camera_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    جلب كافة القواعد المربوطة بكاميرا معينة
    """
    query = text("""
        SELECT id, branch_id, camera_id, name, raw_text_command, parsed_rule_json, is_active
        FROM rules WHERE camera_id = :camera_id
    """)
    
    result = await db.execute(query, {"camera_id": camera_id})
    rows = result.fetchall()
    
    return [
        RuleResponse(
            id=str(r[0]),
            branch_id=str(r[1]),
            camera_id=str(r[2]),
            name=r[3],
            raw_text_command=r[4],
            parsed_rule_json=r[5] if isinstance(r[5], dict) else json.loads(r[5]),
            is_active=r[6]
        ) for r in rows
    ]

# تم استيراد مكتبة json هنا لضمان عمل التحويل بنجاح
import json
