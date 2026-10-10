# El mostrador queda sin token: /mostrador/ siempre activo y público.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_mostrador'),
    ]

    operations = [
        migrations.DeleteModel(
            name='MostradorToken',
        ),
    ]
