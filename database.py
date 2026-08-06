import sqlite3
from datetime import datetime
import config

def get_db_connection():
    conn = sqlite3.connect(config.DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(store, app_id, end_date)
        )
    ''')
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
            region_restricted, region_alternative, url, is_free, notified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        promo_data['store'], promo_data['app_id'], promo_data['title'],
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
        0
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET sent_to_channel = 1 WHERE id = ?', (draft_id,))
    cur.execute('UPDATE promotions SET published = 1 WHERE id = ?', (promo_id,))
    conn.commit()
    conn.close()

init_db()