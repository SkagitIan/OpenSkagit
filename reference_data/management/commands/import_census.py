# management/commands/import_census_acs.py
from django.core.management.base import BaseCommand
from django.db import connection
import requests
import csv
import io

class Command(BaseCommand):
    help = 'Import Census ACS data for Skagit County'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=2023, help='ACS year (default: 2023)')
        parser.add_argument('--drop', action='store_true', help='Drop existing table')
    
    def handle(self, *args, **options):
        year = options['year']
        drop = options['drop']
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Importing Census ACS {year} Data for Skagit County")
        self.stdout.write(f"{'='*60}\n")
        
        # ACS Variables
        variables = {
            'B19013_001E': 'median_income',
            'B15003_022E': 'edu_bachelors',
            'B15003_023E': 'edu_masters', 
            'B15003_024E': 'edu_professional',
            'B15003_025E': 'edu_doctorate',
            'B01001_001E': 'population',
            'B25077_001E': 'median_home_value',  # Added!
            'B25064_001E': 'median_rent',        # Added!
        }
        
        vars_list = ','.join(variables.keys())
        
        # 1. Download from Census API
        self.stdout.write("Downloading data from Census API...")
        url = f"https://api.census.gov/data/{year}/acs/acs5"
        params = {
            'get': f'NAME,{vars_list}',
            'for': 'block group:*',
            'in': 'state:53 county:057'  # WA State, Skagit County
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()
        
        data = response.json()
        header = data[0]
        rows = data[1:]
        
        self.stdout.write(f"  ✓ Downloaded {len(rows)} block groups")
        
        # 2. Create table
        if drop:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE IF EXISTS reference_census_acs CASCADE;")
        
        self.stdout.write("Creating table...")
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reference_census_acs (
                    name TEXT,
                    median_income NUMERIC,
                    edu_bachelors NUMERIC,
                    edu_masters NUMERIC,
                    edu_professional NUMERIC,
                    edu_doctorate NUMERIC,
                    population NUMERIC,
                    median_home_value NUMERIC,
                    median_rent NUMERIC,
                    state_fips TEXT,
                    county_fips TEXT,
                    tract_ce TEXT,
                    block_group_ce TEXT,
                    geoid TEXT,
                    year INTEGER
                );
                
                CREATE INDEX IF NOT EXISTS idx_reference_census_acs_geoid 
                ON reference_census_acs(geoid);
            """)
        
        # 3. Transform and insert data
        self.stdout.write("Inserting data...")
        
        # Map header positions
        name_idx = header.index('NAME')
        var_indices = {variables[var]: header.index(var) for var in variables}
        state_idx = header.index('state')
        county_idx = header.index('county')
        tract_idx = header.index('tract')
        bg_idx = header.index('block group')
        
        with connection.cursor() as cursor:
            for row in rows:
                # Build GEOID
                geoid = f"{row[state_idx]}{row[county_idx]}{row[tract_idx]}{row[bg_idx]}"
                
                # Convert nulls
                def safe_numeric(val):
                    return None if val in [None, '', '-666666666'] else float(val)
                
                cursor.execute("""
                    INSERT INTO reference_census_acs (
                        name, median_income, edu_bachelors, edu_masters, 
                        edu_professional, edu_doctorate, population,
                        median_home_value, median_rent,
                        state_fips, county_fips, tract_ce, block_group_ce, 
                        geoid, year
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    row[name_idx],
                    safe_numeric(row[var_indices['median_income']]),
                    safe_numeric(row[var_indices['edu_bachelors']]),
                    safe_numeric(row[var_indices['edu_masters']]),
                    safe_numeric(row[var_indices['edu_professional']]),
                    safe_numeric(row[var_indices['edu_doctorate']]),
                    safe_numeric(row[var_indices['population']]),
                    safe_numeric(row[var_indices['median_home_value']]),
                    safe_numeric(row[var_indices['median_rent']]),
                    row[state_idx],
                    row[county_idx],
                    row[tract_idx],
                    row[bg_idx],
                    geoid,
                    year
                ))
        
        self.stdout.write(self.style.SUCCESS(f"\n✓ Imported {len(rows)} block groups"))
        
        # 4. Show sample data
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT name, median_income, population, median_home_value
                FROM reference_census_acs 
                LIMIT 5
            """)
            self.stdout.write("\nSample data:")
            for row in cursor.fetchall():
                self.stdout.write(f"  {row[0]}: ${row[1]:,.0f} income, {row[2]:,.0f} pop, ${row[3]:,.0f} homes")