from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional

from app.core.database import get_write_db, get_read_db
from app.services.vpn_service import HeadscaleVPNManager

router = APIRouter(prefix="/branches", tags=["Branches & VPN Management"])
vpn_manager = HeadscaleVPNManager()

class BranchCreate(BaseModel):
    tenant_id: str
    name: str
    address: Optional[str] = None

class BranchResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    address: Optional[str]
    vpn_ip: Optional[str]
    vpn_node_name: Optional[str]
    status: str

class BranchRegisterKeyResponse(BaseModel):
    branch_id: str
    vpn_node_name: str
    preauth_key: str
    connection_command: str

@router.post("/", response_model=BranchRegisterKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_branch(branch: BranchCreate, db: AsyncSession = Depends(get_write_db)):
    """
    إنشاء فرع جديد وتوليد مفتاح VPN خاص لتوصيل أجهزة العميل بالخادم السحابي
    """
    # توليد اسم عقدة فريد للفرع في شبكة الـ VPN
    vpn_node_name = f"node-{branch.tenant_id[:4]}-{branch.name.replace(' ', '-').lower()[:15]}"
    
    # 1. توليد مفتاح التسجيل المسبق من Headscale
    preauth_key = vpn_manager.generate_branch_auth_key(branch.tenant_id, vpn_node_name)
    if not preauth_key:
        raise HTTPException(status_code=500, detail="Failed to generate VPN auth key.")

    # 2. حفظ الفرع في قاعدة البيانات
    query = text("""
        INSERT INTO branches (tenant_id, name, address, vpn_node_name, status)
        VALUES (:tenant_id, :name, :address, :vpn_node_name, 'offline')
        RETURNING id
    """)
    
    try:
        result = await db.execute(query, {
            "tenant_id": branch.tenant_id,
            "name": branch.name,
            "address": branch.address,
            "vpn_node_name": vpn_node_name
        })
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=500, detail="Failed to save branch to database.")
            
        branch_id = str(row[0])
        
        # صياغة أمر التوصيل الجاهز للتشغيل عند العميل
        login_server = "https://vpn.eyeofai.com" # عنوان السيرفر المركزي
        connection_command = f"tailscale up --login-server {login_server} --authkey {preauth_key}"
        
        return BranchRegisterKeyResponse(
            branch_id=branch_id,
            vpn_node_name=vpn_node_name,
            preauth_key=preauth_key,
            connection_command=connection_command
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/tenant/{tenant_id}", response_model=List[BranchResponse])
async def list_branches(tenant_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    سرد كافة فروع مستأجر معين
    """
    query = text("""
        SELECT id, tenant_id, name, address, vpn_ip, vpn_node_name, status
        FROM branches WHERE tenant_id = :tenant_id
    """)
    
    result = await db.execute(query, {"tenant_id": tenant_id})
    rows = result.fetchall()
    
    return [
        BranchResponse(
            id=str(r[0]),
            tenant_id=str(r[1]),
            name=r[2],
            address=r[3],
            vpn_ip=r[4],
            vpn_node_name=r[5],
            status=r[6]
        ) for r in rows
    ]

@router.post("/{branch_id}/sync-vpn", response_model=BranchResponse)
async def sync_branch_vpn_status(branch_id: str, db: AsyncSession = Depends(get_write_db)):
    """
    مزامنة حالة الـ VPN للفرع والاستعلام عن الـ IP الافتراضي الممنوح للجهاز
    """
    # جلب معلومات الفرع الحالية
    query = text("""
        SELECT tenant_id, vpn_node_name FROM branches WHERE id = :branch_id
    """)
    result = await db.execute(query, {"branch_id": branch_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found.")
        
    tenant_id, vpn_node_name = row[0], row[1]
    
    # الاستعلام من Headscale عن الـ IP الحالي
    vpn_ip = vpn_manager.get_branch_ip(str(tenant_id), vpn_node_name)
    
    if vpn_ip:
        # تحديث حالة الفرع كـ online وحفظ الـ IP في قاعدة البيانات
        update_query = text("""
            UPDATE branches 
            SET vpn_ip = :vpn_ip, status = 'online', updated_at = CURRENT_TIMESTAMP
            WHERE id = :branch_id
            RETURNING id, tenant_id, name, address, vpn_ip, vpn_node_name, status
        """)
        res = await db.execute(update_query, {"vpn_ip": vpn_ip, "branch_id": branch_id})
    else:
        # إذا لم يُعثر على الـ IP نعتبره offline
        update_query = text("""
            UPDATE branches 
            SET status = 'offline', updated_at = CURRENT_TIMESTAMP
            WHERE id = :branch_id
            RETURNING id, tenant_id, name, address, vpn_ip, vpn_node_name, status
        """)
        res = await db.execute(update_query, {"branch_id": branch_id})
        
    updated_row = res.fetchone()
    return BranchResponse(
        id=str(updated_row[0]),
        tenant_id=str(updated_row[1]),
        name=updated_row[2],
        address=updated_row[3],
        vpn_ip=updated_row[4],
        vpn_node_name=updated_row[5],
        status=updated_row[6]
    )
