import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection


MANIFEST_PATH = Path(__file__).resolve().parents[2] / "etl" / "resource_manifest.json"


class Command(BaseCommand):
    help = "Compute parcel geometry / planning / water facts from reference_* layers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--roll",
            type=int,
            help="Optional roll_id filter on master_parcel",
        )
        parser.add_argument(
            "--resource",
            type=str,
            help="Optional single reference_* table to run (e.g. reference_wells)",
        )

    def handle(self, *args, **options):
        roll_id = options.get("roll")
        single_resource = options.get("resource")

        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)

        self.stdout.write(f"Loaded manifest with {len(manifest)} resources.")
        lookup_ops = []

        for table_name, cfg in manifest.items():
            if cfg.get("geometry_type") == "raster":
                continue

            if single_resource and table_name != single_resource:
                continue

            ops = cfg.get("operations") or []
            geom_col = cfg.get("geometry_column")

            if not ops:
                continue

            if not geom_col:
                self.stdout.write(f"Skipping {table_name} (no geometry_column).")
                continue

            self.stdout.write(self.style.MIGRATE_HEADING(f"Resource: {table_name}"))

            for op in ops:
                target_model = op.get("target_model")
                output_field = op.get("output_field")
                metric = op.get("metric")
                if metric == "lookup_zoning_rule":
                    lookup_ops.append(op)
                    continue     # <----------------- skip normal handling
                if not target_model or not output_field or not metric:
                    continue

                self.stdout.write(f"  -> {target_model}.{output_field} via {metric}")

                parcel_alias = "pg"
                if target_model == "ParcelGeometry":
                    parcel_alias = "pg_src"

                lateral_sql = build_lateral_sql(
                    metric=metric,
                    ref_table=table_name,
                    ref_geom_col=geom_col,
                    op_cfg=op,
                    parcel_alias=parcel_alias,
                )

                if not lateral_sql:
                    self.stdout.write(
                        self.style.WARNING(f"    Skipping metric {metric} (not implemented).")
                    )
                    continue

                if target_model == "ParcelGeometry":
                    update_sql, params = build_update_sql_for_geometry(
                        output_field=output_field,
                        lateral_sql=lateral_sql,
                        roll_id=roll_id,
                    )
                elif target_model == "ParcelPlanningFacts":
                    update_sql, params = build_update_sql_for_planning(
                        output_field=output_field,
                        lateral_sql=lateral_sql,
                        roll_id=roll_id,
                    )
                elif target_model == "ParcelWaterFacts":
                    update_sql, params = build_update_sql_for_waterfacts(
                        output_field=output_field,
                        lateral_sql=lateral_sql,
                        roll_id=roll_id,
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f"    Unknown target_model {target_model}, skipping.")
                    )
                    continue

                with connection.cursor() as cur:
                    cur.execute(update_sql, params)
                    self.stdout.write(
                        self.style.SUCCESS(f"    Updated {cur.rowcount} rows for {output_field}")
                    )

        # ---------------------------------------------------------
        # POST-PROCESS LOOKUP OPS (run after geometry metrics)
        # ---------------------------------------------------------

        self.stdout.write(self.style.SUCCESS("Parcel facts update complete."))

def build_lateral_sql(
    metric: str,
    ref_table: str,
    ref_geom_col: str,
    op_cfg: dict,
    parcel_alias: str = "pg",
) -> str:
    """
    Returns SQL snippet that SELECTs a single column named 'val'.
    It will be used as a LATERAL subquery joined against each parcel.
    Parcel geometry alias is 'pg.geom_2926'.
    """
    # lookup_zoning_rule is NOT a lateral metric → handled separately
    if metric == "lookup_zoning_rule":
        return None   # <-- Important
    # Common aliases:
    #   pg = parcel_geometry
    #   r  = reference table (ref_table)
    metric_aliases = {
        "area_intersect_pct": "intersection_area_pct",
        "boolean_overlay": "intersects_boolean",
        "categorical_overlay": "intersects_attribute",
        "nearest_distance_ft": "nearest_distance",
    }
    metric = metric_aliases.get(metric, metric)
    if metric == "raster_value" and op_cfg.get("method") == "mean":
        # Preserve legacy manifest configs that used metric=raster_value with method=mean.
        metric = "raster_value_mean"

    # Default parcel geometry
    use_centroid = op_cfg.get("use_centroid", False)
    if use_centroid:
        geom_parcel = f"{parcel_alias}.centroid_2926"
    else:
        geom_parcel = f"{parcel_alias}.geom_2926"
    parcel_centroid = f"{parcel_alias}.centroid_2926"
    geom_ref = f"r.{ref_geom_col}"
    # 1) Basic intersects boolean
    if metric == "intersects_boolean":
        return f"""
            SELECT TRUE AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_parcel}, {geom_ref})
            LIMIT 1
        """

    # 2) Attribute from intersecting geometry
    if metric == "intersects_attribute":
        col = op_cfg["source_column"]
        order_by = op_cfg.get("order_by")

        order_sql = ""
        if order_by:
            order_sql = f"ORDER BY r.{order_by}"

        return f"""
            SELECT r."{col}" AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_parcel}, {geom_ref})
            {order_sql}
            LIMIT 1
        """

    # 3) Intersection area percentage (0–1)
    if metric == "intersection_area_pct":
        return f"""
            SELECT
              ST_Area(ST_Intersection({geom_parcel}, {geom_ref})) /
              NULLIF(ST_Area({geom_parcel}), 0) AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_parcel}, {geom_ref})
            ORDER BY ST_Area(ST_Intersection({geom_parcel}, {geom_ref})) DESC
            LIMIT 1
        """

    # 4) Nearest distance (units of SRID 2926 = feet)
    if metric == "nearest_distance" or metric == "nearest_boundary_distance":
        # For polygons and lines, ST_Distance to geometry is fine.
        return f"""
            SELECT ST_Distance({geom_parcel}, {geom_ref}) AS val
            FROM {ref_table} r
            ORDER BY {geom_parcel} <-> {geom_ref}
            LIMIT 1
        """

    # 5) Nearest attribute (by <-> order)
    if metric == "nearest_attribute":
        col = op_cfg["source_column"]
        return f"""
            SELECT r."{col}" AS val
            FROM {ref_table} r
            ORDER BY {geom_parcel} <-> {geom_ref}
            LIMIT 1
        """

    # --- Buffer intersects (boolean, no filter) ---
    if metric == "buffer_intersects":
        buffer_ft = op_cfg["buffer_distance"]
        return f"""
            SELECT TRUE AS val
            FROM {ref_table} r
            WHERE ST_DWithin({geom_parcel}, {geom_ref}, {buffer_ft})
            LIMIT 1
        """

    # 6) Nearest distance filtered by attribute set
    if metric == "nearest_distance_filtered":
        col = op_cfg["filter_column"]
        vals = op_cfg["filter_values"]
        vals_sql = ", ".join(f"'{v}'" for v in vals)
        return f"""
            SELECT ST_Distance({geom_parcel}, {geom_ref}) AS val
            FROM {ref_table} r
            WHERE r."{col}" IN ({vals_sql})
            ORDER BY {geom_parcel} <-> {geom_ref}
            LIMIT 1
        """
    # --- Raw intersection area (parcel ∩ reference geom) ---
    if metric == "intersection_area":
        return f"""
            SELECT ST_Area(
                ST_Intersection({geom_parcel}, {geom_ref})
            ) AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_parcel}, {geom_ref})
            ORDER BY ST_Area(ST_Intersection({geom_parcel}, {geom_ref})) DESC
            LIMIT 1
        """


    # 7) Simple buffer intersects boolean (no filter)
    if metric == "buffer_intersects_boolean":
        buffer_ft = op_cfg["buffer_ft"]
        return f"""
            SELECT TRUE AS val
            FROM {ref_table} r
            WHERE ST_DWithin({geom_parcel}, {geom_ref}, {buffer_ft})
            LIMIT 1
        """

    # 8) Buffer intersects with filter (e.g. TYPE='LFS')
    if metric == "buffer_intersects_filtered_boolean":
        buffer_ft = op_cfg["buffer_ft"]
        col = op_cfg["filter_column"]
        vals = op_cfg["filter_values"]
        vals_sql = ", ".join(f"'{v}'" for v in vals)
        return f"""
            SELECT TRUE AS val
            FROM {ref_table} r
            WHERE r."{col}" IN ({vals_sql})
              AND ST_DWithin({geom_parcel}, {geom_ref}, {buffer_ft})
            LIMIT 1
        """
    # X) Buffer intersection area (e.g., wetlands buffer)
    if metric == "buffer_intersection_area":
        buffer_ft = op_cfg["buffer_distance"]
        return f"""
            SELECT ST_Area(
                ST_Intersection(
                    {geom_parcel},
                    ST_Buffer({geom_ref}, {buffer_ft})
                )
            ) AS val
            FROM {ref_table} r
            WHERE ST_DWithin({geom_parcel}, {geom_ref}, {buffer_ft})
            LIMIT 1
        """

    # 9) Attribute list (POU water rights → array of IDs)
    if metric == "intersects_attribute_list":
        col = op_cfg["source_column"]
        return f"""
            SELECT ARRAY_AGG(DISTINCT r."{col}") AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_parcel}, {geom_ref})
        """

    # 10) Density per acre (well count / parcel acres)
    if metric == "density_per_acre":
        return f"""
            SELECT
              COUNT(*)::float /
              NULLIF(ST_Area({geom_parcel}) / 43560.0, 0) AS val
            FROM {ref_table} r
            WHERE ST_Contains({geom_parcel}, {geom_ref})
        """

    # 11) Aquifer yield classification (LOW / MEDIUM / HIGH / UNKNOWN)
    if metric == "yield_classification":
        col = op_cfg["source_column"]
        return f"""
            SELECT CASE
                WHEN r."{col}" IS NULL THEN 'UNKNOWN'
                WHEN r."{col}" < 1 THEN 'LOW'
                WHEN r."{col}" < 5 THEN 'MEDIUM'
                ELSE 'HIGH'
            END AS val
            FROM {ref_table} r
            ORDER BY {geom_parcel} <-> {geom_ref}
            LIMIT 1
        """

    if metric == "lookup_zoning_rule":
        output_field = op_cfg["output_field"]
        return f"""
            UPDATE parcel_planning_facts AS pf
            SET {output_field} = zr.id
            FROM zoning_rules zr
            WHERE LOWER(zr.zone_code) = LOWER(pf.zone_code)
            AND LOWER(zr.jurisdiction) = LOWER(pf.zoning_jurisdiction);

        """

    # 12) Raster sampling (DEM / slope / aspect)
    if metric == "raster_value":
        band = op_cfg.get("band", 1)
        srid_expr = f"COALESCE(NULLIF(ST_SRID({geom_ref}), 0), 2926)"
        parcel_centroid_rast = f"ST_Transform({parcel_centroid}, {srid_expr})"

        return f"""
            SELECT ST_Value({geom_ref}, {band}, {parcel_centroid_rast}) AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_ref}, {parcel_centroid_rast})
            LIMIT 1
        """

    if metric == "raster_value_mean":
        band = op_cfg.get("band", 1)
        srid_expr = f"COALESCE(NULLIF(ST_SRID({geom_ref}), 0), 2926)"
        parcel_geom = f"ST_Transform({geom_parcel}, {srid_expr})"
        return f"""
            WITH tile AS (
                SELECT {geom_ref} AS rast
                FROM {ref_table} r
                WHERE ST_Intersects({geom_ref}, {parcel_geom})
                LIMIT 1
            ),
            clipped AS (
                SELECT ST_Clip(rast, {band}, {parcel_geom}, TRUE) AS c
                FROM tile
            )
            SELECT (ST_SummaryStats(c)).mean AS val
            FROM clipped
        """

    if metric == "raster_slope":
        band = op_cfg.get("band", 1)
        srid_expr = f"COALESCE(NULLIF(ST_SRID({geom_ref}), 0), 2926)"
        parcel_centroid_rast = f"ST_Transform({parcel_centroid}, {srid_expr})"
        return f"""
            SELECT ST_Value(
                ST_Slope({geom_ref}, {band}, '32BF', 'DEGREES', 1, FALSE),
                1,
                {parcel_centroid_rast}
            ) AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_ref}, {parcel_centroid_rast})
            LIMIT 1
        """

    if metric == "raster_aspect":
        band = op_cfg.get("band", 1)
        srid_expr = f"COALESCE(NULLIF(ST_SRID({geom_ref}), 0), 2926)"
        parcel_centroid_rast = f"ST_Transform({parcel_centroid}, {srid_expr})"
        return f"""
            SELECT ST_Value(
                ST_Aspect({geom_ref}, {band}, '32BF', 'DEGREES', 1),
                1,
                {parcel_centroid_rast}
            ) AS val
            FROM {ref_table} r
            WHERE ST_Intersects({geom_ref}, {parcel_centroid_rast})
            LIMIT 1
        """

    if metric == "aspect_direction":
        band = op_cfg.get("band", 1)
        srid_expr = f"COALESCE(NULLIF(ST_SRID({geom_ref}), 0), 2926)"
        parcel_centroid_rast = f"ST_Transform({parcel_centroid}, {srid_expr})"
        return f"""
            SELECT CASE
                WHEN val IS NULL THEN NULL
                WHEN val >= 337.5 OR val < 22.5  THEN 'N'
                WHEN val >= 22.5  AND val < 67.5  THEN 'NE'
                WHEN val >= 67.5  AND val < 112.5 THEN 'E'
                WHEN val >= 112.5 AND val < 157.5 THEN 'SE'
                WHEN val >= 157.5 AND val < 202.5 THEN 'S'
                WHEN val >= 202.5 AND val < 247.5 THEN 'SW'
                WHEN val >= 247.5 AND val < 292.5 THEN 'W'
                WHEN val >= 292.5 AND val < 337.5 THEN 'NW'
            END AS val
            FROM (
                SELECT ST_Value(
                    ST_Aspect({geom_ref}, {band}, '32BF', 'DEGREES', 1),
                    1,
                    {parcel_centroid_rast}
                ) AS val
                FROM {ref_table} r
                WHERE ST_Intersects({geom_ref}, {parcel_centroid_rast})
                LIMIT 1
            ) aspect_val
        """
    # contains boolean (point-in-polygon)
    if metric == "contains_boolean":
        return f"""
            SELECT TRUE AS val
            FROM {ref_table} r
            WHERE ST_Contains({geom_parcel}, {geom_ref})
            LIMIT 1
        """

    return None

def build_update_sql_for_geometry(output_field: str, lateral_sql: str, roll_id: int | None):
    params = []
    where_roll = ""
    if roll_id is not None:
        where_roll = "AND mp.roll = %s"
        params.append(roll_id)

    sql = f"""
        UPDATE openskagit_parcelgeometry pg
        SET {output_field} = subq.val
        FROM master_parcel mp
        JOIN openskagit_parcelgeometry pg_src
            ON pg_src.parcel_id = mp.parcel_number
        LEFT JOIN LATERAL (
            {lateral_sql}
        ) subq ON TRUE
        WHERE pg.parcel_id = mp.parcel_number
        {where_roll};
    """
    return sql, params


def build_update_sql_for_planning(output_field: str, lateral_sql: str, roll_id: int | None):
    params = []
    where_roll = ""
    if roll_id is not None:
        where_roll = "AND mp.roll = %s"
        params.append(roll_id)

    sql = f"""
        UPDATE parcel_planning_facts pf
        SET {output_field} = subq.val
        FROM master_parcel mp
        JOIN openskagit_parcelgeometry pg
            ON pg.parcel_id = mp.parcel_number
        LEFT JOIN LATERAL (
            {lateral_sql}
        ) subq ON TRUE
        WHERE pf.parcel_id = mp.parcel_number
        {where_roll};
    """
    return sql, params


def build_update_sql_for_waterfacts(output_field: str, lateral_sql: str, roll_id: int | None):
    params = []
    where_roll = ""
    if roll_id is not None:
        where_roll = "AND mp.roll = %s"
        params.append(roll_id)

    sql = f"""
        UPDATE assessor_waterfacts wf
        SET {output_field} = subq.val
        FROM master_parcel mp
        JOIN openskagit_parcelgeometry pg
            ON pg.parcel_id = mp.parcel_number
        LEFT JOIN LATERAL (
            {lateral_sql}
        ) subq ON TRUE
        WHERE wf.parcel_number = mp.parcel_number
        {where_roll};
    """
    return sql, params

def run_raster_metrics(cursor, roll_id=None):
    """
    Fast raster → parcel join.
    Populates elev, slope, aspect, aspect_dir.
    """

    roll_filter = ""
    params = []

    if roll_id is not None:
        roll_filter = "AND mp.roll = %s"
        params.append(roll_id)

    sql = f"""
    WITH tiles AS (
        SELECT
            pg.parcel_id,
            r.rast,
            ST_Transform(pg.centroid_2926, ST_SRID(r.rast)) AS pt
        FROM reference_elevation r
        JOIN openskagit_parcelgeometry pg
          ON ST_Intersects(
               r.rast,
               ST_Transform(pg.centroid_2926, ST_SRID(r.rast))
             )
        JOIN master_parcel mp
          ON mp.parcel_number = pg.parcel_id
        WHERE pg.centroid_2926 IS NOT NULL
        {roll_filter}
    )
    UPDATE openskagit_parcelgeometry pg
    SET
        elev = ST_Value(t.rast, 1, t.pt),
        slope = ST_Value(
            ST_Slope(t.rast, 1, '32BF', 'DEGREES', 1, FALSE),
            1,
            t.pt
        ),
        aspect = ST_Value(
            ST_Aspect(t.rast, 1, '32BF', 'DEGREES', 1),
            1,
            t.pt
        ),
        aspect_dir = CASE
            WHEN ST_Value(
                ST_Aspect(t.rast, 1, '32BF', 'DEGREES', 1),
                1,
                t.pt
            ) >= 337.5 OR ST_Value(
                ST_Aspect(t.rast, 1, '32BF', 'DEGREES', 1),
                1,
                t.pt
            ) < 22.5 THEN 'N'
            WHEN ST_Value(...) < 67.5  THEN 'NE'
            WHEN ST_Value(...) < 112.5 THEN 'E'
            WHEN ST_Value(...) < 157.5 THEN 'SE'
            WHEN ST_Value(...) < 202.5 THEN 'S'
            WHEN ST_Value(...) < 247.5 THEN 'SW'
            WHEN ST_Value(...) < 292.5 THEN 'W'
            ELSE 'NW'
        END
    FROM tiles t
    WHERE pg.parcel_id = t.parcel_id;
    """

    cursor.execute(sql, params)
