"""
Script para crear un usuario administrador.
Ejecutar con: python crear_admin.py
"""
import os
import sys
import django

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.contrib.auth import get_user_model
from core.models import PerfilUsuario

User = get_user_model()

username = 'claudia'
password = '2211'

# Create user if not exists
user, created = User.objects.get_or_create(username=username)
if created:
    print(f'Usuario {username} creado')
else:
    print(f'Usuario {username} ya existe')

# Set password
user.set_password(password)
user.save()

# Create or update perfil with admin role
perfil, created = PerfilUsuario.objects.get_or_create(user=user, defaults={'rol': 'admin'})
if not created:
    perfil.rol = 'admin'
    perfil.save()

print(f'Listo! Usuario: {username}, Contrasena: {password}, Rol: admin')