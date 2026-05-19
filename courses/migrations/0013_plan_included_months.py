from django.db import migrations, models


def set_default_included_months(apps, schema_editor):
    SubscriptionPlan = apps.get_model("courses", "SubscriptionPlan")
    SubscriptionPlan.objects.filter(billing_period="monthly").update(included_months=1)
    SubscriptionPlan.objects.filter(billing_period="yearly").update(included_months=12)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0012_subscription_per_category_month"),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionplan",
            name="included_months",
            field=models.PositiveSmallIntegerField(
                default=1,
                help_text="Mensuel : laisser 1. Annuel : nombre de mois d’accès consécutifs "
                "(ex. 6, 7, 12) à partir du mois de départ choisi par le candidat.",
                verbose_name="nombre de mois inclus",
            ),
        ),
        migrations.RunPython(set_default_included_months, migrations.RunPython.noop),
    ]
