# منصة عين الذكاء (Eye of AI) - دليل التهيئة والتشغيل للإنتاج

يحتوي هذا المستند على الدليل التفصيلي لإعداد البنية التحتية لمنصة عين الذكاء في بيئة الإنتاج الفعلية (Production Mode)، بما في ذلك إعداد Docker Swarm، خادم Headscale VPN، وتعطيل وضع المحاكاة للتطوير (Mock Mode).

---

## 1. متغيرات البيئة للإنتاج (Production Environment Variables)

يجب ضبط متغيرات البيئة التالية في خادم الإدارة الرئيسي (Manager Node):

```ini
# وضع البيئة (production / development)
APP_ENV=production

# خادم قاعدة البيانات الرئيسي (الكتابة والتعديل)
WRITE_DATABASE_URL=postgresql+asyncpg://admin:secure_password@db-master.example.com:5432/eye_of_ai

# خادم قاعدة البيانات الفرعي (القراءة والاستعلام - Replica)
READ_DATABASE_URL=postgresql+asyncpg://readonly:secure_password@db-replica.example.com:5432/eye_of_ai

# تفاصيل وسيط الرسائل MQTT (Mosquitto Broker)
MQTT_BROKER_HOST=mqtt.example.com
MQTT_BROKER_PORT=1883

# عنوان خادم الذكاء الاصطناعي Ollama المخصص
OLLAMA_API_URL=http://ai-server.example.com:11434

# بوابة دفع Zain Cash الفعالة
ZAIN_CASH_MERCHANT_ID=your_real_merchant_id
ZAIN_CASH_SECRET_KEY=your_real_secret_key
ZAIN_CASH_SANDBOX=false # تفعيل الدفع الفعلي
```

---

## 2. تهيئة بيئة Docker Swarm الموزعة (Multi-Node Cluster)

لتوزيع حاويات Frigate الخاصة بالمستأجرين على خوادم المعالجة (Worker Nodes):

### أ) تهيئة خادم الإدارة (Manager Node):
في خادم FastAPI المركزي، قم بتشغيل الأمر التالي لتهيئة الـ Swarm:
```bash
docker swarm init --advertise-addr <IP_MANAGER_NODE>
```
سيقوم الأمر بإنشاء السرب وإرجاع أمر الانضمام لعقد المعالجة (Worker Join Command) بالشكل التالي:
```bash
docker swarm join --token SWMTKN-1-XXXXXX <IP_MANAGER_NODE>:2377
```

### ب) انضمام خوادم المعالجة (Worker Nodes):
في كل سيرفر مخصص لمعالجة كاميرات Frigate (الـ Workers):
1. تأكد من تنصيب Docker وكرت الشاشة المدمج (Intel GPU/OpenVINO).
2. نفّذ أمر الانضمام المولد من الخطوة السابقة:
   ```bash
   docker swarm join --token SWMTKN-1-XXXXXX <IP_MANAGER_NODE>:2377
   ```

---

## 3. ربط وتكوين خادم Headscale VPN الحقيقي

لربط الفروع بالخادم المركزي دون تعارض في عناوين الـ IP وتجاوز شروط استخدام Cloudflare:

### أ) تنصيب خادم Headscale:
في خادم الإدارة الرئيسي (أو سيرفر مستقل):
1. حمّل حزمة Headscale وثبتها كخدمة (Systemd Service):
   ```bash
   wget https://github.com/juanfont/headscale/releases/download/v0.22.3/headscale_0.22.3_linux_amd64.deb
   sudo dpkg -i headscale_0.22.3_linux_amd64.deb
   ```
2. اضبط الإعدادات في `/etc/headscale/config.yaml`:
   * حدد عنوان الـ IP العام للسيرفر في `server_url` (مثال: `https://vpn.example.com`).
   * اضبط مدى عناوين الـ IP الافتراضية في `ip_prefixes` (مثال: `100.64.0.0/10`).
   * غير نوع قاعدة البيانات إلى PostgreSQL (نفس قاعدة بيانات Supabase) في قسم `db_type`.
3. شغّل الخدمة وتأكد من عملها:
   ```bash
   sudo systemctl enable --now headscale
   ```

### ب) تعطيل وضع المحاكاة (Disable Mock Mode):
برنامج FastAPI يكتشف تلقائياً وجود خادم Headscale في حال توفر ملف الـ CLI الخاص به في مسار النظام (System Path).
1. لتعطيل الـ Mock Mode تماماً في الإنتاج، تأكد من توفر تطبيق `headscale` في خادم تشغيل FastAPI.
2. يتواصل الكود تلقائياً عبر الأوامر البرمجية المباشرة (Subprocess API) لإصدار مفاتيح الربط وتتبع الأجهزة.

---

## 4. ربط وتوصيل أجهزة الزبائن (Client Site Configuration)

عند تسجيل فرع جديد، سيقوم النظام بتوليد مفتاح VPN ذكي من الـ API:
1. عند الزبون، نقوم بتثبيت برنامج Tailscale (حجمه 15 ميجا وخفيف جداً).
2. يتم تشغيل الاتصال وربطه بالخادم الخاص بنا عبر الأمر المولد:
   ```bash
   tailscale up --login-server https://vpn.example.com --authkey <PREAUTH_KEY_GENERATED_BY_API>
   ```
3. يقوم العميل تلقائياً بالانضمام للشبكة وأخذ IP فريد مستقر (مثال: `100.64.0.12`).
4. يبدأ خادم Frigate السحابي بسحب البث مباشرة من هذا العنوان الآمن.
