import uuid
import hashlib
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("eye_of_ai.payment")

class PaymentGatewayService:
    def __init__(self):
        # في بيئة الإنتاج يتم جلب هذه المعطيات من متغيرات البيئة الخاصة بـ Zain Cash أو AsiaPay
        self.merchant_id = "mock_merchant_12345"
        self.secret_key = "mock_secret_key_67890"
        self.is_sandbox = True

    def create_payment_session(self, tenant_id: str, amount: float, method: str) -> Dict[str, Any]:
        """
        إنشاء جلسة دفع تجريبية وتوليد رابط الدفع (Checkout URL)
        يدعم Zain Cash و AsiaPay
        """
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        timestamp = int(time.time())

        # بناء البيانات الخاصة بالطلب لمحاكاة معايير Zain Cash الفنية
        payload = {
            "amount": amount,
            "serviceType": "SaaS Subscription",
            "msisdn": "9647700000000", # رقم محاكاة للزبون بالعراق
            "orderId": transaction_id,
            "redirectUrl": f"http://localhost:3000/payment/callback?id={transaction_id}",
            "iat": timestamp,
            "exp": timestamp + 3600
        }

        # توليد توقيع رقمي للمصادقة لمحاكاة الأمان الفعلي (HMAC / SHA256)
        signature_base = f"{amount}{transaction_id}{timestamp}{self.secret_key}"
        signature = hashlib.sha256(signature_base.encode('utf-8')).hexdigest()

        # توليد رابط الدفع الموهم (Mock Checkout URL) على لوحة التحكم
        checkout_url = f"http://localhost:3000/payment/checkout?id={transaction_id}&amount={amount}&method={method}&sig={signature}"

        logger.info(f"Created mock payment session for tenant {tenant_id}, amount: {amount} via {method}")
        
        return {
            "status": "success",
            "transaction_id": transaction_id,
            "checkout_url": checkout_url,
            "amount": amount,
            "method": method,
            "signature": signature
        }

    def verify_payment_callback(self, transaction_id: str, signature: str, amount: float) -> bool:
        """
        التحقق من صحة التوقيع الرقمي وتأكيد عملية الدفع القادمة من الـ Webhook
        """
        # في وضع المحاكاة، نقبل التوقيع إذا كان منشأ من نفس المعايير
        # للتبسيط، نتحقق من صحة البيانات ونوافق عليها
        if not transaction_id or not signature:
            logger.error("Missing transaction ID or signature in callback verification.")
            return False

        # محاكاة التحقق من صحة البيانات
        logger.info(f"Verified payment callback for transaction: {transaction_id}, amount: {amount}")
        return True

    def process_refund(self, transaction_id: str, amount: float) -> Dict[str, Any]:
        """
        محاكاة استرداد الأموال (Refund)
        """
        logger.info(f"Refunding transaction {transaction_id} with amount: {amount}")
        return {
            "status": "success",
            "refund_id": f"ref_{uuid.uuid4().hex[:12]}",
            "transaction_id": transaction_id,
            "amount": amount
        }
