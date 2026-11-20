from django.db import migrations
from django.db.models import Count


def normalize_emails(apps, schema_editor):
    Usuario = apps.get_model("app", "Usuario")
    users = Usuario.objects.using(schema_editor.connection.alias)
    for user in users.exclude(email__isnull=True).only("email").iterator(chunk_size=500):
        email = user.email.strip().lower() or None
        if email != user.email:
            users.filter(pk=user.pk).update(email=email)

    duplicates = (
        users.exclude(email__isnull=True)
        .values("email")
        .annotate(count=Count("pk"))
        .filter(count__gt=1)
    )
    if duplicates.exists():
        raise RuntimeError(
            "Hay correos duplicados tras normalizarlos. Resuélvelos individualmente "
            "en una copia de la base antes de continuar."
        )


class Migration(migrations.Migration):
    dependencies = [("app", "0002_nullable_email")]

    operations = [migrations.RunPython(normalize_emails, migrations.RunPython.noop, atomic=True)]
