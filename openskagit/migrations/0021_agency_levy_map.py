from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0020_codesetactivationrule"),
    ]

    operations = [
        migrations.CreateModel(
            name="AgencyLevyMap",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tdcode", models.CharField(db_index=True, max_length=9)),
                ("mcag", models.CharField(db_index=True, max_length=10)),
                ("agency_name", models.CharField(blank=True, max_length=255)),
                ("agency_type", models.CharField(blank=True, max_length=100)),
                ("notes", models.TextField(blank=True)),
                ("is_primary", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "agency_levy_map",
            },
        ),
        migrations.AddConstraint(
            model_name="agencylevymap",
            constraint=models.UniqueConstraint(fields=("tdcode", "mcag"), name="uniq_agency_levy_map"),
        ),
        migrations.AddIndex(
            model_name="agencylevymap",
            index=models.Index(fields=["tdcode"], name="openskagit_agencylevymap_tdcode_idx"),
        ),
        migrations.AddIndex(
            model_name="agencylevymap",
            index=models.Index(fields=["mcag"], name="openskagit_agencylevymap_mcag_idx"),
        ),
    ]
