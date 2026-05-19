import zipfile
from datetime import date, datetime as dt_datetime
from io import BytesIO

from django.contrib import admin
from django.contrib import messages as admin_messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone

from .exam_results import (
    _exam_display_title,
    build_exam_results_xlsx,
    exam_results_filename,
    ranked_exam_results,
)
from .subscription_recap import (
    build_subscription_recap_xlsx,
    subscription_recap_filename,
)
from .forms import SubscriptionRequestAdminForm
from .models import (
    Category,
    CorrectionQuiz,
    Course,
    Enrollment,
    ExamQuiz,
    ExamQuizAttempt,
    ExamQuizOption,
    ExamQuizQuestion,
    Lesson,
    LessonProgress,
    MonthlyCorrection,
    MonthlyCourseContent,
    MonthlyExam,
    QuizOption,
    QuizQuestion,
    SubscriptionPlan,
    SubscriptionPlanMonth,
    SubscriptionRequest,
    UserSubscription,
    extend_subscription_after_approval_from_request,
    french_month_name,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(MonthlyCourseContent)
class MonthlyCourseContentAdmin(admin.ModelAdmin):
    """SUJET mensuel : catégorie, année, mois, PDF — plusieurs entrées possibles par période."""

    list_display = ("category", "year", "month_display", "title", "has_pdf", "created_at")
    list_filter = ("category", "year", "month")
    search_fields = ("title", "category__name")
    readonly_fields = ("created_at",)
    fieldsets = (
        (
            None,
            {
                "fields": ("category", "year", "month", "title", "pdf"),
                "description": (
                    "Ajoutez autant de PDF que nécessaire pour la même catégorie et le même mois "
                    "(par ex. plusieurs supports). Indiquez un titre affiché pour les distinguer."
                ),
            },
        ),
        ("Métadonnées", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
    date_hierarchy = "created_at"
    ordering = ("-year", "-month", "category__name", "id")

    @admin.display(description="mois", ordering="month")
    def month_display(self, obj):
        return obj.get_month_display()

    @admin.display(description="PDF", boolean=True)
    def has_pdf(self, obj):
        return bool(obj.pdf)

    def get_changeform_initial_data(self, request):
        today = date.today()
        return {"year": today.year, "month": today.month}


class CorrectionQuizInline(admin.StackedInline):
    model = CorrectionQuiz
    can_delete = False
    max_num = 1
    min_num = 1
    extra = 0
    fk_name = "correction"
    readonly_fields = ("quiz_last_built_for_pdf_key",)
    fieldsets = (
        (
            None,
            {
                "fields": ("title", "quiz_last_built_for_pdf_key"),
                "description": (
                    "Le quiz est construit à partir du <strong>PDF du corrigé</strong> (champ « fichier PDF » "
                    "dans la section du dessus). Ne téléversez <strong>pas</strong> le PDF ici."
                ),
            },
        ),
        (
            "Import CSV (secours uniquement)",
            {
                "fields": ("import_csv",),
                "description": (
                    "Fichier <strong>.csv</strong> seulement (export tableur), si le PDF ne contient pas de "
                    "tableau détectable. Ce n’est pas le champ du corrigé PDF."
                ),
            },
        ),
    )


@admin.register(MonthlyCorrection)
class MonthlyCorrectionAdmin(admin.ModelAdmin):
    list_display = ("category", "year", "month_display", "title", "has_pdf", "created_at")
    list_filter = ("category", "year", "month")
    search_fields = ("title", "category__name")
    readonly_fields = ("created_at",)
    actions = ("rebuild_quiz_from_pdf",)
    fieldsets = (
        (
            None,
            {
                "fields": ("category", "year", "month", "title", "pdf"),
                "description": (
                    "Téléversez le corrigé en PDF. Le quiz interactif est généré automatiquement à partir des "
                    "<strong>tableaux</strong> présents dans ce PDF. Formats reconnus : tableau QCM classique "
                    "(question + plusieurs colonnes de propositions + réponses en indices ou lettres), ou "
                    "<strong>3 colonnes</strong> « N° d’ordre », « Questions », « Réponses » (réponses libres "
                    "ou indices si les choix A/B… sont dans le texte de la question). Si aucun tableau n’est détecté, "
                    "utilisez le champ CSV de secours dans le bloc quiz ou l’action « Reconstruire le quiz depuis le PDF »."
                ),
            },
        ),
        ("Métadonnées", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
    inlines = [CorrectionQuizInline]
    ordering = ("-year", "-month", "category__name", "id")

    @admin.display(description="mois", ordering="month")
    def month_display(self, obj):
        return obj.get_month_display()

    @admin.display(description="PDF", boolean=True)
    def has_pdf(self, obj):
        return bool(obj.pdf)

    def get_changeform_initial_data(self, request):
        today = date.today()
        return {"year": today.year, "month": today.month}

    @admin.action(description="Reconstruire le quiz depuis le PDF (forcer une nouvelle lecture)")
    def rebuild_quiz_from_pdf(self, request, queryset):
        from .pdf_quiz_import import force_rebuild_quiz_from_correction_pdf

        total = 0
        for corr in queryset:
            total += force_rebuild_quiz_from_correction_pdf(corr)
        n_corr = queryset.count()
        self.message_user(
            request,
            f"Lecture PDF terminée : {total} question(s) au total sur {n_corr} corrigé(s). "
            "Si le résultat est 0, le PDF ne contient peut‑être pas de tableau exploitable.",
            level=admin_messages.SUCCESS if total else admin_messages.WARNING,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not getattr(obj, "pdf", None) or not obj.pdf:
            return
        pk = obj.pk

        if change and "pdf" not in form.changed_data:
            return

        self.message_user(
            request,
            "Enregistrement terminé. Génération du quiz en arrière-plan (quelques secondes).",
            admin_messages.INFO,
        )

        def sync_quiz_after_commit():
            from .models import MonthlyCorrection
            from .pdf_quiz_import import sync_quiz_after_correction_saved

            try:
                corr = MonthlyCorrection.objects.get(pk=pk)
            except MonthlyCorrection.DoesNotExist:
                return
            sync_quiz_after_correction_saved(corr)

        from .background_tasks import on_commit_in_background

        transaction.on_commit(on_commit_in_background(sync_quiz_after_commit))


class ExamQuizInline(admin.StackedInline):
    model = ExamQuiz
    can_delete = False
    max_num = 1
    min_num = 1
    extra = 0
    fk_name = "exam"
    readonly_fields = ("quiz_last_built_for_pdf_key",)
    fieldsets = (
        (
            None,
            {
                "fields": ("title", "quiz_last_built_for_pdf_key"),
                "description": (
                    "Le quiz est construit à partir du <strong>PDF de l’examen</strong> (champ « fichier PDF » "
                    "dans la section du dessus)."
                ),
            },
        ),
        (
            "Import CSV (secours uniquement)",
            {
                "fields": ("import_csv",),
                "description": (
                    "Fichier <strong>.csv</strong> seulement, si le PDF ne contient pas de tableau détectable."
                ),
            },
        ),
    )


@admin.register(MonthlyExam)
class MonthlyExamAdmin(admin.ModelAdmin):
    list_display = ("category", "year", "month_display", "title", "has_pdf", "n_results", "created_at")
    list_filter = ("category", "year", "month")
    search_fields = ("title", "category__name")
    readonly_fields = ("created_at", "recap_resultats")
    actions = ("rebuild_quiz_from_pdf", "export_results_excel")
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "category",
                    "year",
                    "month",
                    "title",
                    "pdf",
                    "duration_minutes",
                    "results_collection_days",
                ),
                "description": (
                    "Téléversez l’examen en PDF. Définissez la durée du quiz et la période pendant laquelle "
                    "la <strong>première</strong> composition de chaque candidat est transmise au récapitulatif "
                    "(les reprises restent visibles pour le candidat seulement)."
                ),
            },
        ),
        (
            "Récapitulatif des résultats",
            {
                "fields": ("recap_resultats",),
                "description": (
                    "Premières compositions transmises à l’administrateur (nom, prénom, note, classement). "
                    "Les reprises du quiz par un candidat ne sont pas listées ici."
                ),
            },
        ),
        ("Métadonnées", {"fields": ("created_at",), "classes": ("collapse",)}),
    )
    inlines = [ExamQuizInline]
    ordering = ("-year", "-month", "category__name", "id")

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "<path:object_id>/export-resultats/",
                self.admin_site.admin_view(self.export_resultats_excel_view),
                name="courses_monthlyexam_export_resultats",
            ),
        ] + urls

    def export_resultats_excel_view(self, request, object_id):
        exam = get_object_or_404(MonthlyExam, pk=object_id)
        content = build_exam_results_xlsx(exam)
        filename = exam_results_filename(exam)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @admin.display(description="mois", ordering="month")
    def month_display(self, obj):
        return obj.get_month_display()

    @admin.display(description="PDF", boolean=True)
    def has_pdf(self, obj):
        return bool(obj.pdf)

    @admin.display(description="résultats")
    def n_results(self, obj):
        if not obj.pk:
            return "—"
        return len(ranked_exam_results(obj))

    @admin.display(description="Classement des candidats")
    def recap_resultats(self, obj):
        if not obj.pk:
            return "—"
        rows = ranked_exam_results(obj)
        export_url = reverse("admin:courses_monthlyexam_export_resultats", args=[obj.pk])
        export_btn = format_html(
            '<p style="margin:0 0 12px">'
            '<a class="button" href="{}">Exporter vers Excel (.xlsx)</a>'
            "</p>",
            export_url,
        )
        if not rows:
            return format_html(
                '{}<p class="help">Aucun résultat enregistré pour cet examen.</p>',
                export_btn,
            )
        cell = (
            "padding:10px 12px;border:1px solid #cbd5e1;"
            "vertical-align:middle"
        )
        intro = format_html(
            '<p class="help" style="margin:0 0 12px">'
            "<strong>{}</strong> — {} candidat(s)."
            "</p>",
            _exam_display_title(obj),
            len(rows),
        )
        body = "".join(
            format_html(
                '<tr style="background:{}">'
                '<td style="{}">{}</td>'
                '<td style="{}">{}</td>'
                '<td style="{};text-align:right">{}</td>'
                '<td style="{};text-align:center">{}</td>'
                "</tr>",
                "#f8fafc" if index % 2 == 0 else "#ffffff",
                cell,
                row["nom"],
                cell,
                row["prenom"],
                cell,
                row["note"],
                cell,
                row["classement"],
            )
            for index, row in enumerate(rows)
        )
        table = format_html(
            '<table class="admin-exam-results" style="width:100%;border-collapse:collapse">'
            "<thead><tr style=\"background:#e2e8f0\">"
            '<th style="{};text-align:left;font-weight:600">Nom</th>'
            '<th style="{};text-align:left;font-weight:600">Prénom</th>'
            '<th style="{};text-align:right;font-weight:600">Note</th>'
            '<th style="{};text-align:center;font-weight:600">Classement</th>'
            "</tr></thead><tbody>{}</tbody></table>",
            cell,
            cell,
            cell,
            cell,
            body,
        )
        return format_html("{}{}{}", export_btn, intro, table)

    @admin.action(description="Exporter les résultats (Excel)")
    def export_results_excel(self, request, queryset):
        exams = list(queryset)
        if not exams:
            return
        if len(exams) == 1:
            exam = exams[0]
            content = build_exam_results_xlsx(exam)
            response = HttpResponse(
                content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{exam_results_filename(exam)}"'
            return response

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for exam in exams:
                zf.writestr(
                    exam_results_filename(exam),
                    build_exam_results_xlsx(exam),
                )
        response = HttpResponse(buf.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="resultats_examens.zip"'
        return response

    def get_changeform_initial_data(self, request):
        today = date.today()
        return {"year": today.year, "month": today.month}

    @admin.action(description="Reconstruire le quiz depuis le PDF (forcer une nouvelle lecture)")
    def rebuild_quiz_from_pdf(self, request, queryset):
        from .pdf_quiz_import import force_rebuild_quiz_from_exam_pdf

        total = 0
        for exam in queryset:
            total += force_rebuild_quiz_from_exam_pdf(exam)
        n_exam = queryset.count()
        self.message_user(
            request,
            f"Lecture PDF terminée : {total} question(s) au total sur {n_exam} examen(s).",
            level=admin_messages.SUCCESS if total else admin_messages.WARNING,
        )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not getattr(obj, "pdf", None) or not obj.pdf:
            return
        pk = obj.pk

        if change and "pdf" not in form.changed_data:
            return

        self.message_user(
            request,
            "Enregistrement terminé. Génération du quiz en arrière-plan (quelques secondes).",
            admin_messages.INFO,
        )

        def sync_quiz_after_commit():
            from .models import MonthlyExam
            from .pdf_quiz_import import sync_quiz_after_exam_saved

            try:
                exam = MonthlyExam.objects.get(pk=pk)
            except MonthlyExam.DoesNotExist:
                return
            sync_quiz_after_exam_saved(exam)

        from .background_tasks import on_commit_in_background

        transaction.on_commit(on_commit_in_background(sync_quiz_after_commit))


@admin.register(ExamQuizAttempt)
class ExamQuizAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "exam",
        "nom",
        "prenom",
        "score_points",
        "sent_to_admin",
        "submitted_at",
    )
    list_filter = ("sent_to_admin", "exam__category", "exam__year", "exam__month", "exam")
    search_fields = ("user__last_name", "user__first_name", "user__username")
    readonly_fields = (
        "user",
        "exam",
        "score_points",
        "score_percent",
        "sent_to_admin",
        "submitted_at",
    )
    ordering = ("-submitted_at",)

    @admin.display(description="Nom", ordering="user__last_name")
    def nom(self, obj):
        return obj.user.last_name or "—"

    @admin.display(description="Prénom", ordering="user__first_name")
    def prenom(self, obj):
        return obj.user.first_name or "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ExamQuizOptionInline(admin.TabularInline):
    model = ExamQuizOption
    extra = 1
    ordering = ("order",)


@admin.register(ExamQuizQuestion)
class ExamQuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("exam_quiz", "order", "prompt_preview")
    list_filter = ("exam_quiz__exam__category", "exam_quiz__exam__year")
    search_fields = ("prompt",)
    ordering = ("exam_quiz", "order", "id")
    raw_id_fields = ("exam_quiz",)
    inlines = [ExamQuizOptionInline]

    @admin.display(description="énoncé")
    def prompt_preview(self, obj):
        return (obj.prompt[:80] + "…") if len(obj.prompt) > 80 else obj.prompt


class QuizOptionInline(admin.TabularInline):
    model = QuizOption
    extra = 1
    ordering = ("order",)


@admin.register(QuizQuestion)
class QuizQuestionAdmin(admin.ModelAdmin):
    list_display = ("quiz", "order", "prompt_preview")
    list_filter = ("quiz__correction__category", "quiz__correction__year")
    search_fields = ("prompt",)
    ordering = ("quiz", "order", "id")
    raw_id_fields = ("quiz",)
    inlines = [QuizOptionInline]

    @admin.display(description="énoncé")
    def prompt_preview(self, obj):
        return (obj.prompt[:80] + "…") if len(obj.prompt) > 80 else obj.prompt


class SubscriptionPlanMonthInline(admin.TabularInline):
    model = SubscriptionPlanMonth
    extra = 1
    fields = ("year", "month")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("plan_label", "included_months", "tranche_months_summary", "amount", "is_active")
    list_filter = ("is_active", "billing_period")
    inlines = [SubscriptionPlanMonthInline]
    fieldsets = (
        (
            None,
            {
                "fields": ("billing_period", "name", "included_months", "amount", "is_active"),
                "description": (
                    "<strong>Mensuel</strong> : 1 mois (mois choisi par le candidat). "
                    "<strong>Annuel</strong> : mois consécutifs à partir du mois de départ "
                    "(réglé sur chaque demande avant validation). "
                    "<strong>Tranche</strong> : nom + montant + liste des mois ci-dessous "
                    "(le candidat sélectionne la tranche ; les mois accordés sont ceux de la liste)."
                ),
            },
        ),
    )

    @admin.display(description="formule", ordering="billing_period")
    def plan_label(self, obj):
        return obj.display_label

    @admin.display(description="mois (tranche)")
    def tranche_months_summary(self, obj):
        if obj.billing_period != SubscriptionPlan.BillingPeriod.TRANCHE:
            return "—"
        return obj.tranche_months_display()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.billing_period == SubscriptionPlan.BillingPeriod.TRANCHE and not obj.plan_months.exists():
            self.message_user(
                request,
                "Ajoutez au moins un mois dans la liste « Mois de la tranche » puis enregistrez à nouveau.",
                level=admin_messages.WARNING,
            )


@admin.register(SubscriptionRequest)
class SubscriptionRequestAdmin(admin.ModelAdmin):
    form = SubscriptionRequestAdminForm
    list_display = (
        "candidate_name",
        "content_month",
        "plan",
        "status",
        "created_at",
        "decided_at",
        "decided_by",
    )
    list_filter = ("status", "plan", "category", "year", "month")
    search_fields = (
        "user__username",
        "user__email",
        "user__last_name",
        "user__first_name",
    )
    readonly_fields = (
        "created_at",
        "decided_at",
        "decided_by",
        "covered_periods_preview",
    )
    fieldsets = (
        (
            "Candidat",
            {
                "fields": (
                    "candidate_last_name",
                    "candidate_first_name",
                    "candidate_email",
                    "user",
                ),
                "description": (
                    "Corrigez le nom et le prénom si besoin, puis enregistrez avant "
                    "d’approuver la demande. Le candidat se connecte avec son nom, "
                    "son prénom et son mot de passe (plusieurs homonymes sont possibles)."
                ),
            },
        ),
        (
            "Demande d’abonnement",
            {
                "fields": (
                    "category",
                    "year",
                    "month",
                    "plan",
                    "covered_periods_preview",
                    "status",
                ),
                "description": (
                    "<strong>Annuel</strong> : mois de départ (année + mois) pour les mois consécutifs. "
                    "<strong>Tranche</strong> : les mois accordés sont ceux définis dans la formule "
                    "(le mois de départ sert de référence pour la demande uniquement). "
                    "Enregistrez puis approuvez."
                ),
            },
        ),
        (
            "Traitement",
            {
                "fields": ("created_at", "decided_at", "decided_by"),
            },
        ),
    )
    actions = ("approve_requests", "reject_requests")

    @admin.display(description="candidat", ordering="user__last_name")
    def candidate_name(self, obj):
        user = obj.user
        return f"{user.last_name} {user.first_name}".strip() or user.username

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return (
                (
                    "Demande d’abonnement",
                    {
                        "fields": (
                            "user",
                            "category",
                            "year",
                            "month",
                            "plan",
                            "status",
                        ),
                    },
                ),
                (
                    "Traitement",
                    {"fields": ("created_at", "decided_at", "decided_by")},
                ),
            )
        return self.fieldsets

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if obj:
            readonly.append("user")
            if obj.status != SubscriptionRequest.Status.PENDING:
                readonly.extend(["category", "year", "month", "plan", "status"])
        return readonly

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "recap-export/",
                self.admin_site.admin_view(self.export_recap_excel_view),
                name="courses_subscriptionrequest_export_recap",
            ),
            path(
                "recap-export/month/<str:month_str>/",
                self.admin_site.admin_view(self.export_recap_month_excel_view),
                name="courses_subscriptionrequest_export_recap_month",
            ),
        ] + urls

    def export_recap_excel_view(self, request):
        content = build_subscription_recap_xlsx()
        filename = subscription_recap_filename()
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def export_recap_month_excel_view(self, request, month_str):
        try:
            parsed = dt_datetime.strptime(month_str, "%Y-%m")
            for_month = (parsed.year, parsed.month)
        except ValueError:
            from django.http import Http404

            raise Http404("Mois invalide.")
        content = build_subscription_recap_xlsx(for_month=for_month)
        filename = subscription_recap_filename(for_month=for_month)
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @admin.display(description="accès", ordering="year")
    def content_month(self, obj):
        return obj.access_label()

    @admin.display(description="période accordée (annuel)")
    def covered_periods_preview(self, obj):
        if not obj.pk or not obj.plan_id:
            return "—"
        return obj.covered_periods_display()

    def save_model(self, request, obj, form, change):
        old_status = None
        if change and obj.pk:
            old_status = (
                SubscriptionRequest.objects.filter(pk=obj.pk)
                .values_list("status", flat=True)
                .first()
            )
        super().save_model(request, obj, form, change)
        if (
            obj.status == SubscriptionRequest.Status.APPROVED
            and old_status == SubscriptionRequest.Status.PENDING
        ):
            n_months = extend_subscription_after_approval_from_request(obj)
            self.message_user(
                request,
                f"Abonnement activé : {n_months} mois à partir de "
                f"{french_month_name(obj.month)} {obj.year} "
                f"({obj.covered_periods_display()}).",
                level=admin_messages.SUCCESS,
            )

    @admin.action(description="Approuver les demandes sélectionnées (activer l’abonnement)")
    def approve_requests(self, request, queryset):
        pending = queryset.filter(status=SubscriptionRequest.Status.PENDING)
        count = 0
        for req in pending.select_related("plan", "category", "user"):
            req.refresh_from_db()
            req.status = SubscriptionRequest.Status.APPROVED
            req.decided_at = timezone.now()
            req.decided_by = request.user
            req.save(update_fields=["status", "decided_at", "decided_by"])
            extend_subscription_after_approval_from_request(req)
            count += 1
        self.message_user(
            request,
            f"{count} demande(s) approuvée(s). Le mois de départ enregistré sur chaque "
            f"demande détermine les mois inclus (formule annuelle).",
            level=admin_messages.SUCCESS,
        )

    @admin.action(description="Refuser les demandes sélectionnées")
    def reject_requests(self, request, queryset):
        updated = queryset.filter(status=SubscriptionRequest.Status.PENDING).update(
            status=SubscriptionRequest.Status.REJECTED,
            decided_at=timezone.now(),
            decided_by=request.user,
        )
        self.message_user(request, f"{updated} demande(s) refusée(s).", level=admin_messages.WARNING)


@admin.register(UserSubscription)
class UserSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "content_month", "plan", "granted_at")
    list_filter = ("category", "year", "month", "plan")
    search_fields = ("user__username",)
    fields = ("user", "category", "year", "month", "plan", "granted_at")
    readonly_fields = ("granted_at",)

    @admin.display(description="accès", ordering="year")
    def content_month(self, obj):
        return obj.access_label()


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "instructor", "category", "published", "created_at")
    list_filter = ("published", "category")
    search_fields = ("title", "short_description")
    inlines = [LessonInline]


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("user", "course", "enrolled_at")
    list_filter = ("enrolled_at",)


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "completed_at")
