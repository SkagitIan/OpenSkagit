# management/commands/pipeline/utils.py
from django.db import connection
import logging

logger = logging.getLogger(__name__)

TARGET_SRID = 2926  # Washington State Plane North

def create_spatial_index(table_name, geom_column='geometry'):
    """Create spatial index on a table"""
    with connection.cursor() as cursor:
        index_name = f"idx_{table_name}_{geom_column}_gist"
        
        # Drop index if exists (for reimports)
        cursor.execute(f"DROP INDEX IF EXISTS {index_name};")
        
        # Create new index
        cursor.execute(f"""
            CREATE INDEX {index_name} 
            ON {table_name} 
            USING GIST({geom_column});
        """)
        
        # Optimize
        cursor.execute(f"VACUUM ANALYZE {table_name};")
        
        logger.info(f"✓ Created spatial index on {table_name}.{geom_column}")

def get_table_info(table_name):
    """Get row count and SRID from a table"""
    with connection.cursor() as cursor:
        # Check if table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = %s
            );
        """, [table_name])
        
        if not cursor.fetchone()[0]:
            return None
            
        # Get row count
        cursor.execute(f"SELECT COUNT(*) FROM {table_name};")
        row_count = cursor.fetchone()[0]
        
        # Get SRID (try common geometry column names)
        srid = None
        for col in ['geometry', 'geom', 'wkb_geometry']:
            try:
                cursor.execute(f"SELECT ST_SRID({col}) FROM {table_name} LIMIT 1;")
                srid = cursor.fetchone()[0]
                break
            except:
                continue
        
        return {'row_count': row_count, 'srid': srid}

def log_import(dataset_name, table_name, source_path, success=True, error_msg=None, row_count=0):
    """Log import run to database"""
    from reference_data.models import ReferenceDataImportLog  # Change 'yourapp' to your actual app name
    
    ReferenceDataImportLog.objects.create(
        dataset_name=dataset_name,
        table_name=table_name,
        source_path=source_path,
        success=success,
        error_message=error_msg,
        row_count=row_count,
        srid=TARGET_SRID
    )
    
    if success:
        logger.info(f"✓ Logged successful import: {dataset_name} ({row_count} rows)")
    else:
        logger.error(f"✗ Logged failed import: {dataset_name} - {error_msg}")