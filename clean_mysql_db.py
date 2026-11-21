"""
Script para LIMPIAR (vaciar) todas las tablas de la base MySQL configurada en Django.
ADVERTENCIA: borra TODOS los datos. Usar con precaucion.

Uso:
    python clean_mysql_db.py            # pide confirmacion
    python clean_mysql_db.py --yes      # sin confirmacion
"""
import os
import sys
import django

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.core.management import call_command
from django.db import connections

FORCE = '--yes' in sys.argv

def main():
    if not FORCE:
        resp = input("Esto borrara TODOS los datos de MySQL. Escribe 'SI' para confirmar: ")
        if resp.strip().upper() != 'SI':
            print("Cancelado.")
            return

    with connections['default'].cursor() as c:
        c.execute('SET FOREIGN_KEY_CHECKS=0;')

    call_command('flush', '--noinput')

    with connections['default'].cursor() as c:
        c.execute('SET FOREIGN_KEY_CHECKS=1;')

    print("Base de datos MySQL limpiada.")

if __name__ == '__main__':
    main()
