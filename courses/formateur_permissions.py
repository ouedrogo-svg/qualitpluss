from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Category


def _profile(user):
    try:
        return user.profile
    except ObjectDoesNotExist:
        return None


def user_can_access_full_formateur_space(user) -> bool:
    """Espace formateur complet (contenu + demandes d’abonnement + récap)."""
    if not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False):
        return True
    profile = _profile(user)
    return bool(profile and profile.is_platform_formateur)


def user_can_access_content_formateur_space(user) -> bool:
    """Espace formateur contenu (sans gestion des demandes d’abonnement)."""
    if not user.is_authenticated:
        return False
    if user_can_access_full_formateur_space(user):
        return True
    profile = _profile(user)
    return bool(profile and profile.is_content_formateur)


# Alias historique
def user_can_access_formateur_space(user) -> bool:
    return user_can_access_full_formateur_space(user)


def formateur_has_unrestricted_categories(user) -> bool:
    """Personnel : toutes les catégories, sans filtre M2M."""
    return bool(user.is_authenticated and getattr(user, "is_staff", False))


def formateur_space_assigned_only(request) -> bool:
    """Espace formateur contenu : uniquement les catégories assignées au profil."""
    return getattr(request, "formateur_url_group", "full") == "contenu"


def formateur_category_ids(user, *, assigned_only: bool = False) -> set[int] | None:
    """
    Identifiants des catégories accessibles.
    None = toutes (personnel, espace complet uniquement).
    set() = aucune catégorie assignée.
    assigned_only=True : toujours le M2M du profil (espace contenu).
    """
    if not user.is_authenticated:
        return set()
    if not assigned_only and formateur_has_unrestricted_categories(user):
        return None
    profile = _profile(user)
    if not profile:
        return set()
    return set(profile.categories.values_list("pk", flat=True))


def scope_formateur_categories(
    qs, user, *, category_field="category_id", assigned_only: bool = False
):
    """Filtre un queryset lié à une catégorie selon le profil formateur."""
    ids = formateur_category_ids(user, assigned_only=assigned_only)
    if ids is None:
        return qs
    if not ids:
        return qs.none()
    return qs.filter(**{f"{category_field}__in": ids})


def formateur_category_queryset(user, *, assigned_only: bool = False):
    """Queryset des catégories visibles dans l’espace formateur."""
    qs = Category.objects.all()
    ids = formateur_category_ids(user, assigned_only=assigned_only)
    if ids is None:
        return qs
    if not ids:
        return qs.none()
    return qs.filter(pk__in=ids)


def ensure_formateur_category_access(
    user, category, *, assigned_only: bool = False
) -> None:
    ids = formateur_category_ids(user, assigned_only=assigned_only)
    if ids is None:
        return
    if category.pk not in ids:
        raise PermissionDenied("Vous n’avez pas accès à cette catégorie.")


def get_formateur_category_or_404(user, pk, *, assigned_only: bool = False):
    cat = get_object_or_404(Category, pk=pk)
    ensure_formateur_category_access(user, cat, assigned_only=assigned_only)
    return cat


def get_formateur_object_or_404(
    user, model, pk, *, select_related=(), assigned_only: bool = False
):
    qs = model.objects.all()
    if select_related:
        qs = qs.select_related(*select_related)
    obj = get_object_or_404(qs, pk=pk)
    ensure_formateur_category_access(user, obj.category, assigned_only=assigned_only)
    return obj


def formateur_can_view_category_content(user, category: Category) -> bool:
    """
    Formateur / personnel : consultation du contenu public sans abonnement candidat,
    pour les catégories auxquelles il a accès dans son espace.
    """
    if not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False):
        return True
    if not user_can_access_content_formateur_space(user):
        return False
    ids = formateur_category_ids(user, assigned_only=True)
    return category.pk in ids


def redirect_formateur_login(request):
    return redirect_to_login(request.get_full_path())
