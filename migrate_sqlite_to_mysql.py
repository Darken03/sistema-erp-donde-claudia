"""
Migra datos de SQLite a MySQL usando SQL crudo (INSERT explicito),
lo que garantiza que las fechas (fecha_venta, etc.) se conserven exactamente.

Uso:
    python migrate_sqlite_to_mysql.py "db (10).sqlite3"
    python migrate_sqlite_to_mysql.py "db (10).sqlite3" --clean
"""
import os
import sys
import sqlite3
import django

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.db import connections

SQLITE_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, 'db.sqlite3')
CLEAN = '--clean' in sys.argv

# Tablas que Django crea con `migrate` y NO deben copiarse desde SQLite
SKIP_TABLES = {
    'django_migrations', 'django_content_type', 'auth_permission',
    'django_admin_log', 'django_session',
}

# Conectar a SQLite directamente
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
src_cur = src.cursor()

mysql = connections['default']
mysql_cur = mysql.cursor()

# Desactivar checks de FK
mysql_cur.execute('SET FOREIGN_KEY_CHECKS=0;')

# Obtener lista de tablas en SQLite
src_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
tables = [r[0] for r in src_cur.fetchall()]

for table in tables:
    if table in SKIP_TABLES:
        print(f'{table}: omitida (gestionada por Django)')
        continue

    # Columnas de la tabla en SQLite
    src_cur.execute(f'PRAGMA table_info("{table}")')
    columns = [r[1] for r in src_cur.fetchall()]
    if not columns:
        continue

    # Verificar que la tabla exista en MySQL
    mysql_cur.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s",
        [table],
    )
    if mysql_cur.fetchone()[0] == 0:
        print(f'{table}: no existe en MySQL, se omite')
        continue

    if CLEAN:
        mysql_cur.execute(f'TRUNCATE TABLE `{table}`')

    # Leer filas de SQLite
    src_cur.execute(f'SELECT {", ".join(chr(96)+c+chr(96) for c in columns)} FROM "{table}"')
    rows = src_cur.fetchall()
    if not rows:
        print(f'{table}: 0 filas')
        continue

    # Filtrar filas cuya PK ya exista en MySQL (evita duplicados/conflictos)
    # Detectar PK
    src_cur.execute(f'PRAGMA table_info("{table}")')
    pk_cols = [r[1] for r in src_cur.fetchall() if r[5] == 1]
    if pk_cols and not CLEAN:
        pk = pk_cols[0]
        mysql_cur.execute(f'SELECT `{pk}` FROM `{table}`')
        existing = {r[0] for r in mysql_cur.fetchall()}
        rows = [r for r in rows if r[pk] not in existing]
        if not rows:
            print(f'{table}: 0 nuevos (ya existian)')
            continue

    placeholders = ', '.join(['%s'] * len(columns))
    col_list = ', '.join(f'`{c}`' for c in columns)
    sql = f'INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})'

    data = [tuple(r[c] for c in columns) for r in rows]
    mysql_cur.executemany(sql, data)
    print(f'{table}: {len(data)} filas migradas')

mysql_cur.execute('SET FOREIGN_KEY_CHECKS=1;')

# Resetear AUTO_INCREMENT
for table in tables:
    if table in SKIP_TABLES:
        continue
    try:
        mysql_cur.execute(f'SELECT MAX(id) FROM `{table}`')
        max_id = mysql_cur.fetchone()[0]
        if max_id:
            mysql_cur.execute(f'ALTER TABLE `{table}` AUTO_INCREMENT = {max_id + 1}')
    except Exception:
        pass

src.close()
mysql.close()
print('Migracion completada.')
