SELECT 
  COUNT(DISTINCT a.parcel_number) AS total_res_parcels,
  COUNT(DISTINCT i.parcel_number) AS with_main_improvement,
  ROUND(
    COUNT(DISTINCT i.parcel_number) * 100.0 / COUNT(DISTINCT a.parcel_number),
    2
  ) AS pct_with_main_impr
FROM assessor a
LEFT JOIN improvements i
  ON a.parcel_number = i.parcel_number
 AND i.improvement_detail_class_code IN ('MA','MA1.5','MA2','MA2.5','MA-SPLIT','MA-TRI','SW','MH')
WHERE (a.land_use_code::int) IN (110,111,112,113,120,130,140,180,181,182,190,910,911,912);

DROP MATERIALIZED VIEW IF EXISTS sale_regression_dataset;
CREATE MATERIALIZED VIEW sale_regression_dataset AS
SELECT
    ROW_NUMBER() OVER () AS id,
    s.id AS sale_id,
    s.parcel_number,
    r.year,
    s.sale_price,
    s.sale_date,
    a.assessed_value,
    a.total_market_value,
    a.living_area,
    -- Garage flags
    MAX(CASE WHEN UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'AGAR%' THEN 1 ELSE 0 END) AS has_attached_garage,
    MAX(CASE WHEN UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'DGAR%' THEN 1 ELSE 0 END) AS has_detached_garage,
    -- Main improvement condition
    MAX(i.condition_code) AS condition_code,
    a.acres AS lot_acres,
    a.bedrooms,
    a.bathrooms,
    a.year_built,
    a.eff_year_built,
    a.latitude,
    a.longitude,
    a.neighborhood_code,
    a.land_use_code,
    a.property_type
FROM sales s
JOIN assessor a
  ON s.parcel_number = a.parcel_number
 AND s.roll_id       = a.roll_id
LEFT JOIN improvements i
  ON a.parcel_number = i.parcel_number
 AND a.roll_id       = i.roll_id
 AND (
       -- Keep only main improvements and garage improvements
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'MA%' OR
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'MW%' OR
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'SW%' OR
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'PM%' OR
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'AGAR%' OR
       UPPER(TRIM(i.improvement_detail_type_code)) LIKE 'DGAR%'
     )
LEFT JOIN openskagit_assessmentroll r
  ON a.roll_id = r.id
WHERE
    s.sale_type = 'VALID SALE'
AND s.sale_price IS NOT NULL
AND s.sale_price > 10000
AND s.sale_date >= DATE '2015-01-01'
AND s.sale_date <  DATE '2035-01-01'
AND a.property_type = 'R'
AND a.land_use_code::int IN (110,111,112,113,120,130,140,180,181,182,190,910,911,912)
GROUP BY
    s.id, s.parcel_number, r.year, s.sale_price, s.sale_date,
    a.assessed_value, a.total_market_value,
    a.living_area, a.acres, a.bedrooms, a.bathrooms,
    a.year_built, a.eff_year_built, a.latitude, a.longitude,
    a.neighborhood_code, a.land_use_code, a.property_type;















from django.db import connection

with connection.cursor() as cur:
    cur.execute("""
        SELECT parcel_number, improvement_type, total_area
        FROM property_improvement_features
        WHERE parcel_number = 'P90623';
    """)
    print(cur.fetchall())




python3 manage.py update_assessor_2025 \
  --sqlite-path=/home/django/django_project/django_project/data/skagit_assessor.db \
  --year=2025



Access the Django admin site
    URL: http://159.65.103.78/admin
    User: django
    Pass: 0697515fa5b425f078c1efbfc851fedf

Use these SFTP credentials to upload files with FileZilla/WinSCP/rsync:
    Host: 159.65.103.78
    User: django
    Pass: 0697515fa5b425f078c1efbfc851fedf

Django is configured to use local Postgres as its database. Use the following credentials to manage the database:
    Database: django
    User:     django
    Pass:     6049e95312a01c391ff54518e25b7e9c

postgres=# \l
                              List of databases
   Name    |  Owner   | Encoding | Collate |  Ctype  |   Access privileges   
-----------+----------+----------+---------+---------+-----------------------
 django    | postgres | UTF8     | C.UTF-8 | C.UTF-8 | 
 postgres  | postgres | UTF8     | C.UTF-8 | C.UTF-8 | 
 template0 | postgres | UTF8     | C.UTF-8 | C.UTF-8 | =c/postgres          +
           |          |          |         |         | postgres=CTc/postgres
 template1 | postgres | UTF8     | C.UTF-8 | C.UTF-8 | =c/postgres          +
           |          |          |         |         | postgres=CTc/postgres
(4 rows)

postgres=# \d
Did not find any relations.
postgres=# \du
                                   List of roles
 Role name |                         Attributes                         | Member of 
-----------+------------------------------------------------------------+-----------
 django    |                                                            | {}
 postgres  | Superuser, Create role, Create DB, Replication, Bypass RLS | {}

postgres=# 






Skagit County Assessor SQLite Database Schema
parcels
Column	Type	Description
parcel_number	TEXT	Unique identifier for each property parcel
account_number	TEXT	Assessor account or tax account number
legal_description	TEXT	Legal description of the property
owner_name	TEXT	Name of the property owner
neighborhood_code	TEXT	Code representing the neighborhood area
building_value	INTEGER	Value of buildings on the parcel (improvement value)
land_use	TEXT	Code describing land use category
improved_land_value	INTEGER	Value of improved land (with structures)
unimproved_land_value	INTEGER	Value of unimproved land
timber_land_value	INTEGER	Value attributed to timberland
assessed_value	INTEGER	Total assessed value used for taxation
taxable_value	INTEGER	Value used to calculate property taxes after exemptions
total_market_value	INTEGER	Estimated market value of the property
acres	REAL	Size of the parcel in acres
sale_date	TEXT	Date of the most recent sale on record
sale_price	INTEGER	Price paid in the most recent sale
sale_deed_type	TEXT	Type of deed recorded for the sale
total_taxes	REAL	Total property taxes due
year_built	REAL	Original construction year of the primary improvement
living_area	INTEGER	Total living area in square feet
total_special_assessments	REAL	Total amount of special assessments
general_taxes	REAL	General property tax amount
inactive_date	TEXT	Date when the account became inactive
building_style	TEXT	Style of the main building (code)
foundation	TEXT	Type of foundation (code)
exterior_walls	TEXT	Material of exterior walls (code)
roof_covering	TEXT	Type of roof covering (code)
roof_style	TEXT	Style of roof (code)
floor_covering	TEXT	Type of floor covering (code)
floor_construction	TEXT	Type of floor construction (code)
interior_finish	TEXT	Type of interior finish (code)
plumbing	TEXT	Plumbing fixtures/quality (code)
garage_sqft	INTEGER	Garage area in square feet
heat_air_cond	TEXT	Type of heating and air conditioning (code)
fireplace	TEXT	Fireplace type/count (code)
finished_basement	INTEGER	Finished basement area in square feet
bedrooms	REAL	Number of bedrooms
effective_year_built	REAL	Effective year built (reflects remodels/upgrades)
unfinished_basement	INTEGER	Unfinished basement area in square feet
fire_district	TEXT	Fire district code
school_district	TEXT	School district code
city_district	TEXT	City district code
unit	TEXT	Unit or suite number (if applicable)
levy_code	TEXT	Tax levy code used to calculate taxes
current_use_adjustment	REAL	Current use assessment adjustment value
tide_land_value	INTEGER	Value of tideland rights
senior_exemption_adjustment	INTEGER	Adjustment for senior citizen exemptions
township	TEXT	Township identifier
range	TEXT	Range identifier
section	TEXT	Section identifier
quarter_section	TEXT	Quarter section identifier
tax_year	INTEGER	Tax year of the assessment
appraisal_year	INTEGER	Year the property was last appraised
utilities	TEXT	Utilities available to the property
tax_statement_taxable_value	INTEGER	Taxable value reported on the tax statement
property_type	TEXT	Property type code (e.g., Residential, Commercial)
has_septic	INTEGER	Indicator whether the property has a septic system (1=yes,0=no)
full_address	TEXT	Full physical address combining street number, name, and city/state/zip
land_segments
Column	Type	Description
parcel_number	TEXT	Parcel identifier to which this land segment belongs
property_value_year	TEXT	Year of valuation for the land segment
land_segment_id	TEXT	Identifier for the land segment (unique per parcel)
land_type	TEXT	Type of land (e.g., cleared, timber)
appraisal_method	TEXT	Method used to appraise the land segment
size_acres	REAL	Size of the land segment in acres
size_square_feet	REAL	Size of the land segment in square feet
effective_front	REAL	Effective front footage used for valuation
actual_front	REAL	Actual front footage of the land
land_adjustment_factor	REAL	Adjustment factor applied to land value
adjusted_value	REAL	Adjusted value of the land segment
market_unit_price	REAL	Market unit price per square foot/acre
market_value	REAL	Market value of the land segment
open_space_value	REAL	Value if classified as open space
open_space_use_description	TEXT	Description of the open space use code
ag_unit_price	REAL	Agricultural unit price
open_space_appraisal_method	TEXT	Method used to appraise open space land
land_segment_comment	TEXT	Additional comments or notes about the land segment
improvements
Column	Type	Description
parcel_number	TEXT	Parcel identifier to which this improvement belongs
improvement_id	TEXT	Unique identifier for the improvement record
description	TEXT	Brief description of the improvement (e.g., Single Family Residence)
building_style	TEXT	Building style code
comment	TEXT	Additional comments about the improvement
improvement_value	INTEGER	Value of the improvement
new_construction_year	REAL	Year of new construction (if any)
total_living_area	REAL	Total living area of the improvement in square feet
segment_id	TEXT	Segment identifier relating to this improvement
detail_type_code	TEXT	Detail type code
detail_class_code	TEXT	Detail class code
detail_method_code	TEXT	Detail method code
condition_code	TEXT	Condition code of the improvement
calculated_area	REAL	Calculated area used for valuation
unit_price	REAL	Unit price used to value the improvement
depreciation_pct	REAL	Depreciation percentage applied
detail_value	INTEGER	Calculated value from detail
construction_style	TEXT	Construction style code
foundation	TEXT	Foundation type code
exterior_wall	TEXT	Exterior wall material code
roof_covering	TEXT	Roof covering material code
roof_style	TEXT	Roof style code
flooring	TEXT	Flooring material code
floor_construction	TEXT	Floor construction type code
interior_finish	TEXT	Interior finish code
plumbing	TEXT	Plumbing code
appliances	TEXT	Appliance code
heating_cooling	TEXT	Heating/cooling system code
fireplace	TEXT	Fireplace code
rooms	REAL	Number of rooms
bedrooms	REAL	Number of bedrooms
effective_year_built	REAL	Effective year built accounting for remodels
actual_year_built	INTEGER	Actual year construction was completed
sketch_path	TEXT	URL path to the improvement sketch or photo
sales
Column	Type	Description
sale_id	TEXT	Unique identifier for the sale record
parcel_number	TEXT	Parcel identifier involved in the sale
account_number	TEXT	Account number associated with the sale
sale_price	INTEGER	Sale price in dollars
sale_date	TEXT	Date the sale occurred
sale_type	TEXT	Type of sale (e.g., valid sale)
deed_type	TEXT	Type of deed used in the sale
recording_number	TEXT	Recording number of the transaction
deed_date	TEXT	Date the deed was recorded
reval_area	TEXT	Revaluation area
excise_number	TEXT	Excise tax number for the transaction