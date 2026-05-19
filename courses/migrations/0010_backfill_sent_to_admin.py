from django.db import migrations


def mark_existing_attempts_sent(apps, schema_editor):
    ExamQuizAttempt = apps.get_model("courses", "ExamQuizAttempt")
    ExamQuizAttempt.objects.filter(sent_to_admin=False).update(sent_to_admin=True)


class Migration(migrations.Migration):

    dependencies = [
        ("courses", "0009_exam_duration_and_admin_submission"),
    ]

    operations = [
        migrations.RunPython(mark_existing_attempts_sent, migrations.RunPython.noop),
    ]
