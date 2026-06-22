import json
import subprocess
import shutil
import logging
import random
from typing import Dict, Any, Optional

logger = logging.getLogger("eye_of_ai.vpn_service")

class HeadscaleVPNManager:
    def __init__(self):
        # التحقق مما إذا كان أمر headscale متاحاً في النظام
        self.headscale_cli = shutil.which("headscale")
        if not self.headscale_cli:
            logger.warning("Headscale CLI not found on this system. Operating in MOCK mode for development.")
            self.mock_mode = True
        else:
            self.mock_mode = False

    def _run_cmd(self, args: list) -> tuple:
        """
        تشغيل أمر CLI والتقاط المخرجات والأخطاء
        """
        if self.mock_mode:
            return "", "Mock mode enabled"
        
        try:
            full_cmd = [self.headscale_cli] + args
            result = subprocess.run(
                full_cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                check=True
            )
            return result.stdout.strip(), ""
        except subprocess.CalledProcessError as e:
            logger.error(f"Headscale CLI command failed: {e.cmd} - Error: {e.stderr.strip()}")
            return "", e.stderr.strip()
        except Exception as e:
            logger.error(f"Failed to execute headscale command: {str(e)}")
            return "", str(e)

    def create_tenant_namespace(self, tenant_id: str) -> bool:
        """
        إنشاء مستخدم أو مساحة عمل (Namespace/User) خاصة بالمستأجر في Headscale
        """
        username = f"tenant_{tenant_id[:8]}"
        if self.mock_mode:
            logger.info(f"[MOCK] Created Headscale user: {username}")
            return True
            
        # في الإصدارات الحديثة من headscale نستخدم users create بدلاً من namespaces create
        stdout, stderr = self._run_cmd(["users", "create", username])
        if stderr and "already exists" not in stderr:
            logger.error(f"Failed to create Headscale user {username}: {stderr}")
            return False
        
        logger.info(f"Created Headscale user: {username}")
        return True

    def generate_branch_auth_key(self, tenant_id: str, branch_id: str) -> Optional[str]:
        """
        توليد مفتاح تسجيل مسبق الصلاحية (Pre-authenticated Auth Key) لجهاز فرع الزبون
        صلاحية المفتاح 24 ساعة ويستخدم لمرة واحدة فقط لتسجيل الجهاز
        """
        username = f"tenant_{tenant_id[:8]}"
        if self.mock_mode:
            mock_key = f"mock_key_{tenant_id[:4]}_{branch_id[:4]}_{random.randint(1000,9999)}"
            logger.info(f"[MOCK] Generated Auth Key for {username}: {mock_key}")
            return mock_key

        # التأكد من وجود المستخدم أولاً
        self.create_tenant_namespace(tenant_id)

        # توليد المفتاح (صلاحية 24 ساعة، استخدام لمرة واحدة)
        stdout, stderr = self._run_cmd([
            "preauthkeys", "create", 
            "-u", username, 
            "-e", "24h", 
            "--reusable=false"
        ])
        
        if stderr:
            logger.error(f"Failed to generate PreAuthKey for {username}: {stderr}")
            return None
            
        # المخرجات تحتوي عادة على المفتاح كآخر سطر
        auth_key = stdout.splitlines()[-1] if stdout else None
        logger.info(f"Generated Auth Key for {username}")
        return auth_key

    def get_branch_ip(self, tenant_id: str, branch_node_name: str) -> Optional[str]:
        """
        جلب عنوان الـ IP الممنوح لجهاز الفرع من شبكة الـ VPN
        """
        username = f"tenant_{tenant_id[:8]}"
        if self.mock_mode:
            # توليد عنوان IP وهمي مستقر بناءً على اسم الفرع
            seed = sum(ord(c) for c in branch_node_name)
            random.seed(seed)
            mock_ip = f"100.64.{random.randint(1, 254)}.{random.randint(1, 254)}"
            logger.info(f"[MOCK] Resolved VPN IP for node {branch_node_name}: {mock_ip}")
            return mock_ip

        # جلب قائمة الأجهزة بصيغة JSON
        stdout, stderr = self._run_cmd(["nodes", "list", "-u", username, "-o", "json"])
        if stderr:
            logger.error(f"Failed to list Headscale nodes: {stderr}")
            return None

        try:
            nodes = json.loads(stdout)
            for node in nodes:
                # التحقق من مطابقة اسم العقدة (Node Name)
                if node.get("givenName") == branch_node_name or node.get("name") == branch_node_name:
                    ip_addresses = node.get("ipAddresses", [])
                    if ip_addresses:
                        # نرجع أول عنوان IPv4 (عادة العناوين تبدأ بـ 100.64)
                        for ip in ip_addresses:
                            if ":" not in ip: # استبعاد IPv6
                                logger.info(f"Resolved VPN IP for node {branch_node_name}: {ip}")
                                return ip
            logger.warning(f"Branch node {branch_node_name} not found in Headscale registry.")
            return None
        except Exception as e:
            logger.error(f"Failed to parse Headscale nodes JSON: {str(e)}")
            return None

    def remove_branch_node(self, tenant_id: str, branch_node_name: str) -> bool:
        """
        إزالة جهاز فرع من شبكة الـ VPN وإلغاء تسجيله
        """
        if self.mock_mode:
            logger.info(f"[MOCK] Removed Headscale node: {branch_node_name}")
            return True

        stdout, stderr = self._run_cmd(["nodes", "delete", "-n", branch_node_name, "--yes"])
        if stderr:
            logger.error(f"Failed to delete Headscale node {branch_node_name}: {stderr}")
            return False
            
        logger.info(f"Removed Headscale node: {branch_node_name}")
        return True
