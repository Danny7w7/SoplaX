from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetCompleteView
from django.urls import path

from app import video_sitemaps, views
from app.forms import EmailLoginForm


urlpatterns = [
    path("admin/videos/", views.video_manager, name="video_manager"),
    path("admin/videos/nuevo/", views.video_manager_add, name="video_manager_add"),
    path("admin/videos/<int:video_id>/editar/", views.video_manager_edit, name="video_manager_edit"),
    path(
        "admin/videos/<int:video_id>/miniatura/descargar/",
        views.video_manager_thumbnail_download,
        name="video_manager_thumbnail_download",
    ),
    path("admin/videos/<int:video_id>/eliminar/", views.video_manager_delete, name="video_manager_delete"),
    path("admin/", admin.site.urls),
    path("", views.index, name="home"),
    path("robots.txt", video_sitemaps.robots_txt, name="robots_txt"),
    path("sitemap.xml", video_sitemaps.sitemap_index, name="sitemap_index"),
    path("sitemap-videos-<int:page>.xml", video_sitemaps.sitemap_videos, name="sitemap_videos"),
    path("register/", views.register, name="register"),
    path("register/confirm/", views.register_confirm, name="register_confirm"),
    path("register/confirm/<str:token>/", views.register_token, name="register_token"),
    path("accounts/login/", LoginView.as_view(template_name="login.html", form_class=EmailLoginForm), name="login"),
    path("accounts/email_sent/", views.account_email_sent, name="account_email_sent"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("recover_password/", views.recover_password, name="recover"),
    path(
        "recover_password/confirm/<str:uidb64>/<str:token>/",
        views.AccountPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "recover_password/complete/",
        PasswordResetCompleteView.as_view(template_name="password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("videos/<slug:slug>-<int:id>/", views.play_, name="video_detail"),
    path("videos/<slug:slug>-<int:id>", views.play_),
    path("play/<int:id>/", views.play_, name="play"),
    path("play/<int:id>", views.play_),
    path("redirect/", views.redirect_, name="redirect"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
