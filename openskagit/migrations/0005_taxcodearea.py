from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0004_agencyfinancialsnapshot_details"),
    ]

    state_operations = [
        migrations.CreateModel(
            name="TaxCodeArea",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tca_code", models.CharField(max_length=10)),
                ("tax_year", models.IntegerField()),
                ("county", models.CharField(max_length=100)),
                ("raw_districts_text", models.TextField()),
                ("source", models.CharField(default="WA DOR TaxReport.aspx", max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["tca_code", "-tax_year"],
                "unique_together": {("tca_code", "tax_year")},
            },
        ),
        migrations.CreateModel(
            name="TaxCodeAreaDistrict",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tca_code", models.CharField(max_length=10)),
                ("tax_year", models.IntegerField()),
                ("district_type", models.CharField(max_length=100)),
                ("district_identifier", models.CharField(blank=True, max_length=200)),
                ("raw_label", models.CharField(max_length=255)),
                ("source", models.CharField(default="WA DOR TaxReport.aspx", max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tax_code_area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="districts",
                        to="openskagit.taxcodearea",
                    ),
                ),
            ],
            options={
                "ordering": ["tca_code", "-tax_year", "district_type"],
                "unique_together": {("tca_code", "tax_year", "district_type", "district_identifier")},
            },
        ),
        migrations.AddIndex(
            model_name="taxcodearea",
            index=models.Index(fields=["tca_code", "tax_year"], name="openskagit_tca_year_idx"),
        ),
        migrations.AddIndex(
            model_name="taxcodeareadistrict",
            index=models.Index(fields=["tca_code", "tax_year"], name="openskagit_tcad_year_idx"),
        ),
        migrations.AddIndex(
            model_name="taxcodeareadistrict",
            index=models.Index(fields=["district_type"], name="openskagit_tcad_dtype_idx"),
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=state_operations,
        )
    ]
