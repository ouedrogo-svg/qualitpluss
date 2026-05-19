"""Espace formateur (site public) : contenu mensuel, catégories, abonnements, récap."""

from __future__ import annotations

from datetime import date, datetime as dt_datetime
from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .formateur_forms import (
    CategoryForm,
    MonthlyCorrectionForm,
    MonthlyCourseContentForm,
    MonthlyExamForm,
)
from .formateur_permissions import (
    formateur_category_queryset,
    formateur_has_unrestricted_categories,
    formateur_space_assigned_only,
    get_formateur_category_or_404,
    get_formateur_object_or_404,
    redirect_formateur_login,
    scope_formateur_categories,
    user_can_access_content_formateur_space,
    user_can_access_full_formateur_space,
)
from .forms import SubscriptionRequestAdminForm
from .models import (
    Category,
    MonthlyCorrection,
    MonthlyCourseContent,
    MonthlyExam,
    SubscriptionRequest,
    extend_subscription_after_approval_from_request,
)
from .subscription_recap import (
    build_formateur_contenu_subscription_recap_tree,
    build_formateur_subscription_recap_tree,
    build_subscription_recap_xlsx,
    formateur_contenu_subscription_recap_global_export_url,
    formateur_subscription_recap_global_export_url,
    subscription_recap_filename,
)
from .exam_results import build_exam_results_xlsx, exam_results_filename
from .background_tasks import on_commit_in_background


def _should_sync_quiz_from_form(form) -> bool:
    """Relire le PDF seulement si un fichier a été téléversé (création ou remplacement)."""
    if "pdf" not in form.cleaned_data or not form.cleaned_data["pdf"]:
        return False
    if not form.instance.pk:
        return True
    return "pdf" in form.changed_data


def _fname(request, suffix: str) -> str:
    group = getattr(request, "formateur_url_group", "full")
    prefix = "formateur_contenu" if group == "contenu" else "formateur"
    return f"courses:{prefix}_{suffix}"


def _fredirect(request, suffix: str, **kwargs):
    return redirect(_fname(request, suffix), **kwargs)


def _freverse(request, suffix: str, **kwargs):
    return reverse(_fname(request, suffix), kwargs=kwargs)


def _assigned_only(request) -> bool:
    return formateur_space_assigned_only(request)


def _scope(request, qs, **kwargs):
    return scope_formateur_categories(
        qs, request.user, assigned_only=_assigned_only(request), **kwargs
    )


def _get_obj(request, model, pk, **kwargs):
    return get_formateur_object_or_404(
        request.user, model, pk, assigned_only=_assigned_only(request), **kwargs
    )


def platform_formateur_required(view_fn):
    """Espace formateur complet (avec demandes d’abonnement)."""

    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_formateur_login(request)
        if not user_can_access_full_formateur_space(request.user):
            raise PermissionDenied(
                "Cet espace est réservé aux formateurs plateforme ou au personnel."
            )
        request.formateur_url_group = "full"
        return view_fn(request, *args, **kwargs)

    return _wrapped


def content_formateur_required(view_fn):
    """Contenu + récap (espaces complet ou contenu seul)."""

    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_formateur_login(request)
        if not user_can_access_content_formateur_space(request.user):
            raise PermissionDenied(
                "Cet espace est réservé aux formateurs autorisés ou au personnel."
            )
        if not hasattr(request, "formateur_url_group"):
            path = getattr(request, "path", "") or ""
            request.formateur_url_group = (
                "contenu" if path.startswith("/espace-formateur-contenu") else "full"
            )
        return view_fn(request, *args, **kwargs)

    return _wrapped


def contenu_formateur_route(view_fn):
    """Force les URLs / redirections vers l’espace formateur contenu."""

    @content_formateur_required
    @wraps(view_fn)
    def _wrapped(request, *args, **kwargs):
        request.formateur_url_group = "contenu"
        return view_fn(request, *args, **kwargs)

    return _wrapped


def _schedule_correction_quiz_sync(correction_pk: int):
    def _job():
        from .models import MonthlyCorrection
        from .pdf_quiz_import import sync_quiz_after_correction_saved

        try:
            corr = MonthlyCorrection.objects.get(pk=correction_pk)
        except MonthlyCorrection.DoesNotExist:
            return
        sync_quiz_after_correction_saved(corr)

    transaction.on_commit(on_commit_in_background(_job))


def _schedule_exam_quiz_sync(exam_pk: int):
    def _job():
        from .models import MonthlyExam
        from .pdf_quiz_import import sync_quiz_after_exam_saved

        try:
            exam = MonthlyExam.objects.get(pk=exam_pk)
        except MonthlyExam.DoesNotExist:
            return
        sync_quiz_after_exam_saved(exam)

    transaction.on_commit(on_commit_in_background(_job))


def _formateur_dashboard_content_blocks(user, *, assigned_only: bool = False):
    """Sujets, corrections et examens regroupés par catégorie assignée."""
    categories = formateur_category_queryset(
        user, assigned_only=assigned_only
    ).order_by("name")
    blocks = []
    for cat in categories:
        subjects = list(
            MonthlyCourseContent.objects.filter(category=cat).order_by(
                "-year", "-month", "-created_at"
            )
        )
        corrections = list(
            MonthlyCorrection.objects.filter(category=cat).order_by(
                "-year", "-month", "-created_at"
            )
        )
        exams = list(
            MonthlyExam.objects.filter(category=cat).order_by(
                "-year", "-month", "-created_at"
            )
        )
        if subjects or corrections or exams:
            blocks.append(
                {
                    "category": cat,
                    "subjects": subjects,
                    "corrections": corrections,
                    "exams": exams,
                }
            )
    return blocks


def _formateur_dashboard_context(user, *, assigned_only: bool = False):
    today = date.today()
    categories = formateur_category_queryset(
        user, assigned_only=assigned_only
    ).order_by("name")
    content_blocks = _formateur_dashboard_content_blocks(
        user, assigned_only=assigned_only
    )
    return {
        "assigned_categories": categories,
        "content_by_category": content_blocks,
        "n_categories": categories.count(),
        "n_subjects": scope_formateur_categories(
            MonthlyCourseContent.objects.all(), user, assigned_only=assigned_only
        ).count(),
        "n_corrections": scope_formateur_categories(
            MonthlyCorrection.objects.all(), user, assigned_only=assigned_only
        ).count(),
        "n_exams": scope_formateur_categories(
            MonthlyExam.objects.all(), user, assigned_only=assigned_only
        ).count(),
        "n_pending_subs": scope_formateur_categories(
            SubscriptionRequest.objects.filter(
                status=SubscriptionRequest.Status.PENDING
            ),
            user,
            assigned_only=assigned_only,
        ).count(),
        "today": today,
    }


def _dashboard_assigned_only(user) -> bool:
    """Sur l’accueil formateur : catégories assignées (sauf personnel sans filtre M2M)."""
    return not formateur_has_unrestricted_categories(user)


@platform_formateur_required
def formateur_dashboard(request):
    assigned_only = _dashboard_assigned_only(request.user)
    return render(
        request,
        "courses/formateur/dashboard.html",
        {
            **_formateur_dashboard_context(
                request.user, assigned_only=assigned_only
            ),
            "show_subscriptions": True,
            "show_assigned_categories": assigned_only,
            "show_content_overview": True,
            "space_title": "Espace formateur",
            "space_intro": (
                "Gestion du contenu par mois, des catégories qui vous sont assignées, "
                "des demandes d’abonnement et du récapitulatif — sans abonnement requis "
                "pour consulter vos contenus."
            ),
        },
    )


@contenu_formateur_route
def formateur_contenu_dashboard(request):
    assigned_only = True
    return render(
        request,
        "courses/formateur/dashboard.html",
        {
            **_formateur_dashboard_context(
                request.user, assigned_only=assigned_only
            ),
            "show_subscriptions": False,
            "show_assigned_categories": True,
            "show_content_overview": True,
            "space_title": "Espace formateur contenu",
            "space_intro": (
                "Vos sujets, corrections et examens pour les catégories qui vous sont "
                "assignées — consultation sans abonnement candidat."
            ),
        },
    )


# --- Catégories ---


@content_formateur_required
def formateur_category_list(request):
    ao = _assigned_only(request)
    items = formateur_category_queryset(
        request.user, assigned_only=ao
    ).order_by("name")
    return render(
        request,
        "courses/formateur/category_list.html",
        {
            "items": items,
            "can_create_categories": formateur_has_unrestricted_categories(
                request.user
            ),
        },
    )


@content_formateur_required
def formateur_category_create(request):
    if not formateur_has_unrestricted_categories(request.user):
        raise PermissionDenied(
            "Seul le personnel peut créer des catégories. Contactez l’administrateur."
        )
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Catégorie créée.")
            return _fredirect(request, "category_list")
    else:
        form = CategoryForm()
    return render(
        request,
        "courses/formateur/category_form.html",
        {"form": form, "title": "Nouvelle catégorie"},
    )


@content_formateur_required
def formateur_category_edit(request, pk):
    cat = get_formateur_category_or_404(
        request.user, pk, assigned_only=_assigned_only(request)
    )
    if request.method == "POST":
        form = CategoryForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            messages.success(request, "Catégorie mise à jour.")
            return _fredirect(request, "category_list")
    else:
        form = CategoryForm(instance=cat)
    return render(
        request,
        "courses/formateur/category_form.html",
        {"form": form, "title": "Modifier la catégorie", "category": cat},
    )


@content_formateur_required
def formateur_category_delete(request, pk):
    cat = get_formateur_category_or_404(
        request.user, pk, assigned_only=_assigned_only(request)
    )
    if request.method == "POST":
        name = cat.name
        cat.delete()
        messages.success(request, f"Catégorie « {name} » supprimée.")
        return _fredirect(request, "category_list")
    return render(
        request,
        "courses/formateur/confirm_delete.html",
        {
            "title": "Supprimer la catégorie",
            "object_label": cat.name,
            "warning": "Tous les contenus, examens et abonnements liés à cette catégorie seront supprimés ou affectés.",
            "cancel_suffix": "category_list",
            "form_action": _freverse(request, "category_delete", pk=pk),
        },
    )


# --- Sujets PDF (contenu mensuel) ---


@content_formateur_required
def formateur_monthly_content_list(request):
    items = _scope(
        request, MonthlyCourseContent.objects.select_related("category")
    ).order_by("-year", "-month", "category__name", "id")
    return render(request, "courses/formateur/monthly_content_list.html", {"items": items})


@content_formateur_required
def formateur_monthly_content_create(request):
    today = date.today()
    if request.method == "POST":
        form = MonthlyCourseContentForm(
            request.POST,
            request.FILES,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Sujet (PDF) enregistré.")
            return _fredirect(request, "monthly_content_list")
    else:
        form = MonthlyCourseContentForm(
            initial={"year": today.year, "month": today.month},
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/monthly_content_form.html",
        {"form": form, "title": "Nouveau sujet (PDF par mois)"},
    )


@content_formateur_required
def formateur_monthly_content_edit(request, pk):
    obj = _get_obj(
        request, MonthlyCourseContent, pk, select_related=("category",)
    )
    if request.method == "POST":
        form = MonthlyCourseContentForm(
            request.POST,
            request.FILES,
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Sujet mis à jour.")
            return _fredirect(request, "monthly_content_list")
    else:
        form = MonthlyCourseContentForm(
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/monthly_content_form.html",
        {"form": form, "title": "Modifier le sujet (PDF)", "obj": obj},
    )


@content_formateur_required
def formateur_monthly_content_delete(request, pk):
    obj = _get_obj(request, MonthlyCourseContent, pk)
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Supprimé : {label}")
        return _fredirect(request, "monthly_content_list")
    return render(
        request,
        "courses/formateur/confirm_delete.html",
        {
            "title": "Supprimer ce sujet PDF",
            "object_label": str(obj),
            "warning": "",
            "cancel_suffix": "monthly_content_list",
            "form_action": _freverse(request, "monthly_content_delete", pk=pk),
        },
    )


# --- Corrections ---


@content_formateur_required
def formateur_correction_list(request):
    items = _scope(
        request, MonthlyCorrection.objects.select_related("category")
    ).order_by("-year", "-month", "category__name", "id")
    return render(request, "courses/formateur/correction_list.html", {"items": items})


@content_formateur_required
def formateur_correction_create(request):
    today = date.today()
    if request.method == "POST":
        form = MonthlyCorrectionForm(
            request.POST,
            request.FILES,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            corr = form.save()
            if _should_sync_quiz_from_form(form):
                _schedule_correction_quiz_sync(corr.pk)
                messages.success(
                    request,
                    "Correction enregistrée. Le quiz sera généré automatiquement "
                    "(quelques secondes).",
                )
            else:
                messages.success(request, "Correction enregistrée.")
            return _fredirect(request, "correction_list")
    else:
        form = MonthlyCorrectionForm(
            initial={"year": today.year, "month": today.month},
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/correction_form.html",
        {"form": form, "title": "Nouvelle correction (PDF)"},
    )


@content_formateur_required
def formateur_correction_edit(request, pk):
    obj = _get_obj(request, MonthlyCorrection, pk, select_related=("category",))
    if request.method == "POST":
        form = MonthlyCorrectionForm(
            request.POST,
            request.FILES,
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            corr = form.save()
            if _should_sync_quiz_from_form(form):
                _schedule_correction_quiz_sync(corr.pk)
                messages.success(
                    request,
                    "Correction mise à jour. Le quiz sera régénéré à partir du nouveau PDF.",
                )
            else:
                messages.success(request, "Correction mise à jour.")
            return _fredirect(request, "correction_list")
    else:
        form = MonthlyCorrectionForm(
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/correction_form.html",
        {"form": form, "title": "Modifier la correction", "obj": obj},
    )


@content_formateur_required
def formateur_correction_delete(request, pk):
    obj = _get_obj(request, MonthlyCorrection, pk)
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Supprimé : {label}")
        return _fredirect(request, "correction_list")
    return render(
        request,
        "courses/formateur/confirm_delete.html",
        {
            "title": "Supprimer cette correction",
            "object_label": str(obj),
            "warning": "Le quiz interactif associé sera supprimé.",
            "cancel_suffix": "correction_list",
            "form_action": _freverse(request, "correction_delete", pk=pk),
        },
    )


# --- Examens ---


@content_formateur_required
def formateur_exam_list(request):
    items = _scope(request, MonthlyExam.objects.select_related("category")).order_by(
        "-year", "-month", "category__name", "id"
    )
    return render(request, "courses/formateur/exam_list.html", {"items": items})


@content_formateur_required
def formateur_exam_create(request):
    today = date.today()
    if request.method == "POST":
        form = MonthlyExamForm(
            request.POST,
            request.FILES,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            exam = form.save()
            if _should_sync_quiz_from_form(form):
                _schedule_exam_quiz_sync(exam.pk)
                messages.success(
                    request,
                    "Examen enregistré. Le quiz sera généré automatiquement "
                    "(quelques secondes).",
                )
            else:
                messages.success(request, "Examen enregistré.")
            return _fredirect(request, "exam_list")
    else:
        form = MonthlyExamForm(
            initial={"year": today.year, "month": today.month},
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/exam_form.html",
        {"form": form, "title": "Nouvel examen (PDF)"},
    )


@content_formateur_required
def formateur_exam_edit(request, pk):
    obj = _get_obj(request, MonthlyExam, pk, select_related=("category",))
    if request.method == "POST":
        form = MonthlyExamForm(
            request.POST,
            request.FILES,
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
        if form.is_valid():
            exam = form.save()
            if _should_sync_quiz_from_form(form):
                _schedule_exam_quiz_sync(exam.pk)
                messages.success(
                    request,
                    "Examen mis à jour. Le quiz sera régénéré à partir du nouveau PDF.",
                )
            else:
                messages.success(request, "Examen mis à jour.")
            return _fredirect(request, "exam_list")
    else:
        form = MonthlyExamForm(
            instance=obj,
            formateur_user=request.user,
            assigned_only=_assigned_only(request),
        )
    return render(
        request,
        "courses/formateur/exam_form.html",
        {
            "form": form,
            "title": "Modifier l’examen",
            "obj": obj,
        },
    )


@content_formateur_required
def formateur_exam_delete(request, pk):
    obj = _get_obj(request, MonthlyExam, pk)
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Supprimé : {label}")
        return _fredirect(request, "exam_list")
    return render(
        request,
        "courses/formateur/confirm_delete.html",
        {
            "title": "Supprimer cet examen",
            "object_label": str(obj),
            "warning": "Les résultats de quiz et le fichier seront supprimés.",
            "cancel_suffix": "exam_list",
            "form_action": _freverse(request, "exam_delete", pk=pk),
        },
    )


@content_formateur_required
def formateur_exam_results_export(request, pk):
    exam = _get_obj(request, MonthlyExam, pk)
    content = build_exam_results_xlsx(exam)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{exam_results_filename(exam)}"'
    return response


# --- Abonnements ---


@platform_formateur_required
def formateur_subscription_list(request):
    pending = scope_formateur_categories(
        SubscriptionRequest.objects.filter(
            status=SubscriptionRequest.Status.PENDING
        ).select_related("user", "category", "plan"),
        request.user,
    ).order_by("created_at")
    recent = scope_formateur_categories(
        SubscriptionRequest.objects.exclude(
            status=SubscriptionRequest.Status.PENDING
        ).select_related("user", "category", "plan", "decided_by"),
        request.user,
    ).order_by("-decided_at", "-created_at")[:50]
    return render(
        request,
        "courses/formateur/subscription_list.html",
        {"pending": pending, "recent": recent},
    )


@platform_formateur_required
def formateur_subscription_edit(request, pk):
    req = get_formateur_object_or_404(
        request.user,
        SubscriptionRequest,
        pk,
        select_related=("user", "category", "plan"),
    )
    if req.status != SubscriptionRequest.Status.PENDING:
        return render(
            request,
            "courses/formateur/subscription_readonly.html",
            {"req": req},
        )
    if request.method == "POST":
        form = SubscriptionRequestAdminForm(
            request.POST, instance=req, formateur_user=request.user
        )
        if form.is_valid():
            old_status = SubscriptionRequest.objects.filter(pk=req.pk).values_list(
                "status", flat=True
            ).first()
            obj = form.save()
            if (
                old_status == SubscriptionRequest.Status.PENDING
                and obj.status == SubscriptionRequest.Status.APPROVED
            ):
                obj.decided_at = timezone.now()
                obj.decided_by = request.user
                obj.save(update_fields=["decided_at", "decided_by"])
                n_months = extend_subscription_after_approval_from_request(obj)
                messages.success(
                    request,
                    f"Demande approuvée : {n_months} mois accordé(s) ({obj.covered_periods_display()}).",
                )
            elif (
                old_status == SubscriptionRequest.Status.PENDING
                and obj.status == SubscriptionRequest.Status.REJECTED
            ):
                obj.decided_at = timezone.now()
                obj.decided_by = request.user
                obj.save(update_fields=["decided_at", "decided_by"])
                messages.warning(request, "Demande refusée.")
            else:
                messages.success(request, "Demande mise à jour.")
            return redirect("courses:formateur_subscription_list")
    else:
        form = SubscriptionRequestAdminForm(
            instance=req, formateur_user=request.user
        )
    return render(
        request,
        "courses/formateur/subscription_form.html",
        {"form": form, "req": req},
    )


@platform_formateur_required
def formateur_subscription_approve(request, pk):
    if request.method != "POST":
        return redirect("courses:formateur_subscription_edit", pk=pk)
    req = get_formateur_object_or_404(request.user, SubscriptionRequest, pk)
    if req.status != SubscriptionRequest.Status.PENDING:
        messages.error(request, "Cette demande n’est plus en attente.")
        return redirect("courses:formateur_subscription_list")
    req.status = SubscriptionRequest.Status.APPROVED
    req.decided_at = timezone.now()
    req.decided_by = request.user
    req.save(update_fields=["status", "decided_at", "decided_by"])
    extend_subscription_after_approval_from_request(req)
    messages.success(
        request,
        f"Approuvé : {req.user.get_full_name() or req.user.username} — {req.covered_periods_display()}.",
    )
    return redirect("courses:formateur_subscription_list")


@platform_formateur_required
def formateur_subscription_reject(request, pk):
    if request.method != "POST":
        return redirect("courses:formateur_subscription_edit", pk=pk)
    req = get_formateur_object_or_404(request.user, SubscriptionRequest, pk)
    if req.status != SubscriptionRequest.Status.PENDING:
        messages.error(request, "Cette demande n’est plus en attente.")
        return redirect("courses:formateur_subscription_list")
    req.status = SubscriptionRequest.Status.REJECTED
    req.decided_at = timezone.now()
    req.decided_by = request.user
    req.save(update_fields=["status", "decided_at", "decided_by"])
    messages.warning(request, "Demande refusée.")
    return redirect("courses:formateur_subscription_list")


# --- Récap abonnements ---


@content_formateur_required
def formateur_recap_subscriptions(request):
    if getattr(request, "formateur_url_group", "full") == "contenu":
        tree = build_formateur_contenu_subscription_recap_tree(request.user)
        global_export_url = formateur_contenu_subscription_recap_global_export_url()
    else:
        tree = build_formateur_subscription_recap_tree(request.user)
        global_export_url = formateur_subscription_recap_global_export_url()
    return render(
        request,
        "courses/formateur/recap_subscriptions.html",
        {
            "subscription_recap": tree,
            "global_export_url": global_export_url,
        },
    )


@content_formateur_required
def formateur_recap_export_all(request):
    from .formateur_permissions import formateur_category_ids

    content = build_subscription_recap_xlsx(
        category_ids=formateur_category_ids(
            request.user, assigned_only=_assigned_only(request)
        )
    )
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{subscription_recap_filename()}"'
    return response


@content_formateur_required
def formateur_recap_export_month(request, month_str):
    try:
        parsed = dt_datetime.strptime(month_str, "%Y-%m")
        for_month = (parsed.year, parsed.month)
    except ValueError:
        from django.http import Http404

        raise Http404("Mois invalide.") from None
    from .formateur_permissions import formateur_category_ids

    content = build_subscription_recap_xlsx(
        for_month=for_month,
        category_ids=formateur_category_ids(
            request.user, assigned_only=_assigned_only(request)
        ),
    )
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{subscription_recap_filename(for_month=for_month)}"'
    )
    return response
