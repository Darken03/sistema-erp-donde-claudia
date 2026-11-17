# Generated manually: turno en AbonoDeuda + campos de deudas cobradas aparte en ArqueoTurno.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_deudor_alias'),
    ]

    operations = [
        migrations.AddField(
            model_name='abonodeuda',
            name='turno',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='abonos_deuda', to='core.turno',
            ),
        ),
        migrations.AddField(
            model_name='arqueoturno',
            name='contado_deudas',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='arqueoturno',
            name='esperado_deudas',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='arqueoturno',
            name='esperado_deudas_efectivo',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='arqueoturno',
            name='esperado_deudas_transferencia',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
