from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group

from .models import Usuario, Videos


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


admin.site.unregister(Group)
admin.site.register(Group, SoplaXGroupAdmin)
admin.site.register(Videos)
