from django.core.exceptions import ObjectDoesNotExist

from .models import get_user_subscribed_months, user_has_active_subscription


def subscription(request):
    user = request.user
    subscribed = get_user_subscribed_months(user) if user.is_authenticated else []
    subscribed_keys = {f"{m['year']}-{m['month']}" for m in subscribed}
    return {
        "has_active_subscription": user_has_active_subscription(user),
        "subscribed_months": subscribed,
        "subscribed_month_keys": subscribed_keys,
    }


def formateur_nav(request):
    """Liens des espaces formateur dans l’en-tête du site."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "show_formateur_space": False,
            "show_formateur_contenu_space": False,
        }
    if getattr(user, "is_staff", False):
        return {
            "show_formateur_space": True,
            "show_formateur_contenu_space": True,
        }
    try:
        profile = user.profile
        full = bool(profile.is_platform_formateur)
        contenu = bool(profile.is_content_formateur)
        return {
            "show_formateur_space": full,
            "show_formateur_contenu_space": contenu and not full,
        }
    except ObjectDoesNotExist:
        return {
            "show_formateur_space": False,
            "show_formateur_contenu_space": False,
        }


def formateur_space(request):
    """Contexte gabarits : onglet abonnements uniquement sur l’espace complet."""
    path = getattr(request, "path", "") or ""
    if path.startswith("/espace-formateur-contenu"):
        return {"show_formateur_subscriptions": False}
    if path.startswith("/espace-formateur"):
        return {"show_formateur_subscriptions": True}
    return {}


def admin_exam_recap(request):
    """Récapitulatifs dans l’interface d’administration Django."""
    path = getattr(request, "path", "") or ""
    if not path.startswith("/admin/") or "/login" in path:
        return {}
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not user.is_staff:
        return {}
    from .exam_results import build_admin_exam_recap_tree
    from .subscription_recap import (
        build_admin_subscription_recap_tree,
        subscription_recap_global_export_url,
    )

    return {
        "admin_exam_recap": build_admin_exam_recap_tree(),
        "admin_subscription_recap": build_admin_subscription_recap_tree(),
        "admin_subscription_recap_export_url": subscription_recap_global_export_url(),
    }
