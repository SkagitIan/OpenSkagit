from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0016_assessor_centroid_geog_assessor_embedding"),
    ]

    # Using RunSQL so we can apply indexes that aid ILIKE/prefix and trigram
    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql="DROP EXTENSION IF EXISTS pg_trgm;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_parcel_upper_parcel_number "
                "ON parcel (UPPER(parcel_number));"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_parcel_upper_parcel_number;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS idx_parcel_address_trgm "
                "ON parcel USING GIN (address gin_trgm_ops);"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_parcel_address_trgm;",
        ),
    ]

