FROM python:3.11-slim

# تثبيت المتطلبات الأساسية
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# نسخ المتطلبات أولاً (cache optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ كود التطبيق
COPY . .

# إنشاء مجلدات الوسائط الافتراضية (يمكن ربطها بـ Fly Volume)
RUN mkdir -p /data/backgrounds \
             /data/products/men/men_video \
             /data/products/youth/youth_video \
             /data/products/children/child_video

# المنفذ الذي يستمع عليه التطبيق
EXPOSE 8080

# تشغيل التطبيق عبر Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", "app:app"]