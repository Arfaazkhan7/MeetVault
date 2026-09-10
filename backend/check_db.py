import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'meetingdb.db')
if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    db_path = os.path.join(os.path.dirname(__file__), 'meetvault.db')

conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(f"Tables in {os.path.basename(db_path)}:", c.fetchall())

try:
    c.execute("PRAGMA table_info(meetings);")
    print("Meetings columns:", c.fetchall())
except sqlite3.OperationalError as e:
    print(f"Error querying meetings: {e}")

try:
    c.execute("SELECT * FROM company_members")
    print("Company Members:")
    for row in c.fetchall():
        print(row)
    
    c.execute("SELECT * FROM users")
    print("Users:")
    for row in c.fetchall():
        print(row)
except sqlite3.OperationalError as e:
    print(f"Error querying: {e}")

conn.close()