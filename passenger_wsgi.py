"""
WSGI entry point for Phusion Passenger
"""

import os
import sys

# Add the project directory to Python path
project_home = os.path.dirname(os.path.abspath(__file__))
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')

# Import and create WSGI application
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
