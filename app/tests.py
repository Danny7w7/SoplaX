import json
from datetime import timedelta
from io import StringIO
from pathlib import Path
from smtplib import SMTPException
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import Actor, Categoria, Idioma, Postura, RegistroPendiente, Usuario, Videos


PASSWORD = "a-correct-passphrase-42"
NEW_PASSWORD = "a-different-passphrase-73"


@override_settings(
    DEVELOPMENT=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
)
class AccountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = Usuario.objects.create_user(username="pelican", email="A@example.net", password=PASSWORD)
        cls.inactive = Usuario.objects.create_user(
            username="albatross", email="inactive@example.net", password=PASSWORD, is_active=False
        )

    def setUp(self):
        cache.clear()

    def email_link(self, message=-1):
        return next(line for line in mail.outbox[message].body.splitlines() if line.startswith("http"))

    def submit_registration(self, client, password=NEW_PASSWORD):
        return client.post(
            reverse("register_confirm"),
            {
                "first_name": "Gabriela",
                "last_name": "Díaz",
                "password1": password,
                "password2": password,
            },
        )

    def submit_reset(self, client, path):
        return client.post(path, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

    def test_login_email_and_generic_errors(self):
        url = reverse("login")
        responses = [
            self.client.post(url, {"email": "a@example.net", "password": "invalid"}),
            self.client.post(url, {"email": "missing@example.net", "password": PASSWORD}),
            self.client.post(url, {"email": self.inactive.email, "password": PASSWORD}),
        ]
        for response in responses:
            self.assertContains(response, "Correo o contraseña incorrectos.")
            self.assertNotIn("_auth_user_id", self.client.session)

        response = self.client.post(url, {"email": "A@EXAMPLE.NET", "password": PASSWORD})
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_logout_requires_post_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        self.assertIn("_auth_user_id", client.session)
        client.get(reverse("home"))
        csrf = client.cookies["csrftoken"].value
        response = client.post(reverse("logout"), {"csrfmiddlewaretoken": csrf})
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", client.session)

    @override_settings(PUBLIC_BASE_URL="https://soplax.example")
    def test_recovery_is_generic_and_preserves_account_state(self):
        password = self.user.password
        active_session = Client()
        active_session.force_login(self.user)

        for email in (self.user.email, self.inactive.email, "missing@example.net"):
            response = self.client.post(reverse("recover"), {"email": email})
            self.assertRedirects(response, reverse("account_email_sent"))
            self.assertIn("no-store", response.headers["Cache-Control"])

        self.user.refresh_from_db()
        self.inactive.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.inactive.is_active)
        self.assertEqual(self.user.password, password)
        self.assertTrue(active_session.get(reverse("home")).wsgi_request.user.is_authenticated)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertEqual(urlsplit(self.email_link()).netloc, "soplax.example")

    def test_reset_rotates_password_and_consumes_link(self):
        self.client.post(reverse("recover"), {"email": self.user.email})
        link = urlsplit(self.email_link()).path
        second_browser = Client()
        form_path = self.client.get(link)["Location"]
        self.assertTrue(form_path.endswith("/set-password/"))
        self.assertRedirects(second_browser.get(link), form_path)

        self.assertRedirects(self.submit_reset(self.client, form_path), reverse("password_reset_complete"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_PASSWORD))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.submit_reset(second_browser, form_path), "El enlace de recuperación no está disponible.")

    def test_expired_reset_link_cannot_change_password(self):
        past = default_token_generator._now() - timedelta(minutes=31)
        with patch.object(default_token_generator, "_now", return_value=past):
            self.client.post(reverse("recover"), {"email": self.user.email})
        link = urlsplit(self.email_link()).path
        self.assertContains(self.client.get(link), "El enlace de recuperación no está disponible.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_reset_confirmation_respects_suspensions(self):
        self.client.post(reverse("recover"), {"email": self.user.email})
        form_path = self.client.get(urlsplit(self.email_link()).path)["Location"]
        Usuario.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertContains(self.submit_reset(self.client, form_path), "El enlace de recuperación no está disponible.")
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_register_requires_email_and_valid_password(self):
        email = "new@example.net"
        url = reverse("register")
        self.assertRedirects(self.client.post(url, {"email": self.user.email}), reverse("account_email_sent"))
        self.assertRedirects(self.client.post(url, {"email": "NEW@example.net"}), reverse("account_email_sent"))
        self.assertFalse(Usuario.objects.filter(email=email).exists())
        self.assertEqual(len(mail.outbox), 1)
        link = urlsplit(self.email_link()).path
        self.assertRedirects(self.client.get(link), reverse("register_confirm"))
        self.assertEqual(self.submit_registration(self.client, "short").status_code, 200)
        self.assertFalse(Usuario.objects.filter(email=email).exists())

        self.assertRedirects(self.submit_registration(self.client), reverse("home"))
        user = Usuario.objects.get(email=email)
        self.assertTrue(user.check_password(NEW_PASSWORD))
        self.assertFalse(user.is_staff)
        self.assertFalse(RegistroPendiente.objects.exists())
        self.assertContains(Client().get(link, follow=True), "El enlace de registro no está disponible.")

    def test_two_links_for_same_email_create_one_account(self):
        email = "new@example.net"
        first = self.client
        second = Client()
        for browser in (first, second):
            browser.post(reverse("register"), {"email": email})
            browser.get(urlsplit(self.email_link()).path)
        self.assertRedirects(self.submit_registration(first), reverse("home"))
        self.assertContains(self.submit_registration(second), "El enlace de registro no está disponible.")
        self.assertEqual(Usuario.objects.filter(email=email).count(), 1)

    def test_expired_registration_links_are_unusable_and_can_be_removed(self):
        self.client.post(reverse("register"), {"email": "new@example.net"})
        RegistroPendiente.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(
            self.client.get(urlsplit(self.email_link()).path, follow=True),
            "El enlace de registro no está disponible.",
        )
        call_command("clear_expired_registrations", stdout=StringIO())
        self.assertFalse(RegistroPendiente.objects.exists())

    def test_address_limit_does_not_disclose_account_state(self):
        for _ in range(4):
            self.assertRedirects(
                self.client.post(reverse("recover"), {"email": self.user.email}),
                reverse("account_email_sent"),
            )
        self.assertEqual(len(mail.outbox), 3)

    def test_login_and_admin_login_have_ip_limits(self):
        for route, form_data in [
            ("login", {"email": "missing@example.net", "password": PASSWORD}),
            ("admin:login", {"username": "unknown", "password": PASSWORD}),
        ]:
            for _ in range(10):
                self.assertEqual(self.client.post(reverse(route), form_data).status_code, 200)
            self.assertEqual(self.client.post(reverse(route), form_data).status_code, 429)

    def test_no_work_after_failed_csrf(self):
        client = Client(enforce_csrf_checks=True)
        for route in ("recover", "register", "login", "register_confirm"):
            self.assertEqual(client.post(reverse(route), {"email": self.user.email}).status_code, 403)
        self.assertFalse(mail.outbox)

    @override_settings(DEVELOPMENT=False)
    @patch("app.views.queue_account_email")
    def test_production_enqueues_without_an_account_lookup(self, enqueue):
        with self.assertNumQueries(0):
            self.client.post(reverse("recover"), {"email": self.user.email})
            self.client.post(reverse("recover"), {"email": "missing@example.net"})
        self.assertEqual(enqueue.call_count, 2)

    @patch("app.account_mail.send_mail", side_effect=SMTPException("private SMTP diagnostic"))
    def test_smtp_failure_keeps_responses_generic_and_does_not_log_details(self, send):
        with self.assertLogs("app.account_mail", level="WARNING") as logs:
            self.assertRedirects(
                self.client.post(reverse("register"), {"email": "new@example.net"}),
                reverse("account_email_sent"),
            )
        self.assertNotIn("private SMTP diagnostic", "\n".join(logs.output))
        self.assertFalse(RegistroPendiente.objects.exists())

    def test_staff_cannot_manage_users_or_groups(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.user.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_videos", "change_usuario", "view_group"])
        )
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("admin:app_videos_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:app_usuario_changelist")).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:auth_group_changelist")).status_code, 403)


class CatalogSecurityTests(TestCase):
    def test_catalog_search_finds_partial_titles_in_any_order(self):
        titles = [f"Otro video {number}" for number in range(24)] + [
            "Excursión por el RÍO azul",
            "Excursión por el bosque",
            "El Ri\N{COMBINING ACUTE ACCENT}o azul en invierno",
        ]
        Videos.objects.bulk_create([Videos(nombre=title, visitas=0) for title in titles])

        for query, expected in (
            ("  RIO   excurs  ", [titles[24]]),
            ("río", [titles[24], titles[26]]),
            ("río inexistente", []),
        ):
            with self.subTest(query=query):
                response = self.client.get(reverse("home"), {"search": query})
                self.assertQuerySetEqual(response.context["videos"].values_list("nombre", flat=True), expected)

    def test_catalog_search_and_native_playback(self):
        video = Videos.objects.create(
            nombre="Prueba de catálogo",
            descripcion="Video de prueba",
            miniatura="upload/Miniaturas/Premium/sample.webp",
            video="upload/videos/sample.mp4",
            visitas=2,
        )
        home = self.client.get(reverse("home"), {"search": "catálogo"})
        self.assertContains(home, video.nombre)
        self.assertIn("no-store", home["Cache-Control"])
        playback = reverse("play", args=[video.pk])
        self.client.head(playback)
        video.refresh_from_db()
        self.assertEqual(video.visitas, 2)
        response = self.client.get(playback)
        self.assertContains(response, "upload/videos/sample.mp4")
        self.assertContains(response, "<video")
        self.assertNotContains(response, "magsrv.com")
        self.assertNotContains(response, "fluidplayer")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertNotIn("'unsafe-inline'", response["Content-Security-Policy"].split("script-src ")[1].split(";")[0])
        video.refresh_from_db()
        self.assertEqual(video.visitas, 3)
        self.assertEqual(self.client.get(reverse("play", args=[video.pk + 1])).status_code, 404)


class FrontendTests(TestCase):
    def test_pages_use_native_design_system(self):
        video = Videos.objects.create(
            nombre="Video destacado",
            descripcion="Descripción del video",
            miniatura="upload/Miniaturas/Premium/sample.webp",
            video="upload/videos/sample.mp4",
            visitas=12_400,
        )
        video.categorias.add(Categoria.objects.create(nombre="Categoría visible"))
        pages = ["home", "login", "register", "recover", "account_email_sent", "redirect"]
        urls = [reverse(name) for name in pages] + [reverse("play", args=[video.pk])]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                html = response.content.decode()
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "css/tokens.css")
                self.assertContains(response, "Hecho por un aprendiz SENA")
                self.assertNotIn("bootstrap", html.lower())
                self.assertNotIn("data-bs-", html)
                self.assertNotIn('style="', html)
                self.assertNotIn("bootstrap", response["Content-Security-Policy"])

        home = self.client.get(reverse("home"))
        self.assertContains(home, "12,4 k vistas", count=2)
        playback = self.client.get(reverse("play", args=[video.pk]))
        self.assertContains(playback, "Categoría visible")
        self.assertContains(playback, "upload/Miniaturas/Premium/sample.webp")

    def test_account_menu_uses_native_popover(self):
        staff = Usuario.objects.create_user(username="staff", first_name="Ana", email="ana@example.net", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'popovertarget="account-menu"')
        self.assertContains(response, "Panel de administración")
        self.assertContains(response, "Cerrar sesión")

    def test_age_gate_shows_until_accepted(self):
        for url in (reverse("home"), reverse("login"), reverse("redirect")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'id="age-gate"')
                self.assertContains(response, 'method="dialog"')
                self.assertContains(response, "Solo para mayores de 18 años")

        self.client.cookies["soplax_age_ok"] = "1"
        self.assertNotContains(self.client.get(reverse("home")), 'id="age-gate"')

    @override_settings(DEBUG=False)
    def test_missing_page_uses_branded_template(self):
        response = self.client.get("/no-existe/")
        self.assertContains(response, "No encontramos esta página", status_code=404)
        self.assertContains(response, "Hecho por un aprendiz SENA", status_code=404)

    def test_view_counts_are_compact(self):
        from .templatetags.soplax import vistas

        self.assertEqual(
            [vistas(count) for count in (0, 1, 999, 1_000, 12_400, 999_960, 2_000_000, None)],
            ["0 vistas", "1 vista", "999 vistas", "1 k vistas", "12,4 k vistas", "1 M vistas", "2 M vistas", ""],
        )


class CatalogMetadataTests(TestCase):
    def test_video_editor_can_assign_catalog_entries(self):
        editor = Usuario.objects.create_user(username="editor", is_staff=True)
        editor.user_permissions.add(Permission.objects.get(content_type__app_label="app", codename="change_videos"))
        self.client.force_login(editor)

        video = Videos.objects.create(
            nombre="Video existente",
            descripcion="Descripción de prueba",
            miniatura="upload/Miniaturas/Premium/sample.webp",
            video="upload/videos/sample.mp4",
            visitas=0,
        )
        categories = [Categoria.objects.create(nombre=name) for name in ("Categoría A", "Categoría B")]
        actors = [Actor.objects.create(nombre=name) for name in ("Intérprete A", "Intérprete B")]
        positions = [Postura.objects.create(nombre=name) for name in ("Postura A", "Postura B")]
        language = Idioma.objects.create(nombre="Español")

        response = self.client.post(
            reverse("admin:app_videos_change", args=[video.pk]),
            {
                "nombre": video.nombre,
                "descripcion": video.descripcion,
                "visitas": video.visitas,
                "categorias": [category.pk for category in categories],
                "actores": [actor.pk for actor in actors],
                "posturas": [position.pk for position in positions],
                "idioma": language.pk,
                "_save": "Save",
            },
        )
        self.assertRedirects(response, reverse("admin:app_videos_changelist"))
        video.refresh_from_db()
        self.assertCountEqual(video.categorias.all(), categories)
        self.assertCountEqual(video.actores.all(), actors)
        self.assertCountEqual(video.posturas.all(), positions)
        self.assertEqual(video.idioma, language)

        search = self.client.get(reverse("admin:app_videos_changelist"), {"q": actors[1].nombre})
        self.assertQuerySetEqual(search.context["cl"].result_list, [video])

        language.delete()
        video.refresh_from_db()
        self.assertIsNone(video.idioma_id)
        self.assertEqual(video.video.name, "upload/videos/sample.mp4")


class CatalogSeedTests(TestCase):
    def run_seed(self, rows, *, apply=False):
        with TemporaryDirectory() as directory:
            fixture = Path(directory) / "catalogo.json"
            fixture.write_text(json.dumps(rows), encoding="utf-8")
            output = StringIO()
            args = ["--aplicar"] if apply else []
            call_command("importar_catalogo", str(fixture), *args, stdout=output)
        return output.getvalue()

    def fixture_rows(self):
        return [
            {"model": "app.categoria", "pk": 15, "fields": {"nombre": "Naturaleza"}},
            {"model": "app.actor", "pk": 20, "fields": {"nombre": "Intérprete local"}},
            {"model": "app.idioma", "pk": 25, "fields": {"nombre": "Español"}},
            {"model": "app.postura", "pk": 30, "fields": {"nombre": "Posición local"}},
            {
                "model": "app.videos",
                "pk": 35,
                "fields": {
                    "nombre": "Sendero",
                    "descripcion": "Descripción del origen",
                    "video": "upload/videos/sendero.mp4",
                    "miniatura": "upload/Miniaturas/Premium/sendero.webp",
                    "visitas": 4,
                    "categorias": [15],
                    "actores": [20],
                    "idioma": 25,
                    "posturas": [30],
                },
            },
        ]

    def test_simulates_before_import_and_preserves_content_on_repeat(self):
        rows = self.fixture_rows()
        existing_category = Categoria.objects.create(pk=100, nombre="Naturaleza")
        unrelated_video = Videos.objects.create(
            pk=35, nombre="Video existente", video="upload/videos/existente.mp4", visitas=16
        )
        account = Usuario.objects.create(username="editor")

        with CaptureQueriesContext(connection) as queries:
            output = self.run_seed(rows)
        self.assertTrue(queries.captured_queries)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT ") for query in queries))
        self.assertIn("upload/videos/sendero.mp4", output)
        self.assertIn("Español", output)
        self.assertQuerySetEqual(Videos.objects.all(), [unrelated_video])
        self.assertFalse(Idioma.objects.exists())

        self.run_seed(rows, apply=True)
        added = Videos.objects.get(video="upload/videos/sendero.mp4")
        self.assertNotEqual(added.pk, unrelated_video.pk)
        self.assertEqual(added.miniatura.name, "upload/Miniaturas/Premium/sendero.webp")
        self.assertEqual((added.nombre, added.descripcion, added.visitas), ("Sendero", "Descripción del origen", 4))
        self.assertEqual(added.idioma.nombre, "Español")
        self.assertQuerySetEqual(added.categorias.all(), [existing_category])
        self.assertEqual(added.actores.get().nombre, "Intérprete local")
        self.assertEqual(added.posturas.get().nombre, "Posición local")

        Videos.objects.filter(pk=added.pk).update(nombre="Título editado", visitas=99)
        added.categorias.clear()
        before = list(Videos.objects.order_by("pk").values())
        actual = self.run_seed(rows, apply=True)
        self.assertIn("0 videos", actual)
        self.assertEqual(list(Videos.objects.order_by("pk").values()), before)
        self.assertFalse(added.categorias.exists())
        self.assertEqual(Actor.objects.count(), 1)
        self.assertEqual(Postura.objects.count(), 1)
        self.assertQuerySetEqual(Usuario.objects.all(), [account])

    def test_validates_references_and_rejects_ambiguous_destination(self):
        rows = self.fixture_rows()
        incomplete = [row for row in rows if row["model"] != "app.idioma"]
        with self.assertRaisesMessage(CommandError, "clasificación que falta"):
            self.run_seed(incomplete)

        key = rows[-1]["fields"]["video"]
        Videos.objects.bulk_create([Videos(nombre=name, video=key, visitas=0) for name in ("Uno", "Dos")])
        with self.assertRaisesMessage(CommandError, "más de un video"):
            self.run_seed(rows, apply=True)
        self.assertFalse(Categoria.objects.exists())

    def test_rolls_back_classifications_if_video_insert_fails(self):
        with patch.object(Videos, "save", side_effect=IntegrityError("fallo de prueba")):
            with self.assertRaisesMessage(CommandError, "Se revirtieron los cambios"):
                self.run_seed(self.fixture_rows(), apply=True)
        self.assertFalse(Videos.objects.exists())
        for model in (Actor, Categoria, Idioma, Postura):
            self.assertFalse(model.objects.exists())


class LegacyMigrationTests(TransactionTestCase):
    initial = ("app", "0001_initial")
    latest = ("app", "0008_segmentar_miniaturas_premium")

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.initial])
        self.legacy = executor.loader.project_state([self.initial]).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate([self.latest])

    def test_preserves_account_state_and_video_references(self):
        old_user = self.legacy.get_model("app", "Usuario").objects.create(
            username="historic",
            email=" HISTORIC@EXAMPLE.NET ",
            password="historical-hash",
            is_active=False,
            temp_password="obsolete",
        )
        old_video = self.legacy.get_model("app", "Videos").objects.create(
            nombre="Video existente",
            descripcion="Video de prueba",
            miniatura="upload/photos/legacy.png",
            video="upload/videos/legacy.mp4",
            visitas=3,
        )
        MigrationExecutor(connection).migrate([self.latest])
        user = Usuario.objects.get(pk=old_user.pk)
        self.assertEqual(user.email, "historic@example.net")
        self.assertEqual(user.password, "historical-hash")
        self.assertFalse(user.is_active)
        video = Videos.objects.get(pk=old_video.pk)
        self.assertEqual(video.video.name, "upload/videos/legacy.mp4")
        self.assertEqual(video.miniatura.name, "upload/photos/legacy.png")
        self.assertTrue(video.es_premium)
        self.assertIsNone(video.idioma_id)
        self.assertFalse(video.categorias.exists())
        self.assertFalse(video.actores.exists())
        self.assertFalse(video.posturas.exists())
        self.assertNotIn("temp_password", [field.name for field in Usuario._meta.fields])

    def test_colliding_emails_stop_migration_without_reassigning_accounts(self):
        accounts = self.legacy.get_model("app", "Usuario").objects
        first = accounts.create(username="one", email="SAME@example.net")
        duplicate = accounts.create(username="two", email="same@example.net")
        try:
            with self.assertRaisesMessage(RuntimeError, "Hay correos duplicados"):
                MigrationExecutor(connection).migrate([self.latest])
            first.refresh_from_db()
            self.assertEqual(first.email, "SAME@example.net")
        finally:
            duplicate.delete()
