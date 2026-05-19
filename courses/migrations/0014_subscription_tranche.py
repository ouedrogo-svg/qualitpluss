# Generated manually for tranche d'abonnement

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0013_plan_included_months"),
    ]

    operations = [
        migrations.AlterField(
            model_name="subscriptionplan",
            name="billing_period",
            field=models.CharField(
                choices=[
                    ("monthly", "Mensuel"),
                    ("yearly", "Annuel"),
                    ("tranche", "Tranche"),
                ],
                max_length=20,
                verbose_name="période",
            ),
        ),
        migrations.AddField(
            model_name="subscriptionplan",
            name="name",
            field=models.CharField(
                blank=True,
                help_text="Obligatoire pour une tranche (ex. « Pack 6 mois »). Ignoré pour mensuel / annuel.",
                max_length=120,
                verbose_name="nom de la tranche",
            ),
        ),
        migrations.AlterModelOptions(
            name="subscriptionplan",
            options={
                "ordering": ["billing_period", "name", "pk"],
                "verbose_name": "option d’abonnement",
                "verbose_name_plural": "options d’abonnement",
            },
        ),
        migrations.AddConstraint(
            model_name="subscriptionplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("billing_period", "monthly")),
                fields=("billing_period",),
                name="unique_monthly_subscription_plan",
            ),
        ),
        migrations.AddConstraint(
            model_name="subscriptionplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("billing_period", "yearly")),
                fields=("billing_period",),
                name="unique_yearly_subscription_plan",
            ),
        ),
        migrations.CreateModel(
            name="SubscriptionPlanMonth",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("year", models.PositiveIntegerField(verbose_name="année")),
                (
                    "month",
                    models.PositiveIntegerField(
                        choices=[
                            (1, "janvier"),
                            (2, "février"),
                            (3, "mars"),
                            (4, "avril"),
                            (5, "mai"),
                            (6, "juin"),
                            (7, "juillet"),
                            (8, "août"),
                            (9, "septembre"),
                            (10, "octobre"),
                            (11, "novembre"),
                            (12, "décembre"),
                        ],
                        verbose_name="mois",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        limit_choices_to={"billing_period": "tranche"},
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="plan_months",
                        to="courses.subscriptionplan",
                        verbose_name="formule",
                    ),
                ),
            ],
            options={
                "verbose_name": "mois de la tranche",
                "verbose_name_plural": "mois de la tranche",
                "ordering": ["year", "month"],
            },
        ),
        migrations.AddConstraint(
            model_name="subscriptionplanmonth",
            constraint=models.UniqueConstraint(
                fields=("plan", "year", "month"),
                name="unique_plan_month_in_tranche",
            ),
        ),
    ]
