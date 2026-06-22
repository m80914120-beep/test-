import os
import yaml
import docker
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("eye_of_ai.docker_swarm")

class DockerSwarmManager:
    def __init__(self):
        try:
            # الاتصال بالـ Docker daemon المحلي أو البعيد
            self.client = docker.from_env()
            # التحقق مما إذا كان السيرفر مهيأ كـ Docker Swarm
            self.is_swarm = self.client.info().get("Swarm", {}).get("LocalNodeState") == "Active"
            if not self.is_swarm:
                logger.warning("Docker Swarm is not active. Falling back to standalone container mode for development.")
        except Exception as e:
            logger.error(f"Failed to initialize Docker Client: {str(e)}")
            self.client = None
            self.is_swarm = False

    def generate_frigate_config(self, tenant_id: str, branch_id: str, cameras: list) -> str:
        """
        توليد ملف إعدادات Frigate YAML الخاص بكل مستأجر وفرع
        """
        config = {
            "mqtt": {
                "host": os.getenv("MQTT_BROKER_HOST", "mqtt-broker"),
                "port": int(os.getenv("MQTT_BROKER_PORT", 1883)),
                # نضع معرف الفرع والمستأجر في الـ topic لسهولة الفلترة
                "topic_prefix": f"frigate/{tenant_id}/{branch_id}",
                "client_id": f"frigate_{branch_id}"
            },
            "detectors": {
                "ov": {
                    "type": "openvino",
                    "device": "CPU" # يمكن تغييره لـ GPU في السيرفرات الداعمة
                }
            },
            "cameras": {}
        }

        # إضافة الكاميرات للبث
        for cam in cameras:
            cam_name = cam.get("name", "camera").replace(" ", "_").lower()
            config["cameras"][cam_name] = {
                "ffmpeg": {
                    "inputs": [
                        {
                            "path": cam.get("rtsp_url"),
                            "roles": ["detect", "record"]
                        }
                    ]
                },
                "detect": {
                    "width": cam.get("width", 1280),
                    "height": cam.get("height", 720),
                    "fps": 5 # وضع توفير الباندويث الافتراضي
                },
                # إعداد مناطق المراقبة المخصصة (Zones) إن وجدت
                "zones": cam.get("zones", {})
            }

        # إنشاء مجلد الإعدادات على خادم الاستضافة
        config_dir = f"/var/eye_of_ai/tenants/{tenant_id}/{branch_id}"
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "config.yml")

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

        logger.info(f"Generated Frigate config at: {config_path}")
        return config_dir

    def deploy_frigate_instance(self, tenant_id: str, branch_id: str, cameras: list) -> Dict[str, Any]:
        """
        تشغيل حاوية Frigate جديدة للفرع إما كـ Swarm Service أو Standalone Container (للتطوير المحلي)
        """
        if not self.client:
            return {"status": "error", "message": "Docker client not initialized"}

        service_name = f"frigate-{tenant_id[:8]}-{branch_id[:8]}"
        config_dir = self.generate_frigate_config(tenant_id, branch_id, cameras)

        # تحديد المسارات وحفظ التسجيلات
        volumes = {
            f"{config_dir}/config.yml": {"bind": "/config/config.yml", "mode": "ro"},
            f"/var/eye_of_ai/storage/{tenant_id}/{branch_id}/recordings": {"bind": "/media/frigate", "mode": "rw"}
        }

        image = os.getenv("FRIGATE_IMAGE", "ghcr.io/blakeblackshear/frigate:stable")

        try:
            if self.is_swarm:
                # 1. التشغيل في وضع Docker Swarm الموزع
                # نقوم بتحويل الـ volumes لـ Mounts متوافقة مع Swarm
                mounts = [
                    docker.types.Mount(target="/config/config.yml", source=f"{config_dir}/config.yml", type="bind", read_only=True),
                    docker.types.Mount(target="/media/frigate", source=f"/var/eye_of_ai/storage/{tenant_id}/{branch_id}/recordings", type="bind")
                ]
                
                # إعداد قيود استهلاك الموارد لكل فرع (مثلاً: ربع معالج و 1 جيجا رام كحد أقصى)
                resources = docker.types.Resources(
                    cpu_limit=int(0.5 * 10**9), # 0.5 vCPU
                    mem_limit=1024 * 1024 * 1024 # 1 GB RAM
                )

                service = self.client.services.create(
                    image=image,
                    name=service_name,
                    mounts=mounts,
                    constraints=["node.role == worker"], # تشغيلها على خوادم المعالجة فقط
                    resources=resources,
                    restart_policy=docker.types.RestartPolicy(condition="on-failure")
                )
                logger.info(f"Deployed Swarm Service: {service_name}")
                return {"status": "success", "mode": "swarm", "service_id": service.id, "service_name": service_name}
            else:
                # 2. التشغيل في وضع Standalone (للتطوير المحلي)
                # فحص إن كانت الحاوية تعمل مسبقاً لإعادة تشغيلها
                try:
                    old_container = self.client.containers.get(service_name)
                    old_container.remove(force=True)
                except docker.errors.NotFound:
                    pass

                container = self.client.containers.run(
                    image=image,
                    name=service_name,
                    detach=True,
                    volumes=volumes,
                    shm_size="64m", # مهم جداً لـ Frigate لمعالجة البث في الذاكرة المشتركة
                    restart_policy={"Name": "unless-stopped"}
                )
                logger.info(f"Deployed Standalone Container: {service_name}")
                return {"status": "success", "mode": "standalone", "container_id": container.id, "container_name": service_name}

        except Exception as e:
            logger.error(f"Failed to deploy Frigate instance for branch {branch_id}: {str(e)}")
            return {"status": "error", "message": str(e)}

    def remove_frigate_instance(self, tenant_id: str, branch_id: str) -> bool:
        """
        إيقاف وإزالة خدمة/حاوية Frigate للفرع
        """
        if not self.client:
            return False

        service_name = f"frigate-{tenant_id[:8]}-{branch_id[:8]}"
        try:
            if self.is_swarm:
                service = self.client.services.get(service_name)
                service.remove()
                logger.info(f"Removed Swarm Service: {service_name}")
            else:
                container = self.client.containers.get(service_name)
                container.remove(force=True)
                logger.info(f"Removed Standalone Container: {service_name}")
            return True
        except docker.errors.NotFound:
            logger.warning(f"Frigate instance {service_name} not found for removal.")
            return True
        except Exception as e:
            logger.error(f"Error removing Frigate instance {service_name}: {str(e)}")
            return False

    def get_instance_status(self, tenant_id: str, branch_id: str) -> Dict[str, Any]:
        """
        جلب تفاصيل وحالة تشغيل حاوية Frigate
        """
        if not self.client:
            return {"status": "unknown", "message": "Docker client offline"}

        service_name = f"frigate-{tenant_id[:8]}-{branch_id[:8]}"
        try:
            if self.is_swarm:
                service = self.client.services.get(service_name)
                tasks = service.tasks()
                state = "unknown"
                if tasks:
                    state = tasks[0].get("Status", {}).get("State", "unknown")
                return {
                    "status": "online" if state == "running" else "offline",
                    "mode": "swarm",
                    "state": state,
                    "service_name": service_name
                }
            else:
                container = self.client.containers.get(service_name)
                state = container.status # running, exited, etc.
                return {
                    "status": "online" if state == "running" else "offline",
                    "mode": "standalone",
                    "state": state,
                    "container_name": service_name
                }
        except docker.errors.NotFound:
            return {"status": "offline", "state": "not_found", "message": "Instance does not exist"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
