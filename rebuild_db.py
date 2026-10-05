import sqlite3
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from core.models import Categoria, Producto, Empleado, PerfilUsuario, Turno, Venta, DetalleVenta, EntradaProducto, RetiroDonacion, MovimientoInventario, InventarioDiario, Gasto, Deuda
from django.contrib.auth.models import User, Group, Permission, ContentType
from django.contrib.sessions.models import Session
from django.contrib.admin.models import LogEntry

print("Iniciando reconstrucción...")

# Eliminar DB existente
if os.path.exists('db.sqlite3'):
    os.remove('db.sqlite3')
    print("DB anterior eliminada")

# Crear DB nueva con migraciones
print("Ejecutando migraciones...")
os.system('python manage.py migrate --noinput')

# Conectar a la DB
conn = sqlite3.connect('db.sqlite3')
cursor = conn.cursor()

# Función para copiar tabla
def copy_table(model, batch_size=100):
    """Copia todos los registros de un modelo a la DB."""
    total = model.objects.count()
    if total == 0:
        print(f"  {model.__name__}: sin datos")
        return
    # Obtener campos
    fields = [f.name for f in model._meta.fields]
    placeholders = ','.join(['?' for _ in fields])
    insert_sql = f'INSERT INTO "{model._meta.db_table}" VALUES ({placeholders})'
    
    inserted = 0
    for i in range(0, total, batch_size):
        objs = model.objects.all()[i:i+batch_size]
        rows = []
        for obj in objs:
            vals = []
            for f in fields:
                val = getattr(obj, f)
                if val is None:
                    vals.append(None)
                elif hasattr(val, 'pk'):
                    vals.append(val.pk)
                else:
                    vals.append(val)
            rows.append(vals)
        cursor.executemany(insert_sql, rows)
        inserted += len(rows)
    conn.commit()
    print(f"  {model.__name__}: {inserted} filas")

# Copiar en orden correcto (respetando FKs)
print("\nCopiando datos...")
copy_table(ContentType)
copy_table(Permission)
copy_table(Group)
copy_table(User)
copy_table(Categoria)
copy_table(Producto)
copy_table(Empleado)
copy_table(PerfilUsuario)
copy_table(Turno)
copy_table(Venta)
copy_table(DetalleVenta)
copy_table(EntradaProducto)
copy_table(RetiroDonacion)
copy_table(MovimientoInventario)
copy_table(InventarioDiario)
copy_table(Gasto)
copy_table(Deuda)
copy_table(Session)  # django_session
# LogEntry requiere datos de content_type, ya copiados
copy_table(LogEntry)

# Actualizar secuencias
print("\nActualizando secuencias AUTOINCREMENT...")
tables = [
    'auth_user', 'core_categoria', 'core_producto', 'core_empleado',
    'core_perfilusuario', 'core_turno', 'core_venta', 'core_detalleventa',
    'core_entradaproducto', 'core_movimientoinventario', 'core_inventariodiario',
]

for table in tables:
    cursor.execute(f"SELECT MAX(id) FROM {table}")
    max_id = cursor.fetchone()[0] or 0
    cursor.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, max_id))
    print(f"  {table}: seq={max_id}")

conn.commit()
conn.close()

print("\n✅ Base de datos reconstruida exitosamente")
print("Verificando integridad...")
conn2 = sqlite3.connect('db.sqlite3')
cur2 = conn2.cursor()
cur2.execute('PRAGMA integrity_check')
result = cur2.fetchone()[0]
print(f"Integridad: {result}")
conn2.close()
