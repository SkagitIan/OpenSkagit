# management/commands/import_geo.py
from django.core.management.base import BaseCommand
from django.db import connection
import geopandas as gpd
import fiona
import logging
import zipfile
import tempfile
import os
from pathlib import Path
from .utils import create_spatial_index, log_import, get_table_info, TARGET_SRID

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Import geospatial file (shapefile, geopackage, gdb, or zip) to PostGIS with SRID 2926'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Path to shapefile, geopackage, .gdb, or zip file')
        parser.add_argument('table_name', type=str, help='Target table name (e.g., reference_parcels)')
        parser.add_argument('--dataset-name', type=str, help='Friendly dataset name for logging')
        parser.add_argument('--layer', type=str, help='Layer name (for geopackages/gdb with multiple layers)')
        parser.add_argument('--drop', action='store_true', help='Drop existing table if exists')
        parser.add_argument('--list-layers', action='store_true', help='List layers in file and exit')
        
    def handle(self, *args, **options):
        file_path = options['file_path']
        table_name = options['table_name']
        dataset_name = options.get('dataset_name') or table_name
        layer_name = options.get('layer')
        drop_existing = options['drop']
        list_layers = options['list_layers']
        
        # Detect file type
        is_zip = file_path.endswith('.zip')
        is_gdb = file_path.endswith('.gdb') and os.path.isdir(file_path)
        
        # Handle --list-layers
        if list_layers:
            try:
                if is_zip:
                    read_path = f"zip://{file_path}"
                else:
                    read_path = file_path
                    
                layers = fiona.listlayers(read_path)
                self.stdout.write(self.style.SUCCESS(f"\nLayers in {file_path}:"))
                for i, layer in enumerate(layers, 1):
                    self.stdout.write(f"  {i}. {layer}")
                return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error reading layers: {e}"))
                return
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing Geospatial File: {dataset_name}")
        self.stdout.write(f"{'='*60}\n")
        
        try:
            # 1. Check if table exists
            existing_info = get_table_info(table_name)
            if existing_info:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠ Table '{table_name}' already exists with {existing_info['row_count']} rows"
                    )
                )
                if not drop_existing:
                    self.stdout.write(
                        self.style.ERROR("Use --drop flag to replace existing table")
                    )
                    return
                else:
                    self.stdout.write("Dropping existing table...")
                    with connection.cursor() as cursor:
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
            
            # 2. Read file
            self.stdout.write(f"Reading file: {file_path}")
            
            # Handle different file types
            if is_gdb:
                self.stdout.write("  ✓ Detected File Geodatabase (.gdb)")
                if not layer_name:
                    self.stdout.write(self.style.ERROR("  ERROR: --layer required for .gdb files"))
                    self.stdout.write("  Run with --list-layers to see available layers")
                    return
                self.stdout.write(f"  Layer: {layer_name}")
                gdf = gpd.read_file(file_path, layer=layer_name)
                
            elif is_zip:
                self.stdout.write("  ✓ Detected zip file")
                read_path = f"zip://{file_path}"
                if layer_name:
                    self.stdout.write(f"  Layer: {layer_name}")
                    gdf = gpd.read_file(read_path, layer=layer_name)
                else:
                    gdf = gpd.read_file(read_path)
                    
            else:
                # Regular file (shapefile, geopackage, etc.)
                if layer_name:
                    self.stdout.write(f"  Layer: {layer_name}")
                    gdf = gpd.read_file(file_path, layer=layer_name)
                else:
                    gdf = gpd.read_file(file_path)
                
            original_srid = gdf.crs.to_epsg() if gdf.crs else None
            geom_type = gdf.geometry.geom_type.unique()
            
            self.stdout.write(f"  ✓ Loaded {len(gdf):,} features")
            self.stdout.write(f"  ✓ Original SRID: {original_srid}")
            self.stdout.write(f"  ✓ Geometry types: {', '.join(geom_type)}")
            
            # Show column names
            self.stdout.write(f"  ✓ Columns: {', '.join(gdf.columns[:10].tolist())}" + 
                            (" ..." if len(gdf.columns) > 10 else ""))
            
            # 3. Transform to target SRID if needed
            if original_srid != TARGET_SRID:
                self.stdout.write(f"  → Transforming to SRID {TARGET_SRID}...")
                gdf = gdf.to_crs(epsg=TARGET_SRID)
            
            # 4. Standardize geometry column name
            if gdf.geometry.name != 'geometry':
                gdf = gdf.rename_geometry('geometry')
            
            # 5. Import to PostGIS
            self.stdout.write(f"Importing to table: {table_name}")
            from sqlalchemy import create_engine
            from django.conf import settings
            
            # Build connection string from Django settings
            db = settings.DATABASES['default']
            engine = create_engine(
                f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db.get('PORT', 5432)}/{db['NAME']}"
            )
            
            # For large datasets, show progress
            self.stdout.write("  → Writing to database (this may take a moment for large datasets)...")
            
            gdf.to_postgis(
                table_name,
                engine,
                if_exists='replace',
                index=False,
                chunksize=1000  # Process in chunks for large datasets
            )
            
            self.stdout.write(f"  ✓ Imported {len(gdf):,} rows")
            
            # 6. Create spatial index
            self.stdout.write("Creating spatial index...")
            create_spatial_index(table_name, 'geometry')
            
            # 7. Verify
            final_info = get_table_info(table_name)
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ SUCCESS: {final_info['row_count']:,} rows imported to {table_name} (SRID {final_info['srid']})"
                )
            )
            
            # 8. Log import
            log_import(
                dataset_name=dataset_name,
                table_name=table_name,
                source_path=file_path,
                success=True,
                row_count=final_info['row_count']
            )
            
        except Exception as e:
            error_msg = str(e)
            self.stdout.write(self.style.ERROR(f"\n✗ ERROR: {error_msg}"))
            logger.exception("Import failed")
            
            # Log failure
            log_import(
                dataset_name=dataset_name,
                table_name=table_name,
                source_path=file_path,
                success=False,
                error_msg=error_msg
            )
            
            raise