"""Durée d'examen et fenêtre de collecte des résultats pour l'administrateur."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone

from .models import ExamQuizAttempt, MonthlyExam


def _session_key(exam_pk: int) -> str:
    return f"exam_quiz_started_{exam_pk}"


def get_exam_started_at(request, exam: MonthlyExam) -> datetime | None:
    raw = request.session.get(_session_key(exam.pk))
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def ensure_exam_started(request, exam: MonthlyExam) -> datetime:
    started = get_exam_started_at(request, exam)
    if started is None:
        started = timezone.now()
        request.session[_session_key(exam.pk)] = started.isoformat()
        request.session.modified = True
    return started


def clear_exam_started(request, exam: MonthlyExam) -> None:
    key = _session_key(exam.pk)
    if key in request.session:
        del request.session[key]
        request.session.modified = True


def exam_time_remaining_seconds(request, exam: MonthlyExam) -> int:
    started = get_exam_started_at(request, exam)
    if started is None:
        return exam.duration_minutes * 60
    deadline = started + timedelta(minutes=exam.duration_minutes)
    remaining = (deadline - timezone.now()).total_seconds()
    return max(0, int(remaining))


def is_exam_time_expired(request, exam: MonthlyExam) -> bool:
    return exam_time_remaining_seconds(request, exam) <= 0


def user_has_admin_result(exam: MonthlyExam, user) -> bool:
    return ExamQuizAttempt.objects.filter(
        exam=exam, user=user, sent_to_admin=True
    ).exists()


def should_send_result_to_admin(exam: MonthlyExam, user) -> bool:
    """Première composition uniquement, dans le délai de collecte."""
    if user_has_admin_result(exam, user):
        return False
    return exam.is_within_results_collection_period()


def record_exam_attempt(
    request,
    exam: MonthlyExam,
    user,
    score_points: int,
    score_percent: float,
) -> ExamQuizAttempt:
    sent = should_send_result_to_admin(exam, user)
    attempt = ExamQuizAttempt.objects.create(
        user=user,
        exam=exam,
        score_points=score_points,
        score_percent=score_percent,
        sent_to_admin=sent,
    )
    clear_exam_started(request, exam)
    return attempt
