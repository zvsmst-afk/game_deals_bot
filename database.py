import sqlite3
from datetime import datetime
import config
import logging

logger = logging.getLogger(__name__)

def get_db_connection():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Таблица акций (с колонкой image_url)
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promotions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT NOT NULL,
            app_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            discount_percent INTEGER,
            old_price INTEGER,
            new_price INTEGER,
            currency TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            region_restricted BOOLEAN DEFAULT 0,
            region_alternative TEXT,
            url TEXT,
            is_free BOOLEAN DEFAULT 0,
            notified BOOLEAN DEFAULT 0,
            published BOOLEAN DEFAULT 0,
            image_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(store, app_id, end_date)
        )
    ''')
    
    # Добавляем колонку image_url, если её нет
    try:
        cur.execute('ALTER TABLE promotions ADD COLUMN image_url TEXT')
        logger.info("✅ Колонка image_url добавлена в promotions")
    except sqlite3.OperationalError:
        pass  # колонка уже существует
    
    # Таблица черновиков
    cur.execute('''
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promotion_id INTEGER REFERENCES promotions(id),
            text TEXT,
            media_id TEXT,
            status TEXT DEFAULT 'pending',
            edited_text TEXT,
            sent_to_channel BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def save_promotion(promo_data):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id FROM promotions
        WHERE store = ? AND app_id = ? AND end_date = ?
    ''', (promo_data['store'], promo_data['app_id'], promo_data['end_date']))
    existing = cur.fetchone()
    if existing:
        conn.close()
        return existing['id']
    
    cur.execute('''
        INSERT INTO promotions (
            store, app_id, title, description, discount_percent,
            old_price, new_price, currency, start_date, end_date,
            region_restricted, region_alternative, url, is_free, notified, image_url
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        promo_data['store'], 
        promo_data['app_id'], 
        promo_data['title'],
        promo_data.get('description', ''),
        promo_data.get('discount_percent', 0),
        promo_data.get('old_price'),
        promo_data.get('new_price'),
        promo_data.get('currency', ''),
        promo_data.get('start_date'),
        promo_data['end_date'],
        promo_data.get('region_restricted', 0),
        promo_data.get('region_alternative', ''),
        promo_data['url'],
        promo_data.get('is_free', 0),
        0,  # notified
        promo_data.get('image_url', '')  # image_url
    ))
    promo_id = cur.lastrowid
    conn.commit()
    conn.close()
    return promo_id

def save_draft(promo_id, text, media_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO drafts (promotion_id, text, media_id, status)
        VALUES (?, ?, ?, 'pending')
    ''', (promo_id, text, media_id))
    draft_id = cur.lastrowid
    cur.execute('UPDATE promotions SET notified = 1 WHERE id = ?', (promo_id,))
    conn.commit()
    conn.close()
    return draft_id

def get_draft(draft_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT * FROM drafts WHERE id = ?', (draft_id,))
    row = cur.fetchone()
    conn.close()
    return row

def update_draft_text(draft_id, new_text):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET edited_text = ?, status = "edited" WHERE id = ?', (new_text, draft_id))
    conn.commit()
    conn.close()

def approve_draft(draft_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET status = "approved" WHERE id = ?', (draft_id,))
    conn.commit()
    conn.close()

def reject_draft(draft_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET status = "rejected" WHERE id = ?', (draft_id,))
    conn.commit()
    conn.close()

def mark_published(draft_id, promo_id):
    """Отмечает черновик и акцию как опубликованные"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET sent_to_channel = 1, status = "published" WHERE id = ?', (draft_id,))
    cur.execute('UPDATE promotions SET published = 1 WHERE id = ?', (promo_id,))
    conn.commit()
    conn.close()

def get_promo_image(promo_id):
    """Получает URL картинки для акции"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT image_url FROM promotions WHERE id = ?', (promo_id,))
    row = cur.fetchone()
    conn.close()
    return row['image_url'] if row else None

def get_pending_drafts():
    """Получает все черновики со статусом pending, которые ещё не отправлены"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT d.* FROM drafts d
        WHERE d.status = 'pending' AND d.sent_to_channel = 0
    ''')
    drafts = cur.fetchall()
    conn.close()
    return drafts

def get_scheduled_count():
    """Получает количество запланированных черновиков"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM drafts WHERE status = 'scheduled'")
    count = cur.fetchone()[0]
    conn.close()
    return count

# Инициализация базы данных
init_db()