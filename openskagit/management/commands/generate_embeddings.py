from django.core.management.base import BaseCommand
import pandas as pd
from sentence_transformers import SentenceTransformer
from tqdm import tqdm
import psycopg

# ---- CONFIG ----
DB_URL = "postgresql://django:grandson2025@localhost/skagit"
MODEL_NAME = "all-MiniLM-L6-v2"
VECTOR_DIM = 384
BATCH_SIZE = 1000  # adjust based on droplet RAM

class Command(BaseCommand):
    help = "Generate parcel embeddings in batches with resume capability"

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("🚀 Starting batched embedding generation..."))

        model = SentenceTransformer(MODEL_NAME)
        self.stdout.write(self.style.MIGRATE_LABEL(f"Loaded model: {MODEL_NAME}"))

        # Ensure vector column exists
        with psycopg.connect(DB_URL) as conn:
            conn.execute(f"CREATE EXTENSION IF NOT EXISTS vector;")
            conn.execute(f"ALTER TABLE assessor ADD COLUMN IF NOT EXISTS embedding vector({VECTOR_DIM});")
            conn.commit()

        # Count remaining rows
        with psycopg.connect(DB_URL) as conn:
            total_rows = conn.execute("SELECT COUNT(*) FROM assessor WHERE assessed_value IS NOT NULL;").fetchone()[0]
            remaining = conn.execute("SELECT COUNT(*) FROM assessor WHERE embedding IS NULL;").fetchone()[0]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"🧮 Total parcels: {total_rows}, Remaining to embed: {remaining}"
        ))

        offset = 0
        while True:
            with psycopg.connect(DB_URL) as conn:
                df = pd.read_sql(f"""
                    SELECT a.parcel_number,
                           CONCAT_WS(' ',
                             a.address,
                             'Neighborhood:', a.neighborhood_code,
                             'Land use code:', a.land_use_code,
                             'Assessed value:', a.assessed_value,
                             'Total market value:', a.total_market_value,
                             'Taxable value:', a.taxable_value,
                             'Acreage:', a.acres,
                             'Property type:', a.property_type,
                             'Building style:', a.building_style,
                             'Foundation:', a.foundation,
                             'Exterior walls:', a.exterior_walls,
                             'Roof:', a.roof_covering, a.roof_style,
                             'Bedrooms:', a.bedrooms,
                             'Bathrooms:', a.bathrooms,
                             'Fireplace:', a.fireplace,
                             'Garage sqft:', a.garage_sqft,
                             'Heating:', a.heat_air_cond,
                             'Year built:', a.year_built,
                             'Effective year built:', a.eff_year_built,
                             'Sale price:', a.sale_price,
                             'Sale date:', a.sale_date
                           ) AS description
                    FROM assessor a
                    WHERE a.embedding IS NULL AND a.assessed_value IS NOT NULL
                    ORDER BY a.parcel_number
                    LIMIT {BATCH_SIZE};
                """, conn)

            if df.empty:
                self.stdout.write(self.style.SUCCESS("✅ All parcels embedded. Done."))
                break

            self.stdout.write(self.style.MIGRATE_LABEL(f"Encoding {len(df)} parcels..."))
            tqdm.pandas()
            embeddings = model.encode(df["description"].astype(str).tolist(),
                          normalize_embeddings=True,
                          batch_size=64)

            # turn each row of the matrix into a Python list
            df["embedding"] = [e.tolist() for e in embeddings]


            with psycopg.connect(DB_URL) as conn:
                with conn.cursor() as cur:
                    for parcel, emb in zip(df["parcel_number"], df["embedding"]):
                        cur.execute(
                            "UPDATE assessor SET embedding = %s WHERE parcel_number = %s;",
                            (emb, parcel)
                        )
                conn.commit()

            offset += len(df)
            self.stdout.write(self.style.SUCCESS(f"✅ Processed {offset}/{total_rows} parcels."))

        self.stdout.write(self.style.SUCCESS("🎯 Embedding generation completed."))
