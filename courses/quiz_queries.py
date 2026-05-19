"""Requêtes optimisées pour les quiz (corrections et examens)."""

from django.db.models import Count, Prefetch

from .models import (
    CorrectionQuiz,
    ExamQuiz,
    ExamQuizOption,
    ExamQuizQuestion,
    QuizOption,
    QuizQuestion,
)

CORRECTION_OPTIONS_PREFETCH = Prefetch(
    "options",
    queryset=QuizOption.objects.order_by("order", "id"),
)
CORRECTION_QUESTIONS_PREFETCH = Prefetch(
    "questions",
    queryset=QuizQuestion.objects.order_by("order", "id").prefetch_related(
        CORRECTION_OPTIONS_PREFETCH
    ),
)

EXAM_OPTIONS_PREFETCH = Prefetch(
    "options",
    queryset=ExamQuizOption.objects.order_by("order", "id"),
)
EXAM_QUESTIONS_PREFETCH = Prefetch(
    "questions",
    queryset=ExamQuizQuestion.objects.order_by("order", "id").prefetch_related(
        EXAM_OPTIONS_PREFETCH
    ),
)


def sorted_question_options(question) -> list:
    """Options triées ; utilise le prefetch sans requête SQL supplémentaire."""
    cache = getattr(question, "_prefetched_objects_cache", None)
    if cache and "options" in cache:
        opts = list(cache["options"])
    else:
        opts = list(question.options.order_by("order", "id"))
    return sorted(opts, key=lambda o: (o.order, o.id))


def fetch_correction_quiz(correction):
    """Quiz correction + questions + options en peu de requêtes SQL."""
    return (
        CorrectionQuiz.objects.filter(correction=correction)
        .annotate(n_questions=Count("questions", distinct=True))
        .prefetch_related(CORRECTION_QUESTIONS_PREFETCH)
        .first()
    )


def fetch_exam_quiz(exam):
    """Quiz examen + questions + options en peu de requêtes SQL."""
    return (
        ExamQuiz.objects.filter(exam=exam)
        .annotate(n_questions=Count("questions", distinct=True))
        .prefetch_related(EXAM_QUESTIONS_PREFETCH)
        .first()
    )
