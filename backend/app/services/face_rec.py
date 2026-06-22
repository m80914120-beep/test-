import os
import numpy as np
import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("eye_of_ai.face_rec")

class FaceRecognitionService:
    def __init__(self):
        # محاولة استيراد DeepFace للتأكد من توفره
        try:
            from deepface import DeepFace
            self.deepface_available = True
            logger.info("DeepFace library is successfully loaded and active.")
        except ImportError:
            logger.warning("DeepFace library not found. Running in MOCK Mode for face embeddings.")
            self.deepface_available = False

    def extract_face_embedding(self, image_path: str) -> Optional[List[float]]:
        """
        استخراج ميزات الوجه (Face Embedding) بطول 512 من صورة الوجه المكتشفة
        """
        if not self.deepface_available:
            # وضع المحاكاة: توليد بصمة وجه وهمية مستقرة بطول 512 قيمة عشرية عشوائية
            # نستخدم اسم الملف كبذرة لضمان ثبات البصمة لنفس الصورة أثناء الاختبار
            seed = sum(ord(c) for c in os.path.basename(image_path))
            np.random.seed(seed)
            mock_vector = np.random.uniform(-1, 1, 512).tolist()
            # تعديل الطول ليكون 512 ليتناسب مع pgvector في قاعدة البيانات
            return mock_vector

        try:
            from deepface import DeepFace
            # استخراج الميزات باستخدام نموذج Facenet512 الذي يعطي ناقل بـ 512 بعداً
            embeddings = DeepFace.represent(
                img_path=image_path, 
                model_name="Facenet512",
                enforce_detection=True
            )
            if embeddings:
                # نرجع أول ناقل ميزات مكتشف
                return embeddings[0]["embedding"]
            return None
        except Exception as e:
            logger.error(f"Failed to extract face embedding via DeepFace: {str(e)}")
            return None

    async def search_blacklist_face(
        self, 
        tenant_id: str, 
        embedding: List[float], 
        db: AsyncSession, 
        threshold: float = 0.4
    ) -> Optional[Dict[str, Any]]:
        """
        البحث عن مطابقة للوجه في قائمة المحظورين (Blacklist) باستخدامCosine Similarity في pgvector
        معيار التقييم:
        * في pgvector المشغل <=> يعبر عن Cosine Distance.
        * كلما اقتربت المسافة من 0 كان الوجه أقرب للتطابق.
        * نعتبر الوجه متطابقاً إذا كانت المسافة أقل من الـ threshold (الافتراضي 0.4)
        """
        # تحويل القائمة لنص متوافق مع صيغة pgvector [val1, val2, ...]
        vector_str = f"[{','.join(map(str, embedding))}]"

        query = text("""
            SELECT id, name, image_url, face_embedding <=> :vector_str AS distance
            FROM blacklist_faces
            WHERE tenant_id = :tenant_id
            ORDER BY distance ASC
            LIMIT 1
        """)

        try:
            result = await db.execute(query, {
                "vector_str": vector_str,
                "tenant_id": tenant_id
            })
            row = result.fetchone()
            if row:
                face_id, name, image_url, distance = row[0], row[1], row[2], row[3]
                logger.info(f"Face search results - closest match: '{name}', distance: {distance:.4f}")
                # إذا كانت المسافة أصغر من الحد المسموح، هناك تطابق!
                if distance < threshold:
                    return {
                        "matched": True,
                        "face_id": str(face_id),
                        "name": name,
                        "image_url": image_url,
                        "confidence": float(1.0 - distance) # تحويلها لنسبة مئوية من الثقة
                    }
            return {"matched": False, "message": "No matching face found in blacklist."}
        except Exception as e:
            logger.error(f"Failed to query pgvector database for face match: {str(e)}")
            return {"matched": False, "error": str(e)}

    async def verify_zone_authorization(
        self, 
        tenant_id: str, 
        branch_id: str, 
        camera_id: str, 
        face_id: str, 
        zone_name: str, 
        db: AsyncSession
    ) -> bool:
        """
        التحقق مما إذا كان الوجه المكشوف مصرحاً له بالتواجد في منطقة محددة (مثل: فقط فلان يفتح الكاشير)
        """
        query = text("""
            SELECT is_allowed 
            FROM authorized_rules
            WHERE tenant_id = :tenant_id
              AND branch_id = :branch_id
              AND camera_id = :camera_id
              AND face_id = :face_id
              AND zone_name = :zone_name
        """)
        
        try:
            result = await db.execute(query, {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "camera_id": camera_id,
                "face_id": face_id,
                "zone_name": zone_name
            })
            row = result.fetchone()
            if row:
                # نرجع قيمة الترخيص (True إذا مسموح، False إذا ممنوع)
                return row[0]
            # إذا لم توجد قاعدة تخصيص، نعتبر التواجد في المنطقة ممنوعاً بشكل افتراضي لأمان أفضل (Zero Trust)
            return False
        except Exception as e:
            logger.error(f"Error checking zone authorization: {str(e)}")
            return False
