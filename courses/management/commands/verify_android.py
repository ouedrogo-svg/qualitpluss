"""Verifie que les pages s'affichent correctement pour un navigateur Android (simulation)."""

import socket

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.test import Client

from courses.models import MonthlyCourseContent

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)


def _lan_ip():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except OSError:
        return "127.0.0.1"


class Command(BaseCommand):
    help = "Controle viewport, CSS, PDF inline et hotes autorises pour Android."

    def add_arguments(self, parser):
        parser.add_argument(
            "--port",
            type=int,
            default=8000,
            help="Port du serveur (defaut : 8000)",
        )
        parser.add_argument(
            "--host",
            default="",
            help="IP a simuler (defaut : IP locale detectee)",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        ip = options["host"] or _lan_ip()
        port = options["port"]
        http_host = f"{ip}:{port}"

        public_paths = ["/", "/comptes/connexion/", "/comptes/inscription/"]
        member_paths = []
        mc = (
            MonthlyCourseContent.objects.select_related("category")
            .filter(pdf__isnull=False)
            .exclude(pdf="")
            .first()
        )
        if mc:
            slug, y, m, pk = mc.category.slug, mc.year, mc.month, mc.pk
            member_paths = [
                f"/categorie/{slug}/{y}/{m}/{pk}/",
                f"/categorie/{slug}/{y}/{m}/{pk}/pdf/",
            ]

        errors = []
        ok_count = 0

        public_client = Client(HTTP_USER_AGENT=ANDROID_UA)
        ok_count += self._run_checks(public_client, public_paths, http_host, errors)

        if member_paths:
            member_client = Client(HTTP_USER_AGENT=ANDROID_UA)
            staff = get_user_model().objects.filter(is_superuser=True).first()
            if not staff:
                errors.append("contenu PDF -> aucun superutilisateur pour tester")
            else:
                member_client.force_login(staff)
                ok_count += self._run_checks(
                    member_client, member_paths, http_host, errors
                )

        self.stdout.write("")
        self.stdout.write(f"Hote simule : {http_host}")
        self.stdout.write(
            f"ALLOWED_HOSTS contient {ip!r} : "
            + ("oui" if ip in settings.ALLOWED_HOSTS else "NON")
        )
        origin = f"http://{ip}:{port}"
        self.stdout.write(
            f"CSRF_TRUSTED_ORIGINS contient {origin!r} : "
            + ("oui" if origin in settings.CSRF_TRUSTED_ORIGINS else "NON")
        )
        self.stdout.write("")
        if errors:
            for err in errors:
                self.stdout.write(self.style.ERROR(f"KO  {err}"))
            self.stdout.write(
                self.style.WARNING(
                    f"\n{ok_count} page(s) OK, {len(errors)} probleme(s)."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\nToutes les verifications OK ({ok_count} pages). "
                f"Sur le telephone : http://{ip}:{port}/"
            )
        )

    def _run_checks(self, client, paths, http_host, errors):
        ok = 0
        for path in paths:
            response = client.get(path, HTTP_HOST=http_host)
            if self._check_response(path, response, errors):
                ok += 1
        return ok

    def _check_response(self, path, response, errors):
        if response.status_code != 200:
            errors.append(f"{path} -> HTTP {response.status_code}")
            return False
        if path.endswith("/pdf/"):
            xfo = response.get("X-Frame-Options")
            ct = response.get("Content-Type", "")
            if xfo != "SAMEORIGIN":
                errors.append(f"{path} -> X-Frame-Options={xfo!r}")
                return False
            if "application/pdf" not in ct:
                errors.append(f"{path} -> Content-Type={ct!r}")
                return False
            self.stdout.write(self.style.SUCCESS(f"OK  {path} (PDF lecture en ligne)"))
            return True

        body = response.content.decode()
        for token, label in (
            ("width=device-width", "viewport"),
            ("/static/css/style.css", "CSS"),
        ):
            if token not in body:
                errors.append(f"{path} -> {label} manquant")
                return False
        self.stdout.write(self.style.SUCCESS(f"OK  {path}"))
        return True
