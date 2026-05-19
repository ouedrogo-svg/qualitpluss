"""Tâches légères en arrière-plan (hors requête HTTP)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from django.db import close_old_connections

logger = logging.getLogger(__name__)


def defer_to_background(func: Callable[[], None]) -> None:
    """
    Lance func dans un fil daemon après la fin de la requête.
    Évite de bloquer l’utilisateur pendant l’analyse PDF (pdfplumber).
    """

    def _runner():
        close_old_connections()
        try:
            func()
        except Exception:
            logger.exception("Tâche en arrière-plan échouée")
        finally:
            close_old_connections()

    threading.Thread(target=_runner, daemon=True).start()


def on_commit_in_background(func: Callable[[], None]) -> Callable[[], None]:
    """Retourne un callback transaction.on_commit qui exécute func en arrière-plan."""

    def _callback():
        defer_to_background(func)

    return _callback
