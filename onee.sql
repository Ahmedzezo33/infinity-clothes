CREATE TABLE IF NOT EXISTS products_men (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    image_data BYTEA NOT NULL,
    image_hash TEXT NOT NULL UNIQUE,
    video_url TEXT,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE IF NOT EXISTS products_children (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    image_data BYTEA NOT NULL,
    image_hash TEXT NOT NULL UNIQUE,
	video_url TEXT,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS products_youth (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    image_data BYTEA NOT NULL,
    image_hash TEXT NOT NULL UNIQUE,
	video_url TEXT,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

--الطلبات
-- ==========================================
-- 📦 جدول الطلبات الرئيسي (Orders)
-- ==========================================
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    total_price NUMERIC(10,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'ready', 'delivered', 'cancelled')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ==========================================
-- 📄 جدول تفاصيل عناصر الطلب (Order Items)
-- ==========================================
CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    department VARCHAR(20) NOT NULL,
    product_name VARCHAR(255),
    price NUMERIC(10,2) NOT NULL,           -- السعر النهائي المدفوع
    quantity INTEGER DEFAULT 1,
    price_before NUMERIC(10,2),             -- السعر الأصلي
    discount_percent NUMERIC(5,2) DEFAULT 0,-- نسبة الخصم المطبق
    price_after NUMERIC(10,2),              -- السعر بعد الخصم الأول
    video_url TEXT,                         -- رابط فيديو المنتج
    material TEXT,                          -- خامة المنتج
    CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

-- ==========================================
-- 📊 الفهارس لتحسين سرعة الاستعلامات
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_product_id ON order_items(product_id);




--login
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ================= جدول المستخدمين (محدث) =================
CREATE TABLE users (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    first_name        VARCHAR(50)  NOT NULL,
    last_name         VARCHAR(50)  NOT NULL,
    email             VARCHAR(255) NOT NULL UNIQUE,
    phone             VARCHAR(20),
    password_hash     VARCHAR(255) NOT NULL,
    remember_me       BOOLEAN      DEFAULT FALSE,
    is_active         BOOLEAN      DEFAULT TRUE,
    created_at        TIMESTAMP    DEFAULT NOW(),
    updated_at        TIMESTAMP    DEFAULT NOW(),

    -- 🎁 حقول إحصائية سريعة
    total_spins       INTEGER      DEFAULT 0,
    last_spin_date    DATE,

    -- 🏆 آخر جائزة ربحها
    last_prize_name   VARCHAR(50),
    last_prize_type   VARCHAR(20),
    last_prize_value  NUMERIC(10,2) DEFAULT 0,

    -- 💰 إجمالي الأرصدة المتراكمة
    total_cash_earned NUMERIC(12,2) DEFAULT 0,
    total_coins_earned NUMERIC(12,2) DEFAULT 0,

    -- 📜 سجل المكافآت الكامل (مصفوفة JSONB)
    rewards_history   JSONB DEFAULT '[]'::jsonb,

    -- تقييد نوع الجائزة
    CONSTRAINT chk_prize_type CHECK (last_prize_type IN ('cash_egp', 'gold_coin', 'no_reward'))
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_last_spin ON users(last_spin_date);

-- ================= دالة التحديث التلقائي =================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ================= جدول الجلسات =================
CREATE TABLE user_sessions (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token      VARCHAR(512) NOT NULL UNIQUE,
    expires_at TIMESTAMP    NOT NULL,
    created_at TIMESTAMP    DEFAULT NOW()
);
CREATE INDEX idx_sessions_token   ON user_sessions(token);
CREATE INDEX idx_sessions_user_id ON user_sessions(user_id);













GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO ahmedx3;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ahmedx3;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO ahmedx3;