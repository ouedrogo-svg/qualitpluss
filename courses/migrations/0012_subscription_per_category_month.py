from django.db import migrations, models
import django.db.models.deletion


def assign_default_category(apps, schema_editor):
    Category = apps.get_model("courses", "Category")
    SubscriptionRequest = apps.get_model("courses", "SubscriptionRequest")
    UserSubscription = apps.get_model("courses", "UserSubscription")
    default = Category.objects.order_by("pk").first()
    if not default:
        return
    SubscriptionRequest.objects.filter(category__isnull=True).update(category=default)
    UserSubscription.objects.filter(category__isnull=True).update(category=default)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0011_month_linked_subscription"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="usersubscription",
            name="unique_user_month_subscription",
        ),
        migrations.AddField(
            model_name="subscriptionrequest",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscription_requests",
                to="courses.category",
                verbose_name="catégorie",
            ),
        ),
        migrations.AddField(
            model_name="usersubscription",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="month_subscriptions",
                to="courses.category",
                verbose_name="catégorie",
            ),
        ),
        migrations.RunPython(assign_default_category, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="subscriptionrequest",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="subscription_requests",
                to="courses.category",
                verbose_name="catégorie",
            ),
        ),
        migrations.AlterField(
            model_name="usersubscription",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="month_subscriptions",
                to="courses.category",
                verbose_name="catégorie",
            ),
        ),
        migrations.AddConstraint(
            model_name="usersubscription",
            constraint=models.UniqueConstraint(
                fields=("user", "category", "year", "month"),
                name="unique_user_category_month_subscription",
            ),
        ),
    ]
