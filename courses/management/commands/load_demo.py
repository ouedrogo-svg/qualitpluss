from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from courses.models import Category, Course, Lesson, SubscriptionPlan


class Command(BaseCommand):
    help = "Charge des catégories, cours, leçons et formules d’abonnement de démonstration."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username="demo",
            defaults={"email": "demo@example.com"},
        )
        if created:
            user.set_password("demo1234")
            user.save()

        cat_prog, _ = Category.objects.get_or_create(name="Programmation", defaults={"slug": "programmation"})
        cat_data, _ = Category.objects.get_or_create(name="Données", defaults={"slug": "donnees"})

        monthly, _ = SubscriptionPlan.objects.get_or_create(
            billing_period=SubscriptionPlan.BillingPeriod.MONTHLY,
            defaults={"amount": "5000.00", "is_active": True, "included_months": 1},
        )
        monthly.included_months = 1
        monthly.save(update_fields=["included_months"])
        yearly, _ = SubscriptionPlan.objects.get_or_create(
            billing_period=SubscriptionPlan.BillingPeriod.YEARLY,
            defaults={"amount": "50000.00", "is_active": True, "included_months": 12},
        )
        if yearly.included_months < 2:
            yearly.included_months = 12
            yearly.save(update_fields=["included_months"])

        c1, created1 = Course.objects.get_or_create(
            slug="introduction-a-django",
            defaults={
                "title": "Introduction à Django",
                "short_description": "Créez des sites web avec Python et le framework Django.",
                "description": "Ce cours couvre les bases : modèles, vues, templates et administration. Idéal pour débuter le développement web côté serveur.",
                "category": cat_prog,
                "instructor": user,
                "published": True,
            },
        )
        if created1:
            Lesson.objects.bulk_create(
                [
                    Lesson(
                        course=c1,
                        title="Bienvenue",
                        order=0,
                        content="<p>Bienvenue dans ce cours Django. Vous apprendrez à structurer un projet et à servir des pages dynamiques.</p>",
                    ),
                    Lesson(
                        course=c1,
                        title="Modèles et base de données",
                        order=1,
                        content="<p>Les <strong>modèles</strong> décrivent vos tables. Django génère les migrations et applique les changements à SQLite ou PostgreSQL.</p>",
                    ),
                    Lesson(
                        course=c1,
                        title="Templates",
                        order=2,
                        content="<p>Les templates séparent la présentation du code Python. Utilisez le langage de gabarit Django pour afficher les données.</p>",
                    ),
                ]
            )

        c2, created2 = Course.objects.get_or_create(
            slug="analyse-de-donnees",
            defaults={
                "title": "Analyse de données — bases",
                "short_description": "Comprendre et résumer des jeux de données.",
                "description": "Introduction aux statistiques descriptives, visualisations et bonnes pratiques pour explorer des données.",
                "category": cat_data,
                "instructor": user,
                "published": True,
            },
        )
        if created2:
            Lesson.objects.bulk_create(
                [
                    Lesson(
                        course=c2,
                        title="Types de variables",
                        order=0,
                        content="<p>Variables quantitatives et qualitatives, échelles de mesure.</p>",
                    ),
                    Lesson(
                        course=c2,
                        title="Visualisations",
                        order=1,
                        content="<p>Histogrammes, nuages de points et tableaux croisés pour communiquer des résultats.</p>",
                    ),
                ]
            )

        self.stdout.write(self.style.SUCCESS("Compte démo : demo / demo1234 — cours créés si absents."))
