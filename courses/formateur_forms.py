from django import forms

from .formateur_permissions import formateur_category_queryset
from .models import (
    MONTH_CHOICES,
    Category,
    MonthlyCorrection,
    MonthlyCourseContent,
    MonthlyExam,
)


_ctrl = {"class": "form-control"}


def _apply_formateur_category_scope(form, formateur_user, *, assigned_only=False):
    if formateur_user and formateur_user.is_authenticated and "category" in form.fields:
        form.fields["category"].queryset = formateur_category_queryset(
            formateur_user, assigned_only=assigned_only
        ).order_by("name")


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "slug")
        widgets = {
            "name": forms.TextInput(attrs=_ctrl),
            "slug": forms.TextInput(attrs={**_ctrl, "placeholder": "Laisser vide pour générer depuis le nom"}),
        }
        help_texts = {
            "slug": "Optionnel : identifiant dans l’URL (lettres, chiffres, tirets).",
        }


class MonthlyCourseContentForm(forms.ModelForm):
    class Meta:
        model = MonthlyCourseContent
        fields = ("category", "year", "month", "title", "pdf")
        widgets = {
            "category": forms.Select(attrs=_ctrl),
            "year": forms.NumberInput(attrs=_ctrl),
            "month": forms.Select(choices=MONTH_CHOICES, attrs=_ctrl),
            "title": forms.TextInput(attrs=_ctrl),
            "pdf": forms.FileInput(attrs=_ctrl),
        }

    def __init__(self, *args, formateur_user=None, assigned_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_formateur_category_scope(
            self, formateur_user, assigned_only=assigned_only
        )


class MonthlyCorrectionForm(forms.ModelForm):
    class Meta:
        model = MonthlyCorrection
        fields = ("category", "year", "month", "title", "pdf")
        widgets = {
            "category": forms.Select(attrs=_ctrl),
            "year": forms.NumberInput(attrs=_ctrl),
            "month": forms.Select(choices=MONTH_CHOICES, attrs=_ctrl),
            "title": forms.TextInput(attrs=_ctrl),
            "pdf": forms.FileInput(attrs=_ctrl),
        }

    def __init__(self, *args, formateur_user=None, assigned_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_formateur_category_scope(
            self, formateur_user, assigned_only=assigned_only
        )


class MonthlyExamForm(forms.ModelForm):
    class Meta:
        model = MonthlyExam
        fields = (
            "category",
            "year",
            "month",
            "title",
            "pdf",
            "duration_minutes",
            "results_collection_days",
        )
        widgets = {
            "category": forms.Select(attrs=_ctrl),
            "year": forms.NumberInput(attrs=_ctrl),
            "month": forms.Select(choices=MONTH_CHOICES, attrs=_ctrl),
            "title": forms.TextInput(attrs=_ctrl),
            "pdf": forms.FileInput(attrs=_ctrl),
            "duration_minutes": forms.NumberInput(attrs={**_ctrl, "min": 1}),
            "results_collection_days": forms.NumberInput(attrs={**_ctrl, "min": 1}),
        }

    def __init__(self, *args, formateur_user=None, assigned_only=False, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_formateur_category_scope(
            self, formateur_user, assigned_only=assigned_only
        )
