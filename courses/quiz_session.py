"""Logique partagée des pages quiz interactif (correction ou examen)."""

from __future__ import annotations

from .quiz_import import QUIZ_QUESTION_NUMBER_MAX
from .quiz_queries import sorted_question_options


def quiz_answer_earns_point(selected_ids: set[int], correct_ids: set[int]) -> bool:
    """1 point si toutes les bonnes réponses sont cochées, sans case en trop."""
    if not correct_ids:
        return False
    return selected_ids == correct_ids


def process_quiz_post(request, questions) -> tuple[int, float, list[dict]]:
    """Calcule le score (1 pt / question, sur 60) et les résultats détaillés."""

    score_points = 0
    results = []
    for q in questions:
        key = f"q_{q.id}"
        selected = set()
        for x in request.POST.getlist(key):
            if str(x).isdigit():
                selected.add(int(x))
        good = {o.id for o in sorted_question_options(q) if o.is_correct}
        ok = quiz_answer_earns_point(selected, good)
        if ok:
            score_points += 1
        lettered = []
        for row in q.options_lettered:
            o = row["option"]
            lettered.append(
                {
                    "letter": row["letter"],
                    "line": row["line"],
                    "option": o,
                    "picked": o.id in selected,
                    "should": o.is_correct,
                }
            )
        results.append(
            {
                "question": q,
                "ok": ok,
                "points": 1 if ok else 0,
                "selected_ids": selected,
                "correct_ids": good,
                "options_review": lettered,
            }
        )
    score_percent = round(100 * score_points / QUIZ_QUESTION_NUMBER_MAX, 1)
    return score_points, score_percent, results


def load_quiz_questions(quiz, questions: list, try_rebuild_fn, refetch_fn) -> tuple[object | None, list]:
    """Tente un rebuild si vide, puis recharge le quiz."""
    if quiz and not questions:
        try_rebuild_fn()
        quiz = refetch_fn()
        questions = list(quiz.questions.all()) if quiz else []
    return quiz, questions
