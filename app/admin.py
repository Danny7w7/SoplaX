from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

from .models import Actor, Categoria, Idioma, Postura, Usuario, Videos


class SuperuserOnlyAdmin:
    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(Usuario)
class UsuarioAdmin(SuperuserOnlyAdmin, UserAdmin):
    pass


class SoplaXGroupAdmin(SuperuserOnlyAdmin, GroupAdmin):
    pass


@admin.register(Categoria, Actor, Idioma, Postura)
class CatalogoVideoAdmin(admin.ModelAdmin):
    list_display = ("nombre",)
    search_fields = ("nombre",)


@admin.register(Videos)
class VideosAdmin(admin.ModelAdmin):
    list_display = ("nombre", "idioma", "visitas")
    list_filter = ("categorias", "idioma", "posturas")
    search_fields = (
        "nombre",
        "descripcion",
        "categorias__nombre",
        "actores__nombre",
        "idioma__nombre",
        "posturas__nombre",
    )
    filter_horizontal = ("categorias", "actores", "posturas")


admin.site.unregister(Group)
admin.site.register(Group, SoplaXGroupAdmin)
