import logging
import requests
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.video_utils import probe_rtsp_stream
from app.services.face_rec import FaceRecognitionService

logger = logging.getLogger("eye_of_ai.tamper")

class CameraTamperDetector:
    def __init__(self):
        self.face_service = FaceRecognitionService()

    async def detect_tampering_event(
        self, 
        tenant_id: str, 
        branch_id: str, 
        camera_id: str, 
        camera_name: str, 
        rtsp_url: str, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        الوظيفة الأولى: كشف التلاعب الفردي بالكاميرات
        يتم استدعاء هذه الوظيفة عند اكتشاف خلل في البث أو حدث تلاعب
        """
        # 1. التحقق من سلامة البث عبر ffprobe
        probe = probe_rtsp_stream(rtsp_url)
        if probe["connected"]:
            return {"tampered": False, "message": "Camera stream is healthy."}

        # البث مقطوع! نحاول تحديد آخر صورة قبل انقطاع البث مباشرة
        # Frigate تقدم رابطاً لجلب آخر لقطة نشطة قبل الانقطاع
        # رابط افتراضي: http://frigate-service:5000/api/<camera_name>/latest.jpg
        frigate_latest_url = f"http://frigate-{tenant_id[:8]}-{branch_id[:8]}:5000/api/{camera_name}/latest.jpg"
        temp_img_path = f"/tmp/latest_{camera_id}.jpg"
        
        culprit_name = "مجهول"
        matched_face = None

        try:
            # محاولة تنزيل آخر إطار مسجل
            response = requests.get(frigate_latest_url, timeout=3)
            if response.status_code == 200:
                os.makedirs(os.path.dirname(temp_img_path), exist_ok=True)
                with open(temp_img_path, "wb") as f:
                    f.write(response.content)
                
                # تشغيل التعرف على الوجه لمعرفة الشخص المتسبب بالتخريب إن ظهر
                embedding = self.face_service.extract_face_embedding(temp_img_path)
                if embedding:
                    match_result = await self.face_service.search_blacklist_face(tenant_id, embedding, db)
                    if match_result and match_result.get("matched"):
                        culprit_name = match_result.get("name")
                        matched_face = match_result
        except Exception as e:
            logger.warning(f"Could not retrieve latest frame from Frigate for camera {camera_name}: {str(e)}")

        # إرجاع تفاصيل حدث التلاعب ومحاولة تحديد الهوية
        return {
            "tampered": True,
            "camera_id": camera_id,
            "camera_name": camera_name,
            "error_detail": probe.get("message"),
            "culprit_detected": culprit_name,
            "matched_face_details": matched_face,
            "message": f"⚠️ تلاعب بالكاميرا: انقطع البث عن كاميرا {camera_name}. آخر شخص تم رصده: {culprit_name}"
        }

    async def detect_site_blackout(
        self, 
        tenant_id: str, 
        branch_id: str, 
        db: AsyncSession
    ) -> Dict[str, Any]:
        """
        الوظيفة الثانية: كشف انقطاع التيار الكهربائي أو الإنترنت الكامل عن الموقع
        إذا انقطعت كافة كاميرات الفرع معاً وكان اتصال الـ VPN مقطوعاً
        """
        # 1. الاستعلام عن حالة الفرع الحالية في الداتابيس
        branch_query = text("""
            SELECT name, status, vpn_ip FROM branches WHERE id = :branch_id
        """)
        res = await db.execute(branch_query, {"branch_id": branch_id})
        branch_row = res.fetchone()
        if not branch_row:
            return {"blackout": False, "message": "Branch not found."}
            
        branch_name, vpn_status, vpn_ip = branch_row[0], branch_row[1], branch_row[2]

        # 2. جلب جميع الكاميرات الخاصة بهذا الفرع
        cameras_query = text("""
            SELECT id, name, rtsp_url FROM cameras WHERE branch_id = :branch_id
        """)
        cams_res = await db.execute(cameras_query, {"branch_id": branch_id})
        cams = cams_res.fetchall()

        if not cams:
            return {"blackout": False, "message": "No cameras configured on this branch."}

        # 3. فحص اتصال كل الكاميرات
        all_failed = True
        failed_details = []
        
        for cam in cams:
            cam_id, cam_name, rtsp_url = cam[0], cam[1], cam[2]
            probe = probe_rtsp_stream(rtsp_url)
            if probe["connected"]:
                all_failed = False
                break
            failed_details.append({"camera_id": str(cam_id), "name": cam_name})

        # 4. إذا كانت كل الكاميرات متعطلة والـ VPN مقطوع (status != online)
        # هذا يعني انقطاع الكهرباء أو النت بالكامل عن المنشأة
        if all_failed and vpn_status != "online":
            logger.warning(f"Power outage or general internet loss detected for branch: '{branch_name}'")
            return {
                "blackout": True,
                "branch_id": branch_id,
                "branch_name": branch_name,
                "failed_cameras_count": len(failed_details),
                "message": f"🚨 انقطاع كلي: تم رصد انقطاع للتيار الكهربائي أو خط الإنترنت بالكامل عن فرع '{branch_name}' (انقطاع اتصال الـ VPN وكافة الكاميرات معاً)."
            }

        return {"blackout": False, "message": "Branch site is partially or fully connected."}
