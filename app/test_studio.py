from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse

from .models import Actor, Categoria, Idioma, Postura, Usuario, Videos


def perms(*codenames):
    return Permission.objects.filter(codename__in=codenames)


class StudioTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Usuario.objects.create_superuser("admin", "admin@example.com", "clave-segura-123")
        cls.staff = Usuario.objects.create_user("staff", "staff@example.com", "clave-segura-123", is_staff=True)
        cls.member = Usuario.objects.create_user("member", "member@example.com", "clave-segura-123")

    def login(self, user):
        self.client.force_login(user)


class StudioAccessTests(StudioTestCase):
    def test_anonymous_users_are_sent_to_login(self):
        response = self.client.get(reverse("studio_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_accounts_without_panel_access_are_rejected(self):
        self.login(self.member)
        for name, kwargs in (
            ("studio_dashboard", {}),
            ("studio_catalog", {"kind": "categorias"}),
            ("studio_users", {}),
            ("studio_roles", {}),
        ):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, kwargs=kwargs)).status_code, 403)

    def test_staff_only_sees_sections_allowed_by_their_permissions(self):
        self.staff.user_permissions.add(*perms("view_categoria"))
        self.login(self.staff)
        dashboard = self.client.get(reverse("studio_dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, reverse("studio_catalog", kwargs={"kind": "categorias"}))
        self.assertNotContains(dashboard, reverse("studio_catalog", kwargs={"kind": "actores"}))
        self.assertNotContains(dashboard, reverse("studio_users"))
        self.assertEqual(self.client.get(reverse("studio_catalog", kwargs={"kind": "categorias"})).status_code, 200)
        self.assertEqual(self.client.get(reverse("studio_catalog", kwargs={"kind": "actores"})).status_code, 403)
        self.assertEqual(self.client.get(reverse("studio_catalog_add", kwargs={"kind": "categorias"})).status_code, 403)
        self.assertEqual(self.client.get(reverse("studio_users")).status_code, 403)
        self.assertEqual(self.client.get(reverse("studio_roles")).status_code, 403)

    def test_unknown_catalog_section_is_not_found(self):
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("studio_catalog", kwargs={"kind": "otros"})).status_code, 404)

    def test_account_menu_and_video_library_use_the_studio(self):
        self.login(self.admin)
        self.assertContains(self.client.get(reverse("home")), reverse("studio_dashboard"))
        library = self.client.get(reverse("video_manager"))
        self.assertContains(library, "studio-nav")
        self.assertContains(library, 'aria-current="page"')


class StudioCatalogTests(StudioTestCase):
    def setUp(self):
        self.login(self.admin)

    def test_bulk_add_skips_existing_names_without_case_sensitivity(self):
        Categoria.objects.create(nombre="Amateur")
        response = self.client.post(
            reverse("studio_catalog_add", kwargs={"kind": "categorias"}),
            {"nombres": "amateur\n  Pareja   joven \nNueva\nnueva\n\n"},
        )
        self.assertRedirects(response, reverse("studio_catalog", kwargs={"kind": "categorias"}))
        self.assertQuerySetEqual(
            Categoria.objects.values_list("nombre", flat=True), ["Amateur", "Nueva", "Pareja joven"]
        )

    def test_quick_add_creates_a_single_actor(self):
        self.client.post(reverse("studio_catalog_add", kwargs={"kind": "actores"}), {"nombres": "Ana Ruiz"})
        self.assertTrue(Actor.objects.filter(nombre="Ana Ruiz").exists())

    def test_rename_rejects_duplicates(self):
        first = Categoria.objects.create(nombre="Rubias")
        Categoria.objects.create(nombre="Morenas")
        url = reverse("studio_catalog_edit", kwargs={"kind": "categorias", "pk": first.pk})
        self.assertContains(self.client.post(url, {"nombre": "morenas"}), "Ya existe un elemento con este nombre.")
        self.client.post(url, {"nombre": "Rubias naturales"})
        first.refresh_from_db()
        self.assertEqual(first.nombre, "Rubias naturales")

    def test_list_counts_videos_and_supports_search(self):
        category = Categoria.objects.create(nombre="Exterior")
        Categoria.objects.create(nombre="Interior")
        video = Videos.objects.create(nombre="Paseo", descripcion="", visitas=0)
        video.categorias.add(category)
        response = self.client.get(reverse("studio_catalog", kwargs={"kind": "categorias"}), {"q": "exte"})
        self.assertEqual([item.nombre for item in response.context["items"]], ["Exterior"])
        self.assertEqual(response.context["items"][0].total_videos, 1)

    def test_delete_detaches_videos_without_deleting_them(self):
        category = Categoria.objects.create(nombre="Temporal")
        language = Idioma.objects.create(nombre="Español")
        video = Videos.objects.create(nombre="Clip", descripcion="", visitas=0, idioma=language)
        video.categorias.add(category)

        confirm = self.client.get(reverse("studio_catalog_delete", kwargs={"kind": "categorias", "pk": category.pk}))
        self.assertContains(confirm, "Se quitará de 1 video;")
        self.client.post(reverse("studio_catalog_delete", kwargs={"kind": "categorias", "pk": category.pk}))
        self.client.post(reverse("studio_catalog_delete", kwargs={"kind": "idiomas", "pk": language.pk}))

        video.refresh_from_db()
        self.assertFalse(Categoria.objects.exists())
        self.assertIsNone(video.idioma)
        self.assertFalse(video.categorias.exists())

    def test_staff_with_add_permission_can_create_but_not_delete(self):
        self.staff.user_permissions.add(*perms("view_postura", "add_postura"))
        self.login(self.staff)
        self.client.post(reverse("studio_catalog_add", kwargs={"kind": "posturas"}), {"nombres": "De pie"})
        created = Postura.objects.get(nombre="De pie")
        url = reverse("studio_catalog_delete", kwargs={"kind": "posturas", "pk": created.pk})
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(Postura.objects.filter(pk=created.pk).exists())


class StudioUserTests(StudioTestCase):
    def setUp(self):
        self.login(self.admin)

    def test_staff_cannot_manage_users_even_with_model_permissions(self):
        self.staff.user_permissions.add(*perms("view_usuario", "change_usuario", "add_usuario"))
        self.login(self.staff)
        self.assertEqual(self.client.get(reverse("studio_users")).status_code, 403)
        self.assertEqual(self.client.get(reverse("studio_user_edit", kwargs={"pk": self.member.pk})).status_code, 403)

    def test_superuser_creates_an_account_that_can_sign_in_with_email(self):
        role = Group.objects.create(name="Editores")
        response = self.client.post(reverse("studio_user_add"), {
            "first_name": "Laura",
            "last_name": "Gómez",
            "email": " Laura@Example.com ",
            "password1": "una-clave-muy-segura-2026",
            "password2": "una-clave-muy-segura-2026",
            "is_staff": "on",
            "groups": [role.pk],
        })
        self.assertRedirects(response, reverse("studio_users"))
        account = Usuario.objects.get(email="laura@example.com")
        self.assertTrue(account.is_staff)
        self.assertEqual(list(account.groups.all()), [role])
        self.client.logout()
        login = self.client.post(reverse("login"), {"email": "laura@example.com", "password": "una-clave-muy-segura-2026"})
        self.assertEqual(login.status_code, 302)

    def test_duplicate_email_is_rejected(self):
        response = self.client.post(reverse("studio_user_add"), {
            "first_name": "Otra",
            "last_name": "Cuenta",
            "email": "MEMBER@example.com",
            "password1": "una-clave-muy-segura-2026",
            "password2": "una-clave-muy-segura-2026",
        })
        self.assertContains(response, "Ya existe una cuenta con este correo.")

    def test_superuser_cannot_remove_their_own_access(self):
        self.client.post(reverse("studio_user_edit", kwargs={"pk": self.admin.pk}), {
            "first_name": "Admin",
            "last_name": "",
            "email": "admin@example.com",
        })
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)
        self.assertTrue(self.admin.is_staff)
        self.assertTrue(self.admin.is_superuser)
        self.assertEqual(self.admin.first_name, "Admin")

    def test_superuser_grants_panel_access_and_deactivates_accounts(self):
        self.client.post(reverse("studio_user_edit", kwargs={"pk": self.member.pk}), {
            "first_name": "",
            "last_name": "",
            "email": "member@example.com",
            "is_staff": "on",
        })
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_staff)
        self.assertFalse(self.member.is_active)

    def test_list_filters_team_members(self):
        response = self.client.get(reverse("studio_users"), {"filtro": "equipo"})
        self.assertEqual({account.username for account in response.context["users"]}, {"admin", "staff"})

    def test_password_change(self):
        url = reverse("studio_user_password", kwargs={"pk": self.member.pk})
        self.client.post(url, {"new_password1": "otra-clave-segura-2026", "new_password2": "otra-clave-segura-2026"})
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("otra-clave-segura-2026"))


class StudioRoleTests(StudioTestCase):
    def setUp(self):
        self.login(self.admin)

    def test_create_role_from_permission_matrix(self):
        selected = list(perms("view_videos", "add_videos", "add_categoria").values_list("pk", flat=True))
        response = self.client.post(reverse("studio_role_add"), {"name": "Editor de contenido", "permisos": selected})
        self.assertRedirects(response, reverse("studio_roles"))
        role = Group.objects.get(name="Editor de contenido")
        self.assertEqual(set(role.permissions.values_list("pk", flat=True)), set(selected))

    def test_editing_a_role_keeps_permissions_outside_the_matrix(self):
        role = Group.objects.create(name="Soporte")
        role.permissions.add(*perms("view_usuario", "view_videos"))
        self.client.post(
            reverse("studio_role_edit", kwargs={"pk": role.pk}),
            {"name": "Soporte", "permisos": list(perms("change_actor").values_list("pk", flat=True))},
        )
        self.assertEqual(
            set(role.permissions.values_list("codename", flat=True)), {"view_usuario", "change_actor"}
        )

    def test_permission_outside_the_matrix_cannot_be_granted(self):
        foreign = Permission.objects.get(codename="delete_usuario")
        response = self.client.post(reverse("studio_role_add"), {"name": "Intruso", "permisos": [foreign.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Group.objects.filter(name="Intruso").exists())

    def test_role_permissions_unlock_studio_sections(self):
        role = Group.objects.create(name="Clasificación")
        role.permissions.add(*perms("view_actor", "add_actor"))
        self.staff.groups.add(role)
        self.login(self.staff)
        self.assertEqual(self.client.get(reverse("studio_catalog", kwargs={"kind": "actores"})).status_code, 200)

    def test_delete_role_keeps_member_accounts(self):
        role = Group.objects.create(name="Temporal")
        self.staff.groups.add(role)
        self.assertContains(self.client.get(reverse("studio_role_delete", kwargs={"pk": role.pk})), "1 persona perderá")
        self.client.post(reverse("studio_role_delete", kwargs={"pk": role.pk}))
        self.assertFalse(Group.objects.filter(pk=role.pk).exists())
        self.assertTrue(Usuario.objects.filter(pk=self.staff.pk).exists())


class StudioDashboardTests(StudioTestCase):
    def test_dashboard_summarizes_the_catalog(self):
        Videos.objects.create(nombre="Popular", descripcion="", visitas=1500)
        Videos.objects.create(nombre="Nuevo", descripcion="", visitas=3)
        self.login(self.admin)
        response = self.client.get(reverse("studio_dashboard"))
        self.assertContains(response, "1.503")
        self.assertEqual([video.nombre for video in response.context["top_videos"]], ["Popular", "Nuevo"])
        self.assertEqual(response.context["unclassified_total"], 2)
