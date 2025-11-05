from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0003_cmaanalysis_cmacomparableselection"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS idx_assessor_parcel_upper ON assessor (UPPER(parcel_number));",
            reverse_sql="DROP INDEX IF EXISTS idx_assessor_parcel_upper;",
        ),
    ]

