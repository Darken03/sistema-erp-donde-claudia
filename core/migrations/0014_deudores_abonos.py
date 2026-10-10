# Migración manual: módulo de Deudores + deudas de dinero/producto + abonos.
# - Crea Deudor y AbonoDeuda, amplía Deuda (deudor FK, tipo, producto, motivo).
# - Migra las deudas viejas (nombre_deudor texto -> Deudor; pagado=True -> Abono total).
# - Añade el tipo de movimiento 'deuda' al inventario.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from decimal import Decimal


def migrar_deudas_existentes(apps, schema_editor):
    Deuda = apps.get_model('core', 'Deuda')
    Deudor = apps.get_model('core', 'Deudor')
    AbonoDeuda = apps.get_model('core', 'AbonoDeuda')

    cache = {}
    for deuda in Deuda.objects.all().order_by('id'):
        nombre = (deuda.nombre_deudor or '').strip() or 'Sin nombre'
        if nombre not in cache:
            deudor, _ = Deudor.objects.get_or_create(
                nombre=nombre[:100],
                apellido='',
                ci=None,
            )
            cache[nombre] = deudor
        deuda.deudor = cache[nombre]
        deuda.tipo = 'dinero'
        deuda.cantidad = 1
        deuda.precio_unitario = deuda.monto
        deuda.save(update_fields=['deudor', 'tipo', 'cantidad', 'precio_unitario'])
        if deuda.pagado:
            AbonoDeuda.objects.create(
                deuda=deuda,
                monto=deuda.monto,
                metodo='efectivo',
                nota='Migración: deuda marcada como pagada',
                registrada_por=deuda.registrada_por,
            )


def reversa_migrar_deudas(apps, schema_editor):
    # No reversible con fidelidad total: se deja como no-op.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_deuda'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Deudor',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100)),
                ('apellido', models.CharField(blank=True, default='', max_length=100)),
                ('ci', models.CharField(blank=True, max_length=20, null=True, unique=True)),
                ('telefono', models.CharField(blank=True, default='', max_length=30)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Deudor',
                'verbose_name_plural': 'Deudores',
                'ordering': ['nombre', 'apellido'],
            },
        ),
        migrations.CreateModel(
            name='AbonoDeuda',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('monto', models.DecimalField(decimal_places=2, max_digits=12)),
                ('metodo', models.CharField(choices=[('efectivo', 'Efectivo'), ('transferencia', 'Transferencia')], default='efectivo', max_length=15)),
                ('nota', models.CharField(blank=True, default='', max_length=255)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('deuda', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='abonos', to='core.deuda')),
                ('registrada_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='abonos_deuda', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Abono de Deuda',
                'verbose_name_plural': 'Abonos de Deudas',
                'ordering': ['-fecha'],
            },
        ),
        migrations.AddField(
            model_name='deuda',
            name='deudor',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deudas', to='core.deudor'),
        ),
        migrations.AddField(
            model_name='deuda',
            name='tipo',
            field=models.CharField(choices=[('dinero', 'Dinero'), ('producto', 'Producto')], default='dinero', max_length=10),
        ),
        migrations.AddField(
            model_name='deuda',
            name='producto',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deudas', to='core.producto'),
        ),
        migrations.AddField(
            model_name='deuda',
            name='cantidad',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='deuda',
            name='precio_unitario',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='deuda',
            name='motivo',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AlterField(
            model_name='movimientoinventario',
            name='tipo',
            field=models.CharField(choices=[('entrada', 'Entrada'), ('venta', 'Venta'), ('donacion', 'Donación'), ('deuda', 'Deuda (producto entregado)'), ('ajuste', 'Ajuste'), ('devolucion', 'Devolución')], max_length=15),
        ),
        migrations.RunPython(migrar_deudas_existentes, reversa_migrar_deudas),
        migrations.AlterField(
            model_name='deuda',
            name='deudor',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deudas', to='core.deudor'),
        ),
        migrations.RemoveField(
            model_name='deuda',
            name='nombre_deudor',
        ),
        migrations.RemoveField(
            model_name='deuda',
            name='pagado',
        ),
    ]
