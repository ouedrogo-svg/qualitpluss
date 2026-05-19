"""Lance le serveur de dev accessible depuis un téléphone Android (même Wi‑Fi)."""

import socket

from django.core.management.commands.runserver import Command as RunserverCommand


class Command(RunserverCommand):
    help = (
        "Serveur de développement sur toutes les interfaces (0.0.0.0:8000) "
        "pour tester depuis un téléphone Android."
    )

    default_addr = "0.0.0.0"
    default_port = "8000"

    def handle(self, *args, **options):
        self._print_android_urls()
        super().handle(*args, **options)

    def _print_android_urls(self):
        ips = []
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            ips.append(probe.getsockname()[0])
            probe.close()
        except OSError:
            pass
        port = self.default_port
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Test Android (meme Wi-Fi) ==="))
        if ips:
            for ip in ips:
                self.stdout.write(f"  http://{ip}:{port}/")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  IP locale introuvable — utilisez ipconfig puis http://<IP>:{port}/"
                )
            )
        self.stdout.write("Arrêt : Ctrl+C")
        self.stdout.write("")
