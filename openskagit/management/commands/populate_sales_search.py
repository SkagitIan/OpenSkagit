# openskagit/management/commands/build_sales_search.py

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Rebuild sales_search table from source sales + parcels"

    def handle(self, *args, **options):
        self.stdout.write("Rebuilding sales_search…")

        sql = """
        TRUNCATE TABLE sales_search;

        WITH ranked AS (
            SELECT
                s.id AS sale_id,
                s.parcel_number,
                s.sale_date::date AS sale_date,
                s.sale_price,
                UPPER(TRIM(COALESCE(s.sale_type, ''))) AS sale_type_clean,
                ROW_NUMBER() OVER (
                    PARTITION BY s.parcel_number, s.sale_date::date, s.sale_price
                    ORDER BY s.id
                ) AS rn,

                mp.total_market_value,
                mp.assessed_value,

                mp.final_living_area,
                mp.acres,

                ppf.zoning_jurisdiction,
                ppf.zone_id,

                -- Treat only explicit VALID SALE as a valid/arms-length sale
                CASE WHEN UPPER(TRIM(COALESCE(s.sale_type, ''))) = 'VALID SALE' THEN TRUE ELSE FALSE END AS is_arms_length,

                CASE
                    WHEN COALESCE(mp.total_market_value, mp.assessed_value) > 0
                    THEN s.sale_price / COALESCE(mp.total_market_value, mp.assessed_value)
                    ELSE NULL
                END AS sale_to_market_ratio
            FROM sales s
            JOIN master_parcel mp
              ON mp.parcel_number = s.parcel_number
            LEFT JOIN parcel_planning_facts ppf
              ON ppf.parcel_id = s.parcel_number
            WHERE s.sale_price > 5000
              AND s.sale_date >= CURRENT_DATE - INTERVAL '15 years'
        ),
        base AS (
            SELECT *
            FROM ranked
            WHERE rn = 1
        )

        INSERT INTO sales_search (
            sale_id,
            parcel_number,
            sale_date,
            sale_price,
            market_value,
            assessed_value,
            sale_to_market_ratio,
            living_area,
            lot_size_acres,
            zoning_jurisdiction,
            zone_id,
            is_arms_length,
            ratio_trim_bucket,
            exclude_from_analysis,
            qa_flags,
            created_at
        )
        SELECT
            b.sale_id,
            b.parcel_number,
            b.sale_date,
            b.sale_price,
            b.total_market_value,
            b.assessed_value,
            b.sale_to_market_ratio,
            b.final_living_area,
            b.acres,
            b.zoning_jurisdiction,
            b.zone_id,
            b.is_arms_length,

            CASE
                WHEN b.sale_to_market_ratio IS NULL THEN 'missing'
                WHEN b.sale_to_market_ratio < 0.25 OR b.sale_to_market_ratio > 3 THEN 'extreme'
                WHEN b.sale_to_market_ratio < 0.5 OR b.sale_to_market_ratio > 1.5 THEN 'outside_iaao'
                ELSE 'inside_iaao'
            END AS ratio_trim_bucket,

            CASE
                WHEN NOT b.is_arms_length THEN TRUE
                WHEN b.sale_price < 10000 THEN TRUE
                WHEN b.sale_to_market_ratio IS NULL THEN FALSE
                WHEN b.sale_to_market_ratio < 0.25 OR b.sale_to_market_ratio > 3 THEN TRUE
                ELSE FALSE
            END AS exclude_from_analysis,

            to_jsonb(
                ARRAY_REMOVE(ARRAY[
                    CASE WHEN b.sale_price < 10000 THEN 'low_price' END,
                    CASE WHEN b.final_living_area IS NULL THEN 'missing_living_area' END,
                    CASE WHEN b.acres IS NULL THEN 'missing_lot_size' END,
                    CASE WHEN NOT b.is_arms_length THEN 'non_valid_sale' END
                ], NULL)
            ) AS qa_flags,

            NOW() AS created_at
        FROM base b;
        """

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS("sales_search rebuilt successfully"))
