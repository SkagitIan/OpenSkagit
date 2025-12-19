# management/commands/import_wells.py
from django.core.management.base import BaseCommand
from django.db import connection
import geopandas as gpd
import logging
from .utils import create_spatial_index, log_import, TARGET_SRID
import os

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import Well Reports from Ecology GDB'

    def add_arguments(self, parser):
        parser.add_argument('gdb_path', type=str, help='Path to WR_GEO_WellReports.gdb')
        parser.add_argument('--drop', action='store_true', help='Drop existing table if exists')
        parser.add_argument('--layer', type=str, default='WR_GEO_WellReports', help='Layer name in GDB')
        
    def handle(self, *args, **options):
        gdb_path = options['gdb_path']
        layer_name = options['layer']
        drop_existing = options['drop']
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing Well Reports")
        self.stdout.write(f"{'='*60}\n")
        
        table_name = 'reference_wells'
        
        try:
            # Check if file exists
            if not os.path.exists(gdb_path):
                raise FileNotFoundError(f"GDB not found at: {gdb_path}")
            
            # Drop existing table if requested
            if drop_existing:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
                    self.stdout.write("Dropped existing table")
            
            # 1. Read from GDB
            self.stdout.write(f"Reading layer '{layer_name}' from {gdb_path}...")
            self.stdout.write("(This may take a moment - large dataset)")
            
            gdf = gpd.read_file(gdb_path, layer=layer_name)
            self.stdout.write(f"  ✓ Loaded {len(gdf):,} well reports")
            
            # 2. Standardize column names to lowercase
            gdf.columns = [c.lower() for c in gdf.columns]
            
            # 3. Map columns to consistent names
            column_map = {
                'well_tag_nr': 'well_tag_id',
                'well_depth_qt': 'well_depth',
                'welllog_gpm_qt': 'yield_gpm',
                'well_type_cd': 'use_type',
                'well_log_id': 'well_log_id'
            }
            
            # Apply mapping for columns that exist
            rename_dict = {k: v for k, v in column_map.items() if k in gdf.columns}
            if rename_dict:
                gdf = gdf.rename(columns=rename_dict)
                self.stdout.write(f"  ✓ Renamed columns: {list(rename_dict.values())}")
            
            # Show what columns we have
            important_cols = ['well_tag_id', 'well_depth', 'yield_gpm', 'use_type']
            available_cols = [c for c in important_cols if c in gdf.columns]
            self.stdout.write(f"  ✓ Available data fields: {', '.join(available_cols)}")
            
            # 4. Handle CRS
            if gdf.crs is None:
                self.stdout.write(self.style.WARNING("  ⚠ No CRS defined, assuming EPSG:4326"))
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
            
            original_srid = gdf.crs.to_epsg()
            self.stdout.write(f"  ✓ Original SRID: {original_srid}")
            
            # 5. Transform to target SRID
            if original_srid != TARGET_SRID:
                self.stdout.write(f"  → Transforming to SRID {TARGET_SRID}...")
                gdf = gdf.to_crs(epsg=TARGET_SRID)
            
            # 6. Standardize geometry column
            if gdf.geometry.name != 'geometry':
                gdf = gdf.rename_geometry('geometry')
            
            # 7. Import to PostGIS
            self.stdout.write(f"Importing to table: {table_name}")
            self.stdout.write("  (Processing in chunks - this will take a few minutes)")
            
            from sqlalchemy import create_engine
            from django.conf import settings
            
            db = settings.DATABASES['default']
            engine = create_engine(
                f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db.get('PORT', 5432)}/{db['NAME']}"
            )
            
            # Import in chunks for large dataset
            gdf.to_postgis(
                table_name,
                engine,
                if_exists='replace',
                index=False,
                chunksize=5000  # Process 5000 rows at a time
            )
            
            self.stdout.write(f"  ✓ Imported {len(gdf):,} well reports")
            
            # 8. Create spatial index
            self.stdout.write("Creating spatial index...")
            create_spatial_index(table_name, 'geometry')
            
            # 9. Create additional indexes for common queries
            self.stdout.write("Creating attribute indexes...")
            with connection.cursor() as cursor:
                # Index on well_tag_id for lookups
                if 'well_tag_id' in gdf.columns:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_well_tag_id ON {table_name}(well_tag_id);")
                
                # Index on use_type for filtering
                if 'use_type' in gdf.columns:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table_name}_use_type ON {table_name}(use_type);")
                
                cursor.execute(f"VACUUM ANALYZE {table_name};")
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ SUCCESS: {len(gdf):,} well reports imported to {table_name} (SRID {TARGET_SRID})"
                )
            )
            
            # 10. Show some statistics
            self.stdout.write("\n--- Dataset Statistics ---")
            if 'use_type' in gdf.columns:
                use_types = gdf['use_type'].value_counts()
                self.stdout.write("Well types:")
                for use_type, count in use_types.head(10).items():
                    self.stdout.write(f"  {use_type}: {count:,}")
            
            if 'yield_gpm' in gdf.columns:
                non_null_yield = gdf['yield_gpm'].notna().sum()
                self.stdout.write(f"\nWells with yield data: {non_null_yield:,} ({non_null_yield/len(gdf)*100:.1f}%)")
            
            if 'well_depth' in gdf.columns:
                non_null_depth = gdf['well_depth'].notna().sum()
                self.stdout.write(f"Wells with depth data: {non_null_depth:,} ({non_null_depth/len(gdf)*100:.1f}%)")
            
            # 11. Log import
            log_import(
                dataset_name="Ecology Well Reports",
                table_name=table_name,
                source_path=gdb_path,
                success=True,
                row_count=len(gdf)
            )
            
        except Exception as e:
            error_msg = str(e)
            self.stdout.write(self.style.ERROR(f"\n✗ ERROR: {error_msg}"))
            logger.exception("Wells import failed")
            
            # Log failure
            log_import(
                dataset_name="Ecology Well Reports",
                table_name=table_name,
                source_path=gdb_path,
                success=False,
                error_msg=error_msg
            )
            
            raise