#!/usr/bin/env python3
"""
Migra los datos de la BD de PythonAnywhere (este directorio) a Supabase PostgreSQL.

Uso (desde la raíz del proyecto Django):
    python "BD pythonanywhere/migrar_a_supabase.py"

El script lee la URL de `.bd_supabase_url` (archivo local ignorado por Git,
en esta misma carpeta). Si no existe, usa la variable de entorno DATABASE_URL
o la pide por consola sin mostrarla.
La contraseña NUNCA se escribe en este archivo ni se sube al repositorio.

Qué hace:
  1. Verifica la integridad de la BD SQLite de origen (solo lectura).
  2. Aplica las migraciones de Django en Supabase (si faltan).
  3. Exporta `core` + usuarios desde SQLite con claves primarias (rápido).
  4. Carga esa exportación en Supabase con `loaddata`.
  5. Ajusta las secuencias de PostgreSQL y muestra conteos.

NO toca la bd.sqlite3 de la raíz del proyecto ni los respaldos.
"""

import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_DIR = HERE.parent
SOURCE_DB = HERE / "db.sqlite3"
DUMP_FILE = Path(os.environ.get("TEMP", "/tmp")) / "erp_pa_dump_fast.json"
URL_FILE = HERE / ".bd_supabase_url"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Con DEBUG=True en este proceso evitamos exigir DJANGO_SECRET_KEY para una
# tarea puntual de migración. NO afecta al servicio desplegado en Render.
os.environ.setdefault("DJANGO_DEBUG", "True")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "system_erp.settings")


def _get_dsn():
    dsn = ""
    if URL_FILE.exists():
        dsn = URL_FILE.read_text(encoding="utf-8-sig").strip()
    if not dsn:
        dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        try:
            import getpass
            dsn = getpass.getpass("Pega el DATABASE_URL de Supabase: ").strip()
        except Exception:
            dsn = input("Pega el DATABASE_URL de Supabase: ").strip()
    if not dsn.startswith(("postgresql://", "postgres://")):
        raise SystemExit("ERROR: DATABASE_URL no es una URL de PostgreSQL.")
    return dsn


def _check_source():
    import sqlite3
    if not SOURCE_DB.exists():
        raise SystemExit(f"No existe la BD de origen: {SOURCE_DB}")
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise SystemExit(f"La BD de origen no pasó integrity_check: {result}")
        tablas = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        print(f"Origen: {SOURCE_DB} ({SOURCE_DB.stat().st_size:,} bytes, {tablas} tablas) - OK")
    finally:
        conn.close()


def main():
    _check_source()
    dsn = _get_dsn()
    # IMPORTANTE: definirlo ANTES de importar django.conf.settings, porque
    # settings.py lee DATABASE_URL en el momento de importarse.
    os.environ["DATABASE_URL"] = dsn

    from django.conf import settings

    # Alias de solo lectura hacia la BD de PythonAnywhere.
    settings.DATABASES["source"] = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(SOURCE_DB),
        "ATOMIC_REQUESTS": False,
        "AUTOCOMMIT": True,
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": False,
        "OPTIONS": {},
        "TIME_ZONE": None,
        "USER": "",
        "PASSWORD": "",
        "HOST": "",
        "PORT": "",
        "TEST": {"MIRROR": None, "NAME": None},
    }
    # 'default' ya apunta a Supabase gracias a DATABASE_URL.

    import django
    django.setup()

    from django.core.management import call_command
    from django.db import connections, transaction

    host = settings.DATABASES["default"].get("HOST", "")
    print(f"Destino: PostgreSQL en {host}")
    resp = input("¿Continuar migrando datos a ese destino? (escribe SI): ").strip()
    if resp.upper() != "SI":
        raise SystemExit("Cancelado por el usuario.")

    # 1) Esquema (idempotente: no destruye nada).
    print("\n[1/4] Aplicando migraciones en Supabase...")
    call_command("migrate", database="default", interactive=False, verbosity=1)

    # 2) Volcado rápido desde SQLite con PKs (sin claves naturales).
    print(f"\n[2/4] Exportando datos desde PythonAnywhere -> {DUMP_FILE} ...")
    call_command(
        "dumpdata",
        "core",
        "auth.User",
        database="source",
        indent=0,
        output=str(DUMP_FILE),
        verbosity=0,
    )
    print(f"Exportado: {DUMP_FILE.stat().st_size:,} bytes")

    # 3) Carga en Supabase.
    print("\n[3/4] Cargando datos en Supabase (puede tardar varios minutos)...")
    call_command("loaddata", str(DUMP_FILE), database="default", verbosity=1)

    # 4) Secuencias y verificación.
    print("\n[4/4] Ajustando secuencias y verificando...")
    buf = io.StringIO()
    call_command("sqlsequencereset", "core", database="default", stdout=buf)
    sql = buf.getvalue().strip()
    if sql:
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur:
                cur.execute(sql)

    from core.models import Producto, Venta, Deudor, Deuda, Almacen
    from django.contrib.auth.models import User
    print("\nConteos finales en Supabase:")
    for name, model in [
        ("productos", Producto),
        ("ventas", Venta),
        ("deudores", Deudor),
        ("deudas", Deuda),
        ("almacenes", Almacen),
        ("usuarios", User),
    ]:
        print(f"  {name}: {model.objects.using('default').count()}")

    print("\nMigración terminada. Revisa el ERP en Render.")


if __name__ == "__main__":
    main()
