# seed_db_fixed.py
import os
import psycopg2
import hashlib
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "database": os.environ.get("DB_NAME", "ahmedx3"),
    "user": os.environ.get("DB_USER", "ahmedx3"),
    "password": os.environ.get("DB_PASSWORD", "AHMEDX3COMai"),
    "port": int(os.environ.get("DB_PORT", 5432)),
}
IMAGES_FOLDER = r"D:\projects\one\products"
TABLE_MAP = {
    "men": "products_men",
    "youth": "products_youth", 
    "children": "products_children"
}
def generate_hash(data):
    return hashlib.sha256(data).hexdigest()
def upload_images():
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True 
    cursor = conn.cursor()
    total_uploaded = 0
    total_errors = 0
    for category, table_name in TABLE_MAP.items():
        folder_path = os.path.join(IMAGES_FOLDER, category)
        if not os.path.exists(folder_path):
            print(f"⚠️ المجلد غير موجود: {folder_path}")
            continue
        files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        if not files:
            print(f"⚠️ لا توجد صور في: {folder_path}")
            continue
        print(f"\n📁 جاري رفع {len(files)} صور من فئة '{category}'...")
        for filename in files:
            filepath = os.path.join(folder_path, filename)           
            try:
                with open(filepath, 'rb') as img_file:
                    image_data = img_file.read()               
                image_hash = generate_hash(image_data)
                cursor.execute(
                    f"""
                    INSERT INTO {table_name} (file_name, image_data, image_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (image_hash) DO NOTHING
                    """,
                    (filename, image_data, image_hash)
                )                
                if cursor.rowcount > 0:
                    print(f"  ✅ {filename}")
                    total_uploaded += 1
                else:
                    print(f"  ⏭️ {filename} (موجودة)")       
            except psycopg2.errors.InsufficientPrivilege as e:
                print(f"  ❌ {filename}: خطأ صلاحيات - نفّذ أوامر GRANT أولاً")
                total_errors += 1
                break 
            except Exception as e:
                print(f"  ❌ {filename}: {type(e).__name__}")
                total_errors += 1
    cursor.close()
    conn.close()
    print(f"\n🎉 انتهى! تم رفع {total_uploaded} صورة جديدة، {total_errors} أخطاء.")
if __name__ == "__main__":
    upload_images()