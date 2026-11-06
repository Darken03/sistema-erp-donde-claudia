# Task 3 (modos de operación, spec §5): entidad PuntoVenta + turno con POS.
# `Empleado.punto_venta` y `Turno.punto_venta` son nullable: la historia
# previa queda con NULL. Cambiar de modo NUNCA borra datos.
# (No se toca AlmacenStock: su unique_together vigente se conserva.)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_modo_operacion'),
    ]

    operations = [
        migrations.CreateModel(
            name='PuntoVenta',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nombre', models.CharField(max_length=100, unique=True)),
                ('activo', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('almacen', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='puntos_venta', to='core.almacen')),
            ],
            options={
                'verbose_name': 'Punto de Venta',
                'verbose_name_plural': 'Puntos de Venta',
                'ordering': ['nombre'],
            },
        ),
        migrations.AddField(
            model_name='empleado',
            name='punto_venta',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='empleados', to='core.puntoventa'),
        ),
        migrations.AddField(
            model_name='turno',
            name='punto_venta',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='turnos', to='core.puntoventa'),
        ),
    ]
