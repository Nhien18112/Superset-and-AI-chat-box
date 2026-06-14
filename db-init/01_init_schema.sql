-- ==========================================
-- 1. BẢNG DIMENSION (Danh mục)
-- ==========================================

-- Bảng Mã chứng khoán
CREATE TABLE dim_tickers (
    ticker_id VARCHAR(10) PRIMARY KEY,
    company_name VARCHAR(100),
    industry VARCHAR(50)
);

INSERT INTO dim_tickers (ticker_id, company_name, industry) VALUES
('SSI', 'Chứng khoán SSI', 'Tài chính'),
('FPT', 'FPT Corporation', 'Công nghệ'),
('HPG', 'Tập đoàn Hòa Phát', 'Thép');

-- Bảng Chuyên viên Môi giới (Broker)
CREATE TABLE dim_brokers (
    broker_id VARCHAR(50) PRIMARY KEY,
    broker_name VARCHAR(100)
);

INSERT INTO dim_brokers (broker_id, broker_name) VALUES
('broker_1', 'Trần Quản Lý'),
('broker_2', 'Lê Tư Vấn');

-- Bảng Nhà đầu tư (Investor)
CREATE TABLE dim_investors (
    investor_id VARCHAR(50) PRIMARY KEY,
    investor_name VARCHAR(100),
    broker_id VARCHAR(50) REFERENCES dim_brokers(broker_id)
);

INSERT INTO dim_investors (investor_id, investor_name, broker_id) VALUES
('investor_a', 'Nguyễn Đầu Tư A', 'broker_1'),
('investor_b', 'Trần Đầu Tư B', 'broker_1'),
('investor_c', 'Lê Đầu Tư C', 'broker_2');

-- ==========================================
-- 2. BẢNG FACT (Giao dịch/Sự kiện)
-- ==========================================

-- Bảng Lệnh giao dịch
CREATE TABLE fact_orders (
    order_id SERIAL PRIMARY KEY,
    investor_id VARCHAR(50) REFERENCES dim_investors(investor_id),
    ticker_id VARCHAR(10) REFERENCES dim_tickers(ticker_id),
    order_date DATE,
    order_type VARCHAR(10), -- BUY/SELL
    volume INT,
    price DECIMAL(10, 2),
    status VARCHAR(20)
);

INSERT INTO fact_orders (investor_id, ticker_id, order_date, order_type, volume, price, status) VALUES
('investor_a', 'SSI', '2026-06-14', 'BUY', 1000, 35.5, 'Khớp'),
('investor_a', 'FPT', '2026-06-14', 'BUY', 500, 130.0, 'Khớp'),
('investor_b', 'HPG', '2026-06-14', 'SELL', 2000, 28.0, 'Khớp'),
('investor_c', 'SSI', '2026-06-14', 'BUY', 5000, 35.0, 'Khớp');


-- ==========================================
-- 1. BẢNG DIMENSION (Bổ sung danh mục)
-- ==========================================

-- Bổ sung Mã chứng khoán mới
INSERT INTO dim_tickers (ticker_id, company_name, industry) VALUES
('VNM', 'Sữa Việt Nam (Vinamilk)', 'Tiêu dùng'),
('VCB', 'Vietcombank', 'Tài chính'),
('TCB', 'Techcombank', 'Tài chính'),
('MBB', 'Ngân hàng Quân Đội', 'Tài chính'),
('VIC', 'Tập đoàn Vingroup', 'Bất động sản'),
('VHM', 'Vinhomes', 'Bất động sản'),
('MWG', 'Thế giới Di động', 'Bán lẻ'),
('MSN', 'Tập đoàn Masan', 'Tiêu dùng'),
('GAS', 'Tổng công ty Khí Việt Nam', 'Năng lượng'),
('HDB', 'HDBank', 'Tài chính'),
('VPB', 'VPBank', 'Tài chính'),
('ACB', 'Ngân hàng Á Châu', 'Tài chính')
ON CONFLICT (ticker_id) DO NOTHING;

-- Bổ sung Chuyên viên Môi giới mới
INSERT INTO dim_brokers (broker_id, broker_name) VALUES
('broker_3', 'Nguyễn Văn Cường'),
('broker_4', 'Phạm Thị Dung'),
('broker_5', 'Hoàng Đức Anh'),
('broker_6', 'Đỗ Kim Liên'),
('broker_7', 'Vũ Minh Hoàng'),
('broker_8', 'Ngô Quốc Khánh')
ON CONFLICT (broker_id) DO NOTHING;

-- Bổ sung Nhà đầu tư mới
INSERT INTO dim_investors (investor_id, investor_name, broker_id) VALUES
('investor_01', 'Phạm Minh Trí', 'broker_1'),
('investor_02', 'Nguyễn Hoài Nam', 'broker_1'),
('investor_03', 'Hoàng Thanh Lâm', 'broker_2'),
('investor_04', 'Phùng Quốc Bảo', 'broker_2'),
('investor_05', 'Trịnh Khánh Vy', 'broker_3'),
('investor_06', 'Vũ Thùy Linh', 'broker_3'),
('investor_07', 'Đặng Thế Dũng', 'broker_4'),
('investor_08', 'Bùi Phương Thảo', 'broker_4'),
('investor_09', 'Lý Gia Huy', 'broker_5'),
('investor_10', 'Ngô Bảo Châu', 'broker_5'),
('investor_11', 'Lương Tuấn Kiệt', 'broker_6'),
('investor_12', 'Phan Mỹ Lệ', 'broker_6'),
('investor_13', 'Dương Quốc Trung', 'broker_7'),
('investor_14', 'Võ Hoàng Yến', 'broker_7'),
('investor_15', 'Đỗ Anh Tú', 'broker_8'),
('investor_16', 'Tống Khánh Linh', 'broker_8'),
('investor_17', 'Mai Văn Nam', 'broker_3'),
('investor_18', 'Đinh Công Thành', 'broker_4'),
('investor_19', 'Trần Thị Thu', 'broker_5'),
('investor_20', 'Nguyễn Thị Thủy', 'broker_6')
ON CONFLICT (investor_id) DO NOTHING;

-- ==========================================
-- 2. TỰ ĐỘNG SINH DỮ LIỆU LỆNH GIAO DỊCH (FACT)
-- ==========================================

-- Sinh ngẫu nhiên 5000 lệnh giao dịch trong vòng 365 ngày gần đây
WITH random_orders AS (
    SELECT 
        (SELECT investor_id FROM dim_investors OFFSET floor(random() * (SELECT count(*) FROM dim_investors)) LIMIT 1) as investor_id,
        (SELECT ticker_id FROM dim_tickers OFFSET floor(random() * (SELECT count(*) FROM dim_tickers)) LIMIT 1) as ticker_id,
        CURRENT_DATE - (floor(random() * 365))::INT as order_date,
        (ARRAY['BUY', 'SELL'])[floor(random() * 2) + 1] as order_type,
        (floor(random() * 100) + 1)::INT * 100 as volume,
        (ARRAY['Khớp', 'Chờ', 'Hủy'])[floor(random() * 3) + 1] as status
    FROM generate_series(1, 5000)
)
INSERT INTO fact_orders (investor_id, ticker_id, order_date, order_type, volume, price, status)
SELECT 
    investor_id,
    ticker_id,
    order_date,
    order_type,
    volume,
    -- Tính giá thực tế dựa trên mã chứng khoán (kèm dao động ngẫu nhiên nhỏ)
    CASE 
        WHEN ticker_id = 'FPT' THEN (120 + random() * 20)::DECIMAL(10, 2)
        WHEN ticker_id = 'VCB' THEN (85 + random() * 15)::DECIMAL(10, 2)
        WHEN ticker_id = 'VNM' THEN (60 + random() * 10)::DECIMAL(10, 2)
        WHEN ticker_id = 'VIC' THEN (40 + random() * 8)::DECIMAL(10, 2)
        WHEN ticker_id = 'VHM' THEN (38 + random() * 6)::DECIMAL(10, 2)
        WHEN ticker_id = 'HPG' THEN (25 + random() * 6)::DECIMAL(10, 2)
        WHEN ticker_id = 'SSI' THEN (30 + random() * 8)::DECIMAL(10, 2)
        WHEN ticker_id = 'TCB' THEN (20 + random() * 5)::DECIMAL(10, 2)
        WHEN ticker_id = 'MBB' THEN (18 + random() * 4)::DECIMAL(10, 2)
        WHEN ticker_id = 'MWG' THEN (55 + random() * 10)::DECIMAL(10, 2)
        WHEN ticker_id = 'MSN' THEN (70 + random() * 12)::DECIMAL(10, 2)
        WHEN ticker_id = 'GAS' THEN (75 + random() * 15)::DECIMAL(10, 2)
        WHEN ticker_id = 'HDB' THEN (22 + random() * 4)::DECIMAL(10, 2)
        WHEN ticker_id = 'VPB' THEN (17 + random() * 4)::DECIMAL(10, 2)
        WHEN ticker_id = 'ACB' THEN (24 + random() * 5)::DECIMAL(10, 2)
        ELSE (10 + random() * 100)::DECIMAL(10, 2)
    END as price,
    status
FROM random_orders;

-- Security & Auth Tables
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL, 
    password VARCHAR(255) NOT NULL, 
    role VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO users (username, password, role) VALUES
('investor_a', '{noop}password123', 'ROLE_INVESTOR'),
('broker_1', '{noop}admin123', 'ROLE_BROKER');

-- Chat Persistence Tables
CREATE TABLE chat_sessions (
    session_id VARCHAR(50) PRIMARY KEY,
    username VARCHAR(50) REFERENCES users(username),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_messages (
    message_id SERIAL PRIMARY KEY,
    session_id VARCHAR(50) REFERENCES chat_sessions(session_id),
    sender_type VARCHAR(10) NOT NULL, -- 'USER' or 'AI'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
