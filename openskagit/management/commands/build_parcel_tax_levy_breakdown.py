from django.core.management.base import BaseCommand
from django.db import connection


OUTPUT_TABLE = "parcel_tax_levy_breakdown"


class Command(BaseCommand):
    help = "Build parcel → levy breakdown table from parcel tax history + levy rates"

    def handle(self, *args, **options):
        self.stdout.write("→ Building parcel_tax_levy_breakdown")

        with connection.cursor() as cur:
            self.stdout.write("→ Creating table")
            cur.execute(f"""
                DROP TABLE IF EXISTS {OUTPUT_TABLE};
                CREATE TABLE {OUTPUT_TABLE} (
                    parcel_id TEXT NOT NULL,
                    tax_year INTEGER NOT NULL,
                    tdcode TEXT NOT NULL,
                    district_type TEXT NOT NULL,
                    district_code TEXT NOT NULL,
                    levy_rate NUMERIC,
                    tax_paid NUMERIC,
                    total_levy_rate NUMERIC,
                    levy_share NUMERIC,
                    allocated_tax NUMERIC
                );
            """)

            self.stdout.write("→ Computing levy allocations")
            cur.execute(f"""
                WITH tax_rows AS (
                    SELECT
                        ph.parcel_number AS parcel_id,
                        NULLIF(row->>'TAX YEAR', '')::INTEGER AS tax_year,
                        NULLIF(
                            REGEXP_REPLACE(
                                COALESCE(row->>'TAX', row->>'PROPERTY TAX', row->>'TOTAL TAX', ''),
                                '[^0-9.]',
                                '',
                                'g'
                            ),
                            ''
                        )::NUMERIC AS tax_paid
                    FROM openskagit_parcelhistory ph
                    CROSS JOIN LATERAL jsonb_array_elements(ph.rows) AS row
                    WHERE row ? 'TAX YEAR'
                ),
                parcel_levies AS (
                    SELECT
                        tr.parcel_id,
                        tr.tax_year,
                        tr.tax_paid,
                        p.district_type,
                        p.district_code,
                        d.tdcode,
                        t.levy_rate
                    FROM tax_rows tr
                    JOIN parcel_tax_district p
                      ON p.parcel_id = tr.parcel_id
                    JOIN district_tdcode d
                      ON d.district_type = p.district_type
                     AND d.district_code = p.district_code
                     AND d.assessment_year = tr.tax_year
                    JOIN taxing_district_levy t
                      ON t.tdcode = d.tdcode
                     AND t.assessment_year = tr.tax_year
                    WHERE tr.tax_year IS NOT NULL
                      AND tr.tax_paid IS NOT NULL
                ),
                parcel_totals AS (
                    SELECT
                        parcel_id,
                        tax_year,
                        SUM(levy_rate) AS total_levy_rate
                    FROM parcel_levies
                    GROUP BY parcel_id, tax_year
                )
                INSERT INTO {OUTPUT_TABLE} (
                    parcel_id,
                    tax_year,
                    tdcode,
                    district_type,
                    district_code,
                    levy_rate,
                    tax_paid,
                    total_levy_rate,
                    levy_share,
                    allocated_tax
                )
                SELECT
                    pl.parcel_id,
                    pl.tax_year,
                    pl.tdcode,
                    pl.district_type,
                    pl.district_code,
                    pl.levy_rate,
                    pl.tax_paid,
                    pt.total_levy_rate,
                    CASE
                        WHEN pt.total_levy_rate > 0 THEN pl.levy_rate / pt.total_levy_rate
                        ELSE NULL
                    END AS levy_share,
                    CASE
                        WHEN pt.total_levy_rate > 0 THEN pl.tax_paid * (pl.levy_rate / pt.total_levy_rate)
                        ELSE NULL
                    END AS allocated_tax
                FROM parcel_levies pl
                JOIN parcel_totals pt
                  ON pt.parcel_id = pl.parcel_id
                 AND pt.tax_year = pl.tax_year;
            """)

            self.stdout.write("→ Creating indexes")
            cur.execute(f"""
                CREATE INDEX ON {OUTPUT_TABLE} (parcel_id);
                CREATE INDEX ON {OUTPUT_TABLE} (tax_year);
                CREATE INDEX ON {OUTPUT_TABLE} (tdcode);
                CREATE INDEX ON {OUTPUT_TABLE} (district_type, district_code);
            """)

        self.stdout.write(self.style.SUCCESS("✓ parcel_tax_levy_breakdown built"))
