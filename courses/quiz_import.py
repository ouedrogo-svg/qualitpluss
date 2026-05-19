"""Construction du quiz à partir de tableaux (CSV ou lignes extraites d’un PDF)."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import BinaryIO

# Corrigés type concours : colonne « N° d’ordre » = numéros 1 à 60 uniquement.
QUIZ_QUESTION_NUMBER_MIN = 1
QUIZ_QUESTION_NUMBER_MAX = 60


def _valid_question_number(n: int | None) -> bool:
    return isinstance(n, int) and QUIZ_QUESTION_NUMBER_MIN <= n <= QUIZ_QUESTION_NUMBER_MAX


def _finalize_quiz_specs(specs: list[dict]) -> list[dict]:
    """Une question par numéro d’ordre valide (1–60), triée par numéro."""
    by_number: dict[int, dict] = {}
    for spec in specs:
        n = spec.get("number")
        if not _valid_question_number(n):
            continue
        if n not in by_number:
            by_number[n] = spec
    return [by_number[i] for i in sorted(by_number.keys())]


def _norm_header(s: str) -> str:
    t = (s or "").strip().lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", "_", t)


def _parse_reponses_cell(cell: str) -> list[int]:
    """
    Indices 1-based des bonnes réponses (colonne « Réponses » du corrigé).

    Formats acceptés : 1, 1;3, A, B, C, D, A;B, A,B, AB, AC, CB, ABCD, A+B, etc.
    (A=1, B=2, … ; plusieurs lettres collées = plusieurs bonnes réponses).
    """
    if not cell or not str(cell).strip():
        return []
    raw = str(cell).strip().upper()
    raw = "".join(
        c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn"
    )
    raw = re.sub(r"\s+", "", raw)
    for sep in (";", "|", "/", "\\", "·", "—", "–", "-", "+"):
        raw = raw.replace(sep, ",")
    raw = raw.replace(" ET ", ",").replace(" AND ", ",")
    parts = [p.strip(".,;:)]}(") for p in raw.split(",") if p.strip(".,;:)]}(")]
    out: list[int] = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            n = int(p)
            if n >= 1:
                out.append(n)
            continue
        letters_only = re.sub(r"[^A-Z]", "", p)
        if letters_only and re.sub(r"[A-Z]", "", p) == "":
            for ch in letters_only:
                out.append(ord(ch) - ord("A") + 1)
            continue
        if len(p) == 1 and "A" <= p <= "Z":
            out.append(ord(p) - ord("A") + 1)
    return sorted({i for i in out if i >= 1})


def _detect_answer_column_index(rows: list[list[str]]) -> int | None:
    """Repère la colonne dont les cellules ressemblent le plus à des indices / lettres de correction."""
    if not rows:
        return None
    width = max((len(r) for r in rows), default=0)
    if width < 2:
        return None
    best_j: int | None = None
    best_score = 0
    for j in range(width):
        score = 0
        for r in rows:
            if j < len(r) and _parse_reponses_cell(r[j]):
                score += 1
        if score > best_score:
            best_score = score
            best_j = j
    min_hits = 1 if len(rows) <= 4 else max(2, min(3, len(rows) // 4))
    if best_j is None or best_score < min_hits:
        return None
    return best_j


def _rectangularize_rows(rows: list[list[str]]) -> list[list[str]]:
    """Aligne toutes les lignes sur la même largeur (PDF : cellules fusionnées / colonnes manquantes)."""
    if not rows:
        return rows
    w = max((len(r) for r in rows), default=0)
    if w == 0:
        return rows
    out: list[list[str]] = []
    for r in rows:
        rr = [(r[i] if i < len(r) else "") for i in range(w)]
        out.append(rr)
    return out


def _strip_question_number_prefix(text: str) -> str:
    """Retire « 1. », « N°2 », « Q3) » en tête d’énoncé."""
    t = (text or "").strip()
    t = re.sub(r"^\s*(?:n[o°]\s*)?\d{1,3}\s*[\.\)\:、\-–]\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^\s*q(?:uestion)?\s*\d{1,3}\s*[\.\)\:]\s*", "", t, flags=re.IGNORECASE)
    return t.strip()


_OPTION_LETTER_MARK = re.compile(
    r"(?:^|\n)\s*([A-Ha-h])\s*[\)\.]\s*\t?\s*",
    re.MULTILINE,
)


def _normalize_stem_text(stem: str) -> str:
    """Énoncé sur plusieurs lignes PDF → une seule phrase (comme dans le corrigé)."""
    t = (stem or "").strip()
    if not t or "\n" not in t:
        return t
    return re.sub(r"\s*\n\s*", " ", t).strip()


def _strip_option_letter_prefix(text: str) -> str:
    """Retire « A) » ou « A. » en tête si déjà présent dans le texte extrait."""
    return re.sub(r"^[A-Ha-h]\s*[\)\.]\s*", "", (text or "").strip()).strip()


def strip_nb_references(text: str) -> str:
    """Retire les mentions « NB : Article… » (non affichées dans le quiz)."""
    t = (text or "").strip()
    if not t:
        return ""
    lines = [
        ln
        for ln in t.splitlines()
        if ln.strip() and not re.match(r"^\s*NB\s*:", ln.strip(), flags=re.IGNORECASE)
    ]
    t = "\n".join(lines).strip()
    t = re.sub(r"\s*NB\s*:\s*.*$", "", t, flags=re.IGNORECASE | re.MULTILINE).strip()
    return t


def _normalize_option_texts(texts: list[str]) -> list[str]:
    """Nettoie les propositions (sans ligne NB)."""
    out: list[str] = []
    for raw in texts:
        t = strip_nb_references(_strip_option_letter_prefix(raw))
        if t:
            out.append(t)
    return out


def _split_stem_and_embedded_options(full_question: str) -> tuple[str, list[str]]:
    """
    Détecte des propositions « A) … B) … » (format corrigé) ou « A. … » dans le bloc question.
    Retourne (énoncé principal, textes des propositions sans le préfixe lettre).
    """
    full = (full_question or "").strip()
    if not full:
        return "", []
    marks = _OPTION_LETTER_MARK
    matches = list(marks.finditer(full))
    if len(matches) < 2:
        marks = re.compile(
            r"(?:(?:^|\n)|(?<=[\s\?\!\:;«»]))\s*([A-Ha-h])\s*[\.\)\:、\-–]\s*",
            re.MULTILINE,
        )
        matches = list(marks.finditer(full))
    if len(matches) < 2:
        return full, []
    stem = full[: matches[0].start(1)].strip()
    texts: list[str] = []
    for k, m in enumerate(matches):
        start = m.end()
        end = matches[k + 1].start(1) if k + 1 < len(matches) else len(full)
        chunk = full[start:end].strip()
        if chunk:
            texts.append(_strip_option_letter_prefix(chunk))
    if not stem:
        stem = _strip_question_number_prefix(full[: matches[0].start(1)].strip())
    return _normalize_stem_text(stem), _normalize_option_texts(texts)


def _split_stem_embedded_numbered_options(full_question: str) -> tuple[str, list[str]]:
    """Propositions numérotées « 1) … 2) … » dans la cellule Questions (hors tout-chiffre isolé)."""
    full = (full_question or "").strip()
    if not full:
        return "", []
    marks = re.compile(
        r"(?:(?:^|\n)|(?<=[\s\?\!\:;«»]))\s*([1-9]|1[0-9])\s*[\.\)\:、\-–]\s*",
        re.MULTILINE,
    )
    matches = list(marks.finditer(full))
    if len(matches) < 2:
        return full, []
    stem = full[: matches[0].start(1)].strip()
    texts: list[str] = []
    for k, m in enumerate(matches):
        start = m.end()
        end = matches[k + 1].start(1) if k + 1 < len(matches) else len(full)
        chunk = full[start:end].strip()
        if chunk:
            texts.append(chunk)
    if not stem:
        stem = _strip_question_number_prefix(full[: matches[0].start(1)].strip())
    return stem, texts


def _split_stem_embedded_bullet_options(full_question: str) -> tuple[str, list[str]]:
    """Propositions en puces « - … » ou « • … » sur des lignes distinctes."""
    full = (full_question or "").strip()
    if not full:
        return "", []
    lines = [ln.strip() for ln in full.splitlines() if ln.strip()]
    if len(lines) < 3:
        return full, []
    bullet_pat = re.compile(r"^[\-–•·▪▸]\s*(.+)$")
    bullets: list[str] = []
    first_bi = None
    for i, ln in enumerate(lines):
        m = bullet_pat.match(ln)
        if m:
            if first_bi is None:
                first_bi = i
            bullets.append(m.group(1).strip())
        elif bullets:
            break
    if len(bullets) < 2 or first_bi is None or first_bi == 0:
        return full, []
    stem = "\n".join(lines[:first_bi]).strip()
    if not stem:
        stem = full
    return stem, bullets


def _correct_indices_from_rep_vs_options(embedded: list[str], rep_cell: str) -> list[int]:
    """
    Interprète la colonne « Réponses » pour cocher les bonnes cases : indices / lettres,
    ou texte identique (ou très proche) d’une proposition — jamais affiché comme choix.
    """
    rep = (rep_cell or "").strip()
    if not rep or not embedded:
        return []
    idxs = _parse_reponses_cell(rep)
    idxs_ok = sorted({i for i in idxs if 1 <= i <= len(embedded)})
    if idxs_ok:
        return idxs_ok
    rep_l = rep.lower()
    for j, t in enumerate(embedded):
        tt = t.strip().lower()
        if tt == rep_l:
            return [j + 1]
    if len(rep_l) >= 2:
        for j, t in enumerate(embedded):
            tt = t.strip().lower()
            if rep_l in tt or tt in rep_l:
                return [j + 1]
    return []


def _parse_ordre_cell(cell: str) -> int | None:
    """Numéro de question depuis la colonne « N° d’ordre » (uniquement 1 à 60)."""
    t = (cell or "").strip()
    if not t:
        return None
    m = re.match(r"^\s*(?:n[o°]\s*)?(\d{1,3})\s*[\.\)\:]?\s*$", t, flags=re.IGNORECASE)
    if not m:
        m = re.match(r"^\s*(\d{1,3})\s*$", t)
    if not m:
        return None
    n = int(m.group(1))
    return n if _valid_question_number(n) else None


def _spec_with_number(prompt: str, texts: list[str], correct: list[int], number: int | None) -> dict:
    """Construit une spec ; le champ order en base = number - 1 (numéro affiché = number)."""
    return {"prompt": prompt, "texts": texts, "correct": correct, "number": number}


def _norm_column_header_suggests_ordre(n: str) -> bool:
    """Colonne d’en-tête type « N° d’ordre », « rang », etc. (pas question ni réponse)."""
    if "question" in n or "reponse" in n:
        return False
    return (
        "ordre" in n
        or n in ("no", "rang", "index", "item", "numero")
        or re.match(r"^n_o_?d", n)
        or re.match(r"^n_?d_?ordre", n)
    )


def _column_data_looks_like_ordre_index(data_rows: list[list[str]], col_j: int) -> bool:
    """Heuristique : la colonne contient surtout des numéros d’ordre 1–60."""
    sample = [r for r in data_rows[:30] if r and len(r) > col_j]
    if len(sample) < 2:
        return False
    hits = sum(
        1
        for r in sample
        if _parse_ordre_cell((r[col_j] if col_j < len(r) else "") or "") is not None
    )
    return hits >= max(2, int(len(sample) * 0.6))


def _exclude_column_from_propositions(
    col_i: int,
    *,
    qi: int,
    ri: int,
    norms: list[str],
    data_rows: list[list[str]],
) -> bool:
    """Évite d’utiliser la colonne « N° » comme proposition (erreur fréquente PDF / tableur)."""
    if col_i == qi or col_i == ri:
        return True
    if col_i < len(norms) and _norm_column_header_suggests_ordre(norms[col_i]):
        return True
    if col_i != qi and qi != 0 and col_i == 0 and _column_data_looks_like_ordre_index(data_rows, 0):
        return True
    return False


def _options_texts_align_with_extracted(embedded: list[str], col_texts: list[str]) -> bool:
    """Les options extraites du texte coïncident avec les colonnes (énoncé seul dans la cellule question)."""
    cols = [(c or "").strip() for c in col_texts if (c or "").strip()]
    if len(cols) < 2 or len(embedded) < 2:
        return False
    n = min(len(cols), len(embedded), 6)
    for k in range(n):
        a = re.sub(r"\s+", " ", embedded[k].strip().lower())[:140]
        b = re.sub(r"\s+", " ", cols[k].strip().lower())[:140]
        if a == b or a in b or b in a:
            continue
        return False
    return True


def _stem_for_oqr_with_column_options(q_cell: str, col_texts: list[str]) -> str:
    """
    Énoncé principal quand les réponses sont en colonnes séparées : évite de répéter A/B dans le libellé
    si la cellule question contient déjà le même texte que les colonnes.
    """
    stem_a, emb_a = _split_stem_and_embedded_options(q_cell)
    if stem_a and len(emb_a) >= 2 and _options_texts_align_with_extracted(emb_a, col_texts):
        return _strip_question_number_prefix(stem_a)
    stem_n, emb_n = _split_stem_embedded_numbered_options(q_cell)
    if stem_n and len(emb_n) >= 2 and _options_texts_align_with_extracted(emb_n, col_texts):
        return _strip_question_number_prefix(stem_n)
    return _strip_question_number_prefix(q_cell)


def _detect_answer_column_index_oqr(rows: list[list[str]], i_o: int, width: int) -> int:
    """Colonne « Réponses » : lettres A–D (souvent dernière colonne du corrigé)."""
    sample = rows[: min(50, len(rows))]
    best_j = width - 1
    best_hits = 0
    for j in range(i_o + 1, width):
        hits = 0
        for r in sample:
            if j >= len(r):
                continue
            cell = (r[j] or "").strip().upper()
            if re.match(r"^[A-D](?:\s*[,;]\s*[A-D])*$", cell) or cell in ("A", "B", "C", "D"):
                hits += 1
        if hits > best_hits:
            best_hits = hits
            best_j = j
    return best_j


def _first_ordre_row_index(rows: list[list[str]]) -> int | None:
    for i, r in enumerate(rows):
        if _parse_ordre_cell((r[0] if r else "") or "") is not None:
            return i
    return None


def _table_has_option_rows(rows: list[list[str]]) -> bool:
    """Lignes de propositions (a) b) …) sans numéro d’ordre — suite d’une question."""
    pat = re.compile(r"(?:^|\n)\s*[A-Ha-h1-9]\s*[\)\.]\s*\S", re.MULTILINE)
    for r in rows:
        for c in r:
            if c and pat.search(c):
                return True
    return False


def _spec_is_plausible(spec: dict) -> bool:
    """Évite d’écraser une bonne question par un tableau PDF mal découpé."""
    n_opts = len(spec.get("texts") or [])
    return 2 <= n_opts <= 8 and bool((spec.get("prompt") or "").strip())


def _spec_richness(spec: dict) -> tuple[int, int]:
    return (len(spec.get("texts") or []), len(spec.get("prompt") or ""))


def _enrich_spec_with_continuation(spec: dict, continuation_parts: list[str]) -> dict:
    """Ajoute la suite d’une question (ex. options c) d) sur la page suivante)."""
    extra = "\n".join(p for p in continuation_parts if p).strip()
    if not extra:
        return spec
    _, embedded_extra = _embedded_from_merged_question_text(extra)
    existing = list(spec.get("texts") or [])
    seen = {t.strip().lower() for t in existing}
    merged = list(existing)
    for t in embedded_extra:
        key = t.strip().lower()
        if key and key not in seen:
            merged.append(t)
            seen.add(key)
    if len(merged) <= len(existing):
        combined = f"{spec.get('prompt', '')}\n{extra}".strip()
        stem, embedded = _embedded_from_merged_question_text(combined)
        if len(embedded) > len(existing):
            out = dict(spec)
            out["prompt"] = _normalize_stem_text(stem or spec.get("prompt", ""))
            out["texts"] = embedded
            return out
        return spec
    out = dict(spec)
    out["texts"] = merged
    return out


def _table_correction_layout(rows: list[list[str]]) -> tuple[int, int, int] | None:
    """
    Détecte la structure du corrigé : N° d’ordre | texte question (souvent col. 2) | Réponses.
    Retourne (i_o, i_r, index_première_ligne_données) ou None.
    """
    if not rows:
        return None
    width = max(len(r) for r in rows)
    if width < 3:
        return None

    hdr = _header_ordre_question_reponse_indices(rows[0])
    if hdr:
        return hdr[0], hdr[2], 1

    data_start = 0
    sample = rows[data_start : data_start + min(45, len(rows))]
    ordre_hits = sum(
        1 for r in sample if _parse_ordre_cell((r[0] if r else "") or "") is not None
    )
    i_o = 0
    i_r = _detect_answer_column_index_oqr(rows, i_o, width)

    if ordre_hits >= 2:
        return i_o, i_r, data_start

    if ordre_hits == 1:
        first_ordre = _first_ordre_row_index(rows)
        if first_ordre is not None:
            return i_o, i_r, first_ordre

    if len(rows) >= 2 and _table_has_option_rows(rows):
        return i_o, i_r, data_start

    return None


def _score_correction_table_rows(rows: list[list[str]]) -> int:
    """Nombre de N° d’ordre valides (1–60) dans le tableau."""
    layout = _table_correction_layout(rows)
    if not layout:
        return 0
    i_o, _, data_start = layout
    return sum(
        1
        for r in rows[data_start:]
        if _parse_ordre_cell((r[i_o] if i_o < len(r) else "") or "") is not None
    )


def specs_from_correction_table_rows(rows: list[list[str]]) -> list[dict]:
    """Convertit un tableau corrigé (une ou plusieurs pages) en questions quiz."""
    layout = _table_correction_layout(rows)
    if not layout:
        return []
    i_o, i_r, data_start = layout
    width = max(len(r) for r in rows)
    i_q = i_o + 1 if i_o + 1 < i_r else i_o
    specs = _parse_oqr_multiline_blocks(
        rows[data_start:], i_o=i_o, i_q=i_q, i_r=i_r, width=width
    )
    return _finalize_quiz_specs(specs)


def _header_ordre_question_reponse_indices(header: list[str]) -> tuple[int, int, int] | None:
    """Repère les indices des colonnes « N° d’ordre », « Questions », « Réponses »."""
    norms = [_norm_header(h) for h in header]

    def col_ordre(i: int, n: str) -> bool:
        if "question" in n or "reponse" in n:
            return False
        return (
            "ordre" in n
            or n in ("no", "rang", "index", "item", "numero")
            or re.match(r"^n_o_?d", n)
            or re.match(r"^n_?d_?ordre", n)
        )

    def col_question(i: int, n: str) -> bool:
        return (
            "question" in n
            or n in ("enonce", "intitule", "libelle", "texte", "stem", "prompt", "q")
        )

    def col_reponse(i: int, n: str) -> bool:
        return "reponse" in n or n in ("corrige", "solution", "cle", "key", "rep", "ok")

    i_o = next((i for i, n in enumerate(norms) if col_ordre(i, n)), None)
    i_q = next((i for i, n in enumerate(norms) if col_question(i, n)), None)
    i_r = next((i for i, n in enumerate(norms) if col_reponse(i, n)), None)
    if i_o is None or i_q is None or i_r is None:
        return None
    if len({i_o, i_q, i_r}) != 3:
        return None
    return i_o, i_q, i_r


def _row_merged_content(row: list[str], col_indices: list[int]) -> str:
    """Fusionne le texte des colonnes « question » (souvent réparti sur col. 2–3 dans le PDF)."""
    parts: list[str] = []
    for j in col_indices:
        if j < len(row):
            t = (row[j] or "").strip()
            if t:
                parts.append(t)
    return "\n".join(parts)


def _embedded_from_merged_question_text(full: str) -> tuple[str, list[str]]:
    """Énoncé + propositions A/B/… à partir du bloc texte fusionné (plusieurs lignes PDF)."""
    full = (full or "").strip()
    if not full:
        return "", []
    stem, embedded = _split_stem_and_embedded_options(full)
    if len(embedded) >= 2:
        return _normalize_stem_text(_strip_question_number_prefix(stem)), _normalize_option_texts(embedded)
    stem_n, embedded_n = _split_stem_embedded_numbered_options(full)
    if len(embedded_n) >= 2:
        return _normalize_stem_text(_strip_question_number_prefix(stem_n)), _normalize_option_texts(embedded_n)
    stem_b, embedded_b = _split_stem_embedded_bullet_options(full)
    if len(embedded_b) >= 2:
        return _normalize_stem_text(_strip_question_number_prefix(stem_b)), _normalize_option_texts(embedded_b)
    return _normalize_stem_text(_strip_question_number_prefix(full)), []


def _parse_oqr_multiline_blocks(
    data_rows: list[list[str]],
    *,
    i_o: int,
    i_q: int,
    i_r: int,
    width: int,
) -> list[dict]:
    """
    Corrigé PDF réel : une question occupe plusieurs lignes du tableau.
    - Ligne de tête : N° d’ordre (col. 0) + lettre de réponse (dernière col.)
    - Lignes suivantes : énoncé et « A. … B. … » dans les colonnes centrales (souvent col. 2).
    """
    content_cols = [j for j in range(i_o + 1, i_r)]
    if not content_cols:
        content_cols = [i_q]

    specs: list[dict] = []
    current_n: int | None = None
    current_rep = ""
    block_parts: list[str] = []

    def flush() -> None:
        nonlocal current_n, current_rep, block_parts
        if not _valid_question_number(current_n):
            block_parts = []
            return
        full = "\n".join(block_parts).strip()
        block_parts = []
        if not full:
            return
        stem, embedded = _embedded_from_merged_question_text(full)
        if len(embedded) < 2:
            return
        correct = _correct_indices_from_rep_vs_options(embedded, current_rep)
        prompt = _normalize_stem_text(
            stem or _strip_question_number_prefix(full.splitlines()[0])[:500] or "Question"
        )
        specs.append(_spec_with_number(prompt, embedded, correct, current_n))

    for row in data_rows:
        while len(row) < width:
            row.append("")
        n_ord = _parse_ordre_cell((row[i_o] if i_o < len(row) else "") or "")
        chunk = _row_merged_content(row, content_cols)
        if _valid_question_number(n_ord):
            flush()
            current_n = n_ord
            current_rep = (row[i_r] if i_r < len(row) else "").strip()
            block_parts = [chunk] if chunk else []
        elif current_n is not None and chunk:
            if not re.match(r"^\s*NB\s*:", chunk, flags=re.IGNORECASE):
                block_parts.append(chunk)
    flush()
    return specs


def _rows_look_like_ordre_question_reponse_no_header(rows: list[list[str]]) -> bool:
    """Heuristique : 3 colonnes, 1re colonne = petits entiers sur les premières lignes."""
    if not rows:
        return False
    if not all(len(r) >= 3 for r in rows[: min(10, len(rows))]):
        return False
    sample = rows[: min(8, len(rows))]
    hits = sum(1 for r in sample if _parse_ordre_cell(r[0]) is not None)
    if len(sample) == 1:
        return hits == 1
    return hits >= max(2, len(sample) - 2)


def _try_ordre_question_reponse_table(rows: list[list[str]]) -> list[dict] | None:
    """
    Tableaux type corrigé : N° d’ordre | Questions | … | Réponses.

    - Si des **colonnes de propositions** se trouvent entre « Questions » et « Réponses »
      (ex. A, B, C, D), elles sont utilisées telles que dans le PDF (cas le plus fidèle).
    - Sinon, propositions détectées **dans** la cellule Questions (A., B., …, 1) 2), puces).
    - La colonne « Réponses » sert uniquement aux indices / lettres de correction.
    """
    if not rows:
        return None

    width = max(len(r) for r in rows)
    if width < 3:
        return None

    header = rows[0]
    idx = _header_ordre_question_reponse_indices(header)
    data_start = 1
    if idx is None:
        if width != 3 or not _rows_look_like_ordre_question_reponse_no_header(rows):
            return None
        i_o, i_q, i_r = 0, 1, 2
        data_start = 0
    else:
        if len(rows) < 2:
            return None
        i_o, i_q, i_r = idx

    data_rows = rows[data_start:]
    width = max(width, max((len(r) for r in data_rows), default=0))

    multiline_specs = _parse_oqr_multiline_blocks(
        data_rows, i_o=i_o, i_q=i_q, i_r=i_r, width=width
    )
    if multiline_specs:
        return _finalize_quiz_specs(multiline_specs) or None

    prop_col_indices: list[int] = []
    if i_q < i_r:
        prop_col_indices = [j for j in range(i_q + 1, i_r)]
    content_cols = list(range(i_o + 1, i_r)) or [i_q]

    specs: list[dict] = []
    for row in data_rows:
        while len(row) < width:
            row.append("")
        ordre_s = (row[i_o] if i_o < len(row) else "").strip()
        q_cell = _row_merged_content(row, content_cols) or (row[i_q] if i_q < len(row) else "").strip()
        rep_cell = (row[i_r] if i_r < len(row) else "").strip()
        if not q_cell:
            continue
        n_ord = _parse_ordre_cell(ordre_s)
        if not _valid_question_number(n_ord):
            continue

        embedded: list[str] = []
        stem = ""
        texts_from_cols = (
            [(row[j] if j < len(row) else "").strip() for j in prop_col_indices]
            if len(prop_col_indices) >= 2
            else []
        )
        filled_cols = [t for t in texts_from_cols if t]
        used_col_options = len(prop_col_indices) >= 2 and len(filled_cols) >= 2
        if used_col_options:
            embedded = texts_from_cols
            stem = _stem_for_oqr_with_column_options(q_cell, embedded)
        else:
            stem, embedded = _split_stem_and_embedded_options(q_cell)
            if len(embedded) < 2:
                stem_n, embedded_n = _split_stem_embedded_numbered_options(q_cell)
                if len(embedded_n) >= 2:
                    stem, embedded = stem_n, embedded_n
            if len(embedded) < 2:
                stem_b, embedded_b = _split_stem_embedded_bullet_options(q_cell)
                if len(embedded_b) >= 2:
                    stem, embedded = stem_b, embedded_b
        if len(embedded) < 2:
            continue

        if used_col_options:
            correct = sorted(
                {i for i in _parse_reponses_cell(rep_cell) if 1 <= i <= len(embedded)}
            )
        else:
            correct = _correct_indices_from_rep_vs_options(embedded, rep_cell)

        main = _strip_question_number_prefix(stem) if stem else ""
        if not main and q_cell and used_col_options:
            main = _strip_question_number_prefix(q_cell)
        elif not main and q_cell and not used_col_options:
            first_ln = q_cell.splitlines()[0].strip()
            if first_ln and not re.match(r"^[A-Ha-h]\s*[\.\)\:、\-–]", first_ln):
                main = _strip_question_number_prefix(first_ln)[:500]
        prompt = main or _strip_question_number_prefix(q_cell)[:400] or "Question"
        specs.append(_spec_with_number(prompt, embedded, correct, n_ord))

    return _finalize_quiz_specs(specs) or None


def _normalize_matrix_cell_text(raw: object) -> str:
    """
    Nettoie une cellule de tableau sans fusionner les paragraphes.
    Les corrigés mettent souvent l’énoncé puis, sur les lignes suivantes, « A. … B. … »
    dans la même cellule : il faut conserver les retours à la ligne.
    """
    if raw is None:
        return ""
    s = str(raw).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    lines: list[str] = []
    for ln in s.split("\n"):
        t = re.sub(r"[ \t\u00a0]+", " ", ln).strip()
        if t:
            lines.append(t)
    return "\n".join(lines)


def _normalize_matrix_rows(raw_rows: list[list]) -> list[list[str]]:
    """Convertit une table (PDF/CSV) en lignes de chaînes, cellules None → ''. Les sauts de ligne à l’intérieur d’une cellule sont conservés."""
    out: list[list[str]] = []
    for raw in raw_rows:
        if raw is None:
            continue
        row = []
        for c in raw:
            row.append(_normalize_matrix_cell_text(c))
        if any(cell for cell in row):
            out.append(row)
    return out


def _matrix_rows_to_question_specs_with_header(rows: list[list[str]], skip_header: bool) -> list[dict]:
    if not rows or len(rows) < 2:
        return []
    data_rows = rows[1:] if skip_header else rows
    width = max((len(r) for r in rows), default=0)
    if width < 3:
        return []

    qi, ri = 0, width - 1
    prop_indices: list[int] = []

    if skip_header:
        header = rows[0]
        width = max(width, len(header))
        norms = [_norm_header(h) for h in header] if header else []

        def idx_of(pred) -> int | None:
            for i, n in enumerate(norms):
                if pred(n):
                    return i
            return None

        if norms:
            qi = idx_of(
                lambda n: n
                in (
                    "question",
                    "enonce",
                    "intitule",
                    "intitule_de_la_question",
                    "libelle",
                    "libelle_question",
                    "item",
                    "texte",
                    "q",
                    "n",
                    "no",
                    "numero",
                    "n_question",
                    "titre",
                    "stem",
                    "prompt",
                )
            )
            ri = idx_of(
                lambda n: n
                in (
                    "reponses",
                    "reponse",
                    "reponses_correctes",
                    "reponse_correcte",
                    "bons_indices",
                    "bonne_reponse",
                    "correct",
                    "corrige",
                    "cle",
                    "key",
                    "rep",
                    "reps",
                    "solution",
                    "solutions",
                    "justification",
                    "ok",
                )
            )
        if qi is None:
            qi = 0
        if ri is None:
            ri = width - 1 if width > 2 else width - 1
        prop_indices = sorted(
            i
            for i in range(width)
            if not _exclude_column_from_propositions(
                i, qi=qi, ri=ri, norms=norms, data_rows=data_rows
            )
        )
        if not prop_indices and ri > qi + 1:
            prop_indices = list(range(qi + 1, ri))
    else:
        prop_indices = list(range(1, ri)) if ri > 1 else []

    if len(prop_indices) < 2:
        return []

    specs: list[dict] = []
    for row in data_rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        while len(row) < width:
            row.append("")
        qtext = _strip_question_number_prefix((row[qi] if qi < len(row) else "").strip())
        if not qtext:
            continue
        rep_cell = (row[ri] if ri < len(row) else "").strip()
        correct_idx = _parse_reponses_cell(rep_cell)
        texts = [(row[i] if i < len(row) else "").strip() for i in prop_indices]
        if len(texts) < 2 or not all(texts):
            continue
        qnum = _parse_ordre_cell(row[0]) if qi != 0 and _column_data_looks_like_ordre_index(data_rows, 0) else None
        specs.append(_spec_with_number(qtext, texts, correct_idx, qnum))

    return specs


def matrix_rows_to_question_specs(rows: list[list[str]]) -> list[dict]:
    """
    Interprète une matrice : ligne 0 = en-têtes (cas tableur), puis lignes de questions.

    Colonne « question » (ou 1re colonne), colonnes propositions, colonne « réponses »
    (ou dernière colonne). Si aucune question n’est trouvée, réessaie en traitant
    toutes les lignes comme données (PDF sans ligne d’en-tête textuelle).
    """
    rows = _rectangularize_rows(_normalize_matrix_rows(rows))
    if not rows:
        return []
    oqr = _try_ordre_question_reponse_table(rows)
    if oqr:
        return oqr
    specs = _matrix_rows_to_question_specs_with_header(rows, skip_header=True)
    if specs:
        return _finalize_quiz_specs(specs)
    specs = _matrix_rows_to_question_specs_with_header(rows, skip_header=False)
    if specs:
        return _finalize_quiz_specs(specs)
    ri = _detect_answer_column_index(rows)
    if ri is not None and ri > 0:
        alt = _matrix_rows_to_question_specs_with_columns(rows, qi=0, ri=ri)
        if alt:
            return _finalize_quiz_specs(alt)
    if len(rows) >= 2:
        body = rows[1:]
        ri2 = _detect_answer_column_index(body)
        if ri2 is not None and ri2 > 0:
            alt2 = _matrix_rows_to_question_specs_with_columns(body, qi=0, ri=ri2)
            if alt2:
                return _finalize_quiz_specs(alt2)
    return []


def _matrix_rows_to_question_specs_with_columns(
    rows: list[list[str]], *, qi: int, ri: int
) -> list[dict]:
    """Construit les questions en fixant explicitement les indices question / réponses."""
    if not rows or len(rows) < 1:
        return []
    width = max((len(r) for r in rows), default=0)
    if width < 3 or ri >= width or qi >= width or qi == ri:
        return []
    prop_indices = sorted(
        i
        for i in range(width)
        if not _exclude_column_from_propositions(i, qi=qi, ri=ri, norms=[], data_rows=rows)
    )
    if len(prop_indices) < 2:
        return []
    specs: list[dict] = []
    for row in rows:
        if not row or all(not (c or "").strip() for c in row):
            continue
        while len(row) < width:
            row.append("")
        qtext = _strip_question_number_prefix((row[qi] if qi < len(row) else "").strip())
        if not qtext:
            continue
        rep_cell = (row[ri] if ri < len(row) else "").strip()
        correct_idx = _parse_reponses_cell(rep_cell)
        texts = [(row[i] if i < len(row) else "").strip() for i in prop_indices]
        if len(texts) < 2 or not all(texts):
            continue
        qnum = _parse_ordre_cell(row[0]) if qi != 0 and _column_data_looks_like_ordre_index(rows, 0) else None
        specs.append(_spec_with_number(qtext, texts, correct_idx, qnum))
    return specs


def _clip(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def apply_question_specs_to_quiz(
    quiz,
    specs: list[dict],
    *,
    question_model=None,
    option_model=None,
    quiz_fk_field: str = "quiz",
) -> tuple[int, int]:
    """Remplace toutes les questions du quiz. Retourne (lignes, nombre_questions)."""
    from .models import ExamQuizOption, ExamQuizQuestion, QuizOption, QuizQuestion

    if question_model is None:
        question_model = QuizQuestion
    if option_model is None:
        option_model = QuizOption

    specs = _finalize_quiz_specs(specs)

    quiz.questions.all().delete()
    n_questions = 0
    for spec in specs:
        prompt = _clip(_normalize_stem_text(spec["prompt"]), 4000)
        qnum = spec["number"]
        qq = question_model.objects.create(
            **{quiz_fk_field: quiz},
            order=qnum - 1,
            prompt=prompt,
        )
        n_questions += 1
        correct = set(spec["correct"])
        for j, t in enumerate(spec["texts"], start=1):
            option_model.objects.create(
                question=qq,
                order=j - 1,
                text=_clip(strip_nb_references(t), 500),
                is_correct=j in correct,
            )
    return len(specs), n_questions


def import_quiz_from_csv(
    quiz,
    fileobj: BinaryIO,
    *,
    question_model=None,
    option_model=None,
    quiz_fk_field: str = "quiz",
) -> tuple[int, int]:
    """
    Remplace les questions du quiz par le contenu d’un fichier CSV.

    Même logique de colonnes qu’à l’export d’un tableau depuis le PDF :
    question, propositions…, colonne réponses (indices 1,2,3… ou A,B… ; plusieurs : 1,3).
    """
    raw = fileobj.read()
    if isinstance(raw, str):
        text = raw
    else:
        text = raw.decode("utf-8-sig")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.reader(io.StringIO(text), dialect)
    raw_rows = list(reader)
    specs = matrix_rows_to_question_specs(raw_rows)
    return apply_question_specs_to_quiz(
        quiz,
        specs,
        question_model=question_model,
        option_model=option_model,
        quiz_fk_field=quiz_fk_field,
    )
