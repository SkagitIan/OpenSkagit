from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0004_assessor_parcel_upper_idx"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_assessor_address_trgm "
                "ON assessor USING GIN (address gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_assessor_address_trgm;",
        ),
    ]

