import sqlite3
from django.core.management.base import BaseCommand
from django.db import connection
from openskagit.models import AssessmentRoll, Assessor, Land, Improvements, Sales
import warnings
from django.utils import timezone
warnings.filterwarnings("ignore", message="DateTimeField .* received a naive datetime", category=RuntimeWarning)
from django.utils import timezone
from datetime import datetime



# ──────────────────────────────────────────────────────────────
# Column mappings: SQLite → Django
# ──────────────────────────────────────────────────────────────
COLUMN_MAP_ASSESSOR = {
    "parcel_number": "parcel_number",
    "full_address": "address",
    "neighborhood_code": "neighborhood_code",
    "land_use": "land_use_code",
    "building_value": "building_value",
    "improved_land_value": "impr_land_value",
    "unimproved_land_value": "unimpr_land_value",
    "timber_land_value": "timber_land_value",
    "assessed_value": "assessed_value",
    "taxable_value": "taxable_value",
    "total_market_value": "total_market_value",
    "acres": "acres",
    "sale_date": "sale_date",
    "sale_price": "sale_price",
    "sale_deed_type": "sale_deed_type",
    "total_taxes": "total_taxes",
    "year_built": "year_built",
    "effective_year_built": "eff_year_built",
    "living_area": "living_area",
    "building_style": "building_style",
    "foundation": "foundation",
    "exterior_walls": "exterior_walls",
    "roof_covering": "roof_covering",
    "roof_style": "roof_style",
    "floor_covering": "floor_covering",
    "floor_construction": "floor_construction",
    "interior_finish": "interior_finish",
    "bedrooms": "bedrooms",
    "garage_sqft": "garage_sqft",
    "heat_air_cond": "heat_air_cond",
    "fireplace": "fireplace",
    "finished_basement": "finished_basement",
    "unfinished_basement": "unfinished_basement",
    "fire_district": "fire_district",
    "school_district": "school_district",
    "city_district": "city_district",
    "levy_code": "levy_code",
    "current_use_adjustment": "current_use_adjustment",
    "tide_land_value": "tide_land_value",
    "senior_exemption_adjustment": "senior_exemption_adjustment",
    "property_type": "property_type",
    "has_septic": "has_septic",
}

COLUMN_MAP_LAND = {
    "parcel_number": "parcel_number",
    "property_value_year": "property_value_year",
    "land_segment_id": "land_segment_id",
    "land_type": "land_type",
    "appraisal_method": "appraisal_method",
    "size_acres": "size_acres",
    "size_square_feet": "size_square_feet",
    "effective_front": "effective_front",
    "actual_front": "actual_front",
    "land_adjustment_factor": "land_adjustment_factor",
    "adjusted_value": "adjusted_value",
    "market_unit_price": "market_unit_price",
    "market_value": "market_value",
    "open_space_value": "open_space_value",
    "open_space_use_description": "open_space_use_code_desc",
    "ag_unit_price": "agricultural_unit_price",
    "open_space_appraisal_method": "open_space_appraisal_method",
    "land_segment_comment": "land_segment_comment",
}

COLUMN_MAP_IMPROVEMENTS = {
    "parcel_number": "parcel_number",
    "improvement_id": "improvement_id",
    "description": "description",
    "building_style": "building_style",
    "comment": "comment",
    "improvement_value": "improvement_value",
    "new_construction_year": "new_construction_year",
    "total_living_area": "total_living_area",
    "segment_id": "segment_id",
    "detail_type_code": "improvement_detail_type_code",
    "detail_class_code": "improvement_detail_class_code",
    "detail_method_code": "improvement_detail_method_code",
    "condition_code": "condition_code",
    "calculated_area": "calculated_area",
    "unit_price": "unit_price",
    "depreciation_pct": "depreciation_pct",
    "detail_value": "improvement_detail_value",
    "construction_style": "construction_style",
    "foundation": "foundation",
    "exterior_wall": "exterior_wall",
    "roof_covering": "roof_covering",
    "roof_style": "roof_style",
    "flooring": "flooring",
    "floor_construction": "floor_construction",
    "interior_finish": "interior_finish",
    "plumbing": "plumbing_code",
    "appliances": "appliances",
    "heating_cooling": "heating_cooling",
    "fireplace": "fireplace",
    "rooms": "rooms",
    "bedrooms": "bedrooms",
    "effective_year_built": "effective_year_built",
    "actual_year_built": "actual_year_built",
    "sketch_path": "sketch_path",
}

COLUMN_MAP_SALES = {
    "sale_id": "sale_id",
    "parcel_number": "parcel_number",
    "account_number": "account_number",
    "sale_price": "sale_price",
    "sale_date": "sale_date",
    "sale_type": "sale_type",
    "recording_number": "recording_number",
    "deed_type": "deed_type",
    "deed_date": "deed_date",
    "reval_area": "revaluation_area",
    "excise_number": "excise_number",
}

# ──────────────────────────────────────────────────────────────
def map_fields(raw, mapping):
    """Return a dict of {django_field: value} using provided mapping."""
    return {mapping[k]: v for k, v in raw.items() if k in mapping}


class Command(BaseCommand):
    help = "Import assessor, land, improvements, and sales data from a SQLite roll file."

    def add_arguments(self, parser):
        parser.add_argument("--sqlite-path", required=True)
        parser.add_argument("--year", required=True, type=int)

    def handle(self, *args, **opts):
        sqlite_path = opts["sqlite_path"]
        year = opts["year"]

        roll, created = AssessmentRoll.objects.get_or_create(year=year)
        self.stdout.write(f"📦 Using AssessmentRoll {year} (id={roll.id}, created={created})")

        # ✅ Clean once per roll, not per table
        for model in [Assessor, Land, Improvements, Sales]:
            deleted = model.objects.filter(roll=roll).delete()
            self.stdout.write(f"🧹 Cleared {deleted[0]} existing {model.__name__} records for {year}.")

        conn = sqlite3.connect(sqlite_path)
        cur = conn.cursor()

        def import_table(table_name, model, mapping):
            cur.execute(f"SELECT * FROM {table_name};")
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            records = []
            ignored = set(cols) - set(mapping.keys())

            for row in rows:
                raw = dict(zip(cols, row))
                mapped = map_fields(raw, mapping)
                records.append(model(roll=roll, **mapped))
                # inside your loop that builds `mapped`
                if "sale_date" in mapped and isinstance(mapped["sale_date"], datetime):
                    if timezone.is_naive(mapped["sale_date"]):
                        mapped["sale_date"] = timezone.make_aware(mapped["sale_date"], timezone.get_default_timezone())


            if records:
                model.objects.bulk_create(records, batch_size=1000)
            self.stdout.write(f"✅ {table_name}: imported {len(records)} records.")
            if ignored:
                self.stdout.write(f"⚠️  Ignored columns: {', '.join(sorted(ignored))}")

        # Import each table
        import_table("PARCELS", Assessor, COLUMN_MAP_ASSESSOR)
        import_table("LAND_SEGMENTS", Land, COLUMN_MAP_LAND)
        import_table("IMPROVEMENTS", Improvements, COLUMN_MAP_IMPROVEMENTS)
        import_table("SALES", Sales, COLUMN_MAP_SALES)

        conn.close()
