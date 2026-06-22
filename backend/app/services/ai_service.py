import os
import json
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("eye_of_ai.ai_service")

class AIServiceManager:
    def __init__(self):
        # تحديد المزود الافتراضي (ollama أو claude أو openai)
        self.provider = os.getenv("AI_PROVIDER", "ollama").lower()
        self.ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip("/")
        self.api_key = os.getenv("AI_API_KEY", "")
        self.model = os.getenv("AI_MODEL", "llama3.2:3b") # النموذج الافتراضي لـ Ollama

    def _query_ollama(self, prompt: str, system_prompt: str) -> Optional[str]:
        """
        الاتصال بخادم Ollama المحلي لتشغيل النموذج
        """
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.1 # قيمة منخفضة لضمان الدقة في المخرجات الهيكلية
            }
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "").strip()
            else:
                logger.error(f"Ollama returned error status: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Failed to connect to Ollama at {url}: {str(e)}")
            return None

    def _query_api(self, prompt: str, system_prompt: str) -> Optional[str]:
        """
        الاتصال بالمزود الخارجي الاحتياطي (Claude / OpenAI) في حال إعداد المفاتيح
        """
        if self.provider == "openai":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1
            }
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code == 200:
                    return response.json()["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"OpenAI API call failed: {str(e)}")
        
        # في حال لم ينجح المزوّد الخارجي أو لم يكن مهيئاً، نعود لـ Ollama كـ Fallback
        return self._query_ollama(prompt, system_prompt)

    def parse_text_command_to_rule(self, raw_text: str) -> Dict[str, Any]:
        """
        الوظيفة الأولى: تحويل الأوامر النصية الحرة (العراقية/العربية) إلى قاعدة JSON
        """
        system_prompt = """
        You are an expert AI security engineer. Convert the user's security monitoring request (in Arabic, Iraqi dialect, or English) into a strict JSON Rule object.
        The JSON must contain EXACTLY the following keys:
        1. "zone": The specific area monitored (e.g. "cashier", "entrance", "safe", "warehouse"). If not specified, use "any".
        2. "object": The object detected (e.g. "person", "car", "face_match", "dog", "box"). Default is "person".
        3. "time_range": Time slot in format "HH:MM-HH:MM" (24h). If user says "بالليل" (at night) use "22:00-06:00". If always, use "always".
        4. "action": The notification action (e.g. "notify_telegram", "notify_whatsapp", "notify_sms", "sound_alarm"). Default is "notify_telegram".
        
        Return ONLY valid JSON. No explanations, no markdown wrapper blocks, no backticks.
        
        Example Input: نبهني على التيليجرام إذا دخل شخص للكاشير بالليل
        Example Output: {"zone": "cashier", "object": "person", "time_range": "22:00-06:00", "action": "notify_telegram"}
        """

        prompt = f"User Request: {raw_text}"
        
        response_text = ""
        if self.provider == "ollama":
            response_text = self._query_ollama(prompt, system_prompt)
        else:
            response_text = self._query_api(prompt, system_prompt)

        # تنظيف ومعالجة مخرجات النموذج
        if not response_text:
            # Fallback الافتراضي في حال فشل الـ LLM بالكامل
            return {"zone": "any", "object": "person", "time_range": "always", "action": "notify_telegram"}

        try:
            # تنظيف أي علامات اقتباس أو علامات كود زائدة
            cleaned_text = response_text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned_text)
        except Exception as e:
            logger.error(f"Failed to parse LLM response into JSON. Raw response: {response_text}. Error: {str(e)}")
            # إرجاع قاعدة افتراضية آمنة
            return {"zone": "any", "object": "person", "time_range": "always", "action": "notify_telegram"}

    def formulate_alert_message(self, event_details: dict) -> str:
        """
        الوظيفة الثانية: صياغة التنبيهات الأمنية الاحترافية باللغة العربية بلمسة ملائمة
        """
        system_prompt = """
        You are a professional security operations center (SOC) operator. Write a clear, concise, and professional alert message in Arabic (with a modern touch) based on the event details provided.
        The message should include:
        1. نوع الحدث والمخالفة (Event Type)
        2. اسم الكاميرا والفرع (Location)
        3. الوقت الفعلي للحدث (Time)
        4. الإجراء المقترح للمدير (Suggested action)
        
        Format the message beautifully using emojis and bold text for readability. Return ONLY the alert message text.
        """
        
        prompt = f"Event Details: {json.dumps(event_details, ensure_ascii=False)}"
        
        if self.provider == "ollama":
            msg = self._query_ollama(prompt, system_prompt)
        else:
            msg = self._query_api(prompt, system_prompt)
            
        return msg or f"⚠️ تنبيه أمني: تم رصد حدث غير معتاد في الفرع."

    def generate_security_report(self, events_summary: list) -> str:
        """
        الوظيفة الثالثة: كتابة التقارير الأمنية والتشغيلية الدورية
        """
        system_prompt = """
        You are a chief security officer (CSO). Write a comprehensive, professional Arabic business report summarizing the weekly/monthly security and operational events.
        The report must have:
        1. ملخص تنفيذي (Executive Summary)
        2. تحليل الأحداث المكشوفة والمخالفات المرتكبة
        3. إحصائيات أعطال الكاميرات والتلاعب بالبث
        4. توصيات أمنية وتشغيلية مهمة لتحسين الحماية بالمنشأة
        
        Use professional corporate Arabic phrasing. Keep it structured with headings. Return ONLY the report text.
        """
        
        prompt = f"Events Summary Data: {json.dumps(events_summary, ensure_ascii=False)}"
        
        if self.provider == "ollama":
            report = self._query_ollama(prompt, system_prompt)
        else:
            report = self._query_api(prompt, system_prompt)
            
        return report or "فشل في توليد التقرير الأمني التلقائي."
