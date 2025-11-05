from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = "Clean neighborhood and land use codes in bulk using SQL."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Neighborhood
            cursor.execute("""
                UPDATE assessor
                   SET neighborhood_code = UPPER(REGEXP_REPLACE(neighborhood_code, '\\(([^)]+)\\).*', '\\1')),
                       neighborhood_code_description = INITCAP(TRIM(REGEXP_REPLACE(neighborhood_code, '^\\([^)]*\\)', '')))
                 WHERE neighborhood_code ~ '^\\([^)]*\\)';
            """)
            self.stdout.write("✅ Neighborhood codes cleaned.")

            # Land use
            cursor.execute("""
                UPDATE assessor
                   SET land_use_code = UPPER(REGEXP_REPLACE(land_use_code, '\\(([^)]+)\\).*', '\\1')),
                       land_use_description = INITCAP(TRIM(REGEXP_REPLACE(land_use_code, '^\\([^)]*\\)', '')))
                 WHERE land_use_code ~ '^\\([^)]*\\)';
            """)
            self.stdout.write("✅ Land use codes cleaned.")
