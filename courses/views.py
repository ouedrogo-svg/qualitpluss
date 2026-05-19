import os
import re
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import CourseForm, LessonForm, SubscriptionRequestForm
from .models import (
    Category,
    Course,
    Enrollment,
    Lesson,
    LessonProgress,
    MonthlyCorrection,
    MonthlyCourseContent,
    MonthlyExam,
    SubscriptionPlan,
    SubscriptionRequest,
    content_month_period_label,
    french_month_name,
    subscription_access_label,
    get_user_subscribed_months,
    user_has_active_subscription,
    user_has_month_access,
)

from .quiz_import import QUIZ_QUESTION_NUMBER_MAX, strip_nb_references
from .quiz_queries import fetch_correction_quiz, fetch_exam_quiz, sorted_question_options
from .exam_quiz_timing import (
    ensure_exam_started,
    exam_time_remaining_seconds,
    is_exam_time_expired,
    record_exam_attempt,
    user_has_admin_result,
)
from .quiz_session import load_quiz_questions, process_quiz_post
from .pdf_quiz_import import try_rebuild_quiz_for_correction, try_rebuild_quiz_for_exam

_OPTION_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _strip_legacy_question_prefix(prompt: str) -> str:
    """Retire « Question 12 — » en tête d’énoncé (ancien import) ; le numéro est affiché à part."""
    t = (prompt or "").strip()
    cleaned = re.sub(r"^Question\s+\d{1,3}\s*[—\-–]\s*", "", t, flags=re.IGNORECASE).strip()
    return cleaned or t


def _annotate_quiz_questions_for_template(questions) -> None:
    """Prépare affichage A) B) C) D) et numéro = N° d’ordre du corrigé (cases à cocher pour toutes les questions)."""
    for q in questions:
        q.display_number = min(max(q.order + 1, 1), 60)
        q.prompt = _strip_legacy_question_prefix(strip_nb_references(q.prompt))
        q.options_lettered = []
        for i, o in enumerate(sorted_question_options(q)):
            letter = _OPTION_LETTERS[i] if i < len(_OPTION_LETTERS) else str(i + 1)
            label = strip_nb_references(o.text)
            q.options_lettered.append(
                {
                    "letter": letter,
                    "option": o,
                    "line": f"{letter}) {label}",
                }
            )


def _safe_next_redirect(request, url):
    if (
        url
        and url_has_allowed_host_and_scheme(
            url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return redirect(url)
    return None


def _parse_period_from_path(path: str) -> tuple[int, int] | None:
    match = re.search(r"/categorie/[^/]+/(\d{4})/(\d{1,2})(?:/|$)", path or "")
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if 1 <= month <= 12:
        return year, month
    return None


def _parse_category_slug_from_path(path: str) -> str | None:
    match = re.search(r"/categorie/([^/]+)/", path or "")
    return match.group(1) if match else None


def _subscribe_url_for_period(
    category: Category, year: int, month: int, next_path: str
) -> str:
    params = {
        "category": category.slug,
        "year": year,
        "month": month,
        "next": next_path,
    }
    return f"{reverse('courses:subscribe')}?{urlencode(params)}"


def _user_has_content_access(user, category: Category, year: int, month: int) -> bool:
    """Abonnement candidat ou accès formateur / personnel sur la catégorie."""
    if user_has_month_access(user, category, year, month):
        return True
    from .formateur_permissions import formateur_can_view_category_content

    return formateur_can_view_category_content(user, category)


def _subscription_gate(request, next_path: str, category: Category, year: int, month: int):
    """Redirige vers connexion ou abonnement si le candidat n’a pas accès à ce mois dans cette catégorie."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('accounts:login')}?{urlencode({'next': next_path})}")
    if _user_has_content_access(request.user, category, year, month):
        return None
    label = f"{category.name} — {content_month_period_label(year, month)}"
    messages.warning(
        request,
        f"Un abonnement pour {label} est requis. Choisissez votre formule sur la page suivante.",
    )
    return redirect(_subscribe_url_for_period(category, year, month, next_path))


def _category_month_periods(category: Category) -> list[dict]:
    """Regroupe SUJETS, corrections et examens par période (année, mois)."""
    from collections import defaultdict

    periods: dict[tuple[int, int], dict] = defaultdict(
        lambda: {
            "n_courses": 0,
            "n_corrections": 0,
            "n_exams": 0,
            "has_quiz": False,
        }
    )

    for c in MonthlyCourseContent.objects.filter(category=category).only("year", "month"):
        p = periods[(c.year, c.month)]
        p["year"] = c.year
        p["month"] = c.month
        p["n_courses"] += 1

    corrections = MonthlyCorrection.objects.filter(category=category).annotate(
        nq=Count("quiz__questions", distinct=True)
    )
    for corr in corrections:
        p = periods[(corr.year, corr.month)]
        p["year"] = corr.year
        p["month"] = corr.month
        p["n_corrections"] += 1
        if corr.nq > 0:
            p["has_quiz"] = True

    exams = MonthlyExam.objects.filter(category=category).annotate(
        nq=Count("quiz__questions", distinct=True)
    )
    for exam in exams:
        p = periods[(exam.year, exam.month)]
        p["year"] = exam.year
        p["month"] = exam.month
        p["n_exams"] += 1
        if exam.nq > 0:
            p["has_quiz"] = True

    out: list[dict] = []
    for (year, month), data in sorted(periods.items(), reverse=True):
        out.append(
            {
                "year": year,
                "month": month,
                "period_label": f"{french_month_name(month)} {year}",
                "n_courses": data["n_courses"],
                "n_corrections": data["n_corrections"],
                "n_exams": data["n_exams"],
                "has_quiz": data["has_quiz"],
                "total": data["n_courses"] + data["n_corrections"] + data["n_exams"],
            }
        )
    return out


def _annotate_period_access(periods: list[dict], user, category: Category) -> None:
    for p in periods:
        p["access_granted"] = _user_has_content_access(
            user, category, p["year"], p["month"]
        )


def home(request):
    featured = Course.objects.filter(published=True).select_related("instructor", "category")[:6]
    categories = list(
        Category.objects.annotate(
            n_pdf=Count("monthly_contents", distinct=True),
            n_corrections=Count("monthly_corrections", distinct=True),
            n_exams=Count("monthly_exams", distinct=True),
        ).order_by("name")
    )
    plans = (
        SubscriptionPlan.objects.filter(is_active=True)
        .prefetch_related("plan_months")
        .order_by("billing_period", "name", "pk")
    )
    return render(
        request,
        "courses/home.html",
        {
            "featured_courses": featured,
            "categories": categories,
            "subscription_plans": plans,
        },
    )


def category_months(request, slug):
    category = get_object_or_404(Category, slug=slug)
    periods = _category_month_periods(category)
    _annotate_period_access(periods, request.user, category)
    return render(
        request,
        "courses/category_months.html",
        {
            "category": category,
            "periods": periods,
        },
    )


def category_month_detail(request, slug, year, month):
    category = get_object_or_404(Category, slug=slug)
    if month < 1 or month > 12:
        raise Http404()
    hub_url = reverse(
        "courses:category_month_detail",
        kwargs={"slug": slug, "year": year, "month": month},
    )
    gate = _subscription_gate(request, hub_url, category, year, month)
    if gate:
        return gate

    period_label = f"{french_month_name(month)} {year}"
    courses = MonthlyCourseContent.objects.filter(
        category=category, year=year, month=month
    ).order_by("title", "id")
    corrections = (
        MonthlyCorrection.objects.filter(category=category, year=year, month=month)
        .annotate(n_quiz_questions=Count("quiz__questions", distinct=True))
        .order_by("title", "id")
    )
    exams = (
        MonthlyExam.objects.filter(category=category, year=year, month=month)
        .annotate(n_quiz_questions=Count("quiz__questions", distinct=True))
        .order_by("title", "id")
    )
    if not courses.exists() and not corrections.exists() and not exams.exists():
        raise Http404()

    return render(
        request,
        "courses/category_month_detail.html",
        {
            "category": category,
            "year": year,
            "month": month,
            "period_label": period_label,
            "courses": courses,
            "corrections": corrections,
            "exams": exams,
        },
    )


def category_exams(request, slug):
    return redirect("courses:category_months", slug=slug)


def category_corrections(request, slug):
    return redirect("courses:category_months", slug=slug)


def _get_monthly_exam(request, category_slug, year, month, pk):
    exam = get_object_or_404(
        MonthlyExam.objects.select_related("category"),
        pk=pk,
        category__slug=category_slug,
        year=year,
        month=month,
    )
    return exam.category, exam


def exam_detail(request, category_slug, year, month, pk):
    category, exam = _get_monthly_exam(request, category_slug, year, month, pk)
    gate = _subscription_gate(request, request.get_full_path(), category, year, month)
    if gate:
        return gate
    quiz = fetch_exam_quiz(exam)
    n_questions = quiz.n_questions if quiz else 0
    if quiz and n_questions == 0:
        n_questions = try_rebuild_quiz_for_exam(exam)
        if n_questions > 0:
            quiz = fetch_exam_quiz(exam)
    return render(
        request,
        "courses/exam_detail.html",
        {
            "category": category,
            "exam": exam,
            "quiz": quiz,
            "n_quiz_questions": n_questions,
        },
    )


@login_required
def exam_pdf_download(request, category_slug, year, month, pk):
    category, exam = _get_monthly_exam(request, category_slug, year, month, pk)
    if not _user_has_content_access(request.user, category, year, month):
        messages.error(
            request,
            f"Abonnement pour {category.name} — {content_month_period_label(year, month)} requis pour télécharger cet examen.",
        )
        return redirect(
            _subscribe_url_for_period(category, year, month, request.get_full_path())
        )
    if not exam.pdf:
        raise Http404()
    filename = os.path.basename(exam.pdf.name)
    return FileResponse(exam.pdf.open("rb"), as_attachment=True, filename=filename)


@login_required
def exam_quiz(request, category_slug, year, month, pk):
    category, exam = _get_monthly_exam(request, category_slug, year, month, pk)
    if not _user_has_content_access(request.user, category, year, month):
        messages.error(
            request,
            f"Abonnement pour {category.name} — {content_month_period_label(year, month)} requis pour passer le quiz.",
        )
        return redirect(
            _subscribe_url_for_period(category, year, month, request.get_full_path())
        )
    quiz = fetch_exam_quiz(exam)
    questions = list(quiz.questions.all()) if quiz else []
    quiz, questions = load_quiz_questions(
        quiz,
        questions,
        lambda: try_rebuild_quiz_for_exam(exam),
        lambda: fetch_exam_quiz(exam),
    )
    if not quiz:
        messages.warning(request, "Aucun quiz n’est associé à cet examen.")
        return redirect(exam.get_absolute_url())
    if not questions:
        messages.info(
            request,
            "Les questions du quiz n’ont pas pu être extraites du PDF. "
            "Vérifiez qu’un tableau (énoncé, propositions, réponses) est présent, "
            "ou importez un CSV de secours depuis l’administration.",
        )
        return redirect(exam.get_absolute_url())

    _annotate_quiz_questions_for_template(questions)

    results = None
    score_percent = None
    score_points = None
    show_results = False
    attempt_sent_to_admin = False
    is_retake = user_has_admin_result(exam, request.user)

    if request.method == "POST":
        if is_exam_time_expired(request, exam):
            messages.warning(
                request,
                "Le temps imparti est écoulé. Votre copie a été enregistrée avec les réponses cochées.",
            )
        show_results = True
        score_points, score_percent, results = process_quiz_post(request, questions)
        attempt = record_exam_attempt(
            request, exam, request.user, score_points, score_percent
        )
        attempt_sent_to_admin = attempt.sent_to_admin
        if is_retake and not attempt_sent_to_admin:
            messages.info(
                request,
                "Cette note est visible pour vous uniquement. Seule votre première composition "
                "a été transmise à l’administrateur.",
            )
        elif not attempt_sent_to_admin and not exam.is_within_results_collection_period():
            messages.info(
                request,
                "La période de collecte des résultats est terminée : votre note n’est pas "
                "transmise à l’administrateur.",
            )
    else:
        ensure_exam_started(request, exam)

    return render(
        request,
        "courses/interactive_quiz.html",
        {
            "category": category,
            "document": exam,
            "document_kind": "Examen",
            "quiz": quiz,
            "questions": questions,
            "quiz_progress_total": QUIZ_QUESTION_NUMBER_MAX,
            "results": results,
            "score_points": score_points,
            "score_max_points": QUIZ_QUESTION_NUMBER_MAX,
            "score_percent": score_percent,
            "show_results": show_results,
            "is_exam_quiz": True,
            "exam_duration_minutes": exam.duration_minutes,
            "exam_time_remaining_seconds": exam_time_remaining_seconds(request, exam),
            "exam_is_retake": is_retake,
            "attempt_sent_to_admin": attempt_sent_to_admin,
            "list_url_name": "courses:category_exams",
            "detail_url_name": "courses:exam_detail",
            "quiz_url_name": "courses:exam_quiz",
            "pdf_download_url_name": "courses:exam_pdf_download",
        },
    )


def _get_monthly_correction(request, category_slug, year, month, pk):
    correction = get_object_or_404(
        MonthlyCorrection.objects.select_related("category"),
        pk=pk,
        category__slug=category_slug,
        year=year,
        month=month,
    )
    return correction.category, correction


def correction_detail(request, category_slug, year, month, pk):
    category, correction = _get_monthly_correction(request, category_slug, year, month, pk)
    gate = _subscription_gate(request, request.get_full_path(), category, year, month)
    if gate:
        return gate
    quiz = fetch_correction_quiz(correction)
    n_questions = quiz.n_questions if quiz else 0
    if quiz and n_questions == 0:
        n_questions = try_rebuild_quiz_for_correction(correction)
        if n_questions > 0:
            quiz = fetch_correction_quiz(correction)
    return render(
        request,
        "courses/correction_detail.html",
        {
            "category": category,
            "correction": correction,
            "quiz": quiz,
            "n_quiz_questions": n_questions,
        },
    )


@login_required
@xframe_options_sameorigin
def correction_pdf_inline(request, category_slug, year, month, pk):
    """Affichage PDF en ligne (lecture seule) pour les candidats abonnés."""
    category, correction = _get_monthly_correction(request, category_slug, year, month, pk)
    if not _user_has_content_access(request.user, category, year, month):
        raise Http404()
    if not correction.pdf:
        raise Http404()
    filename = os.path.basename(correction.pdf.name)
    response = FileResponse(
        correction.pdf.open("rb"), as_attachment=False, filename=filename
    )
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def correction_pdf_download(request, category_slug, year, month, pk):
    category, correction = _get_monthly_correction(request, category_slug, year, month, pk)
    if not _user_has_content_access(request.user, category, year, month):
        messages.error(
            request,
            f"Abonnement pour {category.name} — {content_month_period_label(year, month)} requis pour télécharger ce corrigé.",
        )
        return redirect(
            _subscribe_url_for_period(category, year, month, request.get_full_path())
        )
    if not correction.pdf:
        raise Http404()
    filename = os.path.basename(correction.pdf.name)
    return FileResponse(correction.pdf.open("rb"), as_attachment=True, filename=filename)


@login_required
def correction_quiz(request, category_slug, year, month, pk):
    category, correction = _get_monthly_correction(request, category_slug, year, month, pk)
    if not _user_has_content_access(request.user, category, year, month):
        messages.error(
            request,
            f"Abonnement pour {category.name} — {content_month_period_label(year, month)} requis pour passer le quiz.",
        )
        return redirect(
            _subscribe_url_for_period(category, year, month, request.get_full_path())
        )
    quiz = fetch_correction_quiz(correction)
    questions = list(quiz.questions.all()) if quiz else []
    quiz, questions = load_quiz_questions(
        quiz,
        questions,
        lambda: try_rebuild_quiz_for_correction(correction),
        lambda: fetch_correction_quiz(correction),
    )
    if not quiz:
        messages.warning(request, "Aucun quiz n’est associé à cette correction.")
        return redirect(correction.get_absolute_url())
    if not questions:
        messages.info(
            request,
            "Les questions du quiz n’ont pas pu être extraites du PDF. "
            "Vérifiez qu’un tableau (énoncé, propositions, réponses) est présent, "
            "ou importez un CSV de secours depuis l’administration.",
        )
        return redirect(correction.get_absolute_url())

    _annotate_quiz_questions_for_template(questions)

    results = None
    score_percent = None
    score_points = None
    show_results = False
    if request.method == "POST":
        show_results = True
        score_points, score_percent, results = process_quiz_post(request, questions)

    return render(
        request,
        "courses/interactive_quiz.html",
        {
            "category": category,
            "document": correction,
            "document_kind": "Corrigé",
            "quiz": quiz,
            "questions": questions,
            "quiz_progress_total": QUIZ_QUESTION_NUMBER_MAX,
            "results": results,
            "score_points": score_points,
            "score_max_points": QUIZ_QUESTION_NUMBER_MAX,
            "score_percent": score_percent,
            "show_results": show_results,
            "list_url_name": "courses:category_corrections",
            "detail_url_name": "courses:correction_detail",
            "quiz_url_name": "courses:correction_quiz",
            "pdf_download_url_name": "courses:correction_pdf_download",
        },
    )


def monthly_content(request, category_slug, year, month, pk):
    category = get_object_or_404(Category, slug=category_slug)
    content = get_object_or_404(
        MonthlyCourseContent,
        pk=pk,
        category=category,
        year=year,
        month=month,
    )
    gate = _subscription_gate(request, request.get_full_path(), category, year, month)
    if gate:
        return gate
    return render(
        request,
        "courses/monthly_content.html",
        {
            "category": category,
            "content": content,
            "period_label": content.period_label,
        },
    )


@login_required
@xframe_options_sameorigin
def monthly_pdf_inline(request, category_slug, year, month, pk):
    category = get_object_or_404(Category, slug=category_slug)
    content = get_object_or_404(
        MonthlyCourseContent,
        pk=pk,
        category=category,
        year=year,
        month=month,
    )
    if not _user_has_content_access(request.user, category, year, month):
        raise Http404()
    if not content.pdf:
        raise Http404()
    filename = os.path.basename(content.pdf.name)
    response = FileResponse(
        content.pdf.open("rb"), as_attachment=False, filename=filename
    )
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def monthly_pdf_download(request, category_slug, year, month, pk):
    category = get_object_or_404(Category, slug=category_slug)
    content = get_object_or_404(
        MonthlyCourseContent,
        pk=pk,
        category=category,
        year=year,
        month=month,
    )
    if not _user_has_content_access(request.user, category, year, month):
        messages.error(
            request,
            f"Abonnement pour {category.name} — {content_month_period_label(year, month)} requis pour télécharger ce document.",
        )
        return redirect(
            _subscribe_url_for_period(category, year, month, request.get_full_path())
        )
    if not content.pdf:
        raise Http404()
    filename = os.path.basename(content.pdf.name)
    return FileResponse(content.pdf.open("rb"), as_attachment=True, filename=filename)


@login_required
def subscribe(request):
    next_url = request.GET.get("next") or request.POST.get("next") or reverse("courses:home")
    initial_period = None
    initial_category = None
    category_slug = request.GET.get("category") or request.POST.get("category")
    if not category_slug:
        category_slug = _parse_category_slug_from_path(next_url)
    if category_slug:
        initial_category = Category.objects.filter(slug=category_slug).first()
    year_param = request.GET.get("year") or request.POST.get("year")
    month_param = request.GET.get("month") or request.POST.get("month")
    if year_param and month_param:
        try:
            initial_period = (int(year_param), int(month_param))
        except (TypeError, ValueError):
            initial_period = None
    if initial_period is None and not month_param:
        initial_period = _parse_period_from_path(next_url)

    plan_only = bool(initial_category and initial_period)
    if not plan_only:
        messages.info(
            request,
            "Choisissez d’abord une catégorie et un mois depuis l’accueil, "
            "puis cliquez sur « S’abonner » sur le mois souhaité.",
        )
        return redirect(f"{reverse('courses:home')}#categories-par-mois")

    if request.method == "POST":
        form = SubscriptionRequestForm(
            request.POST,
            user=request.user,
            initial_category=initial_category,
            initial_period=initial_period,
        )
        if form.is_valid():
            form.save()
            cat = form.cleaned_data["category"]
            year = form.cleaned_data["year"]
            month = form.cleaned_data["month"]
            plan = form.cleaned_data["plan"]
            label = subscription_access_label(cat, year, month, plan)
            messages.success(
                request,
                f"Votre demande d’accès pour {label} a été enregistrée. "
                "Elle sera examinée par un administrateur.",
            )
            return redirect("courses:my_subscription")
    else:
        form = SubscriptionRequestForm(
            user=request.user,
            initial_category=initial_category,
            initial_period=initial_period,
        )
    plans = list(
        SubscriptionPlan.objects.filter(is_active=True)
        .prefetch_related("plan_months")
        .order_by("billing_period", "name", "pk")
    )
    access_label = subscription_access_label(
        initial_category,
        initial_period[0],
        initial_period[1],
        None,
    )
    return render(
        request,
        "courses/subscribe.html",
        {
            "form": form,
            "plans": plans,
            "next_url": next_url,
            "initial_category": initial_category,
            "initial_period": initial_period,
            "plan_only": plan_only,
            "access_label": access_label,
        },
    )


@login_required
def my_subscription(request):
    reqs = SubscriptionRequest.objects.filter(user=request.user).select_related(
        "plan", "decided_by", "category"
    )
    month_access = get_user_subscribed_months(request.user)
    return render(
        request,
        "courses/my_subscription.html",
        {
            "subscription_requests": reqs,
            "month_access": month_access,
        },
    )


def course_list(request):
    qs = Course.objects.filter(published=True).select_related("instructor", "category")
    q = request.GET.get("q", "").strip()
    cat = request.GET.get("category", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(short_description__icontains=q))
    if cat:
        qs = qs.filter(category__slug=cat)
    categories = Category.objects.all()
    return render(
        request,
        "courses/course_list.html",
        {"courses": qs, "search_query": q, "category_slug": cat, "categories": categories},
    )


def course_detail(request, slug):
    qs = Course.objects.select_related("instructor", "category").prefetch_related("lessons")
    course = get_object_or_404(qs, slug=slug)
    if not course.published:
        if not request.user.is_authenticated or course.instructor_id != request.user.id:
            raise Http404()
    enrolled = False
    if request.user.is_authenticated:
        enrolled = Enrollment.objects.filter(user=request.user, course=course).exists()
    completed_ids = set()
    if request.user.is_authenticated:
        completed_ids = set(
            LessonProgress.objects.filter(user=request.user, lesson__course=course).values_list(
                "lesson_id", flat=True
            )
        )
    return render(
        request,
        "courses/course_detail.html",
        {
            "course": course,
            "enrolled": enrolled,
            "completed_lesson_ids": completed_ids,
            "is_instructor": request.user.is_authenticated and course.instructor_id == request.user.id,
        },
    )


@login_required
def lesson_detail(request, course_slug, pk):
    course = get_object_or_404(
        Course.objects.prefetch_related("lessons"),
        slug=course_slug,
    )
    if not course.published and course.instructor_id != request.user.id:
        raise Http404()
    lesson = get_object_or_404(Lesson, pk=pk, course=course)
    can_access = (
        course.instructor_id == request.user.id
        or Enrollment.objects.filter(user=request.user, course=course).exists()
    )
    if not can_access:
        raise Http404()
    lessons = list(course.lessons.all())
    idx = next((i for i, l in enumerate(lessons) if l.pk == lesson.pk), 0)
    prev_lesson = lessons[idx - 1] if idx > 0 else None
    next_lesson = lessons[idx + 1] if idx + 1 < len(lessons) else None
    completed = LessonProgress.objects.filter(user=request.user, lesson=lesson).exists()
    return render(
        request,
        "courses/lesson_detail.html",
        {
            "course": course,
            "lesson": lesson,
            "prev_lesson": prev_lesson,
            "next_lesson": next_lesson,
            "completed": completed,
        },
    )


@login_required
def enroll(request, slug):
    course = get_object_or_404(Course, slug=slug)
    if not course.published:
        messages.error(request, "Ce SUJET n'est pas encore publié.")
        return redirect("courses:home")
    if course.instructor_id == request.user.id:
        messages.info(request, "Vous êtes le formateur de ce SUJET.")
        return redirect(course.get_absolute_url())
    Enrollment.objects.get_or_create(user=request.user, course=course)
    messages.success(request, f"Inscription confirmée : {course.title}")
    return redirect(course.get_absolute_url())


@login_required
def mark_lesson_complete(request, course_slug, pk):
    if request.method != "POST":
        return redirect("courses:course_detail", slug=course_slug)
    course = get_object_or_404(Course, slug=course_slug)
    if not course.published and course.instructor_id != request.user.id:
        raise Http404()
    lesson = get_object_or_404(Lesson, pk=pk, course=course)
    if not (
        course.instructor_id == request.user.id
        or Enrollment.objects.filter(user=request.user, course=course).exists()
    ):
        raise Http404()
    LessonProgress.objects.get_or_create(user=request.user, lesson=lesson)
    messages.success(request, "Leçon marquée comme terminée.")
    return redirect(lesson.get_absolute_url())


@login_required
def my_learning(request):
    enrollments = (
        Enrollment.objects.filter(user=request.user)
        .select_related("course", "course__instructor")
        .prefetch_related("course__lessons")
    )
    return render(request, "courses/my_learning.html", {"enrollments": enrollments})


@login_required
def my_teaching(request):
    courses = Course.objects.filter(instructor=request.user).order_by("-updated_at")
    return render(request, "courses/my_teaching.html", {"courses": courses})


@login_required
def course_create(request):
    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES)
        if form.is_valid():
            c = form.save(commit=False)
            c.instructor = request.user
            c.save()
            messages.success(request, "SUJET créé. Ajoutez des leçons depuis la fiche SUJET.")
            return redirect("courses:course_edit", slug=c.slug)
    else:
        form = CourseForm()
    return render(request, "courses/course_form.html", {"form": form, "title": "Nouveau SUJET"})


@login_required
def course_edit(request, slug):
    course = get_object_or_404(Course, slug=slug, instructor=request.user)
    if request.method == "POST":
        form = CourseForm(request.POST, request.FILES, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, "SUJET mis à jour.")
            return redirect("courses:course_edit", slug=course.slug)
    else:
        form = CourseForm(instance=course)
    lessons = course.lessons.all()
    return render(
        request,
        "courses/course_edit.html",
        {"form": form, "course": course, "lessons": lessons},
    )


@login_required
def lesson_create(request, course_slug):
    course = get_object_or_404(Course, slug=course_slug, instructor=request.user)
    if request.method == "POST":
        form = LessonForm(request.POST)
        if form.is_valid():
            les = form.save(commit=False)
            les.course = course
            les.save()
            messages.success(request, "Leçon ajoutée.")
            return redirect("courses:course_edit", slug=course.slug)
    else:
        form = LessonForm(initial={"order": course.lessons.count()})
    return render(
        request,
        "courses/lesson_form.html",
        {"form": form, "course": course, "title": "Nouvelle leçon"},
    )


@login_required
def lesson_edit(request, course_slug, pk):
    course = get_object_or_404(Course, slug=course_slug, instructor=request.user)
    lesson = get_object_or_404(Lesson, pk=pk, course=course)
    if request.method == "POST":
        form = LessonForm(request.POST, instance=lesson)
        if form.is_valid():
            form.save()
            messages.success(request, "Leçon enregistrée.")
            return redirect(lesson.get_absolute_url())
    else:
        form = LessonForm(instance=lesson)
    return render(
        request,
        "courses/lesson_form.html",
        {"form": form, "course": course, "lesson": lesson, "title": "Modifier la leçon"},
    )
