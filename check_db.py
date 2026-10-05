import sqlite3

conn = sqlite3.connect('db.sqlite3')
c = conn.cursor()

# Get list of tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('Tables:')
for table in tables:
    print('  ', table[0])
    try:
        c.execute(f'PRAGMA table_info("{table[0]}")')
        cols = c.fetchall()
        print(f'    Columns: {len(cols)}')
        # Try to count rows
        c.execute(f'SELECT COUNT(*) FROM "{table[0]}"')
        count = c.fetchone()[0]
        print(f'    Rows: {count}')
    except Exception as e:
        print(f'    Error: {e}')

conn.close()