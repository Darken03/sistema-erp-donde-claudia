# Mostrador del cliente: token de acceso público + estado del carrito por pantalla.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_deuda_presentacion_cantidad_base'),
    ]

    operations = [
        migrations.CreateModel(
            name='MostradorToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=64, unique=True)),
                ('creado', models.DateTimeField(auto_now_add=True)),
                ('expira', models.DateTimeField()),
                ('activo', models.BooleanField(default=True)),
                ('creado_por', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mostrador_tokens', to='auth.user')),
            ],
            options={
                'verbose_name': 'Token de Mostrador',
                'verbose_name_plural': 'Tokens de Mostrador',
                'ordering': ['-creado'],
            },
        ),
        migrations.CreateModel(
            name='MostradorEstado',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pantalla', models.PositiveSmallIntegerField(unique=True)),
                ('items_json', models.TextField(default='[]')),
                ('total', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('mensaje', models.CharField(choices=[('vacio', 'Vacío'), ('activo', 'Carrito activo'), ('completado', 'Venta completada')], default='vacio', max_length=12)),
                ('cajero_nombre', models.CharField(blank=True, default='', max_length=150)),
                ('actualizado', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Estado de Mostrador',
                'verbose_name_plural': 'Estados de Mostrador',
                'ordering': ['pantalla'],
            },
        ),
    ]
