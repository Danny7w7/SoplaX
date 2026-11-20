from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("app", "0004_unique_email")]

    operations = [migrations.RemoveField(model_name="usuario", name="temp_password")]
