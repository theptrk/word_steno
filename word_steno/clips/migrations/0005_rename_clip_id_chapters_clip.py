# Generated by Django 4.2.10 on 2024-02-28 15:45

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('clips', '0004_chapters'),
    ]

    operations = [
        migrations.RenameField(
            model_name='chapters',
            old_name='clip_id',
            new_name='clip',
        ),
    ]
