# Despliegue del ERP en Render + Supabase (PostgreSQL)

Estado: **infraestructura preparada; migración de datos REAL pendiente y controlada.**

Proyecto: `BizzMaster Claudia\sistema-erp-donde-claudia` (rama `main`).

La aplicación sigue funcionando igual en local con SQLite. Este documento describe
cómo desplegarla sin tocar `db.sqlite3` ni sus respaldos.

---

## 1. Qué se ha cambiado en el repositorio

| Archivo | Cambio |
| --- | --- |
| `system_erp/settings.py` | Configuración dual SQLite (local) / PostgreSQL (Render). Secretos y hosts por variables de entorno. WhiteNoise. Cabeceras de seguridad. |
| `requirements.txt` | Añadidos `gunicorn`, `psycopg[binary]`, `dj-database-url` y `whitenoise`. Se conservaron `waitress` (fijado a `3.0.2`) y `pillow-heif` (fijado a `1.8.0`, usado por `core/forms.py` y `core/views.py`). |
| `.gitignore` | Añadidos `.env`, `.env.*`, `*.env`, `.dev_secret_key` y `*.log`. Ya excluía `db.sqlite3`, `*.backup`, `media/` y `staticfiles/`. |
| `render.yaml` | Blueprint opcional para Render (sin base de datos propia: se usa Supabase). |
| `DEPLOY_RENDER.md` | Este documento. |

No se han ejecutado migraciones destructivas ni scripts de datos (`reset_db.py`,
`rebuild_db.py`, `populate_db.py`, etc.).

---

## 2. Restricciones de datos (IMPORTANTE)

- `db.sqlite3`, `db.sqlite3.backup`, `db.sqlite3.backup_pre_despliegue_2026-09-16`
  y los demás respaldos **no se han tocado**.
- No se importan datos automáticamente durante el build ni el arranque.
- **No ejecutes `python manage.py migrate` contra Supabase hasta que exista un
  respaldo verificado y se revise el plan de migración.** `migrate` crea el
  esquema; no borra datos de SQLite, pero debes decidir cuándo ejecutarlo.
- El build de Render solo instala dependencias y recoge estáticos.

---

## 3. Variables de entorno en Render

Configúralas en el Web Service → *Environment* (o en el Blueprint si usas
`render.yaml`). **La contraseña jamás se escribe en el repositorio.**

| Variable | Valor | Obligatoria | Notas |
| --- | --- | --- | --- |
| `DATABASE_URL` | `postgresql://<USUARIO_SUPABASE>:<NUEVA_CONTRASEÑA>@aws-1-us-east-2.pooler.supabase.com:5432/postgres?sslmode=require` | Sí | Copia el usuario exacto desde el dashboard de Supabase (formato `postgres.<ref-del-proyecto>`). Codifica los caracteres especiales de la contraseña (`@` → `%40`, `#` → `%23`, etc.). Usa la contraseña **nueva** tras rotar la expuesta. |
| `DJANGO_SECRET_KEY` | Valor aleatorio largo (p. ej. generado con `python -c "import secrets; print(secrets.token_urlsafe(50))"`) | Sí | `settings.py` falla a propósito si falta en producción. |
| `DJANGO_DEBUG` | `False` | Sí | Con `DATABASE_URL` definida ya sería `False` por defecto; indícalo igualmente. |
| `DJANGO_ALLOWED_HOSTS` | `tu-servicio.onrender.com,tu-dominio.com` | No | Render aporta `RENDER_EXTERNAL_HOSTNAME` automáticamente y `settings.py` lo añade solo. Añade aquí dominios propios (p. ej. el de Enzonic). |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://tu-servicio.onrender.com,https://tu-dominio.com` | No | Igual que arriba: el host de Render se añade solo con `https://`. |
| `DJANGO_SECURE_SSL_REDIRECT` | `False` | No | Solo si la health check falla por redirecciones. |
| `PYTHON_VERSION` | `3.13.7` | No | Ya viene en `render.yaml` si usas Blueprint. |

### Tipo de conexión a Supabase

- Host: `aws-1-us-east-2.pooler.supabase.com`
- Puerto: `5432` → **Session pooler** (no el transaction pooler, que usa 6543).
- Base de datos: `postgres`
- Usuario: `postgres.<ref-del-proyecto>` (obtén el valor exacto del dashboard; no se guarda en el repositorio)
- SSL: obligatorio (`sslmode=require`).
- `conn_max_age=600` y `conn_health_checks=True` son correctos para el
  **session pooler**. Si en el futuro cambias al *transaction pooler* (puerto
  6543), pon `conn_max_age=0` y desactiva prepared statements
  (`OPTIONS: {'prepare_threshold': None}`). **No cambies host ni puerto sin
  verificarlo en el dashboard de Supabase.**

---

## 4. Comandos recomendados en Render

**Root Directory:** vacío (raíz del repositorio).

**Runtime:** Python 3.13 (`PYTHON_VERSION=3.13.7`).

**Build Command:**

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput
```

`collectstatic` es obligatorio porque se usa
`whitenoise.storage.CompressedManifestStaticFilesStorage`: sin el manifiesto,
Django no arranca. No incluye `migrate`.

**Start Command:**

```bash
gunicorn system_erp.wsgi:application
```

Gunicorn detecta `PORT` de Render y enlaza `0.0.0.0:$PORT`. Equivalente
explícito: `gunicorn system_erp.wsgi:application --bind 0.0.0.0:$PORT`.

**Opcional (recomendado para rendimiento):**

```bash
gunicorn system_erp.wsgi:application --workers 2 --timeout 120
```

En el plan gratuito, usa 1–2 workers para no agotar memoria.

---

## 5. Pasos para desplegar

1. **Rotar la contraseña de Supabase** (la anterior estuvo expuesta). Copiar la
   nueva contraseña del dashboard; no guardarla en archivos.
2. Construir `DATABASE_URL` con esa contraseña (formato de la sección 3).
3. Generar `DJANGO_SECRET_KEY` nuevo.
4. En Render: *New → Web Service* → conectar el repo GitHub (rama `main`) →
   Root Directory vacío → Python 3 → pegar Build y Start commands.
5. Añadir las variables de entorno de la sección 3.
6. Crear el servicio. El build instalará dependencias y recogerá estáticos.
7. **Probar la conexión a Supabase** antes de migrar datos:
   - En Render Shell: `python manage.py check --database default`
   - En Render Shell: `python manage.py dbshell` y `SELECT version();`
   - Si falla, revisar contraseña, codificación URL, SSL y que el proyecto de
     Supabase no esté pausado.
8. Crear el esquema **cuando tú lo decidas**: `python manage.py migrate`.
   (No está incluido en el build.)
9. Verificar: `python manage.py check`, carga del login, y que
   `/static/` responde con WhiteNoise.
10. Migrar los datos reales con un procedimiento controlado (sección 7).

Si usas Blueprint en vez del dashboard: *Blueprints → New Blueprint Instance →
seleccionar el repo → Apply*. Render pedirá los valores `sync: false`.

---

## 6. Archivos multimedia (pendiente de solución persistente)

Situación actual en este proyecto:

- `core.Producto.imagen` → `media/productos/` (**408 archivos**)
- `core.ConfiguracionTienda.logo` → `media/tienda/` (**36 archivos**)
- `MEDIA_ROOT = BASE_DIR / 'media'`, `MEDIA_URL = '/media/'`
- `system_erp/urls.py` sirve `/media/` **solo cuando `DEBUG=True`**.
- `.gitignore` excluye `media/`: **los 444 archivos no se suben a GitHub y, por
  tanto, no existirán en Render**. No se han movido ni borrado.
- El sistema de archivos de Render es efímero: los uploads se perderían al
  reiniciar o redesplegar.

**No se ha cambiado nada de esto todavía.**

Recomendación para cuando se implemente (requiere credenciales externas):

1. **Supabase Storage** (coherente con la BD) usando el SDK `supabase` o su API
   S3-compatible con `django-storages` (`S3Boto3Storage`).
   - Añadir `django-storages[boto3]` a `requirements.txt`.
   - Crear un bucket privado/público según convenga y una policy de acceso.
   - Añadir variables: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` /
     `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`,
     `AWS_S3_ENDPOINT_URL`.
   - Definir `STORAGES['default']` con el backend remoto, manteniendo
     `MEDIA_URL` apropiada.
   - Subir los 444 archivos de `media/` con un script **explícito y manual**
     (nunca automático en el deploy).
2. Alternativa simple: Cloudinary (`django-cloudinary-storage`).

Hasta entonces, el ERP en Render funcionará sin imágenes/subidas persistentes.

---

## 7. Procedimiento controlado de migración de datos (PENDIENTE)

No ejecutado. Orden sugerido, con respaldo y verificación en cada paso:

1. `python manage.py dumpdata --natural-foreign --natural-primary -o backup_antes_migracion.json`
   (en local, sobre SQLite; guardar fuera del repo).
2. Verificar integridad de `db.sqlite3` y copias existentes (`PRAGMA integrity_check`).
3. Crear esquema en Supabase: `python manage.py migrate` (Render Shell).
4. Cargar datos con `python manage.py loaddata backup_antes_migracion.json`
   **solo después** de revisar el archivo y en una ventana controlada.
5. Ajustar secuencias de PostgreSQL: `python manage.py sqlsequencereset core | python manage.py shell`.
6. Verificar conteos de inventario, ventas, compras, deudas, pagos, almacenes
   y usuarios contra SQLite.
7. Copiar los 444 archivos de `media/` al almacenamiento persistente (sección 6).

**No hacerlo de forma automática en build ni en start.**

---

## 8. Comprobaciones realizadas en este repositorio

- [x] `python manage.py check` (local, SQLite)
- [x] Importación de `system_erp.settings` sin `DATABASE_URL` → SQLite
- [x] Importación con `DATABASE_URL` de prueba → PostgreSQL (sin conectar)
- [x] Importación de `system_erp.wsgi:application`
- [x] `python manage.py collectstatic --noinput --dry-run`
- [x] `.gitignore` excluye `.env`, secretos, SQLite, respaldos y `media/`
- [x] `db.sqlite3`: `PRAGMA integrity_check` = `ok` (solo lectura)
- [ ] Conexión real a Supabase con la contraseña nueva (PENDIENTE de credenciales)
- [ ] `python manage.py migrate` en Supabase (PENDIENTE de decisión/respaldo)
- [ ] Migración de datos reales (PENDIENTE, controlada)

---

## 9. Problemas / precauciones detectados

- `requirements.txt` tenía 5 dependencias; se añadieron 4 para Render y se
  fijaron `waitress` y `pillow-heif` a las versiones instaladas para que el
  build sea reproducible. Gunicorn sustituye a `waitress` en Render, pero este
  último se mantiene para no romper PythonAnywhere/Enzonic.
- **Migración 0033:** `0033_abono_turno_arqueo_deudas` ya está aplicada en este
  SQLite. No se ejecutó nada aquí. Al crear el esquema en Supabase con
  `migrate`, la migración se aplicará allí; asegúrate de que el orden sea
  esquema → datos para que las columnas nuevas existan antes de `loaddata`.
- **Imágenes:** hay 444 archivos en `media/` (408 de productos y 36 de tienda),
  pero están fuera de Git. Deben subirse al almacenamiento persistente en un
  paso manual (sección 6); Render no los tendrá.
- **`staticfiles/` está trackeado en Git** (143 archivos) pese a estar en
  `.gitignore`. Render regenera el directorio con `collectstatic`, así que no
  afecta al despliegue; no se borró nada.
- **Entorno local:** el `venv\` del proyecto puede no tener las dependencias
  nuevas (`whitenoise`, `dj-database-url`, `psycopg`, `gunicorn`,
  `pillow-heif`). Usa el Python global (3.13.7) o ejecuta
  `pip install -r requirements.txt` dentro del entorno virtual antes de probar.
- En Windows, `gunicorn` no importa (`grp` no existe). Es normal: se ejecuta en
  Linux/Render. La verificación local se hace con `manage.py check` y
  `collectstatic --dry-run`.
- `DEBUG` por defecto depende de `DATABASE_URL`: en local sin la variable sigue
  siendo `True`, por lo que el comportamiento local no cambia.
- Si se define `DJANGO_DEBUG=False` en local sin `DJANGO_SECRET_KEY`, Django
  exigirá la variable (comportamiento intencionado).
