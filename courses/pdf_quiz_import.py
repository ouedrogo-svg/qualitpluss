"""Extraction des tableaux d’un PDF de correction pour alimenter le quiz."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from django.core.cache import cache

from .quiz_import import (
    QUIZ_QUESTION_NUMBER_MAX,
    _enrich_spec_with_continuation,
    _finalize_quiz_specs,
    _first_ordre_row_index,
    _parse_ordre_cell,
    _normalize_matrix_rows,
    _row_merged_content,
    _score_correction_table_rows,
    _spec_is_plausible,
    _spec_richness,
    _table_correction_layout,
    _table_has_option_rows,
    _valid_question_number,
    apply_question_specs_to_quiz,
    matrix_rows_to_question_specs,
    specs_from_correction_table_rows,
)

logger = logging.getLogger(__name__)

# Réglages pdfplumber : lignes / texte, tolérances (snap/join), mots minimum par arête.
# Les corrigés académiques varient beaucoup ; on enchaîne plusieurs profils.
_TABLE_EXTRACT_PRESETS: tuple[dict, ...] = (
    {},
    {"vertical_strategy": "lines", "horizontal_strategy": "lines"},
    {"vertical_strategy": "lines", "horizontal_strategy": "lines", "snap_tolerance": 2, "join_tolerance": 2},
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 6,
        "join_tolerance": 6,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
        "edge_min_length": 2,
    },
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 10,
        "join_tolerance": 10,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    },
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 5,
        "join_tolerance": 5,
        "text_x_tolerance": 5,
        "text_y_tolerance": 5,
    },
    {"vertical_strategy": "text", "horizontal_strategy": "text"},
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 5,
        "join_tolerance": 5,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    },
    {"vertical_strategy": "lines", "horizontal_strategy": "text", "snap_tolerance": 5, "join_tolerance": 5},
    {"vertical_strategy": "text", "horizontal_strategy": "lines", "snap_tolerance": 5, "join_tolerance": 5},
)


def _merge_words_line_to_cells(line_ws: list[dict], x_gap: float) -> list[str]:
    """Regroupe les mots d’une même ligne en « cellules » selon l’espace horizontal."""
    if not line_ws:
        return []
    parts: list[str] = [str(line_ws[0].get("text") or "").strip()]
    cur_right = float(line_ws[0]["x1"])
    for w in line_ws[1:]:
        x0 = float(w["x0"])
        if x0 - cur_right > x_gap:
            parts.append(str(w.get("text") or "").strip())
        else:
            parts[-1] = (parts[-1] + " " + str(w.get("text") or "").strip()).strip()
        cur_right = max(cur_right, float(w["x1"]))
    return [p for p in parts if p]


def _words_cluster_matrix_from_page(page, x_gap: float) -> list[list[str]] | None:
    """
    Secours quand extract_tables produit peu : reconstruit des lignes type tableau
    à partir des positions des mots (QCM souvent alignés en colonnes).
    """
    try:
        words = page.extract_words(keep_blank_chars=False)
    except TypeError:
        words = page.extract_words()
    except Exception:
        return None
    if not words:
        return None
    by_y: dict[float, list[dict]] = defaultdict(list)
    for w in words:
        yk = round(float(w["top"]) / 2.5) * 2.5
        by_y[yk].append(w)
    rows_out: list[list[str]] = []
    for yk in sorted(by_y.keys()):
        line = sorted(by_y[yk], key=lambda z: float(z["x0"]))
        cells = _merge_words_line_to_cells(line, x_gap)
        if len(cells) >= 3:
            rows_out.append(cells)
    if len(rows_out) < 2:
        return None
    return rows_out


def _iter_raw_tables_from_pdf(path: str):
    """Itère des matrices (lignes de cellules) issues du PDF, sans doublons évidents."""
    import pdfplumber

    seen_fp: set[int] = set()

    def _emit_normalized(norm: list[list[str]]):
        if len(norm) < 2:
            return
        fp = hash(tuple(tuple(r[:12]) for r in norm[:10]))
        if fp in seen_fp:
            return
        seen_fp.add(fp)
        yield norm

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for settings in _TABLE_EXTRACT_PRESETS:
                try:
                    if settings:
                        raw_tables = page.extract_tables(table_settings=settings) or []
                    else:
                        raw_tables = page.extract_tables() or []
                except TypeError:
                    raw_tables = page.extract_tables() or []
                except Exception:
                    logger.debug("extract_tables a échoué pour un réglage", exc_info=True)
                    continue
                for raw in raw_tables:
                    norm = _normalize_matrix_rows(raw)
                    yield from _emit_normalized(norm)

            for gap in (8.0, 12.0, 18.0, 26.0, 36.0):
                pseudo = _words_cluster_matrix_from_page(page, gap)
                if pseudo:
                    norm = _normalize_matrix_rows(pseudo)
                    yield from _emit_normalized(norm)


def _consolidated_correction_rows_from_pdf(path: str) -> list[list[str]]:
    """
    Sur chaque page, concatène les lignes de tous les tableaux utiles
    (corrigé principal + suite de question en fin de page).
    """
    import pdfplumber

    consolidated: list[list[str]] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                page_chunks: list[list[str]] = []
                for raw in page.extract_tables() or []:
                    rows = _normalize_matrix_rows(raw)
                    if not rows:
                        continue
                    layout = _table_correction_layout(rows)
                    if layout:
                        _, _, data_start = layout
                        first_ordre = _first_ordre_row_index(rows)
                        if first_ordre and first_ordre > 0:
                            page_chunks.append(rows[:first_ordre])
                        page_chunks.append(rows[data_start:])
                    elif _table_has_option_rows(rows):
                        page_chunks.append(rows)
                if not page_chunks:
                    continue
                for chunk in page_chunks:
                    consolidated.extend(chunk)
    except Exception:
        logger.debug("Consolidation lignes corrigé impossible", exc_info=True)
        return []
    return consolidated


def _score_quiz_specs(specs: list[dict]) -> tuple[int, int, int]:
    """Plus haut = mieux : couverture 1–60, puis nombre de questions."""
    if not specs:
        return (0, 0, 0)
    numbers = {s["number"] for s in specs if _valid_question_number(s.get("number"))}
    coverage = len(numbers)
    n = len(specs)
    ideal_gap = abs(n - QUIZ_QUESTION_NUMBER_MAX)
    return (coverage, n, -ideal_gap)


def best_question_specs_from_correction_pdf(path: str) -> list[dict]:
    """
    Extraction conforme au PDF : fusionne toutes les sources (pages + tableaux),
    une entrée par numéro d’ordre (1–60) pour ne pas perdre la dernière question isolée.
    """
    try:
        by_number: dict[int, dict] = {}

        def absorb(specs: list[dict]) -> None:
            for spec in _finalize_quiz_specs(specs):
                n = spec.get("number")
                if not _valid_question_number(n) or not _spec_is_plausible(spec):
                    continue
                if n not in by_number or _spec_richness(spec) > _spec_richness(by_number[n]):
                    by_number[n] = spec

        data_rows = _consolidated_correction_rows_from_pdf(path)
        if data_rows:
            absorb(specs_from_correction_table_rows(data_rows))

        last_ordre: int | None = max(by_number.keys()) if by_number else None
        for rows in _iter_raw_tables_from_pdf(path):
            layout = _table_correction_layout(rows)
            if not layout:
                continue
            i_o, i_r, _data_start = layout
            width = max(len(r) for r in rows)
            content_cols = [j for j in range(i_o + 1, i_r)]
            if not content_cols:
                content_cols = [min(i_o + 1, width - 1)]

            first_ordre_i = _first_ordre_row_index(rows)
            if first_ordre_i is None:
                continue

            first_ordre_n = _parse_ordre_cell((rows[first_ordre_i][0] if first_ordre_i < len(rows) else "") or "")

            # Suite d’une question sur la page suivante (ex. options c) d) puis n° 60)
            if (
                first_ordre_i > 0
                and last_ordre
                and first_ordre_n
                and first_ordre_n == last_ordre + 1
                and last_ordre in by_number
            ):
                lead_parts: list[str] = []
                for r in rows[:first_ordre_i]:
                    chunk = _row_merged_content(r, content_cols)
                    if chunk and not re.match(r"^\s*NB\s*:", chunk, flags=re.IGNORECASE):
                        lead_parts.append(chunk)
                if lead_parts and len(lead_parts) <= 8:
                    enriched = _enrich_spec_with_continuation(by_number[last_ordre], lead_parts)
                    if _spec_is_plausible(enriched) and _spec_richness(enriched) > _spec_richness(
                        by_number[last_ordre]
                    ):
                        by_number[last_ordre] = enriched

            # Petit tableau isolé (ex. question 60 seule) non capté par la consolidation
            if len(rows) <= 12 and first_ordre_n:
                specs = specs_from_correction_table_rows(rows)
                if not specs:
                    specs = _finalize_quiz_specs(matrix_rows_to_question_specs(rows))
                absorb(specs)

            if by_number:
                last_ordre = max(by_number.keys())

        return [by_number[i] for i in sorted(by_number.keys())]
    except Exception:
        logger.exception("Lecture PDF pour quiz impossible : %s", path)
        return []


def import_quiz_from_pdf_document(
    quiz,
    document,
    *,
    quiz_model,
    question_model=None,
    option_model=None,
    quiz_fk_field: str = "quiz",
) -> int:
    """
    Reconstruit le quiz à partir du PDF (correction ou examen).
    Retourne le nombre de questions créées (0 si aucun tableau exploitable).
    """
    n = 0
    if not document.pdf:
        return 0
    try:
        try:
            path = document.pdf.path
        except (ValueError, NotImplementedError):
            logger.warning("Stockage de fichiers sans chemin local : impossible d’analyser le PDF.")
        else:
            specs = best_question_specs_from_correction_pdf(path)
            if specs:
                _, n = apply_question_specs_to_quiz(
                    quiz,
                    specs,
                    question_model=question_model,
                    option_model=option_model,
                    quiz_fk_field=quiz_fk_field,
                )
            else:
                quiz.questions.all().delete()
                n = 0
    except Exception:
        logger.exception("Erreur lors de l’analyse ou de l’import du quiz depuis le PDF")
        n = 0
    finally:
        quiz_model.objects.filter(pk=quiz.pk).update(
            quiz_last_built_for_pdf_key=document.pdf.name
        )
    return n


def import_quiz_from_correction_pdf(quiz, correction) -> int:
    from .models import CorrectionQuiz

    return import_quiz_from_pdf_document(quiz, correction, quiz_model=CorrectionQuiz)


def import_quiz_from_exam_pdf(quiz, exam) -> int:
    from .models import ExamQuiz, ExamQuizOption, ExamQuizQuestion

    return import_quiz_from_pdf_document(
        quiz,
        exam,
        quiz_model=ExamQuiz,
        question_model=ExamQuizQuestion,
        option_model=ExamQuizOption,
        quiz_fk_field="exam_quiz",
    )


def sync_quiz_after_correction_saved(
    correction, *, force: bool = False
) -> tuple[int, str | None]:
    """
    À appeler une fois la correction (et l’inline quiz) enregistrées.
    Retourne (nombre_de_questions, message_erreur_éventuel — toujours None si pas d’exception globale).
    """
    from .models import CorrectionQuiz

    if not correction.pdf:
        return 0, None
    quiz, _ = CorrectionQuiz.objects.get_or_create(correction=correction, defaults={})
    pdf_key = correction.pdf.name
    if not force and pdf_key and quiz.quiz_last_built_for_pdf_key == pdf_key:
        n_existing = quiz.questions.count()
        if n_existing > 0:
            return n_existing, None
    n = import_quiz_from_correction_pdf(quiz, correction)
    return n, None


def force_rebuild_quiz_from_correction_pdf(correction) -> int:
    """Action admin : oublie la synchro et relit le PDF."""
    from .models import CorrectionQuiz

    quiz, _ = CorrectionQuiz.objects.get_or_create(correction=correction, defaults={})
    CorrectionQuiz.objects.filter(pk=quiz.pk).update(quiz_last_built_for_pdf_key="")
    quiz.refresh_from_db()
    return import_quiz_from_correction_pdf(quiz, correction)


def _try_rebuild_quiz_for_document(
    document,
    *,
    quiz_model,
    parent_fk_name: str,
    force_rebuild_fn,
    cache_prefix: str,
) -> int:
    from django.db.models import Count

    quiz = (
        quiz_model.objects.filter(**{parent_fk_name: document})
        .annotate(n_questions=Count("questions", distinct=True))
        .first()
    )
    if not quiz:
        quiz_model.objects.get_or_create(**{parent_fk_name: document}, defaults={})
        return 0
    n = quiz.n_questions
    if n > 0 or not document.pdf:
        return n
    try:
        document.pdf.path
    except (ValueError, NotImplementedError):
        return 0
    cache_key = f"{cache_prefix}:{document.pk}:{document.pdf.name}"
    if cache.get(cache_key):
        return 0
    n_new = force_rebuild_fn(document)
    quiz.refresh_from_db()
    n = quiz.questions.count()
    if n_new == 0:
        cache.set(cache_key, 1, timeout=900)
    else:
        cache.delete(cache_key)
    return n


def sync_quiz_after_exam_saved(exam, *, force: bool = False) -> tuple[int, str | None]:
    from .models import ExamQuiz

    if not exam.pdf:
        return 0, None
    quiz, _ = ExamQuiz.objects.get_or_create(exam=exam, defaults={})
    pdf_key = exam.pdf.name
    if not force and pdf_key and quiz.quiz_last_built_for_pdf_key == pdf_key:
        n_existing = quiz.questions.count()
        if n_existing > 0:
            return n_existing, None
    n = import_quiz_from_exam_pdf(quiz, exam)
    return n, None


def force_rebuild_quiz_from_exam_pdf(exam) -> int:
    from .models import ExamQuiz

    quiz, _ = ExamQuiz.objects.get_or_create(exam=exam, defaults={})
    ExamQuiz.objects.filter(pk=quiz.pk).update(quiz_last_built_for_pdf_key="")
    quiz.refresh_from_db()
    return import_quiz_from_exam_pdf(quiz, exam)


def try_rebuild_quiz_for_correction(correction) -> int:
    from .models import CorrectionQuiz

    return _try_rebuild_quiz_for_document(
        correction,
        quiz_model=CorrectionQuiz,
        parent_fk_name="correction",
        force_rebuild_fn=force_rebuild_quiz_from_correction_pdf,
        cache_prefix="quiz_autobuild_fail",
    )


def try_rebuild_quiz_for_exam(exam) -> int:
    from .models import ExamQuiz

    return _try_rebuild_quiz_for_document(
        exam,
        quiz_model=ExamQuiz,
        parent_fk_name="exam",
        force_rebuild_fn=force_rebuild_quiz_from_exam_pdf,
        cache_prefix="exam_quiz_autobuild_fail",
    )
