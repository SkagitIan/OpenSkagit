# management/commands/import_arcgis_rest.py
from django.core.management.base import BaseCommand
from django.db import connection
import geopandas as gpd
import requests
from shapely.geometry import shape
import logging
from .utils import create_spatial_index, log_import, TARGET_SRID
from psycopg2.extras import execute_values
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Import data from ArcGIS REST API endpoint to PostGIS with SRID 2926'

    def add_arguments(self, parser):
        parser.add_argument('rest_url', type=str, help='ArcGIS REST API query endpoint URL (or MapServer URL for --list-layers)')
        parser.add_argument('table_name', type=str, nargs='?', help='Target table name (not needed for --list-layers)')
        parser.add_argument('--dataset-name', type=str, help='Friendly dataset name for logging')
        parser.add_argument('--source-srid', type=int, help='Source SRID if known (default: detect from API)')
        parser.add_argument('--where', type=str, default='1=1', help='SQL WHERE clause for filtering (default: 1=1)')
        parser.add_argument('--drop', action='store_true', help='Drop existing table if exists')
        parser.add_argument('--list-layers', action='store_true', help='List available layers in the MapServer and exit')
        parser.add_argument('--import-all', action='store_true')

        
    def handle(self, *args, **options):
        rest_url = options['rest_url']
        table_name = options.get('table_name')
        list_layers = options['list_layers']
        if options.get("import_all"):
            base = rest_url.rstrip('/').split('/FeatureServer')[0] + '/FeatureServer'

            MITIGATION_LAYERS = {
                0: ("Updated_PropMitZone", "ZONE"),
                1: ("FloddLayer_inBufferZone", "FLOOD_BUFFER"),
                2: ("Dissolved_Watercourses_3", "WATERCOURSE"),
                3: ("Dissolved_Waterbodies", "WATERBODY"),
                4: ("RedZoneParcels", "RED"),
                5: ("YellowZoneParcels", "YELLOW"),
                6: ("SecondHalf_GreenZoneParcels", "GREEN"),
                7: ("FirstHalf_GreenZoneParcels", "GREEN"),
            }

            for layer_id, (layer_name, mitigation_class) in MITIGATION_LAYERS.items():
                layer_url = f"{base}/{layer_id}/query"
                self.stdout.write(f"→ Importing {layer_name}")
                self.import_layer(
                    layer_url,
                    table_name,
                    layer_id,
                    layer_name,
                    mitigation_class
                )
            return

        # Handle --list-layers
        if list_layers:
            self.list_mapserver_layers(rest_url)
            return
        
        # Validate table_name is provided for import
        if not table_name:
            self.stdout.write(self.style.ERROR("Error: table_name is required for import (or use --list-layers)"))
            return
        
        dataset_name = options.get('dataset_name') or table_name
        source_srid = options.get('source_srid')
        where_clause = options['where']
        drop_existing = options['drop']
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing from ArcGIS REST API: {dataset_name}")
        self.stdout.write(f"{'='*60}\n")
        
        try:
            # Drop existing table if requested
            if drop_existing:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
                    self.stdout.write("Dropped existing table")
            
            # 1. Download data from ArcGIS REST API
            self.stdout.write(f"Querying ArcGIS REST API...")
            self.stdout.write(f"  URL: {rest_url}")
            self.stdout.write(f"  WHERE: {where_clause}")
            
            params = {
                "where": where_clause,
                "outFields": "*",
                "f": "geojson",
                "returnGeometry": "true"
            }
            
            response = requests.get(rest_url, params=params, timeout=120)
            response.raise_for_status()
            
            data = response.json()
            
            # 2. Parse features (handle ESRI quirks)
            features = []
            skipped = 0
            
            for feat in data.get("features", []):
                try:
                    geom = shape(feat["geometry"])
                    props = feat.get("properties", {})
                    features.append({"geometry": geom, **props})
                except Exception as e:
                    skipped += 1
                    continue
            
            if not features:
                raise ValueError("No valid features returned from API")
            
            self.stdout.write(f"  ✓ Downloaded {len(features):,} features")
            if skipped > 0:
                self.stdout.write(self.style.WARNING(f"  ⚠ Skipped {skipped} invalid features"))
            
            # 3. Detect or use provided SRID
            if source_srid:
                crs = f"EPSG:{source_srid}"
                self.stdout.write(f"  ✓ Using provided SRID: {source_srid}")
            else:
                # Try to detect from spatialReference in response
                spatial_ref = data.get("crs", {}).get("properties", {}).get("name", "")
                if "2285" in spatial_ref or "NAD83" in spatial_ref:
                    crs = "EPSG:2285"  # Common for Skagit County
                    self.stdout.write(f"  ✓ Detected SRID: 2285")
                elif "2926" in spatial_ref:
                    crs = "EPSG:2926"
                    self.stdout.write(f"  ✓ Detected SRID: 2926")
                else:
                    crs = "EPSG:4326"  # Default fallback
                    self.stdout.write(self.style.WARNING(f"  ⚠ Could not detect SRID, assuming 4326"))
            
            # 4. Create GeoDataFrame
            gdf = gpd.GeoDataFrame(features, crs=crs)
            
            # Show geometry type
            geom_types = gdf.geometry.geom_type.unique()
            self.stdout.write(f"  ✓ Geometry types: {', '.join(geom_types)}")
            
            # Show columns
            self.stdout.write(f"  ✓ Columns: {', '.join(gdf.columns[:10].tolist())}" + 
                            (" ..." if len(gdf.columns) > 10 else ""))
            
            # 5. Transform to target SRID
            original_srid = gdf.crs.to_epsg()
            if original_srid != TARGET_SRID:
                self.stdout.write(f"  → Transforming from SRID {original_srid} to {TARGET_SRID}...")
                gdf = gdf.to_crs(epsg=TARGET_SRID)
            
            # 6. Standardize geometry column name
            if gdf.geometry.name != 'geometry':
                gdf = gdf.rename_geometry('geometry')
            
            # 7. Import to PostGIS
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
            
            self.stdout.write(f"  ✓ Imported {len(gdf):,} rows")
            
            # 8. Create spatial index
            self.stdout.write("Creating spatial index...")
            create_spatial_index(table_name, 'geometry')
            
            # 9. Verify
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*), ST_SRID(geometry) FROM {table_name} GROUP BY ST_SRID(geometry);")
                result = cursor.fetchone()
                count, srid = result
            
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n✓ SUCCESS: {count:,} rows imported to {table_name} (SRID {srid})"
                )
            )
            
            # 10. Log import
            log_import(
                dataset_name=dataset_name,
                table_name=table_name,
                source_path=rest_url,
                success=True,
                row_count=count
            )
            
        except Exception as e:
            error_msg = str(e)
            self.stdout.write(self.style.ERROR(f"\n✗ ERROR: {error_msg}"))
            logger.exception("ArcGIS REST import failed")
            
            # Log failure
            log_import(
                dataset_name=dataset_name,
                table_name=table_name,
                source_path=rest_url,
                success=False,
                error_msg=error_msg
            )
            
            raise
        


    def import_layer(self, rest_url, table_name, layer_id, layer_name, mitigation_class):
        params = {
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson"
        }

        response = requests.get(rest_url, params=params, timeout=120)
        response.raise_for_status()
        data = response.json()

        rows = []
        skipped = 0

        for feat in data.get("features", []):
            try:
                geom = shape(feat["geometry"])
                rows.append((
                    layer_id,
                    layer_name,
                    mitigation_class,
                    layer_name,                     # source_layer
                    feat.get("properties", {}),     # attributes
                    geom.wkt                        # geometry as WKT
                ))
            except Exception:
                skipped += 1

        if not rows:
            self.stdout.write(self.style.WARNING(f"No features for {layer_name}"))
            return

        with connection.cursor() as dj_cur:
            psyco_cur = dj_cur.connection.cursor()

            execute_values(
                psyco_cur,
                f"""
                INSERT INTO {table_name} (
                    layer_id,
                    layer_name,
                    mitigation_class,
                    source_layer,
                    attributes,
                    geometry
                )
                VALUES %s
                """,
                rows,
                template="""
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s::jsonb,
                    ST_SetSRID(ST_GeomFromText(%s), 2926)
                )
                """,
                page_size=1000
            )


        create_spatial_index(table_name, "geometry")

        self.stdout.write(
            self.style.SUCCESS(
                f"✓ {layer_name}: inserted {len(rows)} rows (skipped {skipped})"
            )
        )

    def list_mapserver_layers(self, mapserver_url):
        """List all available layers in a MapServer"""
        # Remove /query or layer number from URL if present
        base_url = mapserver_url.split('/query')[0].split('/MapServer')[0] + '/MapServer'
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Listing layers from: {base_url}")
        self.stdout.write(f"{'='*60}\n")
        
        try:
            response = requests.get(base_url, params={'f': 'pjson'}, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            layers = data.get('layers', [])
            
            if not layers:
                self.stdout.write(self.style.WARNING("No layers found in this MapServer"))
                return
            
            self.stdout.write(self.style.SUCCESS(f"Found {len(layers)} layers:\n"))
            
            for layer in layers:
                layer_id = layer.get('id')
                layer_name = layer.get('name', 'Unknown')
                geom_type = layer.get('geometryType', 'Unknown')
                
                self.stdout.write(f"  [{layer_id}] {layer_name}")
                self.stdout.write(f"      Type: {geom_type}")
                self.stdout.write(f"      URL: {base_url}/{layer_id}/query\n")
            
            self.stdout.write(self.style.SUCCESS("\nTo import a layer, use:"))
            self.stdout.write(f"python manage.py import_arcgis_rest \"{base_url}/LAYER_ID/query\" table_name --drop\n")
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error listing layers: {e}"))