import app.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0007_clasificacion_video"),
    ]

    operations = [
        migrations.AddField(
            model_name="videos",
            name="es_premium",
            field=models.BooleanField(default=True, verbose_name="contenido premium"),
        ),
        migrations.AlterField(
            model_name="videos",
            name="miniatura",
            field=models.FileField(upload_to=app.models.miniatura_upload_to),
        ),
    ]
