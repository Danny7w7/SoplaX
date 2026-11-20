from django.contrib.auth.models import AbstractUser
from django.db import models


def normalize_account_email(email):
    return (email or "").strip().lower()


class Usuario(AbstractUser):
    email = models.EmailField("email address", unique=True, blank=True, null=True)

    def clean(self):
        super().clean()
        self.email = normalize_account_email(self.email) or None

    def save(self, *args, **kwargs):
        self.email = normalize_account_email(self.email) or None
        return super().save(*args, **kwargs)


class RegistroPendiente(models.Model):
    token_hash = models.CharField(max_length=64, primary_key=True, editable=False)
    email = models.EmailField()
    expires_at = models.DateTimeField(db_index=True)


class Videos(models.Model):
    nombre = models.CharField(max_length=100, null=False)
    descripcion = models.CharField(max_length=1000, null=False)
    miniatura = models.FileField(upload_to='upload/photos')
    video = models.FileField(upload_to='upload/videos')
    visitas = models.IntegerField()
