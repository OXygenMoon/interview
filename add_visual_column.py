
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'app.db')

def migrate():
    print(f"Checking database at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN visual_context TEXT")
        print("Successfully added 'visual_context' column to chat_messages table.")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("Column 'visual_context' already exists.")
        else:
            print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
