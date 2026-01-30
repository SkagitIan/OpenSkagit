from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Audit residential planning readiness and zoning reference integrity (fully qualified)"

    def run_query(self, title, sql):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}"))
        with connection.cursor() as cursor:
            cursor.execute(sql)
            cols = [c[0] for c in cursor.description]
            rows = cursor.fetchall()

        for row in rows:
            for k, v in zip(cols, row):
                self.stdout.write(f"  {k:45s}: {v}")
            self.stdout.write("")

    def handle(self, *args, **options):

        # ==================================================
        # SECTION 1 — RESIDENTIAL PARCEL BASELINE
        # ==================================================
        self.run_query(
            "RESIDENTIAL PARCEL BASELINE",
            """
            SELECT
                COUNT(*) AS total_residential_parcels,
                COUNT(pg.parcel_id) AS with_geometry,
                COUNT(pp.parcel_id) AS with_planning,
                ROUND(100.0 * COUNT(pg.parcel_id) / COUNT(*), 1) AS pct_geometry,
                ROUND(100.0 * COUNT(pp.parcel_id) / COUNT(*), 1) AS pct_planning
            FROM master_parcel mp
            LEFT JOIN openskagit_parcelgeometry pg
                ON pg.parcel_id = mp.parcel_number
            LEFT JOIN parcel_planning_facts pp
                ON pp.parcel_id = mp.parcel_number
            WHERE mp.proptype = 'R';
            """
        )

        # ==================================================
        # SECTION 2 — RESIDENTIAL ZONING ATTRIBUTION
        # (parcel_planning_facts ONLY)
        # ==================================================
        self.run_query(
            "RESIDENTIAL ZONING ATTRIBUTION",
            """
            SELECT
                COUNT(*) AS residential_with_planning,
                COUNT(pp.zone_code) AS zoning_code_present,
                ROUND(100.0 * COUNT(pp.zone_code) / COUNT(*), 1) AS pct_zoned,
                COUNT(pp.zoning_jurisdiction) AS jurisdiction_present,
                COUNT(pp.zoning_general_class) AS general_class_present,
                COUNT(pp.zoning_specific_class) AS specific_class_present
            FROM parcel_planning_facts pp
            JOIN master_parcel mp
                ON mp.parcel_number = pp.parcel_id
            WHERE mp.proptype = 'R';
            """
        )

        # ==================================================
        # SECTION 3 — reference_zoning (RAW GIS FEED)
        # ==================================================
        self.run_query(
            "REFERENCE_ZONING — RAW GIS FEED",
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(rz."ZONING_COD") AS zoning_code_present,
                COUNT(rz."ZONING_LAB") AS zoning_label_present,
                COUNT(rz.geometry) AS rows_with_geometry,
                COUNT(*) FILTER (WHERE rz.geometry IS NULL) AS missing_geometry
            FROM reference_zoning rz;
            """
        )

        # ==================================================
        # SECTION 4 — reference_zoning_zones (CANONICAL RULES)
        # ==================================================
        self.run_query(
                "REFERENCE_ZONING_ZONES — WAZA / CANONICAL RULES",
                """
                SELECT
                    COUNT(*) AS total_zones,
                    COUNT(rzz.zoneid) AS zoneid_present,
                    COUNT(rzz.wazazonegeneral) AS general_class_present,
                    COUNT(rzz.wazazonespecific) AS specific_class_present,

                    COUNT(rzz.geom) AS zones_with_geometry,
                    COUNT(*) FILTER (WHERE rzz.geom IS NULL) AS zones_missing_geometry,

                    COUNT(rzz.denminlotsizesqft) AS min_lot_size_present,
                    COUNT(rzz.dimmaxheight) AS max_height_present,
                    COUNT(rzz.dimmaxfar) AS max_far_present
                FROM reference_zoning_zones rzz;
                """
            )


        # ==================================================
        # SECTION 5 — reference_zoning_envelope (BUILDABILITY)
        # ==================================================
        self.run_query(
                "REFERENCE_ZONING_ENVELOPE — CANONICAL ZONING RULES",
                """
                SELECT
                    COUNT(*) AS total_zones,
                    COUNT(rze.zone_code) AS zone_code_present,
                    COUNT(rze.zoning_general_class) AS general_class_present,
                    COUNT(rze.zoning_specific_class) AS specific_class_present,

                    COUNT(rze.allows_residential) AS allows_residential_flag,
                    COUNT(rze.min_lot_size_sqft) AS min_lot_size_present,
                    COUNT(rze.max_height_ft) AS max_height_present,
                    COUNT(rze.max_far) AS max_far_present,

                    COUNT(rze.geometry) AS zones_with_geometry,
                    COUNT(*) FILTER (WHERE rze.geometry IS NULL) AS zones_missing_geometry
                FROM reference_zoning_envelope rze;
                """
            )

        # ==================================================
        # SECTION 6 — ORPHAN ZONE CHECK (CRITICAL)
        # ==================================================
        self.run_query(
            "ZONING ORPHAN CHECK — PARCEL → CANONICAL ZONES",
            """
            SELECT
                COUNT(DISTINCT pp.zone_code) AS parcel_zone_codes,
                COUNT(DISTINCT rze.zone_code) AS canonical_zone_codes,
                COUNT(DISTINCT pp.zone_code)
                    FILTER (WHERE rze.zone_code IS NULL)
                    AS orphan_parcel_zones
            FROM parcel_planning_facts pp
            LEFT JOIN reference_zoning_envelope rze
                ON rze.zone_code = pp.zone_code;
            """
        )


        self.stdout.write(self.style.SUCCESS(
            "\nResidential planning + zoning audit completed successfully."
        ))
