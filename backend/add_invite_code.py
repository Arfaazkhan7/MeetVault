import sqlite3
conn = sqlite3.connect('meetingdb.db')
cursor = conn.cursor()

# Add invite_code column
cursor.execute('ALTER TABLE meetings ADD COLUMN invite_code TEXT')
print('Added invite_code column')

# Create unique index
cursor.execute('CREATE UNIQUE INDEX ix_meetings_invite_code ON meetings (invite_code)')
print('Created unique index')

conn.commit()
conn.close()
print('Done')