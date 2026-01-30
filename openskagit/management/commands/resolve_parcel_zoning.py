from django.core.management.base import BaseCommand
from django.db import connection, transaction

from reference_data.management.commands.spatial_eval import dataset_is_available


class Command(BaseCommand):
    help = "Resolve zoning envelopes onto parcels and populate ParcelPlanningFacts"

    def handle(self, *args, **options):
        self.stdout.write("Resolving parcel zoning envelopes…")

        dataset_available = dataset_is_available("reference_zoning_envelope")

        clear_sql = """
        UPDATE parcel_planning_facts
        SET
            zoning_jurisdiction = NULL,
            zone_code = NULL,
            zoning_general_class = NULL,
            zoning_specific_class = NULL,

            zoning_allows_residential = NULL,
            zoning_allows_duplex = NULL,
            zoning_allows_multifamily = NULL,
            zoning_allows_retail = NULL,
            zoning_allows_office = NULL,
            zoning_allows_industrial = NULL,
            zoning_allows_heavy_industrial = NULL,
            zoning_allows_agriculture = NULL,
            zoning_allows_forestry = NULL,
            zoning_allows_green_energy = NULL,
            zoning_allows_data_center = NULL,
            zoning_allows_warehouse = NULL,

            zoning_min_lot_size_sqft = NULL,
            zoning_max_lot_coverage_pct = NULL,
            zoning_max_height_ft = NULL,
            zoning_max_stories = NULL,
            zoning_max_far = NULL,
            zoning_min_far = NULL,

            zoning_max_density_du_ac = NULL,
            zoning_min_density_du_ac = NULL,
            zoning_max_units_per_lot = NULL,
            zoning_adus_allowed_count = NULL,
            zoning_adu_owner_occupancy_required = NULL,

            zoning_parking_min_residential = NULL,
            zoning_parking_min_middle_housing = NULL,
            zoning_parking_min_apartment = NULL,
            zoning_parking_min_retail = NULL,
            zoning_parking_min_restaurant = NULL,
            zoning_parking_min_office = NULL,

            zoning_source = NULL,
            zoning_reference_url = NULL,
            zoning_last_verified = NULL,

            last_updated = NOW();
        """

        sql = """
        WITH zoning_hits AS (
            SELECT
                p.parcel_number AS parcel_id,
                z.id AS zoning_id,
                z.source,
                CASE
                    WHEN z.source = 'ManualOverride' THEN 3
                    WHEN z.source = 'CityGIS' THEN 2
                    WHEN z.source = 'WAZA' THEN 1
                    ELSE 0
                END AS source_rank,
                ST_Area(
                    ST_Intersection(g.geom_2926, z.geometry)
                ) AS intersect_area
            FROM master_parcel p
            JOIN openskagit_parcelgeometry g
            ON g.parcel_id = p.parcel_number
            JOIN reference_zoning_envelope z
            ON ST_Intersects(g.geom_2926, z.geometry)

        ),
        ranked_zoning AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY parcel_id
                    ORDER BY
                        source_rank DESC,
                        intersect_area DESC,
                        zoning_id ASC
                ) AS rn
            FROM zoning_hits
        )
        UPDATE parcel_planning_facts f
        SET
            zoning_jurisdiction = z.jurisdiction,
            zone_code = z.zone_code,
            zoning_general_class = z.zoning_general_class,
            zoning_specific_class = z.zoning_specific_class,

            zoning_allows_residential = z.allows_residential,
            zoning_allows_duplex = z.allows_duplex,
            zoning_allows_multifamily = z.allows_multifamily,
            zoning_allows_retail = z.allows_retail,
            zoning_allows_office = z.allows_office,
            zoning_allows_industrial = z.allows_industrial,
            zoning_allows_heavy_industrial = z.allows_heavy_industrial,
            zoning_allows_agriculture = z.allows_agriculture,
            zoning_allows_forestry = z.allows_forestry,
            zoning_allows_green_energy = z.allows_green_energy,
            zoning_allows_data_center = z.allows_data_center,
            zoning_allows_warehouse = z.allows_warehouse,

            zoning_min_lot_size_sqft = z.min_lot_size_sqft,
            zoning_max_lot_coverage_pct = z.max_lot_coverage_pct,
            zoning_max_height_ft = z.max_height_ft,
            zoning_max_stories = z.max_stories,
            zoning_max_far = z.max_far,
            zoning_min_far = z.min_far,

            zoning_max_density_du_ac = z.max_density_du_ac,
            zoning_min_density_du_ac = z.min_density_du_ac,
            zoning_max_units_per_lot = z.max_units_per_lot,
            zoning_adus_allowed_count = z.adus_allowed_count,
            zoning_adu_owner_occupancy_required = z.adu_owner_occupancy_required,

            zoning_parking_min_residential = z.parking_min_residential,
            zoning_parking_min_middle_housing = z.parking_min_middle_housing,
            zoning_parking_min_apartment = z.parking_min_apartment,
            zoning_parking_min_retail = z.parking_min_retail,
            zoning_parking_min_restaurant = z.parking_min_restaurant,
            zoning_parking_min_office = z.parking_min_office,

            zoning_source = z.source,
            zoning_reference_url = z.reference_url,
            zoning_last_verified = z.source_last_verified,

            last_updated = NOW()
        FROM ranked_zoning r
        JOIN reference_zoning_envelope z
          ON z.id = r.zoning_id
        WHERE
            r.rn = 1
            AND f.parcel_id = r.parcel_id;
        """

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(clear_sql)
                if not dataset_available:
                    self.stdout.write(
                        self.style.WARNING(
                            "reference_zoning_envelope unavailable; zoning fields set to unknown."
                        )
                    )
                    return
                cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS("Parcel zoning resolution complete."))
