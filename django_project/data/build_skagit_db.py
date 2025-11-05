"""
Build Skagit County Assessor SQLite Database
-------------------------------------------

This script loads the raw Skagit County assessor text files and produces a
SQLite database (`skagit_assessor.db`) with four normalized tables:

* **parcels** – one record per parcel with a full address and key valuation fields
* **land_segments** – one record per land segment (for parcels with multiple land types)
* **improvements** – one record per improvement (e.g. house, garage)
* **sales** – one record per recorded property sale

The script expects the following files to be present in the same directory:

* `AssessorData.txt`
* `Land.txt`
* `Sales.txt`
* `Improvements.txt`

These files can be extracted from the public ZIP archive available on
Skagit County’s assessments data download page.  After downloading
`SkagitAssessmentData.zip` and extracting it, place the text files next to
this script and run:

```
python build_skagit_db.py
```

The resulting SQLite database (`skagit_assessor.db`) will appear in the
same directory.
"""

import pandas as pd
import numpy as np
import sqlite3
import re
import os


def load_raw_data():
    """Load the raw assessor data files into pandas DataFrames."""
    assessor = pd.read_csv('AssessorData.txt', sep='|', dtype=str, encoding='latin1', on_bad_lines='skip')
    land = pd.read_csv('Land.txt', sep='|', dtype=str, encoding='latin1', on_bad_lines='skip')
    sales = pd.read_csv('Sales.txt', sep='|', dtype=str, encoding='latin1', on_bad_lines='skip')
    improvements = pd.read_csv('Improvements.txt', sep='|', dtype=str, encoding='latin1', on_bad_lines='skip')
    return assessor, land, sales, improvements


def build_full_address(row: pd.Series) -> str:
    """
    Combine street number, street name and city/state/zip into a single full
    address string.  Missing components are skipped.
    """
    parts = [row.get('Situs Street Number', ''), row.get('Situs Street Name', ''), row.get('Situs City State Zip', '')]
    parts = [str(x).strip() for x in parts if pd.notnull(x) and str(x).strip() != '']
    return ' '.join(parts) if parts else None


def parse_bedrooms(val) -> float:
    """
    Normalize bedroom counts to a floating point number.  Handles strings
    containing digits (e.g. '3+', '2.00') by extracting the first digit.
    Returns NaN when no numeric information is present.
    """
    if pd.isnull(val):
        return np.nan
    # Already numeric?  return as float
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val)
    match = re.search(r'\d+', s)
    return float(match.group(0)) if match else np.nan


def build_parcels_table(assessor: pd.DataFrame) -> pd.DataFrame:
    """Transform the assessor DataFrame into the parcels table."""
    # Column mapping from raw names to normalized names
    cols = {
        'Parcel Number': 'parcel_number',
        'Account Number': 'account_number',
        'Legal Description': 'legal_description',
        'Owner Name': 'owner_name',
        'Neighborhood Code': 'neighborhood_code',
        'Building Value': 'building_value',
        'Land Use': 'land_use',
        'Impr Land Value': 'improved_land_value',
        'Unimpr Land Value': 'unimproved_land_value',
        'Timber Land Value': 'timber_land_value',
        'Assessed Value': 'assessed_value',
        'Taxable Value': 'taxable_value',
        'Total Market Value': 'total_market_value',
        'Acres': 'acres',
        'Sale Date': 'sale_date',
        'Sale Price': 'sale_price',
        'Sale Deed Type': 'sale_deed_type',
        'Total Taxes': 'total_taxes',
        'Year Built': 'year_built',
        'Living Area': 'living_area',
        'Tot Special Assessments': 'total_special_assessments',
        'General Taxes': 'general_taxes',
        'Inactive Date': 'inactive_date',
        'BuildingStyle': 'building_style',
        'Foundation': 'foundation',
        'Exterior Walls': 'exterior_walls',
        'Roof Covering': 'roof_covering',
        'Roof Style': 'roof_style',
        'Floor Covering': 'floor_covering',
        'Floor Construction': 'floor_construction',
        'Interior Finish': 'interior_finish',
        'Plumbing': 'plumbing',
        'GarageSqFt': 'garage_sqft',
        'Heat Air Cond': 'heat_air_cond',
        'Fireplace': 'fireplace',
        'FinishedBasement': 'finished_basement',
        'Number of Bedrooms': 'bedrooms',
        'Eff Year Built': 'effective_year_built',
        'UnfinishedBasement': 'unfinished_basement',
        'Fire District': 'fire_district',
        'School District': 'school_district',
        'City District': 'city_district',
        'Unit': 'unit',
        'Levy Code': 'levy_code',
        'Current Use Adjustment': 'current_use_adjustment',
        'Tide Land Value': 'tide_land_value',
        'Senior Exemption Adjustment': 'senior_exemption_adjustment',
        'Township': 'township',
        'Range': 'range',
        'Section': 'section',
        'Quarter Section': 'quarter_section',
        'Tax Year': 'tax_year',
        'Appraisal Year': 'appraisal_year',
        'Utilities': 'utilities',
        'Tax Statement Taxable Value': 'tax_statement_taxable_value',
        'PropType': 'property_type',
        'HasSeptic': 'has_septic'
    }
    parcels = assessor[list(cols.keys())].rename(columns=cols)
    # Full address
    parcels['full_address'] = assessor.apply(build_full_address, axis=1)
    # Convert numeric strings to numeric types
    numeric_cols = [
        'building_value','improved_land_value','unimproved_land_value','timber_land_value',
        'assessed_value','taxable_value','total_market_value','acres','sale_price','total_taxes',
        'year_built','living_area','total_special_assessments','general_taxes','garage_sqft','finished_basement',
        'bedrooms','effective_year_built','unfinished_basement','current_use_adjustment','tide_land_value',
        'senior_exemption_adjustment','tax_year','appraisal_year','tax_statement_taxable_value'
    ]
    for col in numeric_cols:
        parcels[col] = pd.to_numeric(parcels[col].str.replace(',', ''), errors='coerce')
    # Parse bedrooms
    parcels['bedrooms'] = parcels['bedrooms'].apply(parse_bedrooms)
    # Convert has_septic to 0/1
    parcels['has_septic'] = parcels['has_septic'].map(lambda x: 1 if str(x).strip().lower() == 'true' else (0 if str(x).strip().lower() == 'false' else None))
    return parcels


def build_land_segments_table(land: pd.DataFrame) -> pd.DataFrame:
    """Transform the land DataFrame into the land_segments table."""
    cols = {
        'ParcelNumber': 'parcel_number',
        'prop_val_yr': 'property_value_year',
        'land_seg_id': 'land_segment_id',
        'land_type': 'land_type',
        'appr_meth': 'appraisal_method',
        'size_acres': 'size_acres',
        'size_square_feet': 'size_square_feet',
        'effective_front': 'effective_front',
        'actual_front': 'actual_front',
        'land_adj_factor': 'land_adjustment_factor',
        'adj_value': 'adjusted_value',
        'mkt_unit_price': 'market_unit_price',
        'market_value': 'market_value',
        'open_space_val': 'open_space_value',
        'open_space_use_code_desc': 'open_space_use_description',
        'ag_unit_price': 'ag_unit_price',
        'os_appr_meth': 'open_space_appraisal_method',
        'land_seg_comment': 'land_segment_comment'
    }
    land_segments = land[list(cols.keys())].rename(columns=cols)
    numeric_cols = ['size_acres','size_square_feet','effective_front','actual_front','land_adjustment_factor',
                    'adjusted_value','market_unit_price','market_value','open_space_value','ag_unit_price']
    for col in numeric_cols:
        land_segments[col] = pd.to_numeric(land_segments[col].str.replace(',', ''), errors='coerce')
    return land_segments


def build_sales_table(sales: pd.DataFrame) -> pd.DataFrame:
    """Transform the sales DataFrame into the sales table."""
    cols = {
        'SaleID': 'sale_id',
        'Parcel Number': 'parcel_number',
        'Account Number': 'account_number',
        'sale price': 'sale_price',
        'sale date': 'sale_date',
        'sale type': 'sale_type',
        'Recording Number': 'recording_number',
        'Deed Type': 'deed_type',
        'deed date': 'deed_date',
        'reval area': 'reval_area',
        'Excise Number': 'excise_number'
    }
    sales_tbl = sales[list(cols.keys())].rename(columns=cols)
    sales_tbl['sale_price'] = pd.to_numeric(sales_tbl['sale_price'].str.replace(',', ''), errors='coerce')
    return sales_tbl


def build_improvements_table(improvements: pd.DataFrame) -> pd.DataFrame:
    """Transform the improvements DataFrame into the improvements table."""
    cols = {
        'ParcelNumber': 'parcel_number',
        'imprv_id': 'improvement_id',
        'description': 'description',
        'building_style': 'building_style',
        'comment': 'comment',
        'imprv_val': 'improvement_value',
        'new_const_year': 'new_construction_year',
        'tot_living_area': 'total_living_area',
        'segment_id': 'segment_id',
        'imprv_det_type_cd': 'detail_type_code',
        'imprv_det_class_cd': 'detail_class_code',
        'imprv_det_meth_cd': 'detail_method_code',
        'condition_cd': 'condition_code',
        'calc_area': 'calculated_area',
        'unit_price': 'unit_price',
        'dep_pct': 'depreciation_pct',
        'imprv_det_val': 'detail_value',
        'ConstructionStyle': 'construction_style',
        'Foundation': 'foundation',
        'ExteriorWall': 'exterior_wall',
        'RoofCovering': 'roof_covering',
        'RoofStyle': 'roof_style',
        'Flooring': 'flooring',
        'FloorConstruction': 'floor_construction',
        'InteriorFinish': 'interior_finish',
        'Plumbing': 'plumbing',
        'Appliances': 'appliances',
        'HeatingCooling': 'heating_cooling',
        'Fireplace': 'fireplace',
        'Rooms': 'rooms',
        'Bedrooms': 'bedrooms',
        'effective_yr_blt': 'effective_year_built',
        'actual_year_built': 'actual_year_built',
        'sketchpath': 'sketch_path'
    }
    imprv_tbl = improvements[list(cols.keys())].rename(columns=cols)
    numeric_cols = ['improvement_value','new_construction_year','total_living_area','calculated_area','unit_price',
                    'depreciation_pct','detail_value','rooms','bedrooms','effective_year_built','actual_year_built']
    for col in numeric_cols:
        imprv_tbl[col] = pd.to_numeric(imprv_tbl[col].str.replace(',', ''), errors='coerce')
    return imprv_tbl


def create_database(parcels: pd.DataFrame, land_segments: pd.DataFrame, improvements: pd.DataFrame, sales: pd.DataFrame, db_path: str = 'skagit_assessor.db') -> None:
    """Write the DataFrames to a SQLite database with appropriate indexes."""
    conn = sqlite3.connect(db_path)
    parcels.to_sql('parcels', conn, index=False, if_exists='replace')
    land_segments.to_sql('land_segments', conn, index=False, if_exists='replace')
    improvements.to_sql('improvements', conn, index=False, if_exists='replace')
    sales.to_sql('sales', conn, index=False, if_exists='replace')
    # Create indexes on parcel_number for faster joins
    conn.execute('CREATE INDEX IF NOT EXISTS idx_parcels_parcel_number ON parcels(parcel_number)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_land_segments_parcel_number ON land_segments(parcel_number)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_improvements_parcel_number ON improvements(parcel_number)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_sales_parcel_number ON sales(parcel_number)')
    conn.commit()
    conn.close()


def main() -> None:
    assessor, land, sales, improvements = load_raw_data()
    parcels_tbl = build_parcels_table(assessor)
    land_tbl = build_land_segments_table(land)
    sales_tbl = build_sales_table(sales)
    imprv_tbl = build_improvements_table(improvements)
    create_database(parcels_tbl, land_tbl, imprv_tbl, sales_tbl)
    print('Database built successfully: skagit_assessor.db')


if __name__ == '__main__':
    main()