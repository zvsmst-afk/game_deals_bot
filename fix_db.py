# fix_db.py
import sqlite3
import os

def fix_database():
    db_path = 'deals.db'
    if not os.path.exists(db_path):
        print("❌ База данных не найдена")
        return
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # Проверяем, есть ли колонка image_url
    cur.execute("PRAGMA table_info(promotions)")
    columns = [col[1] for col in cur.fetchall()]
    
    if 'image_url' not in columns:
        print("➕ Добавляю колонку image_url...")
        cur.execute('ALTER TABLE promotions ADD COLUMN image_url TEXT')
        print("✅ Колонка image_url добавлена")
    else:
        print("ℹ️ Колонка image_url уже существует")
    
    conn.commit()
    conn.close()
    print("✅ Готово!")

if __name__ == '__main__':
    fix_database()