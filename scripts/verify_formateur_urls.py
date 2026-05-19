#!/usr/bin/env python
"""Vérifie les URLs de l'espace formateur (reverse, resolve, templates)."""
import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.urls import NoReverseMatch, resolve, reverse

FORMATEUR_NAMES = [
    "formateur_dashboard",
    "formateur_category_list",
    "formateur_category_create",
    "formateur_category_edit",
    "formateur_category_delete",
    "formateur_monthly_content_list",
    "formateur_monthly_content_create",
    "formateur_monthly_content_edit",
    "formateur_monthly_content_delete",
    "formateur_correction_list",
    "formateur_correction_create",
    "formateur_correction_edit",
    "formateur_correction_delete",
    "formateur_exam_list",
    "formateur_exam_create",
    "formateur_exam_edit",
    "formateur_exam_delete",
    "formateur_exam_results_export",
    "formateur_subscription_list",
    "formateur_subscription_edit",
    "formateur_subscription_approve",
    "formateur_subscription_reject",
    "formateur_recap_subscriptions",
    "formateur_recap_export_all",
    "formateur_recap_export_month",
]

KWARGS_MAP = {
    "formateur_category_edit": {"pk": 1},
    "formateur_category_delete": {"pk": 1},
    "formateur_monthly_content_edit": {"pk": 1},
    "formateur_monthly_content_delete": {"pk": 1},
    "formateur_correction_edit": {"pk": 1},
    "formateur_correction_delete": {"pk": 1},
    "formateur_exam_edit": {"pk": 1},
    "formateur_exam_delete": {"pk": 1},
    "formateur_exam_results_export": {"pk": 1},
    "formateur_subscription_edit": {"pk": 1},
    "formateur_subscription_approve": {"pk": 1},
    "formateur_subscription_reject": {"pk": 1},
    "formateur_recap_export_month": {"month_str": "2026-05"},
}

RESOLVE_PATHS = [
    ("/espace-formateur/", "courses:formateur_dashboard"),
    ("/espace-formateur/categories/", "courses:formateur_category_list"),
    ("/espace-formateur/categories/nouvelle/", "courses:formateur_category_create"),
    ("/espace-formateur/categories/1/modifier/", "courses:formateur_category_edit"),
    ("/espace-formateur/sujets-pdf/nouveau/", "courses:formateur_monthly_content_create"),
    ("/espace-formateur/examens/nouveau/", "courses:formateur_exam_create"),
    ("/espace-formateur/examens/1/export-resultats.xlsx", "courses:formateur_exam_results_export"),
    ("/espace-formateur/abonnements/1/", "courses:formateur_subscription_edit"),
    ("/espace-formateur/abonnements/1/approuver/", "courses:formateur_subscription_approve"),
    ("/espace-formateur/recap-abonnements/export.xlsx", "courses:formateur_recap_export_all"),
    ("/espace-formateur/recap-abonnements/export-2026-05.xlsx", "courses:formateur_recap_export_month"),
]


def main():
    errors = []
    print("=== reverse() ===")
    for name in FORMATEUR_NAMES:
        kw = KWARGS_MAP.get(name, {})
        try:
            url = reverse(f"courses:{name}", kwargs=kw)
            print(f"  OK  {name:42} -> {url}")
        except NoReverseMatch as e:
            errors.append(f"reverse courses:{name}: {e}")
            print(f"  ERR {name}: {e}")

    print("\n=== resolve() ===")
    for path, expected in RESOLVE_PATHS:
        try:
            match = resolve(path)
            ok = match.view_name == expected
            status = "OK" if ok else "MISMATCH"
            if not ok:
                errors.append(f"resolve {path}: expected {expected}, got {match.view_name}")
            print(f"  {status}  {path} -> {match.view_name}")
        except Exception as e:
            errors.append(f"resolve {path}: {e}")
            print(f"  ERR {path}: {e}")

    from courses.subscription_recap import (
        formateur_subscription_recap_global_export_url,
        formateur_subscription_recap_month_export_url,
    )

    print("\n=== subscription_recap helpers ===")
    g = formateur_subscription_recap_global_export_url()
    m = formateur_subscription_recap_month_export_url(2026, 5)
    print(f"  global: {g}")
    print(f"  month:  {m}")
    try:
        resolve(g)
        resolve(m)
        print("  OK  both resolve")
    except Exception as e:
        errors.append(f"recap helper resolve: {e}")
        print(f"  ERR {e}")

    print("\n=== templates {% url %} ===")
    pattern = re.compile(r"url\s+'courses:(formateur_[^']+)'")
    found = set()
    tpl_dir = BASE / "templates"
    for f in tpl_dir.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            found.add(m.group(1))
    for n in sorted(found):
        if n not in FORMATEUR_NAMES:
            errors.append(f"template unknown url name: {n}")
            print(f"  WARN unknown: {n}")
    missing_in_tpl = set(FORMATEUR_NAMES) - found - {
        "formateur_recap_export_all",
        "formateur_recap_export_month",
        "formateur_subscription_approve",
        "formateur_subscription_reject",
    }
    print(f"  {len(found)} names referenced in templates")
    if missing_in_tpl:
        print(f"  (not in templates, OK if export/action only: {sorted(missing_in_tpl)})")

    print("\n=== distinction formateur/ vs espace-formateur/ ===")
    old = [
        reverse("courses:course_create"),
        reverse("courses:my_teaching"),
    ]
    new = reverse("courses:formateur_dashboard")
    print(f"  cours catalogue (ancien): {old[0]}, {old[1]}")
    print(f"  contenu plateforme (nouveau): {new}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} error(s)")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print("SUCCESS: all formateur URLs verified.")


if __name__ == "__main__":
    main()
