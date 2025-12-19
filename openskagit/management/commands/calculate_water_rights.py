import geopandas as gpd
import pandas as pd
import os
import math
import gc
import fiona
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from django.conf import settings
from django.core.management.base import BaseCommand

# --- CONSTANTS ---
# Ensure this path is correct for your local machine
GDB_PATH = '/home/django/django_project/django_project/data/GWIS_SDEexport/GWIS_SDEexport.gdb'
POU_GDB_LAYER_NAME = 'WR_Doc_POU1'
GEOMETRY_LAYER = 'D_Point'
ATTRIBUTES_LAYER = 'D_Point_WR_Doc'

FINAL_POU_TABLE = 'public.ecology_pou'
FINAL_DIVERSIONS_TABLE = 'public.ecology_diversions'
SKAGIT_BOUNDARY_TABLE = 'public.skagit_county_boundary'

ASSESSOR_GEOM_CRS = 'EPSG:2926'
GEOGRAPHIC_CRS = 'EPSG:4326'
DIVERSION_SEARCH_RADIUS_M = 5000
JOIN_KEY = 'd_point_id'
DEFAULT_YEAR = 2025

# Chunk sizes specifically tuned for memory safety
LOAD_BATCH_SIZE = 5000  # Reads GDB in chunks of 5000 rows
CALC_BATCH_SIZE = 15000  # Processes SQL calculations in chunks of 5000 parcels


def build_local_engine():
    """Create an SQLAlchemy engine using the Django local PostGIS settings."""
    db_conf = settings.DATABASES['default']
    options = db_conf.get('OPTIONS') or {}
    query = {k: v for k, v in options.items() if v is not None}

    return create_engine(
        URL.create(
            drivername='postgresql+psycopg2',
            username=db_conf.get('USER'),
            password=db_conf.get('PASSWORD'),
            host=db_conf.get('HOST') or 'localhost',
            port=db_conf.get('PORT') or 5432,
            database=db_conf.get('NAME'),
            query=query,
        ),
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


class Command(BaseCommand):
    help = 'Calculates water rights using memory-safe chunked loading to prevent OOM errors.'

    def add_arguments(self, parser):
        parser.add_argument('--year', '-y', type=int, default=DEFAULT_YEAR, help='Assessment roll year.')

    def handle(self, *args, **options):
        target_year = options['year']
        self.stdout.write(self.style.NOTICE(f"Starting Water Rights Calculation for {target_year}..."))

        try:
            engine = build_local_engine()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Failed to create database engine: {exc}"))
            return

        # 1. Load Data (Diversions is small, POU requires chunking)
        try:
            self.load_diversions_data(engine)
            # 🛑 CRITICAL CHANGE: Use the chunked loader
            self.load_pou_polygons_chunked(engine)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Data loading failed: {exc}"))
            return

        # 2. Process Calculations
        self.process_calculations(engine, target_year)

    def load_diversions_data(self, engine):
        """Loads diversion point geometries (memory safe for points)."""
        self.stdout.write("1. Loading Diversions Data...")
        if not os.path.exists(GDB_PATH):
            raise FileNotFoundError(f"GDB not found at: {GDB_PATH}")

        # Load Geometry
        geom_gdf = gpd.read_file(GDB_PATH, layer=GEOMETRY_LAYER)
        geom_gdf.columns = [c.lower() for c in geom_gdf.columns]

        # Load Attributes
        attr_df = gpd.read_file(GDB_PATH, layer=ATTRIBUTES_LAYER)
        attr_df.columns = [c.lower() for c in attr_df.columns]

        column_map = {}
        if 'wr_doc_nr' not in attr_df.columns:
            candidates = [c for c in attr_df.columns if 'wrdocnr' in c or 'wr_doc' in c]
            if candidates:
                column_map[candidates[0]] = 'wr_doc_nr'
            else:
                raise KeyError("FATAL: Could not find 'wr_doc_nr' in attributes.")

        if column_map:
            attr_df = attr_df.rename(columns=column_map)

        self.stdout.write("   - Merging Geometry and Attributes...")
        merged_gdf = geom_gdf.merge(attr_df, on=JOIN_KEY, how='left', suffixes=('', '_doc'))

        # Ensure Date Column
        if 'eventdate' not in merged_gdf.columns:
            if 'created_td' in merged_gdf.columns:
                merged_gdf = merged_gdf.rename(columns={'created_td': 'eventdate'})
            else:
                merged_gdf['eventdate'] = pd.NaT

        self.stdout.write("   - Reprojecting to EPSG:4326...")
        merged_gdf = merged_gdf.to_crs(GEOGRAPHIC_CRS)

        geom_col = merged_gdf.geometry.name
        if geom_col != 'geom_4326':
            merged_gdf.rename(columns={geom_col: 'geom_4326'}, inplace=True)
            merged_gdf.set_geometry('geom_4326', inplace=True)

        self.stdout.write("   - Uploading to PostGIS...")
        merged_gdf.to_postgis(FINAL_DIVERSIONS_TABLE.split('.')[-1], engine, if_exists='replace', schema='public')
        self.stdout.write(self.style.SUCCESS("   - Diversions loaded."))

        # Explicit memory cleanup
        del geom_gdf, attr_df, merged_gdf
        gc.collect()

    def load_pou_polygons_chunked(self, engine):
        """
        Reads POU polygons in chunks, filters to Skagit, and uploads.
        This prevents loading 160k+ complex polygons into RAM at once.
        """
        self.stdout.write("2. Loading POU Data (Chunked Strategy)...")

        # 1. Get Boundary Geometry
        with engine.connect() as conn:
            skagit_boundary_gdf = gpd.read_postgis(
                f"SELECT geom_2926 FROM {SKAGIT_BOUNDARY_TABLE} LIMIT 1",
                conn, geom_col='geom_2926', crs=ASSESSOR_GEOM_CRS
            )
        skagit_geom = skagit_boundary_gdf.iloc[0]['geom_2926']

        # 2. Get total feature count
        total_features = 0
        try:
            with fiona.open(GDB_PATH, layer=POU_GDB_LAYER_NAME) as src:
                total_features = len(src)
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"   - Could not get feature count: {e}. Estimating."))
            total_features = 200000

        self.stdout.write(f"   - Total POU features to scan: {total_features}")

        # 3. Iterate in chunks
        # We start with 'replace' to clear the table, then switch to 'append'
        if_exists_mode = 'replace'
        chunks_processed = 0
        records_saved = 0

        for start_idx in range(0, total_features, LOAD_BATCH_SIZE):
            end_idx = start_idx + LOAD_BATCH_SIZE
            self.stdout.write(f"   - Processing chunk {chunks_processed + 1}: rows {start_idx} to {end_idx}...")

            try:
                # Read ONLY specific rows to keep memory low
                gdf_chunk = gpd.read_file(
                    GDB_PATH,
                    layer=POU_GDB_LAYER_NAME,
                    rows=slice(start_idx, end_idx)
                )

                if gdf_chunk.empty:
                    break

                # Reproject if needed
                if gdf_chunk.crs != ASSESSOR_GEOM_CRS:
                    gdf_chunk = gdf_chunk.to_crs(ASSESSOR_GEOM_CRS)

                # Filter: Check intersection with Skagit (much faster than clip)
                # We only keep rows that touch Skagit County
                mask = gdf_chunk.intersects(skagit_geom)
                filtered_chunk = gdf_chunk[mask].copy()

                if not filtered_chunk.empty:
                    # Clean columns
                    filtered_chunk.columns = [c.lower() for c in filtered_chunk.columns]

                    if 'wr_doc_nr' not in filtered_chunk.columns:
                        if 'wrdocnr' in filtered_chunk.columns:
                            filtered_chunk.rename(columns={'wrdocnr': 'wr_doc_nr'}, inplace=True)

                    # Fix Geometry Column Name
                    geom_col = filtered_chunk.geometry.name
                    if geom_col != 'geom_2926':
                        filtered_chunk.rename(columns={geom_col: 'geom_2926'}, inplace=True)
                        filtered_chunk.set_geometry('geom_2926', inplace=True)

                    # Upload
                    filtered_chunk.to_postgis(
                        FINAL_POU_TABLE.split('.')[-1],
                        engine,
                        if_exists=if_exists_mode,
                        schema='public'
                    )

                    records_saved += len(filtered_chunk)
                    # Important: Switch to append after the first successful batch
                    if_exists_mode = 'append'
                
                # Explicit cleanup to appease the OOM killer
                del gdf_chunk, filtered_chunk, mask
                gc.collect()
                chunks_processed += 1

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     > Error in chunk {start_idx}: {e}"))
                continue

        self.stdout.write(self.style.SUCCESS(f"   - POU Data Loaded. Saved {records_saved} relevant records."))

    def process_calculations(self, engine, target_year):
        """Runs the calculation logic in batches."""
        self.stdout.write("\n3. Setting up Batched Calculations...")

        try:
            # Fetch parcel list (pre-clipped)
            with engine.connect() as conn:
                parcel_sql = f"""
                    WITH skagit_geom AS (SELECT geom_2926 FROM {SKAGIT_BOUNDARY_TABLE} LIMIT 1)
                    SELECT DISTINCT a.parcel_number
                    FROM public.assessor AS a
                    JOIN public.openskagit_assessmentroll AS r ON a.roll_id = r.id
                    JOIN skagit_geom AS s ON a.geom_2926 && s.geom_2926 AND ST_Intersects(a.geom_2926, s.geom_2926)
                    WHERE r.year = {target_year};
                """
                all_parcels = pd.read_sql(text(parcel_sql), conn)['parcel_number'].tolist()

            total_parcels = len(all_parcels)
            num_batches = math.ceil(total_parcels / CALC_BATCH_SIZE)
            self.stdout.write(f"   - Found {total_parcels} parcels. Processing in {num_batches} batches...")

            for i in range(num_batches):
                start = i * CALC_BATCH_SIZE
                end = min((i + 1) * CALC_BATCH_SIZE, total_parcels)
                batch_parcels = all_parcels[start:end]
                
                # Format string list for SQL
                parcel_str = ", ".join([f"'{p}'" for p in batch_parcels])

                self.stdout.write(f"   - Batch {i+1}/{num_batches} ({len(batch_parcels)} parcels)...")
                self._run_sql_batch(engine, parcel_str)
                gc.collect()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Calculation failed: {e}"))

    def _run_sql_batch(self, engine, parcel_list_str):
        """Runs the spatial SQL for a specific list of parcels."""
        temp_tables = ['temp_centroids', 'temp_pou', 'temp_diversion', 'temp_results']

        with engine.begin() as conn:
            # 1. Centroids
            conn.execute(text(f"""
                CREATE TEMPORARY TABLE temp_centroids AS 
                SELECT parcel_number, geom_2926, ST_Centroid(geom_4326) as centroid_geog 
                FROM public.assessor WHERE parcel_number IN ({parcel_list_str})
            """))

            # 2. POU (Spatial Join)
            # Note: We check if the table exists first to avoid errors if the POU load matched 0 records
            pou_exists = conn.execute(text(f"SELECT to_regclass('{FINAL_POU_TABLE}')")).scalar()
            
            if pou_exists:
                conn.execute(text(f"""
                    CREATE TEMPORARY TABLE temp_pou AS 
                    SELECT c.parcel_number, TRUE as has_right, ARRAY_AGG(DISTINCT p.wr_doc_nr) as rights 
                    FROM temp_centroids c JOIN {FINAL_POU_TABLE} p 
                    ON c.geom_2926 && p.geom_2926 AND ST_Intersects(c.geom_2926, p.geom_2926)
                    GROUP BY c.parcel_number
                """))
            else:
                conn.execute(text("CREATE TEMPORARY TABLE temp_pou (parcel_number text, has_right boolean, rights text[])"))

            # 3. Diversions (Proximity)
            conn.execute(text(f"""
                CREATE TEMPORARY TABLE temp_diversion AS 
                SELECT DISTINCT ON (c.parcel_number) c.parcel_number, d.wr_doc_nr, 
                ST_DistanceSphere(c.centroid_geog, d.geom_4326) as dist_m, d.eventdate
                FROM temp_centroids c JOIN {FINAL_DIVERSIONS_TABLE} d 
                ON ST_DWithin(c.centroid_geog, d.geom_4326, {DIVERSION_SEARCH_RADIUS_M})
                ORDER BY c.parcel_number, dist_m
            """))

            # 4. Final Merge & Update
            conn.execute(text(f"""
                INSERT INTO public.assessor_waterfacts (
                    parcel_number, has_pou_water_right, pou_right_numbers, 
                    nearest_diversion_right, nearest_diversion_distance_m, nearest_right_priority_date
                )
                SELECT 
                    c.parcel_number, COALESCE(p.has_right, FALSE), p.rights, 
                    d.wr_doc_nr, d.dist_m, d.eventdate
                FROM temp_centroids c
                LEFT JOIN temp_pou p ON c.parcel_number = p.parcel_number
                LEFT JOIN temp_diversion d ON c.parcel_number = d.parcel_number
                ON CONFLICT (parcel_number) DO UPDATE SET
                    has_pou_water_right = EXCLUDED.has_pou_water_right,
                    pou_right_numbers = EXCLUDED.pou_right_numbers,
                    nearest_diversion_right = EXCLUDED.nearest_diversion_right,
                    nearest_diversion_distance_m = EXCLUDED.nearest_diversion_distance_m,
                    nearest_right_priority_date = EXCLUDED.nearest_right_priority_date;
            """))

            # Clean up
            for t in temp_tables:
                conn.execute(text(f"DROP TABLE IF EXISTS {t}"))