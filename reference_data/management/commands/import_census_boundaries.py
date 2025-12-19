# management/commands/import_census_boundaries.py
from django.core.management.base import BaseCommand
from django.db import connection
import geopandas as gpd
import requests
import zipfile
import io
import tempfile
import os

class Command(BaseCommand):
    help = 'Import Census block group boundaries for Skagit County'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=2023, help='Census year (default: 2023)')
        parser.add_argument('--drop', action='store_true', help='Drop existing table')
        parser.add_argument('--level', type=str, default='bg', 
                          choices=['bg', 'tract', 'county'],
                          help='Geography level: bg (block group), tract, or county')
    
    def handle(self, *args, **options):
        year = options['year']
        drop = options['drop']
        level = options['level']
        
        # Geography codes
        geo_codes = {
            'bg': ('bg', 'Block Groups', 'reference_census_block_groups'),
            'tract': ('tract', 'Tracts', 'reference_census_tracts'),
            'county': ('county', 'Counties', 'reference_census_counties')
        }
        
        geo_code, geo_name, table_name = geo_codes[level]
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing Census {geo_name} {year} for Washington State")
        self.stdout.write(f"{'='*60}\n")
        
        # 1. Download from Census TIGER
        self.stdout.write(f"Downloading {geo_name} boundaries from Census TIGER...")
        
        # Census TIGER URL format
        url = f"https://www2.census.gov/geo/tiger/TIGER{year}/{geo_code.upper()}/tl_{year}_53_{geo_code}.zip"
        
        self.stdout.write(f"  URL: {url}")
        
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self.stdout.write(self.style.ERROR(f"Failed to download: {e}"))
            self.stdout.write(f"\nTry manually downloading from:")
            self.stdout.write(f"https://www.census.gov/cgi-bin/geo/shapefiles/index.php")
            return
        
        self.stdout.write(f"  ✓ Downloaded {len(response.content):,} bytes")
        
        # 2. Extract and read shapefile
        self.stdout.write("Extracting and reading shapefile...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Extract zip
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                z.extractall(tmpdir)
            
            # Find .shp file
            shp_file = None
            for file in os.listdir(tmpdir):
                if file.endswith('.shp'):
                    shp_file = os.path.join(tmpdir, file)
                    break
            
            if not shp_file:
                self.stdout.write(self.style.ERROR("No shapefile found in download"))
                return
            
            # Read with geopandas
            gdf = gpd.read_file(shp_file)
            
            self.stdout.write(f"  ✓ Loaded {len(gdf):,} {geo_name.lower()}")
        
        # 3. Filter to Skagit County (COUNTYFP = 057)
        if level in ['bg', 'tract']:
            original_count = len(gdf)
            gdf = gdf[gdf['COUNTYFP'] == '057'].copy()
            self.stdout.write(f"  ✓ Filtered to Skagit County: {len(gdf):,} {geo_name.lower()}")
            
            if gdf.empty:
                self.stdout.write(self.style.WARNING("No features found for Skagit County!"))
                return
        
        # 4. Transform to SRID 2926
        original_srid = gdf.crs.to_epsg() if gdf.crs else 4269
        self.stdout.write(f"  ✓ Original SRID: {original_srid}")
        
        if original_srid != 2926:
            self.stdout.write("  → Transforming to SRID 2926...")
            gdf = gdf.to_crs(epsg=2926)
        
        # 5. Standardize columns
        gdf.columns = [c.lower() for c in gdf.columns]
        
        # Rename geometry column
        if gdf.geometry.name != 'geometry':
            gdf = gdf.rename_geometry('geometry')
        
        # 6. Add year column
        gdf['census_year'] = year
        
        # 7. Show what we have
        self.stdout.write(f"\nColumns: {', '.join(gdf.columns[:10])}" + 
                         (" ..." if len(gdf.columns) > 10 else ""))
        
        # 8. Import to PostGIS
        self.stdout.write(f"\nImporting to table: {table_name}")
        
        from sqlalchemy import create_engine
        from django.conf import settings
        
        db = settings.DATABASES['default']
        engine = create_engine(
            f"postgresql://{db['USER']}:{db['PASSWORD']}@{db['HOST']}:{db.get('PORT', 5432)}/{db['NAME']}"
        )
        
        if drop:
            self.stdout.write("Dropping existing table...")
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE;")
        
        gdf.to_postgis(
            table_name,
            engine,
            if_exists='replace' if drop else 'append',
            index=False,
            chunksize=100
        )
        
        self.stdout.write(f"  ✓ Imported {len(gdf):,} rows")
        
        # 9. Create indexes
        self.stdout.write("Creating indexes...")
        with connection.cursor() as cursor:
            # Spatial index
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geometry 
                ON {table_name} USING GIST(geometry);
            """)
            
            # GEOID index
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_geoid 
                ON {table_name}(geoid);
            """)
            
            # County index (for tracts/block groups)
            if level in ['bg', 'tract']:
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_countyfp 
                    ON {table_name}(countyfp);
                """)
            
            cursor.execute(f"VACUUM ANALYZE {table_name};")
        
        # 10. Verify
        with connection.cursor() as cursor:
            cursor.execute(f"""
                SELECT COUNT(*), ST_SRID(geometry) 
                FROM {table_name} 
                GROUP BY ST_SRID(geometry);
            """)
            count, srid = cursor.fetchone()
        
        self.stdout.write(
            self.style.SUCCESS(
                f"\n✓ SUCCESS: {count:,} {geo_name.lower()} imported to {table_name} (SRID {srid})"
            )
        )
        
        # 11. Show sample
        self.stdout.write("\nSample records:")
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT geoid, namelsad FROM {table_name} LIMIT 5;")
            for geoid, name in cursor.fetchall():
                self.stdout.write(f"  {geoid}: {name}")
        
        # 12. Show usage instructions
        self.stdout.write(self.style.SUCCESS(f"\n{'='*60}"))
        self.stdout.write("Next steps:")
        self.stdout.write(f"{'='*60}")
        self.stdout.write("\n1. Import Census ACS data:")
        self.stdout.write("   python manage.py import_census_acs --drop")
        self.stdout.write("\n2. Join census data to parcels:")
        self.stdout.write(f"""
   WITH parcel_census AS (
       SELECT DISTINCT ON (a.parcel_number)
           a.parcel_number,
           c.median_income,
           c.median_home_value,
           c.population,
           c.geoid as census_geoid
       FROM assessor a
       JOIN {table_name} bg ON ST_Intersects(a.geom_2926, bg.geometry)
       JOIN reference_census_acs c ON bg.geoid = c.geoid
   )
   UPDATE assessor a
   SET 
       census_median_income = pc.median_income,
       census_median_home_value = pc.median_home_value,
       census_geoid = pc.census_geoid
   FROM parcel_census pc
   WHERE a.parcel_number = pc.parcel_number;
        """)