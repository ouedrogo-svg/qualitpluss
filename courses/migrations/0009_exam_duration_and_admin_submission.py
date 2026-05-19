from django.db import migrations, models


def mark_existing_attempts_sent(apps, schema_editor):
    ExamQuizAttempt = apps.get_model("courses", "ExamQuizAttempt")
    ExamQuizAttempt.objects.all().update(sent_to_admin=True)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0008_exam_quiz_attempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="monthlyexam",
            name="duration_minutes",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Temps imparti au candidat pour valider le quiz une fois l’épreuve commencée.",
                verbose_name="durée de l’examen (minutes)",
            ),
        ),
        migrations.AddField(
            model_name="monthlyexam",
            name="results_collection_days",
            field=models.PositiveIntegerField(
                default=7,
                help_text="Nombre de jours après la création de l’examen pendant lesquels la première "
                "composition de chaque candidat est enregistrée pour l’administrateur.",
                verbose_name="collecte des résultats (jours)",
            ),
        ),
        migrations.AddField(
            model_name="examquizattempt",
            name="sent_to_admin",
            field=models.BooleanField(
                default=False,
                help_text="Vrai uniquement pour la première composition enregistrée dans le délai de collecte.",
                verbose_name="transmis à l’administrateur",
            ),
        ),
        migrations.RunPython(mark_existing_attempts_sent, migrations.RunPython.noop),
    ]
