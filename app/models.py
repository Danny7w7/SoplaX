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


class ElementoCatalogo(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        abstract = True
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Categoria(ElementoCatalogo):
    class Meta(ElementoCatalogo.Meta):
        verbose_name = "categoría"
        verbose_name_plural = "categorías"


class Actor(ElementoCatalogo):
    class Meta(ElementoCatalogo.Meta):
        verbose_name_plural = "actores"


class Idioma(ElementoCatalogo):
    pass


class Postura(ElementoCatalogo):
    pass


def miniatura_directory(es_premium):
    segment = "Premium" if es_premium else "NoPremium"
    return f"upload/Miniaturas/{segment}"


def miniatura_upload_to(instance, filename):
    return f"{miniatura_directory(instance.es_premium)}/{filename}"


class Videos(models.Model):
    nombre = models.CharField(max_length=100, null=False)
    descripcion = models.CharField(max_length=1000, null=False)
    es_premium = models.BooleanField(default=True, verbose_name="contenido premium")
    miniatura = models.FileField(upload_to=miniatura_upload_to)
    video = models.FileField(upload_to='upload/videos')
    visitas = models.IntegerField()
    categorias = models.ManyToManyField(Categoria, blank=True, related_name="videos", verbose_name="categorías")
    actores = models.ManyToManyField(Actor, blank=True, related_name="videos")
    idioma = models.ForeignKey(Idioma, on_delete=models.SET_NULL, null=True, blank=True, related_name="videos")
    posturas = models.ManyToManyField(Postura, blank=True, related_name="videos")

    class Meta:
        verbose_name = "video"
        verbose_name_plural = "videos"
