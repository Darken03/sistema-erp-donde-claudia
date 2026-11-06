# Reconstruye la migración 0022_precios_anticrisis que ya está aplicada
# en la base de producción (costo congelado por venta + historial de
# precios). Su archivo original se perdió en el repo; este conserva el
# mismo nombre para no romper el historial aplicado en producción.
# (Generado a partir del estado de core/models.py.)

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_arqueoturno_decision_arqueoturno_decision_nota_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='detalleventa',
            name='costo_unitario_base',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AlterField(
            model_name='perfilusuario',
            name='rol',
            field=models.CharField(choices=[('admin', 'Administrador'), ('cajero', 'Cajero'), ('almacenero', 'Almacenero')], default='cajero', max_length=10),
        ),
        migrations.CreateModel(
            name='HistorialPrecio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('precio_compra_antes', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('precio_compra_despues', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('precio_venta_antes', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('precio_venta_despues', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('costo_entrada', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('margen_resultante', models.DecimalField(decimal_places=4, default=0, max_digits=7)),
                ('accion', models.CharField(choices=[('entrada_ok', 'Entrada con margen OK'), ('entrada_margen_bajo', 'Entrada con margen bajo (confirmada)'), ('entrada_perdida_actualiza', 'Entrada en pérdida → venta actualizada'), ('entrada_perdida_asumida', 'Entrada en pérdida → pérdida asumida'), ('edicion_manual', 'Edición manual de precio')], default='entrada_ok', max_length=30)),
                ('motivo', models.CharField(blank=True, default='', max_length=255)),
                ('fecha', models.DateTimeField(auto_now_add=True)),
                ('entrada', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='historial_precios', to='core.entradaproducto')),
                ('producto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='historial_precios', to='core.producto')),
                ('usuario', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Historial de Precio',
                'verbose_name_plural': 'Historial de Precios',
                'ordering': ['-fecha'],
            },
        ),
    ]
