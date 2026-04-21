import sqlite3

conn = sqlite3.connect('db.sqlite3')
cur = conn.cursor()

cur.execute("""
    SELECT sql FROM sqlite_master
    WHERE type='table'
    AND sql IS NOT NULL
    AND (name LIKE 'accounts_%' OR name LIKE 'vacancies_%')
    ORDER BY name
""")

with open('schema.sql', 'w', encoding='utf-8') as f:
    for row in cur.fetchall():
        f.write(row[0] + ';\n\n')

conn.close()
print('Done — schema.sql создан')