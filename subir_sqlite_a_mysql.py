#!/usr/bin/env python
"""
Sube los datos de un archivo SQLite3 a la base de datos MySQL configurada en
system_erp.settings (variables de entorno DB_NAME, DB_USER, DB_PASSWORD, DB_HOST,
DB_PORT). Está pensado para ejecutarse EN EL SERVIDOR (cPanel/Passenger) durante
una ventana breve sin ventas: el destino es la BD local del hosting.

Uso típico en el servidor:

    # 1) subir el db.sqlite3 de PythonAnywhere a una ruta del servidor, p. ej.
    #    /home/USUARIO/sistema-erp/db.sqlite3
    # 2) con la app en mantenimiento (o sin ventas), ejecutar:
    python subir_sqlite_a_mysql.py --sqlite /home/USUARIO/sistema-erp/db.sqlite3

    # Si ya está en la raíz del proyecto o en SQLITE_SOURCE, basta:
    python subir_sqlite_a_mysql.py

    # Para probar sin escribir nada:
    python subir_sqlite_a_mysql.py --dry-run

Opciones:
  --sqlite RUTA     Ruta al db.sqlite3 de origen (por defecto: ./db.sqlite3 o SQLITE_SOURCE).
  --dry-run         Solo valida el origen y muestra los conteos; no escribe en MySQL.
  --no-verificar    Omite la comparación final de conteos.

Notas:
  * Se conservan los IDs (PK) de todas las filas. Volver a ejecutar el script
    actualiza las filas existentes en MySQL; no debería duplicarlas.
  * NO se usa --natural-primary: los usuarios de Django no tienen natural key y
    eso deja los PK sin definir (rompe las claves foráneas).
  * Se desconectan los signals que crean PerfilUsuario automáticamente para
    evitar el choque "Duplicate entry ... for key 'user_id'".
  * Se corrigen texto en Latin-1 que pueda tener el SQLite antiguo.
"""

import argparse
import io
import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connections  # noqa: E402

SQLITE_ALIAS = 'sqlite_origen'

TABLAS_VERIFICAR = [
    'auth_user',
    'core_perfilusuario',
    'core_categoria',
    'core_producto',
    'core_venta',
    'core_detalleventa',
    'core_deuda',
    'core_abonodeuda',
    'core_empleado',
    'core_arqueoturno',
    'core_almacenstock',
    'core_movimientoinventario',
    'core_configuraciontienda',
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument('--sqlite', default=None, help='Ruta al db.sqlite3 de origen.')
    parser.add_argument('--dry-run', action='store_true', help='No escribe en MySQL.')
    parser.add_argument('--no-verificar', action='store_true', help='Omite la comparación final.')
    return parser.parse_args()


def resolver_sqlite(argumento):
    candidato = argumento or os.environ.get('SQLITE_SOURCE') or str(BASE_DIR / 'db.sqlite3')
    ruta = Path(candidato).expanduser().resolve()
    if not ruta.is_file():
        raise SystemExit(f'ERROR: no existe el archivo SQLite: {ruta}')
    with ruta.open('rb') as handle:
        cabecera = handle.read(16)
    if cabecera != b'SQLite format 3\x00':
        raise SystemExit(f'ERROR: {ruta} no parece un archivo SQLite válido.')
    return ruta


def verificar_destino():
    conf = settings.DATABASES['default']
    engine = conf.get('ENGINE', '')
    if 'mysql' not in engine:
        raise SystemExit(
            'ERROR: el destino no es MySQL (ENGINE=%s). Configura DB_* en el servidor.' % engine
        )
    try:
        connections['default'].ensure_connection()
    except Exception as exc:
        raise SystemExit(f'ERROR: no se pudo conectar a MySQL: {exc}')
    cursor = connections['default'].cursor()
    cursor.execute("SELECT 1 FROM information_schema.tables "
                   "WHERE table_schema=DATABASE() AND table_name='django_migrations'")
    if not cursor.fetchone():
        raise SystemExit(
            'ERROR: la BD de destino no tiene el esquema. Ejecuta antes: python manage.py migrate'
        )
    cursor.close()
    print('Destino MySQL: {name} @ {host}:{port} (usuario {user})'.format(
        name=conf.get('NAME'), host=conf.get('HOST'), port=conf.get('PORT'),
        user=conf.get('USER')))


def configurar_sqlite(ruta):
    connections.databases[SQLITE_ALIAS] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': str(ruta),
        'OPTIONS': {},
        'TIME_ZONE': None,
        'CONN_MAX_AGE': 0,
        'ATOMIC_REQUESTS': False,
        'AUTOCOMMIT': True,
        'CONN_HEALTH_CHECKS': False,
        'TEST': {},
    }


def corregir_latin1(texto):
    """Convierte bytes Latin-1 que Django serializó como surrogates a UTF-8 real."""
    return ''.join(
        chr(ord(car) - 0xDC00) if 0xDC80 <= ord(car) <= 0xDCFF else car
        for car in texto
    )


def volcar(ruta_sqlite, ruta_fixture):
    configurar_sqlite(ruta_sqlite)
    buffer = io.StringIO()
    print('Volcando datos desde %s ...' % ruta_sqlite.name)
    call_command(
        'dumpdata',
        database=SQLITE_ALIAS,
        natural_foreign=True,
        exclude=['contenttypes', 'auth.permission'],
        verbosity=0,
        stdout=buffer,
    )
    contenido = corregir_latin1(buffer.getvalue())
    with open(ruta_fixture, 'w', encoding='utf-8', newline='') as handle:
        handle.write(contenido)
    print('Volcado generado: %d objetos, %d bytes' % (
        contenido.count('"model"'), len(contenido.encode('utf-8'))))


def cargar(ruta_fixture):
    from django.contrib.auth.models import User
    from django.db.models.signals import post_save
    from core.models import crear_perfil_usuario, guardar_perfil_usuario

    post_save.disconnect(crear_perfil_usuario, sender=User)
    post_save.disconnect(guardar_perfil_usuario, sender=User)
    try:
        call_command('loaddata', str(ruta_fixture), verbosity=1)
    finally:
        post_save.connect(crear_perfil_usuario, sender=User)
        post_save.connect(guardar_perfil_usuario, sender=User)


def conteos(ruta_sqlite):
    import sqlite3

    resultado = {}
    conn_sqlite = sqlite3.connect(str(ruta_sqlite))
    cursor_sqlite = conn_sqlite.cursor()
    cursor_mysql = connections['default'].cursor()
    for tabla in TABLAS_VERIFICAR:
        try:
            cursor_sqlite.execute('SELECT COUNT(*) FROM "%s"' % tabla)
            origen = cursor_sqlite.fetchone()[0]
        except Exception as exc:
            origen = 'ERR: %s' % exc
        try:
            cursor_mysql.execute('SELECT COUNT(*) FROM `%s`' % tabla)
            destino = cursor_mysql.fetchone()[0]
        except Exception as exc:
            destino = 'ERR: %s' % exc
        resultado[tabla] = (origen, destino)
    cursor_sqlite.close()
    cursor_mysql.close()
    conn_sqlite.close()
    return resultado


def main():
    args = parse_args()
    ruta_sqlite = resolver_sqlite(args.sqlite)
    print('Origen SQLite: %s' % ruta_sqlite)
    verificar_destino()

    with tempfile.TemporaryDirectory(prefix='subida_sqlite_') as temporal:
        ruta_fixture = Path(temporal) / 'datos.json'
        volcar(ruta_sqlite, ruta_fixture)

        if args.dry_run:
            print('DRY-RUN: no se escribió nada en MySQL.')
            return

        print('Cargando datos en MySQL ...')
        cargar(ruta_fixture)
        print('Carga terminada.')

    if not args.no_verificar:
        print('\nComparación de conteos (SQLite -> MySQL):')
        print('%-32s %10s %10s' % ('tabla', 'sqlite', 'mysql'))
        for tabla, (origen, destino) in conteos(ruta_sqlite).items():
            marca = 'OK' if origen == destino else '*** DIFIERE ***'
            print('%-32s %10s %10s  %s' % (tabla, origen, destino, marca))


if __name__ == '__main__':
    main()
