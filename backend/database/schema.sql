-- تفعيل إضافة pgvector للتعرف على الوجوه ومطابقتها
CREATE EXTENSION IF NOT EXISTS vector;

-- 1. جدول المستأجرين (Tenants)
CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    business_type VARCHAR(100) NOT NULL,
    plan VARCHAR(50) NOT NULL DEFAULT 'basic', -- basic, advanced, professional
    status VARCHAR(50) NOT NULL DEFAULT 'active', -- active, suspended, expired
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE
);

-- 2. جدول الفروع (Branches)
CREATE TABLE IF NOT EXISTS branches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    vpn_ip VARCHAR(50) UNIQUE, -- عنوان الـ IP الافتراضي الممنوح عبر Headscale
    vpn_node_name VARCHAR(100) UNIQUE, -- اسم العقدة في شبكة VPN
    status VARCHAR(50) NOT NULL DEFAULT 'offline', -- online, offline
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. جدول الكاميرات (Cameras)
CREATE TABLE IF NOT EXISTS cameras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    rtsp_url TEXT NOT NULL, -- عنوان البث المحلي عبر الـ VPN (مثال: rtsp://100.64.0.12:554/stream)
    width INTEGER DEFAULT 1920,
    height INTEGER DEFAULT 1080,
    status VARCHAR(50) NOT NULL DEFAULT 'offline', -- online, offline, flickering
    bitrate INTEGER DEFAULT 0, -- البت ريت الحالي بالكيلوبت
    frame_loss_rate FLOAT DEFAULT 0.0, -- معدل فقدان الإطارات
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. جدول قوالب الأنشطة التجارية (Business Templates)
CREATE TABLE IF NOT EXISTS business_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_type VARCHAR(100) UNIQUE NOT NULL, -- mall, restaurant, warehouse, etc.
    suggested_rules JSONB NOT NULL, -- القواعد الافتراضية المقترحة للنشاط
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. جدول القواعد الذكية (Rules)
CREATE TABLE IF NOT EXISTS rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    raw_text_command TEXT NOT NULL, -- الأمر النصي العراقي/العربي (مثال: نبهني إذا دخل شخص للكاشير بالليل)
    parsed_rule_json JSONB NOT NULL, -- القاعدة بعد ترجمتها بالذكاء الاصطناعي
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. سجل الوجوه المحظورة (Blacklist Faces)
CREATE TABLE IF NOT EXISTS blacklist_faces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name VARCHAR(255),
    face_embedding vector(512), -- بصمة الوجه بطول 512 (متوافقة مع FaceNet/ArcFace)
    image_url TEXT, -- مسار حفظ لقطة الوجه في التخزين السحابي
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. قواعد التفويض والتراخيص (Authorized Rules)
CREATE TABLE IF NOT EXISTS authorized_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    face_id UUID NOT NULL REFERENCES blacklist_faces(id) ON DELETE CASCADE,
    zone_name VARCHAR(100) NOT NULL, -- اسم المنطقة المخصصة (Polygon Zone)
    is_allowed BOOLEAN DEFAULT TRUE, -- هل يسمح له بالتواجد هنا؟
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. جدول سجل الأحداث (Events)
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    rule_id UUID REFERENCES rules(id) ON DELETE SET NULL,
    frigate_event_id VARCHAR(100), -- معرف الحدث في نظام Frigate لمطابقته
    event_type VARCHAR(100) NOT NULL, -- person, car, face_match, tamper, etc.
    status VARCHAR(50) NOT NULL DEFAULT 'unread', -- unread, read, archived
    detection_image_url TEXT, -- لقطة الحدث
    detection_video_url TEXT, -- مقطع الحدث
    raw_description TEXT, -- التفسير الخام التلقائي
    ai_description TEXT, -- الرسالة الاحترافية المصاغة بالذكاء الاصطناعي (العراقية/العربية)
    is_false_positive BOOLEAN DEFAULT FALSE, -- للتغذية الراجعة (Feedback Loop)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. جدول المدفوعات والفواتير (Payments)
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    amount DECIMAL(10, 2) NOT NULL,
    payment_status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, completed, failed
    gateway_transaction_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- فهارس لتحسين سرعة الاستعلامات
CREATE INDEX IF NOT EXISTS idx_branches_tenant ON branches(tenant_id);
CREATE INDEX IF NOT EXISTS idx_cameras_branch ON cameras(branch_id);
CREATE INDEX IF NOT EXISTS idx_rules_camera ON rules(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_tenant ON events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_blacklist_faces_tenant ON blacklist_faces(tenant_id);
