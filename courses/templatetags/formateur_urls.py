from django import template
from django.urls import reverse

register = template.Library()


def _url_name(request, suffix: str) -> str:
    group = getattr(request, "formateur_url_group", "full")
    prefix = "formateur_contenu" if group == "contenu" else "formateur"
    return f"courses:{prefix}_{suffix}"


@register.simple_tag(takes_context=True)
def formateur_url(context, suffix, *args, **kwargs):
    """Lien vers l’espace formateur actif (complet ou contenu seul)."""
    request = context["request"]
    return reverse(_url_name(request, suffix), args=args, kwargs=kwargs)
