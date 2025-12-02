from django.db import migrations, models
import django.contrib.gis.db.models.fields as gis_models


class Migration(migrations.Migration):

    dependencies = [
        ('openskagit', '0033_adjustmentrunsummary_content'),
    ]

    operations = [

        # --- TERRAIN FIELDS ---
        migrations.AddField(
            model_name='assessor',
            name='elevation',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='slope',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='aspect',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='aspect_dir',
            field=models.TextField(null=True, blank=True),
        ),

        # --- FLOOD FIELDS ---
        migrations.AddField(
            model_name='assessor',
            name='in_flood_zone',
            field=models.BooleanField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_distance',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_static_bfe',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_depth',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_velocity',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_sfha',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_zone',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_zone_subtype',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='flood_zone_id',
            field=models.TextField(null=True, blank=True),
        ),

        # --- DISTANCE FIELDS ---
        migrations.AddField(
            model_name='assessor',
            name='dist_major_road',
            field=models.FloatField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='dist_floodway',
            field=models.FloatField(null=True, blank=True),
        ),

        # --- GEOMETRY FIELDS (OPTIONAL) ---
        # If you want Django to be aware of them:
        migrations.AddField(
            model_name='assessor',
            name='geom_backup',
            field=gis_models.GeometryField(srid=3857, null=True, blank=True),
        ),
        migrations.AddField(
            model_name='assessor',
            name='geom_2926',
            field=gis_models.MultiPolygonField(srid=2926, null=True, blank=True),
        ),

        # geom_4326 is generated in SQL, you typically do NOT define it in Django.
    ]
