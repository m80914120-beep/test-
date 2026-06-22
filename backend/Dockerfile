# استخدام نسخة بايثون رسمية وخفيفة
FROM python:3.10-slim

# ضبط متغيرات البيئة لمنع بايثون من كتابة ملفات pyc ولعرض المخرجات فوراً
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# تثبيت مكتبات النظام المطلوبة لـ OpenCV ومكتبات معالجة الصور
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات أولاً لتسريع الكاش في دوكر
COPY requirements.txt .

# تثبيت الحزم المطلوبة
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود المصدري للمشروع
COPY . .

# فتح منفذ الـ API الافتراضي
EXPOSE 8000

# تشغيل خادم uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
