from datetime import date

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


def forwards_migrate_subscriptions(apps, schema_editor):
    UserSubscription = apps.get_model("courses", "UserSubscription")
    SubscriptionRequest = apps.get_model("courses", "SubscriptionRequest")
    today = date.today()
    default_year, default_month = today.year, today.month
    now = timezone.now()

    for req in SubscriptionRequest.objects.all():
        if req.year is None:
            req.year = default_year
        if req.month is None:
            req.month = default_month
        req.save(update_fields=["year", "month"])

    for sub in UserSubscription.objects.all():
        if sub.year is None:
            sub.year = default_year
        if sub.month is None:
            sub.month = default_month
        if not sub.granted_at:
            sub.granted_at = getattr(sub, "updated_at", None) or now
        sub.save(update_fields=["year", "month", "granted_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0010_backfill_sent_to_admin"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="subscriptionrequest",
            name="year",
            field=models.PositiveIntegerField(
                null=True,
                verbose_name="année du contenu",
                help_text="Mois de publication auquel la demande donne accès après validation.",
            ),
        ),
        migrations.AddField(
            model_name="subscriptionrequest",
            name="month",
            field=models.PositiveIntegerField(
                null=True,
                choices=[
                    (1, "Janvier"),
                    (2, "Février"),
                    (3, "Mars"),
                    (4, "Avril"),
                    (5, "Mai"),
                    (6, "Juin"),
                    (7, "Juillet"),
                    (8, "Août"),
                    (9, "Septembre"),
                    (10, "Octobre"),
                    (11, "Novembre"),
                    (12, "Décembre"),
                ],
                verbose_name="mois du contenu",
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="year",
            field=models.PositiveIntegerField(null=True, verbose_name="année du contenu"),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="month",
            field=models.PositiveIntegerField(
                null=True,
                choices=[
                    (1, "Janvier"),
                    (2, "Février"),
                    (3, "Mars"),
                    (4, "Avril"),
                    (5, "Mai"),
                    (6, "Juin"),
                    (7, "Juillet"),
                    (8, "Août"),
                    (9, "Septembre"),
                    (10, "Octobre"),
                    (11, "Novembre"),
                    (12, "Décembre"),
                ],
                verbose_name="mois du contenu",
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="granted_at",
            field=models.DateTimeField(null=True, verbose_name="accordé le"),
        ),
        migrations.RunPython(forwards_migrate_subscriptions, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="usersubscription",
            name="valid_until",
        ),
        migrations.RemoveField(
            model_name="usersubscription",
            name="updated_at",
        ),
        migrations.AlterField(
            model_name="subscriptionrequest",
            name="year",
            field=models.PositiveIntegerField(
                verbose_name="année du contenu",
                help_text="Mois de publication auquel la demande donne accès après validation.",
            ),
        ),
        migrations.AlterField(
            model_name="subscriptionrequest",
            name="month",
            field=models.PositiveIntegerField(
                choices=[
                    (1, "Janvier"),
                    (2, "Février"),
                    (3, "Mars"),
                    (4, "Avril"),
                    (5, "Mai"),
                    (6, "Juin"),
                    (7, "Juillet"),
                    (8, "Août"),
                    (9, "Septembre"),
                    (10, "Octobre"),
                    (11, "Novembre"),
                    (12, "Décembre"),
                ],
                verbose_name="mois du contenu",
            ),
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="month_subscriptions",
                to=settings.AUTH_USER_MODEL,
                verbose_name="utilisateur",
            ),
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="year",
            field=models.PositiveIntegerField(verbose_name="année du contenu"),
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="month",
            field=models.PositiveIntegerField(
                choices=[
                    (1, "Janvier"),
                    (2, "Février"),
                    (3, "Mars"),
                    (4, "Avril"),
                    (5, "Mai"),
                    (6, "Juin"),
                    (7, "Juillet"),
                    (8, "Août"),
                    (9, "Septembre"),
                    (10, "Octobre"),
                    (11, "Novembre"),
                    (12, "Décembre"),
                ],
                verbose_name="mois du contenu",
            ),
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="granted_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="accordé le"),
        ),
        migrations.AlterModelOptions(
            name="usersubscription",
            options={
                "ordering": ["-year", "-month", "user__username"],
                "verbose_name": "abonnement mensuel",
                "verbose_name_plural": "abonnements mensuels",
            },
        ),
        migrations.AddConstraint(
            model_name="usersubscription",
            constraint=models.UniqueConstraint(
                fields=("user", "year", "month"),
                name="unique_user_month_subscription",
            ),
        ),
    ]
