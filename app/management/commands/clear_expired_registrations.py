from django.core.management.base import BaseCommand
from django.utils import timezone

from app.models import RegistroPendiente


class Command(BaseCommand):
    help = "Elimina las verificaciones de correo de registro vencidas."

    def handle(self, *args, **options):
        count, _ = RegistroPendiente.objects.filter(expires_at__lte=timezone.now()).delete()
        self.stdout.write(f"Verificaciones vencidas eliminadas: {count}")
