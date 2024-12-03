CREATE TABLE IF NOT EXISTS payment (
    id INT PRIMARY KEY AUTO_INCREMENT,
    space_id VARCHAR(255),
    space_name VARCHAR(255),
    user_id VARCHAR(255),
    user_name VARCHAR(255),
    tid VARCHAR(255),
    order_number VARCHAR(20),
    p_status ENUM('PENDING', 'COMPLETED', 'FAILED', 'CANCELED'),
    amount INT,
    payment_method VARCHAR(100),
    payment_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_payment_tid (tid)
);