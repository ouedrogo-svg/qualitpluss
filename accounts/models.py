from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Profil étendu : droits sans accès complet à l’admin Django."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name="utilisateur",
    )
    is_platform_formateur = models.BooleanField(
        "formateur plateforme (contenu & abonnements)",
        default=False,
        help_text=(
            "Accès à « Espace formateur » : contenu, demandes d’abonnement et récap. "
            "Incompatible avec le rôle « formateur contenu seul » (choisir l’un ou l’autre)."
        ),
    )
    is_content_formateur = models.BooleanField(
        "formateur contenu (sans demandes d’abonnement)",
        default=False,
        help_text=(
            "Accès à « Espace formateur contenu » : catégories, sujets PDF, corrections, "
            "examens et récap abonnements — sans validation des demandes d’abonnement."
        ),
    )
    categories = models.ManyToManyField(
        "courses.Category",
        blank=True,
        related_name="formateurs",
        verbose_name="catégories assignées",
        help_text=(
            "Limite l’espace formateur à ces catégories (contenu, abonnements, récap). "
            "Obligatoire pour un formateur non personnel : sans catégorie assignée, "
            "aucun accès aux données par catégorie."
        ),
    )

    class Meta:
        verbose_name = "profil utilisateur"
        verbose_name_plural = "profils utilisateur"

    def __str__(self):
        return f"Profil — {self.user}"
