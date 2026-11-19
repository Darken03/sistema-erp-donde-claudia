# Base de datos local en XAMPP (`algomio_dondeclaudia`)

## Estado actual

- Servidor: MariaDB 10.11.16 de XAMPP (`C:\xampp\mysql\bin\mysqld.exe`), corriendo en `localhost:3306`.
- Base de datos creada: `algomio_dondeclaudia` (utf8mb4 / utf8mb4_unicode_ci).
- Usuario: `algomio_bizzmaster` / contraseña `Algo@2026`, con todos los privilegios sobre esa BD
  (definido para `localhost` y `127.0.0.1`).
- Usuario root de XAMPP: la contraseña original se desconocía, así que se resetó mediante
  `--skip-grant-tables`. La nueva contraseña quedó guardada en `.mysql_root_password.local.txt`
  (archivo ignorado por Git). Ya se actualizó `C:\xampp\phpMyAdmin\config.inc.php` con esa
  contraseña (`$cfg['Servers'][$i]['password']` y `AllowNoPassword = false`) para que
  phpMyAdmin no siga generando warnings de "Access denied for user 'root'... (using password: NO)".
- El esquema se aplicó con `manage.py migrate` y los datos del `db.sqlite3` se importaron
  completa y correctamente (verificación de conteos: `auth_user` 9, `core_producto` 198,
  `core_venta` 464, `core_detalleventa` 786, `core_movimientoinventario` 924, etc.).

## Cómo usar el proyecto ahora

No hay que hacer nada especial: `python manage.py runserver` y el resto de comandos usan
MySQL por defecto. Para volver a SQLite de forma puntual:

```powershell
$env:DB_ENGINE='django.db.backends.sqlite3'
$env:DB_NAME='C:\ruta\completa\a\db.sqlite3'
python manage.py check
Remove-Item Env:DB_ENGINE, Env:DB_NAME
```

## Cómo repetir la migración de datos (SQLite → MySQL)

1. El SQLite debe estar al día con las migraciones:
   ```powershell
   $env:DB_ENGINE='django.db.backends.sqlite3'; $env:DB_NAME=(Join-Path (Get-Location) 'db.sqlite3')
   python manage.py migrate --noinput
   python manage.py dumpdata --natural-foreign --exclude contenttypes --exclude auth.permission -o datos_sqlite.json
   Remove-Item Env:DB_ENGINE, Env:DB_NAME
   ```
2. Si el volcado contiene bytes Latin-1 (por ejemplo `Panqu\xe9`), convertirlos a UTF-8:
   ```python
   raw = open('datos_sqlite.json', 'rb').read()
   s = raw.decode('utf-8', errors='surrogateescape')
   s = ''.join(chr(ord(c) - 0xDC00) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in s)
   open('datos_sqlite.json', 'w', encoding='utf-8', newline='').write(s)
   ```
3. Cargar en MySQL desconectando los signals que crean `PerfilUsuario` automáticamente
   (si no, chocan con los perfiles del volcado):
   ```bash
   python manage.py shell -c "
   from django.core.management import call_command
   from django.contrib.auth.models import User
   from django.db.models.signals import post_save
   from core.models import crear_perfil_usuario, guardar_perfil_usuario
   post_save.disconnect(crear_perfil_usuario, sender=User)
   post_save.disconnect(guardar_perfil_usuario, sender=User)
   call_command('loaddata', 'datos_sqlite.json', verbosity=1)
   "
   ```

## Comandos útiles

```powershell
& 'C:\xampp\mysql\bin\mysql.exe' -u algomio_bizzmaster '-pAlgo@2026' algomio_dondeclaudia -e "SHOW TABLES;"
```

También se puede usar `python manage.py dbshell`.
