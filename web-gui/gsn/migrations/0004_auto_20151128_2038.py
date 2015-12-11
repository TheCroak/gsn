# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('gsn', '0003_auto_20151128_2028'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gsnuser',
            name='access_token',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='gsnuser',
            name='refresh_token',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AlterField(
            model_name='gsnuser',
            name='token_created_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='gsnuser',
            name='token_expire_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]