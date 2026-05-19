import os
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


class Category(models.Model):
    name = models.CharField("nom", max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)

    class Meta:
        verbose_name = "catégorie"
        verbose_name_plural = "catégories"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)


def french_month_name(month: int) -> str:
    names = {
        1: "Janvier",
        2: "Février",
        3: "Mars",
        4: "Avril",
        5: "Mai",
        6: "Juin",
        7: "Juillet",
        8: "Août",
        9: "Septembre",
        10: "Octobre",
        11: "Novembre",
        12: "Décembre",
    }
    return names.get(month, str(month))


MONTH_CHOICES = [(i, french_month_name(i)) for i in range(1, 13)]


def monthly_pdf_upload_to(instance, filename):
    _, ext = os.path.splitext(filename)
    ext = (ext or ".pdf").lower()
    if ext != ".pdf":
        ext = ".pdf"
    return f"cours_mois/{instance.year}/{instance.month:02d}/{uuid.uuid4().hex}{ext}"


class MonthlyCourseContent(models.Model):
    """SUJET du mois pour une catégorie : un fichier PDF géré par l’administrateur."""

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="monthly_contents",
        verbose_name="catégorie",
    )
    year = models.PositiveIntegerField("année")
    month = models.PositiveIntegerField("mois", choices=MONTH_CHOICES)
    pdf = models.FileField(
        "fichier PDF",
        upload_to=monthly_pdf_upload_to,
        validators=[FileExtensionValidator(["pdf"])],
    )
    title = models.CharField("titre affiché", max_length=200, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "contenu mensuel (PDF)"
        verbose_name_plural = "contenus mensuels (PDF)"
        ordering = ["-year", "-month", "category__name", "id"]

    def __str__(self):
        period = f"{french_month_name(self.month)} {self.year}"
        if self.title:
            return f"{self.category} — {period} — {self.title}"
        if self.pk:
            return f"{self.category} — {period} (#{self.pk})"
        return f"{self.category} — {period}"

    def period_label(self) -> str:
        return f"{french_month_name(self.month)} {self.year}"

    @property
    def year_month_key(self) -> str:
        return f"{self.year}-{self.month}"

    def clean(self):
        if self.month < 1 or self.month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})

    def get_absolute_url(self):
        return reverse(
            "courses:monthly_content",
            kwargs={
                "category_slug": self.category.slug,
                "year": self.year,
                "month": self.month,
                "pk": self.pk,
            },
        )


def correction_pdf_upload_to(instance, filename):
    _, ext = os.path.splitext(filename)
    ext = (ext or ".pdf").lower()
    if ext != ".pdf":
        ext = ".pdf"
    return f"corrections/{instance.year}/{instance.month:02d}/{uuid.uuid4().hex}{ext}"


class MonthlyCorrection(models.Model):
    """Corrigé type PDF par catégorie et par mois (plusieurs fichiers possibles par période)."""

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="monthly_corrections",
        verbose_name="catégorie",
    )
    year = models.PositiveIntegerField("année")
    month = models.PositiveIntegerField("mois", choices=MONTH_CHOICES)
    pdf = models.FileField(
        "fichier PDF (correction)",
        upload_to=correction_pdf_upload_to,
        validators=[FileExtensionValidator(["pdf"])],
    )
    title = models.CharField("titre affiché", max_length=200, blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "correction mensuelle (PDF)"
        verbose_name_plural = "corrections mensuelles (PDF)"
        ordering = ["-year", "-month", "category__name", "id"]

    def __str__(self):
        period = f"{french_month_name(self.month)} {self.year}"
        if self.title:
            return f"[Corrigé] {self.category} — {period} — {self.title}"
        if self.pk:
            return f"[Corrigé] {self.category} — {period} (#{self.pk})"
        return f"[Corrigé] {self.category} — {period}"

    def period_label(self) -> str:
        return f"{french_month_name(self.month)} {self.year}"

    @property
    def year_month_key(self) -> str:
        return f"{self.year}-{self.month}"

    def clean(self):
        if self.month < 1 or self.month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})

    def get_absolute_url(self):
        return reverse(
            "courses:correction_detail",
            kwargs={
                "category_slug": self.category.slug,
                "year": self.year,
                "month": self.month,
                "pk": self.pk,
            },
        )


def exam_pdf_upload_to(instance, filename):
    _, ext = os.path.splitext(filename)
    ext = (ext or ".pdf").lower()
    if ext != ".pdf":
        ext = ".pdf"
    return f"examens/{instance.year}/{instance.month:02d}/{uuid.uuid4().hex}{ext}"


class MonthlyExam(models.Model):
    """Examen mensuel par catégorie : PDF + quiz interactif (même logique que les corrections)."""

    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="monthly_exams",
        verbose_name="catégorie",
    )
    year = models.PositiveIntegerField("année")
    month = models.PositiveIntegerField("mois", choices=MONTH_CHOICES)
    pdf = models.FileField(
        "fichier PDF (examen)",
        upload_to=exam_pdf_upload_to,
        validators=[FileExtensionValidator(["pdf"])],
    )
    title = models.CharField("titre affiché", max_length=200, blank=True)
    duration_minutes = models.PositiveIntegerField(
        "durée de l’examen (minutes)",
        default=60,
        help_text="Temps imparti au candidat pour valider le quiz une fois l’épreuve commencée.",
    )
    results_collection_days = models.PositiveIntegerField(
        "collecte des résultats (jours)",
        default=7,
        help_text="Nombre de jours après la création de l’examen pendant lesquels la première "
        "composition de chaque candidat est enregistrée pour l’administrateur.",
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "examen mensuel (PDF)"
        verbose_name_plural = "examens mensuels (PDF)"
        ordering = ["-year", "-month", "category__name", "id"]

    def __str__(self):
        period = f"{french_month_name(self.month)} {self.year}"
        if self.title:
            return f"[Examen] {self.category} — {period} — {self.title}"
        if self.pk:
            return f"[Examen] {self.category} — {period} (#{self.pk})"
        return f"[Examen] {self.category} — {period}"

    def period_label(self) -> str:
        return f"{french_month_name(self.month)} {self.year}"

    @property
    def year_month_key(self) -> str:
        return f"{self.year}-{self.month}"

    def clean(self):
        if self.month < 1 or self.month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})

    def get_absolute_url(self):
        return reverse(
            "courses:exam_detail",
            kwargs={
                "category_slug": self.category.slug,
                "year": self.year,
                "month": self.month,
                "pk": self.pk,
            },
        )

    def results_collection_deadline(self):
        return self.created_at + timedelta(days=self.results_collection_days)

    def is_within_results_collection_period(self, at=None):
        at = at or timezone.now()
        return at <= self.results_collection_deadline()


class ExamQuizAttempt(models.Model):
    """Résultat d’un candidat à un quiz d’examen (meilleure note utilisée pour le classement)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="exam_quiz_attempts",
        verbose_name="candidat",
    )
    exam = models.ForeignKey(
        MonthlyExam,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
        verbose_name="examen",
    )
    score_points = models.PositiveSmallIntegerField("note (points)")
    score_percent = models.DecimalField(
        "note (%)",
        max_digits=5,
        decimal_places=1,
        blank=True,
        null=True,
    )
    submitted_at = models.DateTimeField("soumis le", auto_now_add=True)
    sent_to_admin = models.BooleanField(
        "transmis à l’administrateur",
        default=False,
        help_text="Vrai uniquement pour la première composition enregistrée dans le délai de collecte.",
    )

    class Meta:
        verbose_name = "résultat d’examen"
        verbose_name_plural = "résultats d’examens"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["exam", "-score_points"]),
            models.Index(fields=["exam", "user"]),
        ]

    def __str__(self):
        return f"{self.user} — {self.exam} — {self.score_points} pt"


def validate_quiz_import_csv_file(value):
    """CSV uniquement ; message explicite si un PDF est déposé par erreur à la place du corrigé."""
    if not value or not getattr(value, "name", None):
        return
    ext = os.path.splitext(value.name)[1].lower()
    if ext == ".pdf":
        raise ValidationError(
            "Vous avez choisi un fichier PDF : mettez-le dans le champ « fichier PDF (correction) » "
            "en haut de cette page (correction mensuelle), pas ici. Ce champ sert uniquement à un "
            "fichier .csv en secours si le PDF ne contient pas de tableau détectable.",
            code="quiz_import_pdf_wrong_field",
        )
    if ext != ".csv":
        raise ValidationError(
            "Ce champ accepte uniquement un fichier .csv (export tableur).",
            code="quiz_import_extension",
        )


class CorrectionQuiz(models.Model):
    """Quiz lié au PDF du corrigé : tableaux extraits automatiquement ; CSV optionnel."""

    correction = models.OneToOneField(
        MonthlyCorrection,
        on_delete=models.CASCADE,
        related_name="quiz",
        verbose_name="correction",
    )
    title = models.CharField("titre du quiz", max_length=200, blank=True)
    quiz_last_built_for_pdf_key = models.CharField(
        "clé du dernier PDF utilisé pour le quiz",
        max_length=500,
        blank=True,
        editable=False,
        help_text="Technique : évite de relire le PDF à chaque enregistrement. Une action admin permet de forcer une nouvelle lecture.",
    )
    import_csv = models.FileField(
        "import CSV (secours)",
        upload_to="quiz_imports/",
        blank=True,
        null=True,
        validators=[validate_quiz_import_csv_file],
        help_text=(
            "Optionnel si le PDF ne contient pas de tableau détectable. Même structure : "
            "colonnes propositions + colonne « réponses » (indices 1,2,3… ou A,B… ; plusieurs : 1,3)."
        ),
    )

    class Meta:
        verbose_name = "quiz de correction"
        verbose_name_plural = "quiz de correction"

    def __str__(self):
        return self.title or f"Quiz — {self.correction}"

    def save(self, *args, **kwargs):
        prev_csv_name = None
        if self.pk:
            row = CorrectionQuiz.objects.filter(pk=self.pk).only("import_csv").first()
            if row and row.import_csv:
                prev_csv_name = row.import_csv.name

        super().save(*args, **kwargs)

        cur_csv = self.import_csv.name if self.import_csv else None
        if cur_csv and cur_csv != prev_csv_name:
            from .quiz_import import import_quiz_from_csv

            with self.import_csv.open("rb") as fh:
                import_quiz_from_csv(self, fh)
            self.import_csv.delete(save=False)
            pdf_key = ""
            if self.correction_id and self.correction.pdf:
                pdf_key = self.correction.pdf.name
            CorrectionQuiz.objects.filter(pk=self.pk).update(
                import_csv=None,
                quiz_last_built_for_pdf_key=pdf_key,
            )
            return

        # La construction du quiz depuis le PDF est faite après sauvegarde complète
        # dans l’admin (save_related) ou via l’action « Reconstruire le quiz… ».


def validate_exam_quiz_import_csv_file(value):
    """CSV uniquement ; message explicite si un PDF est déposé par erreur à la place de l’examen."""
    if not value or not getattr(value, "name", None):
        return
    ext = os.path.splitext(value.name)[1].lower()
    if ext == ".pdf":
        raise ValidationError(
            "Vous avez choisi un fichier PDF : mettez-le dans le champ « fichier PDF (examen) » "
            "en haut de cette page (examen mensuel), pas ici. Ce champ sert uniquement à un "
            "fichier .csv en secours si le PDF ne contient pas de tableau détectable.",
            code="quiz_import_pdf_wrong_field",
        )
    if ext != ".csv":
        raise ValidationError(
            "Ce champ accepte uniquement un fichier .csv (export tableur).",
            code="quiz_import_extension",
        )


class ExamQuiz(models.Model):
    """Quiz lié au PDF de l’examen : tableaux extraits automatiquement ; CSV optionnel."""

    exam = models.OneToOneField(
        MonthlyExam,
        on_delete=models.CASCADE,
        related_name="quiz",
        verbose_name="examen",
    )
    title = models.CharField("titre du quiz", max_length=200, blank=True)
    quiz_last_built_for_pdf_key = models.CharField(
        "clé du dernier PDF utilisé pour le quiz",
        max_length=500,
        blank=True,
        editable=False,
        help_text="Technique : évite de relire le PDF à chaque enregistrement.",
    )
    import_csv = models.FileField(
        "import CSV (secours)",
        upload_to="quiz_imports/exams/",
        blank=True,
        null=True,
        validators=[validate_exam_quiz_import_csv_file],
        help_text=(
            "Optionnel si le PDF ne contient pas de tableau détectable. Même structure : "
            "colonnes propositions + colonne « réponses » (A, B, AB, etc.)."
        ),
    )

    class Meta:
        verbose_name = "quiz d’examen"
        verbose_name_plural = "quiz d’examen"

    def __str__(self):
        return self.title or f"Quiz — {self.exam}"

    def save(self, *args, **kwargs):
        prev_csv_name = None
        if self.pk:
            row = ExamQuiz.objects.filter(pk=self.pk).only("import_csv").first()
            if row and row.import_csv:
                prev_csv_name = row.import_csv.name

        super().save(*args, **kwargs)

        cur_csv = self.import_csv.name if self.import_csv else None
        if cur_csv and cur_csv != prev_csv_name:
            from .quiz_import import import_quiz_from_csv

            with self.import_csv.open("rb") as fh:
                import_quiz_from_csv(
                    self,
                    fh,
                    question_model=ExamQuizQuestion,
                    option_model=ExamQuizOption,
                    quiz_fk_field="exam_quiz",
                )
            self.import_csv.delete(save=False)
            pdf_key = ""
            if self.exam_id and self.exam.pdf:
                pdf_key = self.exam.pdf.name
            ExamQuiz.objects.filter(pk=self.pk).update(
                import_csv=None,
                quiz_last_built_for_pdf_key=pdf_key,
            )


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(
        CorrectionQuiz,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="quiz",
    )
    order = models.PositiveIntegerField("ordre", default=0)
    prompt = models.TextField("énoncé")

    class Meta:
        verbose_name = "question"
        verbose_name_plural = "questions"
        ordering = ["quiz", "order", "id"]

    def __str__(self):
        return f"Q{self.order + 1} — {self.prompt[:60]}"


class QuizOption(models.Model):
    question = models.ForeignKey(
        QuizQuestion,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="question",
    )
    order = models.PositiveIntegerField("ordre", default=0)
    text = models.CharField("texte", max_length=500)
    is_correct = models.BooleanField("bonne réponse", default=False)

    class Meta:
        verbose_name = "proposition"
        verbose_name_plural = "propositions"
        ordering = ["question", "order", "id"]

    def __str__(self):
        mark = "✓" if self.is_correct else ""
        return f"{mark} {self.text[:40]}"


class ExamQuizQuestion(models.Model):
    exam_quiz = models.ForeignKey(
        ExamQuiz,
        on_delete=models.CASCADE,
        related_name="questions",
        verbose_name="quiz",
    )
    order = models.PositiveIntegerField("ordre", default=0)
    prompt = models.TextField("énoncé")

    class Meta:
        verbose_name = "question (examen)"
        verbose_name_plural = "questions (examen)"
        ordering = ["exam_quiz", "order", "id"]

    def __str__(self):
        return f"Q{self.order + 1} — {self.prompt[:60]}"


class ExamQuizOption(models.Model):
    question = models.ForeignKey(
        ExamQuizQuestion,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="question",
    )
    order = models.PositiveIntegerField("ordre", default=0)
    text = models.CharField("texte", max_length=500)
    is_correct = models.BooleanField("bonne réponse", default=False)

    class Meta:
        verbose_name = "proposition (examen)"
        verbose_name_plural = "propositions (examen)"
        ordering = ["question", "order", "id"]

    def __str__(self):
        mark = "✓" if self.is_correct else ""
        return f"{mark} {self.text[:40]}"


class SubscriptionPlan(models.Model):
    class BillingPeriod(models.TextChoices):
        MONTHLY = "monthly", "Mensuel"
        YEARLY = "yearly", "Annuel"
        TRANCHE = "tranche", "Tranche"

    billing_period = models.CharField(
        "période",
        max_length=20,
        choices=BillingPeriod.choices,
    )
    name = models.CharField(
        "nom de la tranche",
        max_length=120,
        blank=True,
        help_text="Obligatoire pour une tranche (ex. « Pack 6 mois »). Ignoré pour mensuel / annuel.",
    )
    amount = models.DecimalField("montant (FCFA ou devise locale)", max_digits=12, decimal_places=2)
    included_months = models.PositiveSmallIntegerField(
        "nombre de mois inclus",
        default=1,
        help_text="Mensuel : laisser 1. Annuel : nombre de mois d’accès consécutifs "
        "(ex. 6, 7, 12) à partir du mois de départ défini sur chaque demande "
        "(modifiable par l’administrateur avant validation).",
    )
    is_active = models.BooleanField("actif", default=True)

    class Meta:
        verbose_name = "option d’abonnement"
        verbose_name_plural = "options d’abonnement"
        ordering = ["billing_period", "name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["billing_period"],
                condition=models.Q(billing_period="monthly"),
                name="unique_monthly_subscription_plan",
            ),
            models.UniqueConstraint(
                fields=["billing_period"],
                condition=models.Q(billing_period="yearly"),
                name="unique_yearly_subscription_plan",
            ),
        ]

    def __str__(self):
        if self.billing_period == self.BillingPeriod.TRANCHE:
            label = self.name or "Tranche"
            n = self.plan_months.count() if self.pk else 0
            if n:
                return f"{label} ({n} mois) — {self.amount}"
            return f"{label} — {self.amount}"
        if self.billing_period == self.BillingPeriod.YEARLY and self.included_months > 1:
            return f"{self.get_billing_period_display()} ({self.included_months} mois) — {self.amount}"
        return f"{self.get_billing_period_display()} — {self.amount}"

    @property
    def display_label(self) -> str:
        if self.billing_period == self.BillingPeriod.TRANCHE:
            return self.name or "Tranche"
        if (
            self.billing_period == self.BillingPeriod.YEARLY
            and self.included_months > 1
        ):
            return f"{self.get_billing_period_display()} ({self.included_months} mois)"
        return self.get_billing_period_display()

    def months_granted(self) -> int:
        if self.billing_period == self.BillingPeriod.MONTHLY:
            return 1
        if self.billing_period == self.BillingPeriod.TRANCHE:
            if self.pk:
                return self.plan_months.count()
            return 0
        return max(1, self.included_months)

    def get_covered_periods(
        self, start_year: int, start_month: int
    ) -> list[tuple[int, int]]:
        if self.billing_period == self.BillingPeriod.TRANCHE:
            return list(
                self.plan_months.order_by("year", "month").values_list("year", "month")
            )
        return consecutive_content_months(start_year, start_month, self.months_granted())

    def tranche_months_display(self) -> str:
        periods = (
            list(self.plan_months.order_by("year", "month"))
            if self.pk
            else []
        )
        if not periods:
            return "—"
        return ", ".join(
            content_month_period_label(pm.year, pm.month) for pm in periods
        )

    def clean(self):
        if self.billing_period == self.BillingPeriod.MONTHLY:
            self.included_months = 1
            self.name = ""
        elif self.billing_period == self.BillingPeriod.YEARLY:
            if self.included_months < 1:
                raise ValidationError(
                    {"included_months": "Indiquez au moins 1 mois pour la formule annuelle."}
                )
            self.name = ""
        elif self.billing_period == self.BillingPeriod.TRANCHE:
            self.included_months = 0
            if not (self.name or "").strip():
                raise ValidationError(
                    {"name": "Indiquez un nom pour cette tranche (ex. « Pack printemps »)."}
                )
        qs = SubscriptionPlan.objects.filter(billing_period=self.billing_period)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if self.billing_period in (
            self.BillingPeriod.MONTHLY,
            self.BillingPeriod.YEARLY,
        ) and qs.exists():
            raise ValidationError(
                {
                    "billing_period": (
                        f"Une formule « {self.get_billing_period_display()} » existe déjà."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if self.billing_period == self.BillingPeriod.MONTHLY:
            self.included_months = 1
            self.name = ""
        elif self.billing_period == self.BillingPeriod.TRANCHE:
            self.included_months = 0
        super().save(*args, **kwargs)


class SubscriptionPlanMonth(models.Model):
    """Mois de contenu inclus dans une tranche d’abonnement."""

    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.CASCADE,
        related_name="plan_months",
        verbose_name="formule",
        limit_choices_to={"billing_period": SubscriptionPlan.BillingPeriod.TRANCHE},
    )
    year = models.PositiveIntegerField("année")
    month = models.PositiveIntegerField("mois", choices=MONTH_CHOICES)

    class Meta:
        verbose_name = "mois de la tranche"
        verbose_name_plural = "mois de la tranche"
        ordering = ["year", "month"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "year", "month"],
                name="unique_plan_month_in_tranche",
            )
        ]

    def __str__(self):
        return content_month_period_label(self.year, self.month)

    def clean(self):
        if self.month < 1 or self.month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})


class SubscriptionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "En attente de validation"
        APPROVED = "approved", "Approuvée"
        REJECTED = "rejected", "Refusée"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscription_requests",
        verbose_name="candidat",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="subscription_requests",
        verbose_name="catégorie",
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT,
        related_name="requests",
        verbose_name="formule",
    )
    year = models.PositiveIntegerField(
        "année du contenu",
        help_text="Mois de publication auquel la demande donne accès après validation.",
    )
    month = models.PositiveIntegerField("mois du contenu", choices=MONTH_CHOICES)
    status = models.CharField(
        "statut",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField("demandé le", auto_now_add=True)
    decided_at = models.DateTimeField("traité le", null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_requests_reviewed",
        verbose_name="décideur",
    )

    class Meta:
        verbose_name = "demande d’abonnement"
        verbose_name_plural = "demandes d’abonnement"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.access_label()} — {self.plan} ({self.get_status_display()})"

    def access_label(self) -> str:
        return subscription_access_label(
            self.category, self.year, self.month, self.plan
        )

    def period_label(self) -> str:
        return self.access_label()

    def covered_periods(self) -> list[tuple[int, int]]:
        """Mois de contenu accordés (consécutifs ou liste fixe pour une tranche)."""
        if not self.plan_id:
            return consecutive_content_months(self.year, self.month, 1)
        return self.plan.get_covered_periods(self.year, self.month)

    def covered_periods_display(self) -> str:
        periods = self.covered_periods()
        if not periods:
            return "—"
        if self.plan_id and self.plan.billing_period == SubscriptionPlan.BillingPeriod.TRANCHE:
            return ", ".join(content_month_period_label(y, m) for y, m in periods)
        if len(periods) == 1:
            y, m = periods[0]
            return content_month_period_label(y, m)
        y0, m0 = periods[0]
        y1, m1 = periods[-1]
        return (
            f"{content_month_period_label(y0, m0)} → "
            f"{content_month_period_label(y1, m1)} ({len(periods)} mois)"
        )

    def clean(self):
        if self.month is None or self.year is None:
            return
        if self.month < 1 or self.month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})


class UserSubscription(models.Model):
    """Droit d’accès au contenu d’une catégorie pour un mois donné."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="month_subscriptions",
        verbose_name="utilisateur",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="month_subscriptions",
        verbose_name="catégorie",
    )
    year = models.PositiveIntegerField("année du contenu")
    month = models.PositiveIntegerField("mois du contenu", choices=MONTH_CHOICES)
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_grants",
        verbose_name="formule",
    )
    granted_at = models.DateTimeField("accordé le", auto_now_add=True)

    class Meta:
        verbose_name = "abonnement mensuel"
        verbose_name_plural = "abonnements mensuels"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category", "year", "month"],
                name="unique_user_category_month_subscription",
            )
        ]
        ordering = ["-year", "-month", "category__name", "user__username"]

    def __str__(self):
        return f"{self.user} — {self.access_label()}"

    def access_label(self) -> str:
        return f"{self.category} — {french_month_name(self.month)} {self.year}"

    def period_label(self) -> str:
        return self.access_label()


def content_month_period_label(year: int, month: int) -> str:
    return f"{french_month_name(month)} {year}"


def consecutive_content_months(
    start_year: int, start_month: int, count: int
) -> list[tuple[int, int]]:
    """Mois de contenu consécutifs à partir de (start_year, start_month), inclus."""
    if count < 1:
        return []
    periods: list[tuple[int, int]] = []
    year, month = start_year, start_month
    for _ in range(count):
        periods.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def subscription_access_label(
    category: Category,
    year: int,
    month: int,
    plan: SubscriptionPlan | None,
) -> str:
    if not plan:
        start = content_month_period_label(year, month)
        return f"{category} — {start}"
    periods = plan.get_covered_periods(year, month)
    if not periods:
        return f"{category} — {content_month_period_label(year, month)}"
    if plan.billing_period == SubscriptionPlan.BillingPeriod.TRANCHE:
        months_txt = ", ".join(content_month_period_label(y, m) for y, m in periods)
        return f"{category} — {months_txt} ({plan.display_label})"
    if len(periods) == 1:
        return f"{category} — {content_month_period_label(*periods[0])}"
    y0, m0 = periods[0]
    y1, m1 = periods[-1]
    return (
        f"{category} — {content_month_period_label(y0, m0)} → "
        f"{content_month_period_label(y1, m1)} ({len(periods)} mois)"
    )


def available_content_months(category: Category) -> list[tuple[int, int]]:
    """Périodes (année, mois) pour lesquelles du contenu existe dans cette catégorie."""
    keys: set[tuple[int, int]] = set()
    for model in (MonthlyCourseContent, MonthlyCorrection, MonthlyExam):
        keys.update(
            model.objects.filter(category=category)
            .values_list("year", "month")
            .distinct()
        )
    if not keys:
        today = timezone.localdate()
        keys.add((today.year, today.month))
    return sorted(keys, reverse=True)


def _resolve_category_id(category) -> int:
    if isinstance(category, Category):
        return category.pk
    if isinstance(category, int):
        return category
    return Category.objects.values_list("pk", flat=True).get(slug=category)


def user_has_month_access(user, category, year: int, month: int) -> bool:
    if not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False):
        return True
    category_id = _resolve_category_id(category)
    if hasattr(user, "_prefetched_objects_cache") and "month_subscriptions" in user._prefetched_objects_cache:
        return any(
            s.category_id == category_id and s.year == year and s.month == month
            for s in user.month_subscriptions.all()
        )
    return UserSubscription.objects.filter(
        user=user, category_id=category_id, year=year, month=month
    ).exists()


def user_has_active_subscription(user) -> bool:
    """Vrai si le candidat a au moins un mois de contenu débloqué."""
    if not user.is_authenticated:
        return False
    if getattr(user, "is_staff", False):
        return True
    if hasattr(user, "_prefetched_objects_cache") and "month_subscriptions" in user._prefetched_objects_cache:
        return bool(user.month_subscriptions.all())
    return UserSubscription.objects.filter(user=user).exists()


def get_user_subscribed_months(user) -> list[dict]:
    if not user.is_authenticated:
        return []
    if hasattr(user, "_prefetched_objects_cache") and "month_subscriptions" in user._prefetched_objects_cache:
        qs = user.month_subscriptions.all()
    else:
        qs = UserSubscription.objects.filter(user=user).select_related("category").order_by(
            "-year", "-month", "category__name"
        )
    return [
        {
            "category": sub.category,
            "year": sub.year,
            "month": sub.month,
            "label": sub.access_label(),
            "plan": sub.plan,
            "granted_at": sub.granted_at,
        }
        for sub in qs
    ]


def extend_subscription_after_approval(
    user, plan: SubscriptionPlan, category: Category, year: int, month: int
) -> int:
    """
    Accorde l’accès pour chaque mois couvert par la formule.
    Pour l’annuel : ``included_months`` mois consécutifs à partir de (year, month).
    Retourne le nombre de mois accordés.
    """
    granted = 0
    for y, m in plan.get_covered_periods(year, month):
        sub, created = UserSubscription.objects.get_or_create(
            user=user,
            category=category,
            year=y,
            month=m,
            defaults={"plan": plan},
        )
        if not created and plan:
            sub.plan = plan
            sub.save(update_fields=["plan"])
        granted += 1
    return granted


def extend_subscription_after_approval_from_request(
    request: SubscriptionRequest,
) -> int:
    """Accorde l’accès selon le mois de départ et la formule enregistrés sur la demande."""
    return extend_subscription_after_approval(
        request.user,
        request.plan,
        request.category,
        request.year,
        request.month,
    )


class Course(models.Model):
    title = models.CharField("titre", max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_description = models.CharField("résumé", max_length=300)
    description = models.TextField("description")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
        verbose_name="catégorie",
    )
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses_teaching",
        verbose_name="formateur",
    )
    cover = models.ImageField("image de couverture", upload_to="covers/", blank=True, null=True)
    published = models.BooleanField("publié", default=False)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    updated_at = models.DateTimeField("mis à jour le", auto_now=True)

    class Meta:
        verbose_name = "SUJET"
        verbose_name_plural = "SUJETS"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200]
            self.slug = base
            n = 1
            while Course.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{base}-{n}"
                n += 1
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("courses:course_detail", kwargs={"slug": self.slug})


class Lesson(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons", verbose_name="cours")
    title = models.CharField("titre", max_length=200)
    order = models.PositiveIntegerField("ordre", default=0)
    content = models.TextField("contenu (HTML simple autorisé)")

    class Meta:
        verbose_name = "leçon"
        verbose_name_plural = "leçons"
        ordering = ["course", "order", "id"]

    def __str__(self):
        return f"{self.course.title} — {self.title}"

    def get_absolute_url(self):
        return reverse(
            "courses:lesson_detail",
            kwargs={"course_slug": self.course.slug, "pk": self.pk},
        )


class Enrollment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="utilisateur",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="enrollments",
        verbose_name="cours",
    )
    enrolled_at = models.DateTimeField("inscrit le", auto_now_add=True)

    class Meta:
        verbose_name = "inscription"
        verbose_name_plural = "inscriptions"
        constraints = [
            models.UniqueConstraint(fields=["user", "course"], name="unique_enrollment_user_course"),
        ]

    def __str__(self):
        return f"{self.user} → {self.course}"


class LessonProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
        verbose_name="utilisateur",
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name="progress_records",
        verbose_name="leçon",
    )
    completed_at = models.DateTimeField("terminé le", auto_now_add=True)

    class Meta:
        verbose_name = "progression leçon"
        verbose_name_plural = "progressions leçons"
        constraints = [
            models.UniqueConstraint(fields=["user", "lesson"], name="unique_lesson_progress_user_lesson"),
        ]
