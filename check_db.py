
import sqlite3
import os

db_path = os.path.join(os.getcwd(), 'instance', 'app.db')
if not os.path.exists(db_path):
    # try root path
    db_path = 'app.db'

print(f"Checking DB at {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if column exists
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'profile_info' not in columns:
        print("Adding profile_info column...")
        cursor.execute("ALTER TABLE users ADD COLUMN profile_info JSON")
        conn.commit()
        print("Column added.")
    else:
        print("Column profile_info already exists.")
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
