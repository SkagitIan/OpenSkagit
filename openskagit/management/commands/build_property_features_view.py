from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Build simple materialized views for parcel and improvement rollups."

    def handle(self, *args, **options):
        with connection.cursor() as cur:
            self.stdout.write("Dropping any old views...")
            cur.execute("DROP MATERIALIZED VIEW IF EXISTS property_improvement_features CASCADE;")
            cur.execute("DROP MATERIALIZED VIEW IF EXISTS property_features CASCADE;")

            self.stdout.write("Creating lean property_features view...")
            cur.execute("""
                CREATE MATERIALIZED VIEW property_features AS
                SELECT
                    p.parcel_number,
                    MAX(p.address) AS address,
                    MAX(p.neighborhood_code) AS neighborhood_code,
                    MAX(p.land_use_code) AS land_use_code,
                    MAX(a.assessed_value) AS assessed_value,
                    SUM(l.size_acres) AS land_acres,
                    SUM(l.market_value) AS land_market_value
                FROM parcel p
                LEFT JOIN assessor a ON p.parcel_number = a.parcel_number
                LEFT JOIN land l ON p.parcel_number = l.parcel_number
                GROUP BY p.parcel_number;
            """)
            cur.execute("CREATE UNIQUE INDEX idx_property_features_parcel ON property_features (parcel_number);")

            self.stdout.write("Creating compact property_improvement_features view...")
            cur.execute("""
                CREATE MATERIALIZED VIEW property_improvement_features AS
                SELECT
                    p.parcel_number,
                    TRIM(UPPER(i.description)) AS improvement_type,
                    SUM(i.calculated_area) AS total_area,
                    COUNT(*) AS structure_count
                FROM parcel p
                LEFT JOIN improvements i ON p.parcel_number = i.parcel_number
                WHERE i.description IS NOT NULL AND TRIM(i.description) <> ''
                GROUP BY p.parcel_number, TRIM(UPPER(i.description));
            """)
            cur.execute("CREATE INDEX idx_property_improvement_features_parcel ON property_improvement_features (parcel_number);")

            self.stdout.write("Refreshing both views (non-concurrent for improvements)...")
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY property_features;")
            cur.execute("REFRESH MATERIALIZED VIEW property_improvement_features;")


        self.stdout.write(self.style.SUCCESS("✅ property_features and property_improvement_features built and refreshed."))
