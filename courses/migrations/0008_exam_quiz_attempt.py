import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0007_monthly_exams"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamQuizAttempt",
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
                (
                    "score_points",
                    models.PositiveSmallIntegerField(verbose_name="note (points)"),
                ),
                (
                    "score_percent",
                    models.DecimalField(
                        blank=True,
                        decimal_places=1,
                        max_digits=5,
                        null=True,
                        verbose_name="note (%)",
                    ),
                ),
                (
                    "submitted_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="soumis le"),
                ),
                (
                    "exam",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quiz_attempts",
                        to="courses.monthlyexam",
                        verbose_name="examen",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_quiz_attempts",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="candidat",
                    ),
                ),
            ],
            options={
                "verbose_name": "résultat d’examen",
                "verbose_name_plural": "résultats d’examens",
                "ordering": ["-submitted_at"],
            },
        ),
        migrations.AddIndex(
            model_name="examquizattempt",
            index=models.Index(
                fields=["exam", "-score_points"], name="courses_exa_exam_id_6a8f2d_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="examquizattempt",
            index=models.Index(fields=["exam", "user"], name="courses_exa_exam_id_9c4e1a_idx"),
        ),
    ]
