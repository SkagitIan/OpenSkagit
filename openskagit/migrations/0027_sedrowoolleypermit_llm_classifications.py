from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0026_sedrowoolleypermit_sedrowoolleypermitsyncrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="sedrowoolleypermit",
            name="completion_confidence",
            field=models.DecimalField(blank=True, decimal_places=3, max_digits=4, null=True),
        ),
        migrations.AddField(
            model_name="sedrowoolleypermit",
            name="data_quality_flags",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="sedrowoolleypermit",
            name="project_type_normalized",
            field=models.CharField(
                blank=True,
                choices=[
                    ("new_sfr", "New SFR"),
                    ("new_mf", "New MF"),
                    ("adu", "ADU"),
                    ("addition", "Addition"),
                    ("remodel", "Remodel"),
                    ("demo", "Demo"),
                    ("site_civil", "Site / Civil"),
                    ("utility", "Utility"),
                    ("other", "Other"),
                ],
                db_index=True,
                default="",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="sedrowoolleypermit",
            name="scope_intensity",
            field=models.CharField(
                blank=True,
                choices=[
                    ("major", "Major"),
                    ("moderate", "Moderate"),
                    ("minor", "Minor"),
                    ("admin_only", "Admin Only"),
                ],
                db_index=True,
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="sedrowoolleypermit",
            name="taxability_class",
            field=models.CharField(
                choices=[
                    ("high_taxable", "High Taxable"),
                    ("medium_taxable", "Medium Taxable"),
                    ("low_taxable", "Low Taxable"),
                    ("non_taxable", "Non-Taxable"),
                    ("unknown", "Unknown"),
                ],
                db_index=True,
                default="unknown",
                max_length=20,
            ),
        ),
    ]
