import logging

from botocore.exceptions import BotoCoreError, ClientError
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, router, transaction
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.views.decorators.http import require_http_methods

from .models import Actor, Categoria, Idioma, Postura, Usuario, Videos
from .video_previews import discard_preview_file, queue_video_preview
from .video_uploads import VideoFileForm, VideoUploadForm, store_video_uploads


logger = logging.getLogger(__name__)


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
    form = VideoFileForm
    list_display = ("nombre", "es_premium", "idioma", "visitas")
    list_filter = ("es_premium", "categorias", "idioma", "posturas")
    search_fields = (
        "nombre",
        "descripcion",
        "categorias__nombre",
        "actores__nombre",
        "idioma__nombre",
        "posturas__nombre",
    )
    filter_horizontal = ("categorias", "actores", "posturas")

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            readonly_fields.append("es_premium")
        return readonly_fields

    def save_model(self, request, obj, form, change):
        if change:
            obj.save(update_fields=form.video_update_fields())
        else:
            super().save_model(request, obj, form, change)
        if not change or "video" in form.changed_data:
            using = router.db_for_write(self.model)
            queue_video_preview(obj, using=using)
            replaced_preview = getattr(form, "replaced_preview_name", "")
            if change and replaced_preview:
                transaction.on_commit(lambda: discard_preview_file(replaced_preview, using=using), using=using)

    @method_decorator(require_http_methods(["GET", "HEAD", "POST"]))
    def add_view(self, request, form_url="", extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied

        request.current_app = self.admin_site.name
        if request.method == "POST":
            form = VideoUploadForm(request.POST, request.FILES)
            if form.is_valid():
                video = form.save(commit=False)
                video.visitas = 0
                try:
                    with store_video_uploads(video), transaction.atomic(using=router.db_for_write(self.model)):
                        self.save_model(request, video, form, change=False)
                        self.save_related(request, form, [], change=False)
                        self.log_addition(request, video, self.construct_change_message(request, form, [], add=True))
                except (DatabaseError, OSError, BotoCoreError, ClientError):
                    logger.exception("No se pudo publicar un video.")
                    form.add_error(None, "No se pudo publicar el video. Vuelve a intentarlo.")
                else:
                    if "_publish" not in request.POST:
                        return self.response_add(request, video)
                    self.message_user(
                        request,
                        format_html(
                            'Se publicó «{}». <a href="{}">Ver video</a>.',
                            video.nombre,
                            video.get_absolute_url(),
                        ),
                        level="success",
                    )
                    return redirect("admin:app_videos_add")
        else:
            form = VideoUploadForm(initial=self.get_changeform_initial_data(request))

        can_view_videos = self.has_view_or_change_permission(request)
        return TemplateResponse(
            request,
            "admin/video_upload.html",
            {
                "form": form,
                "form_url": form_url,
                "can_view_videos": can_view_videos,
                **(extra_context or {}),
            },
        )


admin.site.unregister(Group)
admin.site.register(Group, SoplaXGroupAdmin)
