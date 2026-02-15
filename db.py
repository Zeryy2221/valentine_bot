import sqlite3

conn = sqlite3.connect("valentine_bot.db")
cursor = conn.cursor()

# Пользователи
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT
)
""")

# Ссылки
cursor.execute("""
CREATE TABLE IF NOT EXISTS links (
    owner_id INTEGER,
    code TEXT PRIMARY KEY,
    clicks INTEGER DEFAULT 0
)
""")

# Валентинки
cursor.execute("""
CREATE TABLE IF NOT EXISTS valentines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    to_user INTEGER,
    from_user INTEGER,
    from_username TEXT,
    text TEXT,
    anonymous INTEGER DEFAULT 0,
    revealed INTEGER DEFAULT 0
)
""")

conn.commit()