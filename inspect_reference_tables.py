import json
import psycopg2
from psycopg2.extras import RealDictCursor

OUTPUT_FILE = "reference_table_manifest.json"

def q(col):
    """Quote a column name safely for Postgres."""
    return f'"{col}"'


def get_reference_tables(conn):
    query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        AND table_name LIKE 'reference_%'
        ORDER BY table_name;
    """
    cur = conn.cursor()
    cur.execute(query)
    return [row[0] for row in cur.fetchall()]


def detect_geom_column(conn, table):
    query = f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='{table}'
        AND udt_name IN ('geometry', 'geography');
    """
    cur = conn.cursor()
    cur.execute(query)
    result = cur.fetchall()

    if not result:
        # Fallback: look for any column containing 'geom'
        cur.execute(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public'
            AND table_name='{table}'
            AND column_name ILIKE '%geom%';
        """)
        result = cur.fetchall()

    return result[0][0] if result else None


def get_row_count(conn, table):
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table};")
    return cur.fetchone()[0]


def get_null_geom_count(conn, table, geom_col):
    if geom_col is None:
        return None
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {geom_col} IS NULL;")
    return cur.fetchone()[0]


def get_geom_type(conn, table, geom_col):
    if geom_col is None:
        return None
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT ST_GeometryType({geom_col}) AS gtype, COUNT(*)
        FROM {table}
        WHERE {geom_col} IS NOT NULL
        GROUP BY gtype;
        """
    )
    rows = cur.fetchall()
    # Return a dict of geometry types and counts
    return {row[0]: row[1] for row in rows}

def get_columns(conn, table):
    query = f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema='public'
        AND table_name='{table}';
    """
    cur = conn.cursor()
    cur.execute(query)
    return {row[0]: row[1] for row in cur.fetchall()}

def get_sample_rows(conn, table, geom_col):
    """
    Return only non-geom columns so output is readable.
    Columns are quoted to handle case-sensitive names.
    """
    cols = get_columns(conn, table)
    non_geom_cols = [c for c in cols.keys() if c != geom_col]

    # Avoid SELECTing huge geometries and empty column lists
    if not non_geom_cols:
        return []

    # Quote all columns so OBJECTID / PermitNumber work
    cols_str = ", ".join(q(c) for c in non_geom_cols)

    query = f'SELECT {cols_str} FROM "{table}" LIMIT 5;'

    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute(query)
        return cur.fetchall()
    except Exception as e:
        return [{"error": str(e)}]


def build_manifest():
    conn = psycopg2.connect(
        host="localhost",
        database="skagit",
        user="django",
        password="grandson2025"
    )

    tables = get_reference_tables(conn)
    manifest = {}

    for t in tables:
        geom_col = detect_geom_column(conn, t)
        
        manifest[t] = {
            "row_count": get_row_count(conn, t),
            "geometry_column": geom_col,
            "null_geometry_count": get_null_geom_count(conn, t, geom_col),
            "geometry_types": get_geom_type(conn, t, geom_col),
            "columns": get_columns(conn, t),
            "sample_rows": get_sample_rows(conn, t, geom_col),
        }

    import decimal

    def json_default(o):
        if isinstance(o, decimal.Decimal):
            return float(o)
        return str(o)  # fallback for anything weird

    with open(OUTPUT_FILE, "w") as f:
        json.dump(manifest, f, indent=4, default=json_default)


    print(f"\nManifest written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_manifest()
