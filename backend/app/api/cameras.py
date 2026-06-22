from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional
import urllib.parse

from app.core.database import get_write_db, get_read_db
from app.services.docker_swarm import DockerSwarmManager
from app.services.video_utils import probe_rtsp_stream

router = APIRouter(prefix="/cameras", tags=["Cameras & Frigate Deployment"])
swarm_manager = DockerSwarmManager()

class CameraCreate(BaseModel):
    branch_id: str
    name: str
    rtsp_path: str # مسار البث المباشر (مثل: h264/ch1/main)
    width: Optional[int] = 1280
    height: Optional[int] = 720

class CameraResponse(BaseModel):
    id: str
    branch_id: str
    name: str
    rtsp_url: str
    width: int
    height: int
    status: str

@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def add_camera(camera: CameraCreate, db: AsyncSession = Depends(get_write_db)):
    """
    إضافة كاميرا جديدة للفرع. يتم بناء رابط البث تلقائياً بالاعتماد على الـ VPN IP الخاص بالفرع
    """
    # 1. جلب بيانات الفرع للوصول للـ VPN IP
    branch_query = text("""
        SELECT tenant_id, vpn_ip, status FROM branches WHERE id = :branch_id
    """)
    result = await db.execute(branch_query, {"branch_id": camera.branch_id})
    branch_row = result.fetchone()
    if not branch_row:
        raise HTTPException(status_code=404, detail="Branch not found.")
        
    tenant_id, vpn_ip, branch_status = branch_row[0], branch_row[1], branch_row[2]
    if not vpn_ip:
        raise HTTPException(
            status_code=400, 
            detail="Branch is not connected to VPN yet. Connect the branch PC first to get a VPN IP."
        )

    # 2. بناء رابط الـ RTSP الآمن المار عبر النفق المغلق
    # مثال: rtsp://100.64.0.12:554/h264/ch1/main
    clean_path = camera.rtsp_path.lstrip("/")
    rtsp_url = f"rtsp://{vpn_ip}:554/{clean_path}"

    # 3. حفظ الكاميرا في الداتابيس
    insert_query = text("""
        INSERT INTO cameras (branch_id, name, rtsp_url, width, height, status)
        VALUES (:branch_id, :name, :rtsp_url, :width, :height, 'offline')
        RETURNING id, branch_id, name, rtsp_url, width, height, status
    """)
    
    try:
        res = await db.execute(insert_query, {
            "branch_id": camera.branch_id,
            "name": camera.name,
            "rtsp_url": rtsp_url,
            "width": camera.width,
            "height": camera.height
        })
        row = res.fetchone()
        return CameraResponse(
            id=str(row[0]),
            branch_id=str(row[1]),
            name=row[2],
            rtsp_url=row[3],
            width=row[4],
            height=row[5],
            status=row[6]
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/branch/{branch_id}/deploy")
async def deploy_branch_frigate(branch_id: str, db: AsyncSession = Depends(get_write_db)):
    """
    تجميع إعدادات الكاميرات الحالية وتشغيل حاوية Frigate الخاصة بالفرع برمجياً
    """
    # 1. جلب بيانات الفرع والمستأجر
    branch_query = text("""
        SELECT tenant_id, status FROM branches WHERE id = :branch_id
    """)
    br_res = await db.execute(branch_query, {"branch_id": branch_id})
    br_row = br_res.fetchone()
    if not br_row:
        raise HTTPException(status_code=404, detail="Branch not found.")
    
    tenant_id = str(br_row[0])

    # 2. جلب كافة الكاميرات المضافة للفرع
    cameras_query = text("""
        SELECT name, rtsp_url, width, height FROM cameras WHERE branch_id = :branch_id
    """)
    cams_res = await db.execute(cameras_query, {"branch_id": branch_id})
    cams_rows = cams_res.fetchall()
    
    if not cams_rows:
        raise HTTPException(status_code=400, detail="Cannot deploy Frigate with zero cameras. Add at least one camera first.")

    cameras_list = [
        {"name": r[0], "rtsp_url": r[1], "width": r[2], "height": r[3]}
        for r in cams_rows
    ]

    # 3. إطلاق الحاوية عبر Docker Swarm/Standalone Manager
    deploy_result = swarm_manager.deploy_frigate_instance(tenant_id, branch_id, cameras_list)
    
    if deploy_result.get("status") == "error":
        raise HTTPException(status_code=500, detail=deploy_result.get("message"))
        
    return deploy_result

@router.get("/branch/{branch_id}/status")
async def get_frigate_status(branch_id: str, db: AsyncSession = Depends(get_read_db)):
    """
    الاستعلام عن حالة تشغيل حاوية Frigate الخاصة بالفرع
    """
    branch_query = text("SELECT tenant_id FROM branches WHERE id = :branch_id")
    res = await db.execute(branch_query, {"branch_id": branch_id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found.")
        
    tenant_id = str(row[0])
    return swarm_manager.get_instance_status(tenant_id, branch_id)

@router.post("/{camera_id}/test-connection")
async def test_camera_connection(camera_id: str, db: AsyncSession = Depends(get_write_db)):
    """
    زر اختبار الاتصال: فحص البث المباشر وجودة الاتصال عبر FFprobe وتحديث حالة الكاميرا
    """
    query = text("SELECT name, rtsp_url FROM cameras WHERE id = :camera_id")
    res = await db.execute(query, {"camera_id": camera_id})
    row = res.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Camera not found.")
        
    name, rtsp_url = row[0], row[1]
    
    logger.info(f"Testing stream connection to camera '{name}' via: {rtsp_url}")
    # تشغيل الفحص الحقيقي
    probe_result = probe_rtsp_stream(rtsp_url)
    
    # تحديث حالة الكاميرا في الداتابيس بناءً على نتيجة الفحص
    status_str = "online" if probe_result["connected"] else "offline"
    update_query = text("""
        UPDATE cameras 
        SET status = :status, updated_at = CURRENT_TIMESTAMP
        WHERE id = :camera_id
    """)
    await db.execute(update_query, {"status": status_str, "camera_id": camera_id})
    
    # إعداد الـ Response
    if probe_result["connected"]:
        return {
            "camera_id": camera_id,
            "rtsp_url": rtsp_url,
            "status": "online",
            "codec": probe_result.get("codec"),
            "width": probe_result.get("width"),
            "height": probe_result.get("height"),
            "fps": probe_result.get("fps"),
            "message": probe_result.get("message")
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "camera_id": camera_id,
                "rtsp_url": rtsp_url,
                "status": "offline",
                "message": probe_result.get("message")
            }
        )
