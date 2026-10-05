# Deudas con presentación de venta (ej. cartón de huevo vs huevo suelto).
# cantidad = unidades de la presentación; cantidad_base = unidades base p/ stock.
import django.db.models.deletion
from django.db import migrations, models
from decimal import Decimal


def backfill_cantidad_base(apps, schema_editor):
    Deuda = apps.get_model('core', 'Deuda')
    for d in Deuda.objects.filter(tipo='producto'):
        try:
            base = d.cantidad_base if d.cantidad_base is not None else Decimal('0')
        except Exception:
            base = Decimal('0')
        if not base:
            d.cantidad_base = d.cantidad or Decimal('1')
            d.save(update_fields=['cantidad_base'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_detalleventa_cantidad_base_producto_permite_decimal_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='deuda',
            name='presentacion',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='deudas', to='core.presentacionproducto'),
        ),
        migrations.AddField(
            model_name='deuda',
            name='cantidad_base',
            field=models.DecimalField(decimal_places=3, default=0, max_digits=12),
        ),
        migrations.RunPython(backfill_cantidad_base, noop),
    ]
