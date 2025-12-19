# management/commands/import_water_rights.py
from django.core.management.base import BaseCommand
from django.db import connection
import geopandas as gpd
import pandas as pd
import logging
from .utils import create_spatial_index, log_import, TARGET_SRID

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import Water Rights data from GWIS GDB (Points of Diversion and Place of Use)'

    def add_arguments(self, parser):
        parser.add_argument('gdb_path', type=str, help='Path to GWIS_SDEexport.gdb')
        parser.add_argument('--drop', action='store_true', help='Drop existing tables if they exist')
        
    def handle(self, *args, **options):
        gdb_path = options['gdb_path']
        drop_existing = options['drop']
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing Water Rights Data")
        self.stdout.write(f"{'='*60}\n")
        
        try:
            # Import Points of Diversion
            self.import_diversions(gdb_path, drop_existing)
            
            # Import Place of Use
            self.import_pou(gdb_path, drop_existing)
            
            self.stdout.write(self.style.SUCCESS("\n✓ Water Rights import complete!"))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ ERROR: {e}"))
            logger.exception("Water rights import failed")
            raise
    
    def import_diversions(self, gdb_path, drop_existing):
        """Import Points of Diversion (merged geometry + attributes)"""
        self.stdout.write("\n--- Points of Diversion ---")
        
        table_name = 'reference_water_diversions'
        
        # Check if table exists
        if drop_existing:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        
        # 1. Load Geometry layer
        self.stdout.write("Loading geometry layer: D_Point...")
        geom_gdf = gpd.read_file(gdb_path, layer='D_Point')
        geom_gdf.columns = [c.lower() for c in geom_gdf.columns]
        self.stdout.write(f"  ✓ Loaded {len(geom_gdf)} diversion points")
        
        # 2. Load Attributes layer
        self.stdout.write("Loading attributes layer: D_Point_WR_Doc...")
        attr_df = gpd.read_file(gdb_path, layer='D_Point_WR_Doc')
        attr_df.columns = [c.lower() for c in attr_df.columns]
        
        # Handle column naming variations
        if 'wr_doc_nr' not in attr_df.columns:
            for col in attr_df.columns:
                if 'wrdocnr' in col or 'wr_doc' in col:
                    attr_df = attr_df.rename(columns={col: 'wr_doc_nr'})
                    break
        
        # 3. Merge geometry and attributes
        self.stdout.write("Merging geometry and attributes...")
        join_key = 'd_point_id'
        merged_gdf = geom_gdf.merge(
            attr_df,
            on=join_key,
            how='left',
            suffixes=('', '_attr')
        )
        
        # Handle priority date column
        if 'eventdate' not in merged_gdf.columns:
            if 'created_td' in merged_gdf.columns:
                merged_gdf = merged_gdf.rename(columns={'created_td': 'eventdate'})
            else:
                merged_gdf['eventdate'] = pd.NaT
        
        # 4. Transform to target SRID
        original_srid = merged_gdf.crs.to_epsg() if merged_gdf.crs else None
        self.stdout.write(f"Original SRID: {original_srid}")
        
        if original_srid != TARGET_SRID:
            self.stdout.write(f"Transforming to SRID {TARGET_SRID}...")
            merged_gdf = merged_gdf.to_crs(epsg=TARGET_SRID)
        
        # Standardize geometry column
        if merged_gdf.geometry.name != 'geometry':
            merged_gdf = merged_gdf.rename_geometry('geometry')
        
        # 5. Import to PostGIS
        self.stdout.write(f"Importing to table: {table_name}")
        from sqlalchemy import create_engine
        from django.conf import settings
        
        db = settings.DATABASES['default']
        engine = create_engine(
            f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db.get('PORT', 5432)}/{db['NAME']}"
        )
        
        merged_gdf.to_postgis(
            table_name,
            engine,
            if_exists='replace',
            index=False,
            chunksize=1000
        )
        
        self.stdout.write(f"  ✓ Imported {len(merged_gdf):,} diversion points")
        
        # 6. Create spatial index
        create_spatial_index(table_name, 'geometry')
        
        # 7. Log import
        log_import(
            dataset_name="Water Rights - Points of Diversion",
            table_name=table_name,
            source_path=gdb_path,
            success=True,
            row_count=len(merged_gdf)
        )
        
        self.stdout.write(self.style.SUCCESS(f"✓ Diversions imported to {table_name}"))
    
    def import_pou(self, gdb_path, drop_existing):
        """Import Place of Use polygons"""
        self.stdout.write("\n--- Place of Use (POU) ---")
        
        table_name = 'reference_water_pou'
        
        # Check if table exists
        if drop_existing:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        
        # 1. Load POU layer
        self.stdout.write("Loading POU layer: WR_Doc_POU1...")
        gdf = gpd.read_file(gdb_path, layer='WR_Doc_POU1')
        gdf.columns = [c.lower() for c in gdf.columns]
        self.stdout.write(f"  ✓ Loaded {len(gdf)} POU polygons")
        
        # Handle column naming
        if 'wr_doc_nr' not in gdf.columns:
            if 'wrdocnr' in gdf.columns:
                gdf = gdf.rename(columns={'wrdocnr': 'wr_doc_nr'})
        
        # 2. Transform to target SRID
        original_srid = gdf.crs.to_epsg() if gdf.crs else None
        self.stdout.write(f"Original SRID: {original_srid}")
        
        if original_srid != TARGET_SRID:
            self.stdout.write(f"Transforming to SRID {TARGET_SRID}...")
            gdf = gdf.to_crs(epsg=TARGET_SRID)
        
        # Standardize geometry column
        if gdf.geometry.name != 'geometry':
            gdf = gdf.rename_geometry('geometry')
        
        # 3. Import to PostGIS
        self.stdout.write(f"Importing to table: {table_name}")
        from sqlalchemy import create_engine
        from django.conf import settings
        
        db = settings.DATABASES['default']
        engine = create_engine(
            f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db.get('PORT', 5432)}/{db['NAME']}"
        )
        
        gdf.to_postgis(
            table_name,
            engine,
            if_exists='replace',
            index=False,
            chunksize=1000
        )
        
        self.stdout.write(f"  ✓ Imported {len(gdf):,} POU polygons")
        
        # 4. Create spatial index
        create_spatial_index(table_name, 'geometry')
        
        # 5. Log import
        log_import(
            dataset_name="Water Rights - Place of Use",
            table_name=table_name,
            source_path=gdb_path,
            success=True,
            row_count=len(gdf)
        )
        
        self.stdout.write(self.style.SUCCESS(f"✓ POU imported to {table_name}"))