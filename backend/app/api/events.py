from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional
import io

from app.core.database import get_read_db, get_write_db
from app.services.ai_service import AIServiceManager
from app.services.report_generator import SecurityReportGenerator

router = APIRouter(prefix="/events", tags=["Events Logs & Security Reports"])
ai_manager = AIServiceManager()

@router.get("/tenant/{tenant_id}")
async def list_tenant_events(tenant_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    جلب كافة الأحداث المسجلة للمستأجر
    """
    query = text("""
        SELECT e.id, e.event_type, e.status, e.raw_description, e.ai_description, 
               e.created_at, c.name AS camera_name, b.name AS branch_name
        FROM events e
        JOIN cameras c ON e.camera_id = c.id
        JOIN branches b ON e.branch_id = b.id
        WHERE e.tenant_id = :tenant_id
        ORDER BY e.created_at DESC
    """)
    
    try:
        result = await db.execute(query, {"tenant_id": tenant_id})
        rows = result.fetchall()
        
        return [
            {
                "event_id": str(r[0]),
                "event_type": r[1],
                "status": r[2],
                "raw_description": r[3],
                "ai_description": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "camera_name": r[6],
                "branch_name": r[7]
            } for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tenant/{tenant_id}/report/pdf")
async def export_pdf_report(tenant_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    تصدير التقرير الأمني بصيغة PDF يتضمن تحليل الذكاء الاصطناعي للأحداث
    """
    # 1. جلب اسم المستأجر
    tenant_query = text("SELECT name FROM tenants WHERE id = :tenant_id")
    tenant_res = await db.execute(tenant_query, {"tenant_id": tenant_id})
    tenant_row = tenant_res.fetchone()
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    tenant_name = tenant_row[0]

    # 2. جلب الأحداث الأخيرة
    events = await list_tenant_events(tenant_id, db)
    
    # 3. توليد ملخص الأحداث للمستشعر (AI Summary Report)
    # نقوم بتمرير ملخص بسيط للأحداث للـ LLM لصياغة التقرير
    summary_data = [
        {"camera": e["camera_name"], "type": e["event_type"], "time": e["created_at"]}
        for e in events[:20] # نمرر آخر 20 حدثاً فقط لتوفير الباندويث والتوكنز
    ]
    
    ai_summary = ai_manager.generate_security_report(summary_data)
    
    # 4. توليد الـ PDF
    pdf_data = SecurityReportGenerator.generate_pdf_report(tenant_name, events, ai_summary)
    
    # إرجاع ملف الـ PDF كبث للمتصفح للتحميل المباشر
    return StreamingResponse(
        io.BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=security_report_{tenant_id[:8]}.pdf"}
    )

@router.get("/tenant/{tenant_id}/report/xlsx")
async def export_excel_report(tenant_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    تصدير تقرير الأحداث بصيغة Excel
    """
    # 1. جلب اسم المستأجر
    tenant_query = text("SELECT name FROM tenants WHERE id = :tenant_id")
    tenant_res = await db.execute(tenant_query, {"tenant_id": tenant_id})
    tenant_row = tenant_res.fetchone()
    if not tenant_row:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    tenant_name = tenant_row[0]

    # 2. جلب الأحداث
    events = await list_tenant_events(tenant_id, db)
    
    # 3. توليد ملخص بسيط لادراجه في صفحة الملخص
    summary_data = [
        {"camera": e["camera_name"], "type": e["event_type"], "time": e["created_at"]}
        for e in events[:20]
    ]
    ai_summary = ai_manager.generate_security_report(summary_data)

    # 4. توليد الـ Excel
    xlsx_data = SecurityReportGenerator.generate_excel_report(tenant_name, events, ai_summary)
    
    # إرجاع ملف الـ Excel للتحميل المباشر
    return StreamingResponse(
        io.BytesIO(xlsx_data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=security_report_{tenant_id[:8]}.xlsx"}
    )
