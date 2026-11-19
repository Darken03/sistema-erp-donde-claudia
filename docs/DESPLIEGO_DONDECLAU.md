# Despliegue en `dondeclau.algomio.com` (cPanel / Passenger)

Este documento describe cómo quedaría la configuración del ERP para el dominio
`dondeclau.algomio.com` usando cPanel con Phusion Passenger y MySQL/MariaDB.

## 1. Cambios ya aplicados en el repositorio

- `system_erp/settings.py`
  - `dondeclau.algomio.com` agregado a `ALLOWED_HOSTS`.
  - `https://dondeclau.algomio.com` agregado a `CSRF_TRUSTED_ORIGINS`.
  - `DATABASES` ahora usa MySQL por defecto con estos valores:
    - `DB_NAME=algomio_dondeclaudia`
    - `DB_USER=algomio_bizzmaster`
    - `DB_PASSWORD=Algo@2026`
    - `DB_HOST=localhost`
    - `DB_PORT=3306`
  - Todos esos valores se pueden sobrescribir por variables de entorno.
- `requirements.txt`: agregado `mysqlclient==2.3.2`.
- `passenger_wsgi.py`: entry point de Passenger, con la lista de variables de entorno requeridas.
- `.htaccess`: configurado para Passenger en modo `production` (revisar los placeholders `USERNAME`).

## 2. Base de datos en el hosting

1. En cPanel → **MySQL Databases**, crea la base de datos:
   - Nombre: `algomio_dondeclaudia`
2. Crea el usuario:
   - Usuario: `algomio_bizzmaster`
   - Contraseña: `Algo@2026`
3. Asocia el usuario a la BD con **TODOS LOS PRIVILEGIOS**.
4. Sube el código y crea el entorno virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate      # en cPanel puede ser /home/USUARIO/venv/bin/activate
   pip install -r requirements.txt
   ```
5. Define las variables de entorno de la aplicación (en cPanel → *Setup Python App* →
   *Environment variables*, o en el panel de Passenger):
   ```
   DJANGO_DEBUG=False
   DJANGO_SECRET_KEY=<genera una clave larga y aleatoria>
   DJANGO_ALLOWED_HOSTS=dondeclau.algomio.com
   DB_NAME=algomio_dondeclaudia
   DB_USER=algomio_bizzmaster
   DB_PASSWORD=Algo@2026
   DB_HOST=localhost
   DB_PORT=3306
   ```
6. Prepara la BD y lo estático:
   ```bash
   python manage.py migrate --noinput
   python manage.py collectstatic --noinput
   ```

> Si vas a importar la información desde el SQLite local, usa el mismo procedimiento
> de `dumpdata`/`loaddata` descrito en `docs/MIGRACION_MYSQL_LOCAL.md`.

## 3. Passenger

1. El document root del dominio debe contener este proyecto.
2. Revisa `.htaccess`:
   - `PassengerAppRoot` debe apuntar a la carpeta del proyecto.
   - `PassengerPython` debe apuntar al Python del virtualenv.
3. `passenger_wsgi.py` ya define `DJANGO_SETTINGS_MODULE=system_erp.settings` y expone `application`.
4. En cPanel reinicia/recarga la aplicación (botón *Restart*).

## 4. Verificación

```bash
python manage.py check
python manage.py showmigrations core
```

También puedes abrir `https://dondeclau.algomio.com/login/` y comprobar que carga sin
error 400 de `ALLOWED_HOSTS` y que el login hace POST correctamente (CSRF).

## 5. Subir los datos desde el SQLite de PythonAnywhere

Cuando ya tengas el `db.sqlite3` de PythonAnywhere en el servidor, usa el script
`subir_sqlite_a_mysql.py` (incluido en la raíz del proyecto):

```bash
# apaga la app / pon mantenimiento unos segundos para que no haya ventas
python subir_sqlite_a_mysql.py --sqlite /home/USUARIO/sistema-erp/db.sqlite3

# prueba sin escribir nada antes de hacerlo en real:
python subir_sqlite_a_mysql.py --sqlite /home/USUARIO/sistema-erp/db.sqlite3 --dry-run
```

El script conserva los IDs, corrige el texto Latin-1 del SQLite y evita el conflicto
de los signals que crean `PerfilUsuario`. Al terminar imprime una comparación de
conteos por tabla. Si la ruta no se pasa por `--sqlite`, la busca en `SQLITE_SOURCE`
o en `./db.sqlite3`. Para más detalle, ver `docs/MIGRACION_MYSQL_LOCAL.md`.

Para detener la venta brevemente en cPanel/Passenger puedes, por ejemplo,
renombrar `passenger_wsgi.py` a `passenger_wsgi.py.off` (la app deja de responder),
ejecutar el script y volver a renombrarlo. O simplemente hacerlo fuera del horario
de ventas.

## 6. Notas de seguridad

- Cambia `DJANGO_SECRET_KEY` por un valor único en producción.
- Mantén `DJANGO_DEBUG=False` en el dominio público.
- Las credenciales de BD mostradas son las que indicaste para tu aplicación; si el
  hosting permite usuarios de BD con nombre de host restringido, verifica que `algomio_bizzmaster`
  tenga permisos desde `localhost` (o desde el host que use cPanel).
