from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("app", "0005_remove_temp_password")]

    operations = [
        migrations.CreateModel(
            name="RegistroPendiente",
            fields=[
                (
                    "token_hash",
                    models.CharField(editable=False, max_length=64, primary_key=True, serialize=False),
                ),
                ("email", models.EmailField(max_length=254)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
        ),
    ]
