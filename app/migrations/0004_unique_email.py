from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("app", "0003_normalize_email")]

    operations = [
        migrations.AlterField(
            model_name="usuario",
            name="email",
            field=models.EmailField("email address", blank=True, null=True, unique=True),
        ),
    ]
