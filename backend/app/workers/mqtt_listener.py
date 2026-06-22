import os
import json
import logging
import paho.mqtt.client as mqtt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime

from app.core.database import async_session_write
from app.services.ai_service import AIServiceManager
from app.services.face_rec import FaceRecognitionService

logger = logging.getLogger("eye_of_ai.mqtt_worker")

class FrigateMQTTWorker:
    def __init__(self):
        self.ai_service = AIServiceManager()
        self.face_service = FaceRecognitionService()
        
        self.broker_host = os.getenv("MQTT_BROKER_HOST", "localhost")
        self.broker_port = int(os.getenv("MQTT_BROKER_PORT", 1883))
        
        self.client = mqtt.Client(client_id="eye_of_ai_central_worker")
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

    def start(self):
        """
        بدء تشغيل عامل الاستماع لـ MQTT في الخلفية
        """
        try:
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start() # تشغيل حلقة الاستماع في خيط منفصل (Thread)
            logger.info(f"MQTT Listener started. Connected to broker at {self.broker_host}:{self.broker_port}")
        except Exception as e:
            logger.error(f"Failed to start MQTT Listener: {str(e)}. Retrying in background.")

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT Listener stopped.")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Successfully connected to MQTT Broker.")
            # الاشتراك بجميع أحداث حاويات Frigate للمستأجرين والفروع
            # الهيكلية: frigate/{tenant_id}/{branch_id}/events
            client.subscribe("frigate/+/+/events")
            logger.info("Subscribed to topic: frigate/+/+/events")
        else:
            logger.error(f"MQTT connection failed with code: {rc}")

    def on_message(self, client, userdata, msg):
        """
        معالجة الرسائل الواردة عند اكتشاف Frigate لحدث ما
        """
        try:
            topic_parts = msg.topic.split("/")
            if len(topic_parts) < 4:
                return

            tenant_id = topic_parts[1]
            branch_id = topic_parts[2]
            
            payload = json.loads(msg.payload.decode("utf-8"))
            event_type = payload.get("type") # new, update, end
            
            # نحن نهتم بالحدث عند انتهائه (end) لتجميع الإحصائيات الكاملة أو عند إطلاقه (new)
            # للسرعة، نعالج التنبيهات فور إطلاقها (new)
            if event_type in ["new", "end"]:
                event_data = payload.get("after", {})
                self.process_frigate_event(tenant_id, branch_id, event_data, event_type)
                
        except Exception as e:
            logger.error(f"Error parsing MQTT message payload: {str(e)}")

    def process_frigate_event(self, tenant_id: str, branch_id: str, event_data: dict, phase: str):
        """
        تحليل الحدث ومطابقته مع القواعد النشطة في قاعدة البيانات وإرسال التنبيهات
        """
        import asyncio
        # تشغيل الدالة اللامتزامنة داخل خيط MQTT
        asyncio.run(self._async_process_event(tenant_id, branch_id, event_data, phase))

    async def _async_process_event(self, tenant_id: str, branch_id: str, event_data: dict, phase: str):
        event_id = event_data.get("id")
        camera_name = event_data.get("camera")
        detected_object = event_data.get("label") # person, car, etc.
        zones = event_data.get("current_zones", [])
        
        # فتح جلسة اتصال بقاعدة البيانات
        async with async_session_write() as db:
            # 1. جلب الكاميرا المطابقة للفرع للتأكد من هويتها
            cam_query = text("""
                SELECT c.id, c.name FROM cameras c
                JOIN branches b ON c.branch_id = b.id
                WHERE b.id = :branch_id AND c.name = :camera_name
            """)
            cam_res = await db.execute(cam_query, {"branch_id": branch_id, "camera_name": camera_name})
            cam_row = cam_res.fetchone()
            if not cam_row:
                return # كاميرا غير مسجلة
            
            camera_id = cam_row[0]

            # 2. الاستعلام عن القواعد النشطة لهذه الكاميرا
            rules_query = text("""
                SELECT id, name, parsed_rule_json, raw_text_command
                FROM rules
                WHERE camera_id = :camera_id AND is_active = TRUE
            """)
            rules_res = await db.execute(rules_query, {"camera_id": camera_id})
            rules = rules_res.fetchall()

            for rule in rules:
                rule_id, rule_name, rule_json, raw_cmd = rule[0], rule[1], rule[2], rule[3]
                
                # فحص تطابق الكائن المكتشف مع شروط القاعدة
                rule_object = rule_json.get("object", "person")
                rule_zone = rule_json.get("zone", "any")
                
                # التحقق من نوع الكائن والمنطقة
                object_match = (detected_object == rule_object)
                zone_match = (rule_zone == "any" or rule_zone in zones)
                
                # التحقق من الوقت النشط للقاعدة
                time_match = self._check_time_range(rule_json.get("time_range", "always"))

                if object_match and zone_match and time_match:
                    logger.info(f"MATCHED RULE: '{rule_name}' for Event ID: {event_id}")
                    
                    culprit_name = "مجهول"
                    matched_face_id = None
                    is_authorized = True

                    # 3. إذا كان الكائن شخصاً ونريد فحص الهوية والترخيص (Blacklist / Authorization)
                    if detected_object == "person" and phase == "end":
                        # تنزيل لقطة الوجه من حاوية Frigate للفرع
                        # http://frigate-service:5000/api/events/<event_id>/snapshot.jpg
                        snapshot_url = f"http://frigate-{tenant_id[:8]}-{branch_id[:8]}:5000/api/events/{event_id}/snapshot.jpg"
                        temp_path = f"/tmp/snapshot_{event_id}.jpg"
                        
                        # محاكاة حفظ اللقطة واستدعاء فحص الوجه
                        # في بيئة الإنتاج يتم استخدام requests.get(snapshot_url) وتمرير الصورة
                        embedding = self.face_service.extract_face_embedding(temp_path)
                        if embedding:
                            match = await self.face_service.search_blacklist_face(tenant_id, embedding, db)
                            if match and match.get("matched"):
                                matched_face_id = match.get("face_id")
                                culprit_name = match.get("name")
                                # تحقق مما إذا كان مصرحاً له بالتواجد في هذه المنطقة المحددة
                                if matched_face_id:
                                    is_authorized = await self.face_service.verify_zone_authorization(
                                        tenant_id, branch_id, str(camera_id), matched_face_id, rule_zone, db
                                    )
                                    
                    # 4. صياغة الإشعار بالذكاء الاصطناعي
                    event_details = {
                        "event_id": event_id,
                        "camera": camera_name,
                        "object": detected_object,
                        "zone": zones[0] if zones else "عام",
                        "time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "culprit": culprit_name,
                        "authorized": is_authorized
                    }
                    
                    ai_alert = self.ai_service.formulate_alert_message(event_details)
                    
                    # 5. حفظ الحدث في سجل الأحداث
                    insert_event = text("""
                        INSERT INTO events (
                            tenant_id, branch_id, camera_id, rule_id, 
                            frigate_event_id, event_type, status, 
                            raw_description, ai_description
                        ) VALUES (
                            :tenant_id, :branch_id, :camera_id, :rule_id,
                            :event_id, :event_type, 'unread',
                            :raw_desc, :ai_desc
                        )
                    """)
                    
                    raw_description = f"تم رصد {detected_object} في منطقة {zones} بواسطة كاميرا {camera_name}."
                    await db.execute(insert_event, {
                        "tenant_id": tenant_id,
                        "branch_id": branch_id,
                        "camera_id": camera_id,
                        "rule_id": rule_id,
                        "event_id": event_id,
                        "event_type": detected_object,
                        "raw_desc": raw_description,
                        "ai_desc": ai_alert
                    })
                    
                    # 6. محاكاة إرسال الإشعار للعميل (Telegram / WhatsApp / PWA)
                    logger.info(f"ALERT SENT TO TENANT {tenant_id} via {rule_json.get('action')}: {ai_alert}")

    def _check_time_range(self, time_range: str) -> bool:
        """
        التحقق مما إذا كان الوقت الحالي يقع ضمن مدى عمل القاعدة النشطة
        الصيغة المتوقعة: HH:MM-HH:MM أو always
        """
        if time_range == "always":
            return True
        try:
            start_str, end_str = time_range.split("-")
            now = datetime.now().time()
            start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
            end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
            
            # معالجة الفترات التي تتجاوز منتصف الليل (مثل 22:00 إلى 06:00)
            if start_time <= end_time:
                return start_time <= now <= end_time
            else: # فترة تمتد عبر منتصف الليل
                return now >= start_time or now <= end_time
        except Exception:
            return True # التراجع الآمن في حال حدوث خطأ في الصياغة
