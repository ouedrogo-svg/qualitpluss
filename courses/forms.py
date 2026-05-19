from django import forms
from django.db.models import Count, Q
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import (
    Category,
    Course,
    Lesson,
    MONTH_CHOICES,
    SubscriptionPlan,
    SubscriptionRequest,
    available_content_months,
    consecutive_content_months,
    content_month_period_label,
    subscription_access_label,
    user_has_month_access,
)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = [
            "title",
            "short_description",
            "description",
            "category",
            "cover",
            "published",
        ]
        widgets = {
            "short_description": forms.TextInput(attrs={"class": "form-control"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "category": forms.Select(attrs={"class": "form-control"}),
            "cover": forms.FileInput(attrs={"class": "form-control"}),
            "published": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ["title", "order", "content"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "content": forms.Textarea(attrs={"class": "form-control", "rows": 12}),
        }


class SubscriptionRequestForm(forms.ModelForm):
    content_choice = forms.ChoiceField(
        label="Catégorie et mois de départ",
        widget=forms.RadioSelect(),
        help_text="Catégorie ciblée et premier mois de la période. Pour une formule annuelle, "
        "les mois suivants sont inclus selon le nombre défini par l’administrateur.",
    )

    class Meta:
        model = SubscriptionRequest
        fields = ["plan"]
        widgets = {
            "plan": forms.RadioSelect(),
        }

    def __init__(self, *args, user=None, initial_category=None, initial_period=None, **kwargs):
        self.user = user
        self.initial_category = initial_category
        self.initial_period = initial_period
        self.plan_only = bool(initial_category and initial_period)
        super().__init__(*args, **kwargs)
        if self.plan_only:
            del self.fields["content_choice"]
        else:
            self.fields["content_choice"].choices = self._build_content_choices()
            if initial_category and initial_period and not self.is_bound:
                key = self._choice_key(
                    initial_category.pk, initial_period[0], initial_period[1]
                )
                if any(c[0] == key for c in self.fields["content_choice"].choices):
                    self.fields["content_choice"].initial = key
        self.fields["plan"].queryset = (
            SubscriptionPlan.objects.filter(is_active=True)
            .annotate(_n_tranche_months=Count("plan_months"))
            .filter(
                Q(billing_period__in=["monthly", "yearly"])
                | Q(billing_period="tranche", _n_tranche_months__gt=0)
            )
            .prefetch_related("plan_months")
            .order_by("billing_period", "name", "pk")
        )
        self.fields["plan"].label = "Formule d’abonnement"
        self.fields["plan"].empty_label = None

    def _choice_key(self, category_id: int, year: int, month: int) -> str:
        return f"{category_id}:{year}-{month}"

    def _build_content_choices(self) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = []
        categories = Category.objects.order_by("name")
        if self.initial_category:
            categories = categories.filter(pk=self.initial_category.pk)
        for cat in categories:
            for year, month in available_content_months(cat):
                label = f"{cat.name} — {content_month_period_label(year, month)}"
                choices.append((self._choice_key(cat.pk, year, month), label))
        return choices

    def clean_content_choice(self):
        raw = self.cleaned_data.get("content_choice")
        if not raw:
            raise forms.ValidationError("Choisissez une catégorie et un mois.")
        try:
            cat_s, period_s = raw.split(":", 1)
            year_s, month_s = period_s.split("-", 1)
            category_id, year, month = int(cat_s), int(year_s), int(month_s)
        except (ValueError, TypeError):
            raise forms.ValidationError("Choix invalide.") from None
        if month < 1 or month > 12:
            raise forms.ValidationError("Mois invalide.")
        category = Category.objects.filter(pk=category_id).first()
        if not category:
            raise forms.ValidationError("Catégorie introuvable.")
        self.cleaned_data["category"] = category
        self.cleaned_data["year"] = year
        self.cleaned_data["month"] = month
        return raw

    def clean(self):
        cleaned = super().clean()
        if self.plan_only:
            cleaned["category"] = self.initial_category
            cleaned["year"] = self.initial_period[0]
            cleaned["month"] = self.initial_period[1]
        category = cleaned.get("category")
        year = cleaned.get("year")
        month = cleaned.get("month")
        plan = cleaned.get("plan")
        if not self.user or not category or year is None or month is None or not plan:
            return cleaned
        label = subscription_access_label(category, year, month, plan)
        periods = plan.get_covered_periods(year, month)
        if not periods:
            raise forms.ValidationError(
                "Cette formule ne comporte aucun mois d’accès. Contactez l’administrateur."
            )
        if all(user_has_month_access(self.user, category, y, m) for y, m in periods):
            raise forms.ValidationError(f"Vous avez déjà accès à toute la période : {label}.")
        pending_qs = SubscriptionRequest.objects.filter(
            user=self.user,
            category=category,
            plan=plan,
            status=SubscriptionRequest.Status.PENDING,
        )
        if plan.billing_period != SubscriptionPlan.BillingPeriod.TRANCHE:
            pending_qs = pending_qs.filter(year=year, month=month)
        if pending_qs.exists():
            raise forms.ValidationError(
                f"Vous avez déjà une demande en attente pour {label}. "
                "Veuillez attendre la validation par l’administrateur."
            )
        self.instance.user = self.user
        self.instance.category = category
        self.instance.year = year
        self.instance.month = month
        self.instance.plan = plan
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.user = self.user
        obj.category = self.cleaned_data["category"]
        obj.year = self.cleaned_data["year"]
        obj.month = self.cleaned_data["month"]
        if commit:
            obj.save()
        return obj


class SubscriptionRequestAdminForm(forms.ModelForm):
    """Permet à l’administrateur de corriger le candidat avant validation."""

    candidate_last_name = forms.CharField(label="Nom", max_length=150)
    candidate_first_name = forms.CharField(label="Prénom", max_length=150)
    candidate_email = forms.EmailField(
        label="E-mail",
        required=False,
        help_text="Facultatif.",
    )

    class Meta:
        model = SubscriptionRequest
        fields = (
            "user",
            "category",
            "year",
            "month",
            "plan",
            "status",
        )

    def __init__(self, *args, formateur_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if formateur_user and formateur_user.is_authenticated and "category" in self.fields:
            from .formateur_permissions import formateur_category_queryset

            self.fields["category"].queryset = formateur_category_queryset(
                formateur_user
            ).order_by("name")
        if not self.instance.pk:
            for field_name in (
                "candidate_last_name",
                "candidate_first_name",
                "candidate_email",
            ):
                del self.fields[field_name]
            return

        if self.instance.user_id:
            user = self.instance.user
            self.fields["candidate_last_name"].initial = user.last_name
            self.fields["candidate_first_name"].initial = user.first_name
            self.fields["candidate_email"].initial = user.email or ""

        if "user" in self.fields:
            self.fields["user"].disabled = True

        if "year" in self.fields:
            self.fields["year"].label = "Année de départ"
            self.fields["year"].help_text = (
                "Premier mois de contenu accordé (formule annuelle : point de départ du pack)."
            )
        if "month" in self.fields:
            self.fields["month"].label = "Mois de départ"
            self.fields["month"].widget = forms.Select(choices=MONTH_CHOICES)
            self.fields["month"].help_text = (
                "Les mois inclus de la formule annuelle sont accordés à partir de ce mois."
            )
        if "plan" in self.fields:
            self.fields["plan"].help_text = (
                "Mensuel / annuel : mois de départ ci-dessous. Tranche : mois fixes définis dans la formule."
            )

        if self.instance.status != SubscriptionRequest.Status.PENDING:
            for field_name in (
                "candidate_last_name",
                "candidate_first_name",
                "candidate_email",
                "category",
                "year",
                "month",
                "plan",
                "status",
            ):
                if field_name in self.fields:
                    self.fields[field_name].disabled = True

    def clean_candidate_last_name(self):
        nom = self.cleaned_data["candidate_last_name"].strip()
        if not nom:
            raise ValidationError("Le nom est obligatoire.")
        return nom

    def clean_candidate_first_name(self):
        prenom = self.cleaned_data["candidate_first_name"].strip()
        if not prenom:
            raise ValidationError("Le prénom est obligatoire.")
        return prenom

    def clean(self):
        cleaned = super().clean()
        if self.instance.status != SubscriptionRequest.Status.PENDING:
            return cleaned
        year = cleaned.get("year")
        month = cleaned.get("month")
        plan = cleaned.get("plan")
        if year is None or month is None:
            return cleaned
        if month < 1 or month > 12:
            raise ValidationError({"month": "Le mois doit être compris entre 1 et 12."})
        if plan:
            periods = plan.get_covered_periods(year, month)
            if not periods:
                raise ValidationError(
                    "Impossible de calculer la période accordée pour cette formule."
                )
        return cleaned

    def save(self, commit=True):
        request = super().save(commit=False)
        if (
            commit
            and request.user_id
            and request.status == SubscriptionRequest.Status.PENDING
            and "candidate_last_name" in self.cleaned_data
        ):
            user = request.user
            user.last_name = self.cleaned_data["candidate_last_name"]
            user.first_name = self.cleaned_data["candidate_first_name"]
            user.email = (self.cleaned_data.get("candidate_email") or "").strip()
            user.save(update_fields=["last_name", "first_name", "email"])
        if commit:
            request.save()
        return request
