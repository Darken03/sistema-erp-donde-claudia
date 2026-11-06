"""
WSGI para PythonAnywhere (dondeclaudia.pythonanywhere.com).

COMO USARLO:
1. En el dashboard de PythonAnywhere abre la pestaña "Web" y tu app.
2. En "Code" → "WSGI configuration file" abre el archivo
   /var/www/dondeclaudia_pythonanywhere_com_wsgi.py
3. BORRA todo su contenido y pega este archivo completo.
4. Ajusta PROJECT_DIR si subiste el proyecto con otro nombre de carpeta.
5. Recarga la app (botón verde "Reload").
"""
import os
import sys

# Carpeta del proyecto en PythonAnywhere (ajústala si cambia el nombre).
PROJECT_DIR = '/home/dondeclaudia/sistema-erp'

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
