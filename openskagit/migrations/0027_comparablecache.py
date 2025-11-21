from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openskagit', '0026_assessor_centroid_geog_assessor_embedding_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ComparableCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('parcel_number', models.CharField(db_index=True, max_length=20)),
                ('roll_year', models.IntegerField(db_index=True)),
                ('radius_meters', models.IntegerField()),
                ('limit', models.IntegerField()),
                ('comparables', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('last_refreshed', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'comparable_cache',
                'unique_together': {('parcel_number', 'roll_year', 'radius_meters', 'limit')},
                'indexes': [
                    models.Index(fields=['parcel_number', 'roll_year'], name='openskagit_compcache_parcel_roll_idx'),
                ],
            },
        ),
    ]
