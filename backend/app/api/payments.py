from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from app.core.database import get_write_db
from app.services.payment import PaymentGatewayService

router = APIRouter(prefix="/payments", tags=["Mock Payments"])
payment_service = PaymentGatewayService()

class CheckoutRequest(BaseModel):
    tenant_id: str
    amount: float
    method: str # zain_cash, asiacell_cash

class CheckoutResponse(BaseModel):
    transaction_id: str
    checkout_url: str
    amount: float
    method: str

class CallbackVerifyRequest(BaseModel):
    transaction_id: str
    signature: str
    amount: float

@router.post("/checkout", response_model=CheckoutResponse)
async def create_payment_session(request: CheckoutRequest, db: AsyncSession = Depends(get_write_db)):
    """
    إنشاء جلسة دفع سريعة للزبون وحفظ المعاملة كمعلقة (Pending)
    """
    # 1. التحقق من وجود المستأجر
    tenant_query = text("SELECT name FROM tenants WHERE id = :tenant_id")
    tenant_res = await db.execute(tenant_query, {"tenant_id": request.tenant_id})
    if not tenant_res.fetchone():
        raise HTTPException(status_code=404, detail="Tenant not found.")

    # 2. إنشاء الجلسة من بوابة الدفع التجريبية
    session = payment_service.create_payment_session(request.tenant_id, request.amount, request.method)
    
    # 3. حفظ المعاملة في جدولPayments
    insert_query = text("""
        INSERT INTO payments (tenant_id, amount, payment_status, gateway_transaction_id)
        VALUES (:tenant_id, :amount, 'pending', :transaction_id)
    """)
    
    try:
        await db.execute(insert_query, {
            "tenant_id": request.tenant_id,
            "amount": request.amount,
            "transaction_id": session["transaction_id"]
        })
        
        return CheckoutResponse(
            transaction_id=session["transaction_id"],
            checkout_url=session["checkout_url"],
            amount=session["amount"],
            method=session["method"]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/callback-verify")
async def verify_payment_callback(request: CallbackVerifyRequest, db: AsyncSession = Depends(get_write_db)):
    """
    التحقق وتأكيد استلام الدفعة من بوابة الدفع برمجياً وتمديد صلاحية المستأجر تلقائياً
    """
    # 1. التحقق الفني من التوقيع
    is_valid = payment_service.verify_payment_callback(
        request.transaction_id, 
        request.signature, 
        request.amount
    )
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid digital signature or parameters.")

    # 2. الاستعلام عن تفاصيل المعاملة في جدول المدفوعات
    payment_query = text("""
        SELECT tenant_id, payment_status FROM payments 
        WHERE gateway_transaction_id = :transaction_id
    """)
    payment_res = await db.execute(payment_query, {"transaction_id": request.transaction_id})
    payment_row = payment_res.fetchone()
    
    if not payment_row:
        raise HTTPException(status_code=404, detail="Transaction record not found in database.")
        
    tenant_id, current_status = payment_row[0], payment_row[1]
    
    if current_status == "completed":
        return {"status": "success", "message": "Payment was already processed and verified."}

    # 3. تحديث حالة الدفع إلى مكتمل وتمديد اشتراك العميل 30 يوماً
    new_expiry = datetime.utcnow() + timedelta(days=30)
    
    update_payment = text("""
        UPDATE payments SET payment_status = 'completed', updated_at = CURRENT_TIMESTAMP
        WHERE gateway_transaction_id = :transaction_id
    """)
    
    update_tenant = text("""
        UPDATE tenants 
        SET expires_at = :new_expiry, status = 'active', updated_at = CURRENT_TIMESTAMP
        WHERE id = :tenant_id
    """)
    
    try:
        # تحديث جدول المدفوعات وجدول المستأجرين في نفس المعاملة (Transaction)
        await db.execute(update_payment, {"transaction_id": request.transaction_id})
        await db.execute(update_tenant, {"new_expiry": new_expiry, "tenant_id": tenant_id})
        
        return {
            "status": "success", 
            "message": "Payment verified successfully. Tenant subscription extended by 30 days.",
            "tenant_id": tenant_id,
            "expires_at": new_expiry
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
