from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView, PasswordResetCompleteView
from django.urls import path

from app import views
from app.forms import EmailLoginForm


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="home"),
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
    path("play/<int:id>/", views.play_, name="play"),
    path("redirect/", views.redirect_, name="redirect"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
