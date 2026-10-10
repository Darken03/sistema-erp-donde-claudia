# Modos de operación, Fase 1: setting modo_operacion (default pos_almacenes).
# Cambiar de modo NUNCA borra datos; la migración fija el modo actual
# en todas las filas existentes sin tocar nada más.

from django.db import migrations, models


def fijar_modo_default(apps, schema_editor):
    ConfiguracionTienda = apps.get_model('core', 'ConfiguracionTienda')
    ConfiguracionTienda.objects.all().update(modo_operacion='pos_almacenes')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0025_multi_almacen_config'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuraciontienda',
            name='modo_operacion',
            field=models.CharField(choices=[('solo_pos', 'Solo POS (sin almacén)'), ('pos_almacenes', 'POS + almacenes'), ('multi_pos', 'Multi-POS (varios puntos de venta)')], default='pos_almacenes', max_length=15),
        ),
        migrations.RunPython(fijar_modo_default, migrations.RunPython.noop),
    ]
