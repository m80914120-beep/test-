from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta

from app.core.database import get_write_db, get_read_db

router = APIRouter(prefix="/tenants", tags=["Tenants & Subscriptions"])

class TenantCreate(BaseModel):
    name: str
    business_type: str
    plan: str = "basic" # basic, advanced, professional

class TenantResponse(BaseModel):
    id: str
    name: str
    business_type: str
    plan: str
    status: str
    expires_at: Optional[datetime]

@router.post("/", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(tenant: TenantCreate, db: AsyncSession = Depends(get_write_db)):
    """
    إنشاء حساب مستأجر جديد وتفعيل اشتراك افتراضي لمدة 30 يوم
    """
    expires_at = datetime.utcnow() + timedelta(days=30)
    
    query = text("""
        INSERT INTO tenants (name, business_type, plan, status, expires_at)
        VALUES (:name, :business_type, :plan, 'active', :expires_at)
        RETURNING id, name, business_type, plan, status, expires_at
    """)
    
    try:
        result = await db.execute(query, {
            "name": tenant.name,
            "business_type": tenant.business_type,
            "plan": tenant.plan,
            "expires_at": expires_at
        })
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="Failed to create tenant.")
            
        return TenantResponse(
            id=str(row[0]),
            name=row[1],
            business_type=row[2],
            plan=row[3],
            status=row[4],
            expires_at=row[5]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    جلب بيانات المستأجر
    """
    query = text("""
        SELECT id, name, business_type, plan, status, expires_at
        FROM tenants WHERE id = :tenant_id
    """)
    
    result = await db.execute(query, {"tenant_id": tenant_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant not found.")
        
    return TenantResponse(
        id=str(row[0]),
        name=row[1],
        business_type=row[2],
        plan=row[3],
        status=row[4],
        expires_at=row[5]
    )
