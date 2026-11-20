from uuid import uuid4

from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.core.validators import MaxLengthValidator

from .models import Usuario, normalize_account_email


class AccountEmailForm(forms.Form):
    email = forms.EmailField(label="Correo electrónico", max_length=254)

    def clean_email(self):
        return normalize_account_email(self.cleaned_data["email"])


class EmailLoginForm(AccountEmailForm):
    password = forms.CharField(label="Contraseña", strip=False, max_length=4096, widget=forms.PasswordInput)

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        if email is None or password is None:
            return cleaned_data

        account = Usuario.objects.filter(email=email).only("email", "username").first()
        if account is not None and account.email == email:
            self.user = authenticate(self.request, username=account.username, password=password)
        else:
            # Match the work done for an incorrect password on a known account.
            Usuario().set_password(password)
        if self.user is None:
            raise forms.ValidationError("Correo o contraseña incorrectos.", code="invalid_login")
        return cleaned_data

    def get_user(self):
        return self.user


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre", max_length=150)
    last_name = forms.CharField(label="Apellido", max_length=150)

    class Meta:
        model = Usuario
        fields = ("first_name", "last_name")

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.email = email
        self.instance.username = uuid4().hex
        for name in ("password1", "password2"):
            self.fields[name].validators.append(MaxLengthValidator(4096))


class AccountSetPasswordForm(SetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("new_password1", "new_password2"):
            self.fields[name].validators.append(MaxLengthValidator(4096))
