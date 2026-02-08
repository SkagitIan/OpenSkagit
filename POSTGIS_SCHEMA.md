# Postgres / PostGIS Schema

Authoritative database schema exported directly from Postgres.
Use this file as the **single source of truth** for LLM-assisted coding.

## `census.acs_bg_skagit` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `name` | text (text) | YES |  |
| `median_income` | numeric (numeric) | YES |  |
| `edu_bachelor` | numeric (numeric) | YES |  |
| `edu_master` | numeric (numeric) | YES |  |
| `edu_professional` | numeric (numeric) | YES |  |
| `edu_doctorate` | numeric (numeric) | YES |  |
| `population` | numeric (numeric) | YES |  |
| `statefp` | text (text) | YES |  |
| `countyfp` | text (text) | YES |  |
| `tractce` | text (text) | YES |  |
| `blkgrpce` | text (text) | YES |  |
| `geoid` | text (text) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `name` | Block Group 1; Census Tract 9402.01; Skagit County; Washington |
| `median_income` | 96094 |
| `edu_bachelor` | 354 |
| `edu_master` | 201 |
| `edu_professional` | 40 |
| `edu_doctorate` | 18 |
| `population` | 1495 |
| `statefp` | 53 |
| `countyfp` | 057 |
| `tractce` | 940201 |
| `blkgrpce` | 1 |
| `geoid` | 530579402011 |

---

## `census.bg_skagit` (t)

**Geometry Columns:**
- `geom_2926` (MULTIPOLYGON, SRID 2926)
- `geom` (MULTIPOLYGON, SRID 2285)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | YES |  |
| `statefp` | character varying(2) (varchar) | YES |  |
| `countyfp` | character varying(3) (varchar) | YES |  |
| `tractce` | character varying(6) (varchar) | YES |  |
| `blkgrpce` | character varying(1) (varchar) | YES |  |
| `geoid` | character varying(12) (varchar) | YES |  |
| `geoidfq` | character varying(21) (varchar) | YES |  |
| `namelsad` | character varying(13) (varchar) | YES |  |
| `mtfcc` | character varying(5) (varchar) | YES |  |
| `funcstat` | character varying(1) (varchar) | YES |  |
| `aland` | numeric(14,0) (numeric) | YES |  |
| `awater` | numeric(14,0) (numeric) | YES |  |
| `intptlat` | character varying(11) (varchar) | YES |  |
| `intptlon` | character varying(12) (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2285) (geometry) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `idx_bg_skagit_geom`
  ```sql
  CREATE INDEX idx_bg_skagit_geom ON census.bg_skagit USING gist (geom)
  ```
- `bg_skagit_geom_2926_idx`
  ```sql
  CREATE INDEX bg_skagit_geom_2926_idx ON census.bg_skagit USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 661 |
| `statefp` | 53 |
| `countyfp` | 057 |
| `tractce` | 951300 |
| `blkgrpce` | 1 |
| `geoid` | 530579513001 |
| `geoidfq` | 1500000US530579513001 |
| `namelsad` | Block Group 1 |
| `mtfcc` | G5030 |
| `funcstat` | S |
| `aland` | 26346423 |
| `awater` | 2578009 |
| `intptlat` | +48.4777411 |
| `intptlon` | -122.2224055 |
| `geom` | 0106000020ED080000010000000103000000010000001F05000079EED1CFB59C3341547BA5E835872041EF9A6C4AC49C3341E1E8464E118A2041FE7DDFA1EF9C3341F9D2DB8F048E2041292FE9924... |
| `geom_2926` | 01060000206E0B0000010000000103000000010000001F05000015C33960B69C3341282EEB7435872041CD7313DBC49C33415DA760DA108A20411DC3DF32F09C334110A5BE1B048E20411D7322244... |

---

## `census.bg_wa_raw` (t)

**Primary Key:** ogc_fid

**Geometry Columns:**
- `geom_2926` (MULTIPOLYGON, SRID 2926)
- `geom` (MULTIPOLYGON, SRID 4269)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | NO | nextval('census.bg_wa_raw_ogc_fid_seq'::regclass) |
| `statefp` | character varying(2) (varchar) | YES |  |
| `countyfp` | character varying(3) (varchar) | YES |  |
| `tractce` | character varying(6) (varchar) | YES |  |
| `blkgrpce` | character varying(1) (varchar) | YES |  |
| `geoid` | character varying(12) (varchar) | YES |  |
| `geoidfq` | character varying(21) (varchar) | YES |  |
| `namelsad` | character varying(13) (varchar) | YES |  |
| `mtfcc` | character varying(5) (varchar) | YES |  |
| `funcstat` | character varying(1) (varchar) | YES |  |
| `aland` | numeric(14,0) (numeric) | YES |  |
| `awater` | numeric(14,0) (numeric) | YES |  |
| `intptlat` | character varying(11) (varchar) | YES |  |
| `intptlon` | character varying(12) (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,4269) (geometry) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `bg_wa_raw_geom_2926_idx`
  ```sql
  CREATE INDEX bg_wa_raw_geom_2926_idx ON census.bg_wa_raw USING gist (geom_2926)
  ```
- `bg_wa_raw_geom_geom_idx`
  ```sql
  CREATE INDEX bg_wa_raw_geom_geom_idx ON census.bg_wa_raw USING gist (geom)
  ```
- `bg_wa_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX bg_wa_raw_pkey ON census.bg_wa_raw USING btree (ogc_fid)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 1 |
| `statefp` | 53 |
| `countyfp` | 009 |
| `tractce` | 001400 |
| `blkgrpce` | 2 |
| `geoid` | 530090014002 |
| `geoidfq` | 1500000US530090014002 |
| `namelsad` | Block Group 2 |
| `mtfcc` | G5030 |
| `funcstat` | S |
| `aland` | 48448210 |
| `awater` | 29529 |
| `intptlat` | +48.0518803 |
| `intptlon` | -123.3209455 |
| `geom` | 0106000020AD100000010000000103000000010000007C0400005C72DC291DD75EC0D6C743DFDD0A484041F50F2219D75EC0DD09F65FE70A48407BA2EBC20FD75EC0588FFB56EB0A484081423D7D0... |
| `geom_2926` | 01060000206E0B0000010000000103000000010000007C0400005201DBA3B9352F41BED1DA3DF1C51841908382C638362F41C2DEDF4290C71841E8E3552253372F419509B65B2EC81841A5CFD1ACA... |

---

## `public.agency_levy_map` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `tdcode` | character varying(9) (varchar) | NO |  |
| `mcag` | character varying(10) (varchar) | NO |  |
| `agency_name` | character varying(255) (varchar) | NO |  |
| `agency_type` | character varying(100) (varchar) | NO |  |
| `notes` | text (text) | NO |  |
| `is_primary` | boolean (bool) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `agency_levy_map_pkey`
  ```sql
  CREATE UNIQUE INDEX agency_levy_map_pkey ON public.agency_levy_map USING btree (id)
  ```
- `uniq_agency_levy_map`
  ```sql
  CREATE UNIQUE INDEX uniq_agency_levy_map ON public.agency_levy_map USING btree (tdcode, mcag)
  ```
- `openskagit_agencylevymap_mcag_idx`
  ```sql
  CREATE INDEX openskagit_agencylevymap_mcag_idx ON public.agency_levy_map USING btree (mcag)
  ```
- `openskagit_agencylevymap_tdcode_idx`
  ```sql
  CREATE INDEX openskagit_agencylevymap_tdcode_idx ON public.agency_levy_map USING btree (tdcode)
  ```
- `agency_levy_map_tdcode_677c8f8d`
  ```sql
  CREATE INDEX agency_levy_map_tdcode_677c8f8d ON public.agency_levy_map USING btree (tdcode)
  ```
- `agency_levy_map_tdcode_677c8f8d_like`
  ```sql
  CREATE INDEX agency_levy_map_tdcode_677c8f8d_like ON public.agency_levy_map USING btree (tdcode varchar_pattern_ops)
  ```
- `agency_levy_map_mcag_3ed72c85_like`
  ```sql
  CREATE INDEX agency_levy_map_mcag_3ed72c85_like ON public.agency_levy_map USING btree (mcag varchar_pattern_ops)
  ```
- `agency_levy_map_mcag_3ed72c85`
  ```sql
  CREATE INDEX agency_levy_map_mcag_3ed72c85 ON public.agency_levy_map USING btree (mcag)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 84 |
| `tdcode` | 290000200 |
| `mcag` |  |
| `agency_name` | State School Part 2 |
| `agency_type` | countywide |
| `notes` | levy_name=State School Part 2; score=0.25 |
| `is_primary` | True |
| `created_at` | 2026-01-23 20:55:27.763542+00:00 |

---

## `public.agent_paymentrecord` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `stripe_session_id` | character varying(255) (varchar) | NO |  |
| `status` | character varying(16) (varchar) | NO |  |
| `amount_usd` | numeric(10,2) (numeric) | YES |  |
| `paid_at` | timestamp with time zone (timestamptz) | YES |  |
| `note` | text (text) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `job_id` | character varying(32) (varchar) | NO |  |

### Foreign Keys

- `job_id` → `public.agent_restaurantreportjob.id`

### Indexes

- `agent_paymentrecord_stripe_session_id_key`
  ```sql
  CREATE UNIQUE INDEX agent_paymentrecord_stripe_session_id_key ON public.agent_paymentrecord USING btree (stripe_session_id)
  ```
- `agent_paymentrecord_stripe_session_id_f454095f_like`
  ```sql
  CREATE INDEX agent_paymentrecord_stripe_session_id_f454095f_like ON public.agent_paymentrecord USING btree (stripe_session_id varchar_pattern_ops)
  ```
- `agent_paymentrecord_job_id_key`
  ```sql
  CREATE UNIQUE INDEX agent_paymentrecord_job_id_key ON public.agent_paymentrecord USING btree (job_id)
  ```
- `agent_paymentrecord_job_id_23f1ef72_like`
  ```sql
  CREATE INDEX agent_paymentrecord_job_id_23f1ef72_like ON public.agent_paymentrecord USING btree (job_id varchar_pattern_ops)
  ```
- `agent_paymentrecord_pkey`
  ```sql
  CREATE UNIQUE INDEX agent_paymentrecord_pkey ON public.agent_paymentrecord USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `stripe_session_id` | dev-64ebedd7de584941969d6439bb8cdcdc |
| `status` | PAID |
| `amount_usd` | 49.00 |
| `paid_at` | 2026-01-30 00:12:14.944382+00:00 |
| `note` |  |
| `created_at` | 2026-01-30 00:12:14.957282+00:00 |
| `updated_at` | 2026-01-30 00:12:14.957302+00:00 |
| `job_id` | 64ebedd7de584941969d6439bb8cdcdc |

---

## `public.agent_restaurantreport` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `slug` | character varying(64) (varchar) | NO |  |
| `payload` | text (text) | NO |  |
| `generated_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `job_id` | character varying(32) (varchar) | NO |  |

### Foreign Keys

- `job_id` → `public.agent_restaurantreportjob.id`

### Indexes

- `agent_restaurantreport_slug_key`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreport_slug_key ON public.agent_restaurantreport USING btree (slug)
  ```
- `agent_restaurantreport_slug_caa58600_like`
  ```sql
  CREATE INDEX agent_restaurantreport_slug_caa58600_like ON public.agent_restaurantreport USING btree (slug varchar_pattern_ops)
  ```
- `agent_restaurantreport_job_id_key`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreport_job_id_key ON public.agent_restaurantreport USING btree (job_id)
  ```
- `agent_restaurantreport_pkey`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreport_pkey ON public.agent_restaurantreport USING btree (id)
  ```
- `agent_restaurantreport_job_id_55fb34cf_like`
  ```sql
  CREATE INDEX agent_restaurantreport_job_id_55fb34cf_like ON public.agent_restaurantreport USING btree (job_id varchar_pattern_ops)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.agent_restaurantreportcheckpoint` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `step` | character varying(64) (varchar) | NO |  |
| `payload` | text (text) | NO |  |
| `schema_version` | character varying(16) (varchar) | NO |  |
| `checksum` | character varying(64) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `job_id` | character varying(32) (varchar) | NO |  |

### Foreign Keys

- `job_id` → `public.agent_restaurantreportjob.id`

### Indexes

- `agent_restaurantreportcheckpoint_pkey`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreportcheckpoint_pkey ON public.agent_restaurantreportcheckpoint USING btree (id)
  ```
- `agent_restaurantreportcheckpoint_job_id_99b52168_like`
  ```sql
  CREATE INDEX agent_restaurantreportcheckpoint_job_id_99b52168_like ON public.agent_restaurantreportcheckpoint USING btree (job_id varchar_pattern_ops)
  ```
- `agent_restaurantreportcheckpoint_job_id_99b52168`
  ```sql
  CREATE INDEX agent_restaurantreportcheckpoint_job_id_99b52168 ON public.agent_restaurantreportcheckpoint USING btree (job_id)
  ```
- `agent_restaurantreportcheckpoint_job_id_step_9ef64d0a_uniq`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreportcheckpoint_job_id_step_9ef64d0a_uniq ON public.agent_restaurantreportcheckpoint USING btree (job_id, step)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.agent_restaurantreportjob` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | character varying(32) (varchar) | NO |  |
| `place_id` | character varying(255) (varchar) | NO |  |
| `place_name` | character varying(255) (varchar) | NO |  |
| `address` | character varying(512) (varchar) | NO |  |
| `status` | character varying(16) (varchar) | NO |  |
| `progress_percent` | smallint (int2) | NO |  |
| `current_step` | character varying(64) (varchar) | NO |  |
| `error_code` | character varying(32) (varchar) | NO |  |
| `error_message` | text (text) | NO |  |
| `progress_log` | jsonb (jsonb) | NO |  |
| `subject_payload` | jsonb (jsonb) | YES |  |
| `vetted_competitors` | jsonb (jsonb) | YES |  |
| `final_payload` | jsonb (jsonb) | YES |  |
| `cost_usd` | numeric(10,2) (numeric) | YES |  |
| `started_at` | timestamp with time zone (timestamptz) | YES |  |
| `completed_at` | timestamp with time zone (timestamptz) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `agent_restaurantreportjob_id_f2d44073_like`
  ```sql
  CREATE INDEX agent_restaurantreportjob_id_f2d44073_like ON public.agent_restaurantreportjob USING btree (id varchar_pattern_ops)
  ```
- `agent_restaurantreportjob_pkey`
  ```sql
  CREATE UNIQUE INDEX agent_restaurantreportjob_pkey ON public.agent_restaurantreportjob USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | ef147901e4c54299963abcd146e4e255 |
| `place_id` | ChIJQVO1ySVshVQRePZHJVd2seM |
| `place_name` | Max Dale's Steak Chop House |
| `address` | 2030 Riverside Dr, Mount Vernon, WA 98273, USA |
| `status` | CREATED |
| `progress_percent` | 0 |
| `current_step` |  |
| `error_code` |  |
| `error_message` |  |
| `progress_log` | [] |
| `subject_payload` | NULL |
| `vetted_competitors` | NULL |
| `final_payload` | NULL |
| `cost_usd` | NULL |
| `started_at` | NULL |
| `completed_at` | NULL |
| `created_at` | 2026-01-30 00:07:28.309125+00:00 |
| `updated_at` | 2026-01-30 00:07:28.311891+00:00 |

---

## `public.assessor` (t)

**Geometry Columns:**
- `geom_backup` (GEOMETRY, SRID 3857)
- `geom_2926` (MULTIPOLYGON, SRID 2926)
- `geom_4326` (MULTIPOLYGON, SRID 4326)
- `geom` (MULTIPOLYGON, SRID 3857)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `address` | text (text) | YES |  |
| `neighborhood_code` | text (text) | YES |  |
| `land_use_code` | text (text) | YES |  |
| `building_value` | real (float4) | YES |  |
| `impr_land_value` | real (float4) | YES |  |
| `unimpr_land_value` | bigint (int8) | YES |  |
| `timber_land_value` | bigint (int8) | YES |  |
| `assessed_value` | bigint (int8) | YES |  |
| `taxable_value` | bigint (int8) | YES |  |
| `total_market_value` | bigint (int8) | YES |  |
| `acres` | real (float4) | YES |  |
| `sale_date` | timestamp without time zone (timestamp) | YES |  |
| `sale_price` | real (float4) | YES |  |
| `sale_deed_type` | text (text) | YES |  |
| `total_taxes` | text (text) | YES |  |
| `year_built` | bigint (int8) | YES |  |
| `eff_year_built` | bigint (int8) | YES |  |
| `living_area` | bigint (int8) | YES |  |
| `building_style` | text (text) | YES |  |
| `foundation` | text (text) | YES |  |
| `exterior_walls` | text (text) | YES |  |
| `roof_covering` | text (text) | YES |  |
| `roof_style` | text (text) | YES |  |
| `floor_covering` | text (text) | YES |  |
| `floor_construction` | text (text) | YES |  |
| `interior_finish` | text (text) | YES |  |
| `bathrooms` | real (float4) | YES |  |
| `bedrooms` | real (float4) | YES |  |
| `garage_sqft` | real (float4) | YES |  |
| `heat_air_cond` | text (text) | YES |  |
| `fireplace` | text (text) | YES |  |
| `finished_basement` | real (float4) | YES |  |
| `unfinished_basement` | bigint (int8) | YES |  |
| `fire_district` | text (text) | YES |  |
| `school_district` | text (text) | YES |  |
| `city_district` | text (text) | YES |  |
| `levy_code` | text (text) | YES |  |
| `current_use_adjustment` | real (float4) | YES |  |
| `tide_land_value` | bigint (int8) | YES |  |
| `senior_exemption_adjustment` | bigint (int8) | YES |  |
| `property_type` | text (text) | YES |  |
| `has_septic` | text (text) | YES |  |
| `latitude` | double precision (float8) | YES |  |
| `longitude` | double precision (float8) | YES |  |
| `embedding` | vector(384) (vector) | YES |  |
| `roll_id` | bigint (int8) | YES |  |
| `id` | bigint (int8) | NO |  |
| `land_use_description` | text (text) | YES |  |
| `neighborhood_code_description` | text (text) | YES |  |
| `in_flood_zone` | boolean (bool) | YES |  |
| `flood_distance` | double precision (float8) | YES |  |
| `flood_static_bfe` | double precision (float8) | YES |  |
| `flood_depth` | double precision (float8) | YES |  |
| `flood_velocity` | double precision (float8) | YES |  |
| `flood_sfha` | text (text) | YES |  |
| `flood_zone` | text (text) | YES |  |
| `flood_zone_subtype` | text (text) | YES |  |
| `flood_zone_id` | text (text) | YES |  |
| `elev` | double precision (float8) | YES |  |
| `slope` | double precision (float8) | YES |  |
| `dist_floodway` | double precision (float8) | YES |  |
| `aspect` | double precision (float8) | YES |  |
| `aspect_dir` | text (text) | YES |  |
| `dist_major_road` | double precision (float8) | YES |  |
| `geom_backup` | geometry(Geometry,3857) (geometry) | YES |  |
| `centroid_geog` | geography(Point,4326) (geography) | YES |  |
| `geom` | geometry(MultiPolygon,3857) (geometry) | YES |  |
| `geom_4326` | geometry(MultiPolygon,4326) (geometry) | YES | st_transform(geom, 4326) |
| `condition_code` | character varying(10) (varchar) | YES |  |
| `condition_score` | integer (int4) | YES |  |
| `quality_score` | double precision (float8) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | YES |  |
| `elevation` | double precision (float8) | YES |  |
| `dist_city_center` | double precision (float8) | YES |  |
| `dist_fire_station` | double precision (float8) | YES |  |
| `dist_hospital` | double precision (float8) | YES |  |
| `dist_minor_road` | double precision (float8) | YES |  |
| `dist_park` | double precision (float8) | YES |  |
| `dist_school` | double precision (float8) | YES |  |
| `dist_supermarket` | double precision (float8) | YES |  |
| `dist_trailhead` | double precision (float8) | YES |  |
| `age` | double precision (float8) | YES |  |
| `age_bucket` | character varying(20) (varchar) | YES |  |
| `age_sq` | double precision (float8) | YES |  |
| `full_bathrooms` | integer (int4) | YES |  |
| `half_bathrooms` | integer (int4) | YES |  |
| `has_adu` | boolean (bool) | YES |  |
| `has_deck` | boolean (bool) | YES |  |
| `has_finished_basement` | boolean (bool) | YES |  |
| `has_pool` | boolean (bool) | YES |  |
| `has_shop` | boolean (bool) | YES |  |
| `improvement_year_built` | bigint (int8) | YES |  |
| `land_use_category` | character varying(100) (varchar) | YES |  |
| `neighborhood_id` | character varying(50) (varchar) | YES |  |
| `number_of_fireplaces` | integer (int4) | YES |  |
| `number_of_outbuildings` | integer (int4) | YES |  |
| `number_of_sheds` | integer (int4) | YES |  |
| `number_of_shops` | integer (int4) | YES |  |
| `renovation_age` | double precision (float8) | YES |  |
| `total_additional_living_area` | double precision (float8) | YES |  |
| `total_basement_area` | double precision (float8) | YES |  |
| `total_deck_area` | double precision (float8) | YES |  |
| `total_garage_area` | double precision (float8) | YES |  |
| `total_improvement_value` | bigint (int8) | YES |  |
| `total_outbuilding_area` | double precision (float8) | YES |  |
| `total_porch_area` | double precision (float8) | YES |  |
| `calculated_square_footage` | double precision (float8) | YES |  |
| `owner_name` | text (text) | YES |  |
| `owner_add_1` | text (text) | YES |  |
| `owner_add_2` | text (text) | YES |  |
| `owner_add_3` | text (text) | YES |  |
| `owner_city` | text (text) | YES |  |
| `owner_state` | text (text) | YES |  |
| `owner_zip` | text (text) | YES |  |

### Foreign Keys

- `roll_id` → `public.openskagit_assessmentroll.id`

### Indexes

- `assessor_address_trgm_idx`
  ```sql
  CREATE INDEX assessor_address_trgm_idx ON public.assessor USING gin (address gin_trgm_ops)
  ```
- `assessor_property_type_idx`
  ```sql
  CREATE INDEX assessor_property_type_idx ON public.assessor USING btree (property_type)
  ```
- `idx_assessor_address_trgm`
  ```sql
  CREATE INDEX idx_assessor_address_trgm ON public.assessor USING gin (address gin_trgm_ops)
  ```
- `idx_assessor_parcel_upper`
  ```sql
  CREATE INDEX idx_assessor_parcel_upper ON public.assessor USING btree (upper(parcel_number))
  ```
- `assessor_centroid_geog_gix`
  ```sql
  CREATE INDEX assessor_centroid_geog_gix ON public.assessor USING gist (centroid_geog)
  ```
- `assessor_parcel_number_idx`
  ```sql
  CREATE INDEX assessor_parcel_number_idx ON public.assessor USING btree (parcel_number)
  ```
- `assessor_geom_4326_idx`
  ```sql
  CREATE INDEX assessor_geom_4326_idx ON public.assessor USING gist (geom_4326)
  ```
- `assessor_geom_2926_idx`
  ```sql
  CREATE INDEX assessor_geom_2926_idx ON public.assessor USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P109486 |
| `address` | NULL |
| `neighborhood_code` | (20EXMPTRES) ALL COUNTY EXEMPT RESIDENTIAL |
| `land_use_code` | NULL |
| `building_value` | 109200.0 |
| `impr_land_value` | 168800.0 |
| `unimpr_land_value` | 0 |
| `timber_land_value` | 0 |
| `assessed_value` | 278000 |
| `taxable_value` | 0 |
| `total_market_value` | 278000 |
| `acres` | 0.22 |
| `sale_date` | NULL |
| `sale_price` | 0.0 |
| `sale_deed_type` | NULL |
| `total_taxes` | 0.0 |
| `year_built` | 1998 |
| `eff_year_built` | 2003 |
| `living_area` | 960 |
| `building_style` | NULL |
| `foundation` | CONCRETE |
| `exterior_walls` | SIDING |
| `roof_covering` | COMP |
| `roof_style` | NULL |
| `floor_covering` | ALLOWANCE |
| `floor_construction` | WOOD SUB FLOOR |
| `interior_finish` | MODERATE CLIMATE INSULATION |
| `bathrooms` | NULL |
| `bedrooms` | NULL |
| `garage_sqft` | NULL |
| `heat_air_cond` | ELECTRIC WALL UNITS |
| `fireplace` | DIRECT VENT |
| `finished_basement` | NULL |
| `unfinished_basement` | NULL |
| `fire_district` | F08 |
| `school_district` | SD101 |
| `city_district` | Skagit County |
| `levy_code` | 1335.0 |
| `current_use_adjustment` | 0.0 |
| `tide_land_value` | 0 |
| `senior_exemption_adjustment` | 0 |
| `property_type` | NULL |
| `has_septic` | NULL |
| `latitude` | NULL |
| `longitude` | NULL |
| `embedding` | NULL |
| `roll_id` | 2 |
| `id` | 358541 |
| `land_use_description` | NULL |
| `neighborhood_code_description` | NULL |
| `in_flood_zone` | NULL |
| `flood_distance` | NULL |
| `flood_static_bfe` | NULL |
| `flood_depth` | NULL |
| `flood_velocity` | NULL |
| `flood_sfha` | NULL |
| `flood_zone` | NULL |
| `flood_zone_subtype` | NULL |
| `flood_zone_id` | NULL |
| `elev` | NULL |
| `slope` | NULL |
| `dist_floodway` | NULL |
| `aspect` | NULL |
| `aspect_dir` | NULL |
| `dist_major_road` | NULL |
| `geom_backup` | NULL |
| `centroid_geog` | NULL |
| `geom` | NULL |
| `geom_4326` | NULL |
| `condition_code` | NULL |
| `condition_score` | NULL |
| `quality_score` | NULL |
| `geom_2926` | NULL |
| `elevation` | NULL |
| `dist_city_center` | NULL |
| `dist_fire_station` | NULL |
| `dist_hospital` | NULL |
| `dist_minor_road` | NULL |
| `dist_park` | NULL |
| `dist_school` | NULL |
| `dist_supermarket` | NULL |
| `dist_trailhead` | NULL |
| `age` | NULL |
| `age_bucket` | NULL |
| `age_sq` | NULL |
| `full_bathrooms` | NULL |
| `half_bathrooms` | NULL |
| `has_adu` | NULL |
| `has_deck` | NULL |
| `has_finished_basement` | NULL |
| `has_pool` | NULL |
| `has_shop` | NULL |
| `improvement_year_built` | NULL |
| `land_use_category` | NULL |
| `neighborhood_id` | NULL |
| `number_of_fireplaces` | NULL |
| `number_of_outbuildings` | NULL |
| `number_of_sheds` | NULL |
| `number_of_shops` | NULL |
| `renovation_age` | NULL |
| `total_additional_living_area` | NULL |
| `total_basement_area` | NULL |
| `total_deck_area` | NULL |
| `total_garage_area` | NULL |
| `total_improvement_value` | NULL |
| `total_outbuilding_area` | NULL |
| `total_porch_area` | NULL |
| `calculated_square_footage` | NULL |
| `owner_name` | UNITED STATES OF AMERICA |
| `owner_add_1` | TR FOR UPPER SKAGIT INDIAN TRIBE |
| `owner_add_2` | 25944 COMMUNITY PLAZA WAY |
| `owner_add_3` | NULL |
| `owner_city` | SEDRO WOOLLEY |
| `owner_state` | WA |
| `owner_zip` | 98284.0 |

---

## `public.assessor_2025_geo` (v)

**Geometry Columns:**
- `geom_backup` (GEOMETRY, SRID 3857)
- `geom` (MULTIPOLYGON, SRID 3857)
- `geom_4326` (MULTIPOLYGON, SRID 4326)
- `geom_2926` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `address` | text (text) | YES |  |
| `neighborhood_code` | text (text) | YES |  |
| `land_use_code` | text (text) | YES |  |
| `building_value` | real (float4) | YES |  |
| `impr_land_value` | real (float4) | YES |  |
| `unimpr_land_value` | bigint (int8) | YES |  |
| `timber_land_value` | bigint (int8) | YES |  |
| `assessed_value` | bigint (int8) | YES |  |
| `taxable_value` | bigint (int8) | YES |  |
| `total_market_value` | bigint (int8) | YES |  |
| `acres` | real (float4) | YES |  |
| `sale_date` | timestamp without time zone (timestamp) | YES |  |
| `sale_price` | real (float4) | YES |  |
| `sale_deed_type` | text (text) | YES |  |
| `total_taxes` | text (text) | YES |  |
| `year_built` | bigint (int8) | YES |  |
| `eff_year_built` | bigint (int8) | YES |  |
| `living_area` | bigint (int8) | YES |  |
| `building_style` | text (text) | YES |  |
| `foundation` | text (text) | YES |  |
| `exterior_walls` | text (text) | YES |  |
| `roof_covering` | text (text) | YES |  |
| `roof_style` | text (text) | YES |  |
| `floor_covering` | text (text) | YES |  |
| `floor_construction` | text (text) | YES |  |
| `interior_finish` | text (text) | YES |  |
| `bathrooms` | real (float4) | YES |  |
| `bedrooms` | real (float4) | YES |  |
| `garage_sqft` | real (float4) | YES |  |
| `heat_air_cond` | text (text) | YES |  |
| `fireplace` | text (text) | YES |  |
| `finished_basement` | real (float4) | YES |  |
| `unfinished_basement` | bigint (int8) | YES |  |
| `fire_district` | text (text) | YES |  |
| `school_district` | text (text) | YES |  |
| `city_district` | text (text) | YES |  |
| `levy_code` | text (text) | YES |  |
| `current_use_adjustment` | real (float4) | YES |  |
| `tide_land_value` | bigint (int8) | YES |  |
| `senior_exemption_adjustment` | bigint (int8) | YES |  |
| `property_type` | text (text) | YES |  |
| `has_septic` | text (text) | YES |  |
| `latitude` | double precision (float8) | YES |  |
| `longitude` | double precision (float8) | YES |  |
| `embedding` | vector(384) (vector) | YES |  |
| `roll_id` | bigint (int8) | YES |  |
| `id` | bigint (int8) | YES |  |
| `land_use_description` | text (text) | YES |  |
| `neighborhood_code_description` | text (text) | YES |  |
| `in_flood_zone` | boolean (bool) | YES |  |
| `flood_distance` | double precision (float8) | YES |  |
| `flood_static_bfe` | double precision (float8) | YES |  |
| `flood_depth` | double precision (float8) | YES |  |
| `flood_velocity` | double precision (float8) | YES |  |
| `flood_sfha` | text (text) | YES |  |
| `flood_zone` | text (text) | YES |  |
| `flood_zone_subtype` | text (text) | YES |  |
| `flood_zone_id` | text (text) | YES |  |
| `elev` | double precision (float8) | YES |  |
| `slope` | double precision (float8) | YES |  |
| `dist_floodway` | double precision (float8) | YES |  |
| `aspect` | double precision (float8) | YES |  |
| `aspect_dir` | text (text) | YES |  |
| `dist_major_road` | double precision (float8) | YES |  |
| `geom_backup` | geometry(Geometry,3857) (geometry) | YES |  |
| `centroid_geog` | geography(Point,4326) (geography) | YES |  |
| `geom` | geometry(MultiPolygon,3857) (geometry) | YES |  |
| `geom_4326` | geometry(MultiPolygon,4326) (geometry) | YES |  |
| `condition_code` | character varying(10) (varchar) | YES |  |
| `condition_score` | integer (int4) | YES |  |
| `quality_score` | double precision (float8) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P109486 |
| `address` | NULL |
| `neighborhood_code` | (20EXMPTRES) ALL COUNTY EXEMPT RESIDENTIAL |
| `land_use_code` | NULL |
| `building_value` | 109200.0 |
| `impr_land_value` | 168800.0 |
| `unimpr_land_value` | 0 |
| `timber_land_value` | 0 |
| `assessed_value` | 278000 |
| `taxable_value` | 0 |
| `total_market_value` | 278000 |
| `acres` | 0.22 |
| `sale_date` | NULL |
| `sale_price` | 0.0 |
| `sale_deed_type` | NULL |
| `total_taxes` | 0.0 |
| `year_built` | 1998 |
| `eff_year_built` | 2003 |
| `living_area` | 960 |
| `building_style` | NULL |
| `foundation` | CONCRETE |
| `exterior_walls` | SIDING |
| `roof_covering` | COMP |
| `roof_style` | NULL |
| `floor_covering` | ALLOWANCE |
| `floor_construction` | WOOD SUB FLOOR |
| `interior_finish` | MODERATE CLIMATE INSULATION |
| `bathrooms` | NULL |
| `bedrooms` | NULL |
| `garage_sqft` | NULL |
| `heat_air_cond` | ELECTRIC WALL UNITS |
| `fireplace` | DIRECT VENT |
| `finished_basement` | NULL |
| `unfinished_basement` | NULL |
| `fire_district` | F08 |
| `school_district` | SD101 |
| `city_district` | Skagit County |
| `levy_code` | 1335.0 |
| `current_use_adjustment` | 0.0 |
| `tide_land_value` | 0 |
| `senior_exemption_adjustment` | 0 |
| `property_type` | NULL |
| `has_septic` | NULL |
| `latitude` | NULL |
| `longitude` | NULL |
| `embedding` | NULL |
| `roll_id` | 2 |
| `id` | 358541 |
| `land_use_description` | NULL |
| `neighborhood_code_description` | NULL |
| `in_flood_zone` | NULL |
| `flood_distance` | NULL |
| `flood_static_bfe` | NULL |
| `flood_depth` | NULL |
| `flood_velocity` | NULL |
| `flood_sfha` | NULL |
| `flood_zone` | NULL |
| `flood_zone_subtype` | NULL |
| `flood_zone_id` | NULL |
| `elev` | NULL |
| `slope` | NULL |
| `dist_floodway` | NULL |
| `aspect` | NULL |
| `aspect_dir` | NULL |
| `dist_major_road` | NULL |
| `geom_backup` | NULL |
| `centroid_geog` | NULL |
| `geom` | NULL |
| `geom_4326` | NULL |
| `condition_code` | NULL |
| `condition_score` | NULL |
| `quality_score` | NULL |
| `geom_2926` | NULL |

---

## `public.assessor_distances` (t)

**Primary Key:** parcel_number

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | NO |  |
| `dist_major_road` | double precision (float8) | YES |  |
| `dist_minor_road` | double precision (float8) | YES |  |
| `dist_floodway` | double precision (float8) | YES |  |
| `dist_city_center` | double precision (float8) | YES |  |
| `dist_school` | double precision (float8) | YES |  |
| `dist_park` | double precision (float8) | YES |  |
| `dist_supermarket` | double precision (float8) | YES |  |
| `dist_hospital` | double precision (float8) | YES |  |
| `dist_fire_station` | double precision (float8) | YES |  |

### Indexes

- `assessor_distances_pkey`
  ```sql
  CREATE UNIQUE INDEX assessor_distances_pkey ON public.assessor_distances USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100003 |
| `dist_major_road` | NULL |
| `dist_minor_road` | NULL |
| `dist_floodway` | NULL |
| `dist_city_center` | NULL |
| `dist_school` | NULL |
| `dist_park` | NULL |
| `dist_supermarket` | NULL |
| `dist_hospital` | NULL |
| `dist_fire_station` | NULL |

---

## `public.assessor_geom4326_nonnull` (v)

**Geometry Columns:**
- `geom_4326` (MULTIPOLYGON, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | YES |  |
| `parcel_number` | text (text) | YES |  |
| `geom_4326` | geometry(MultiPolygon,4326) (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 68268 |
| `parcel_number` | P70317 |
| `geom_4326` | 0106000020E61000000100000001030000000100000021000000C98AD6023A655EC0BA3C02F4C53848403CBAD6023A655EC09CBDFFF3C5384840BF46D7023A655EC00D57FDF3C5384840EE2AD8023... |

---

## `public.assessor_geom_update_log` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `batch_start` | integer (int4) | YES |  |
| `batch_end` | integer (int4) | YES |  |
| `updated_count` | integer (int4) | YES |  |
| `run_at` | timestamp with time zone (timestamptz) | YES | now() |

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.assessor_geom_utm10` (v)

**Geometry Columns:**
- `geom_utm10` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | YES |  |
| `parcel_number` | text (text) | YES |  |
| `geom_utm10` | geometry (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 68268 |
| `parcel_number` | P70317 |
| `geom_utm10` | 01060000201E69000001000000010300000001000000210000002E86D503B4752241E89F9EDDCA785441302AD403B4752241F1809CDDCA7854410083CF03B4752241D9749ADDCA78544154BEC703B... |

---

## `public.assessor_owner_stage` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `aid` | text (text) | YES |  |
| `parcel_number` | text (text) | YES |  |
| `account_number` | text (text) | YES |  |
| `legal_description` | text (text) | YES |  |
| `situs_street_number` | text (text) | YES |  |
| `situs_street_name` | text (text) | YES |  |
| `situs_city_state_zip` | text (text) | YES |  |
| `old_street_number` | text (text) | YES |  |
| `old_street_name` | text (text) | YES |  |
| `old_city_state_zip` | text (text) | YES |  |
| `owner_name` | text (text) | YES |  |
| `owner_add_1` | text (text) | YES |  |
| `owner_add_2` | text (text) | YES |  |
| `owner_add_3` | text (text) | YES |  |
| `owner_city` | text (text) | YES |  |
| `owner_state` | text (text) | YES |  |
| `owner_zip` | text (text) | YES |  |
| `exemptions` | text (text) | YES |  |
| `neighborhood_code` | text (text) | YES |  |
| `building_value` | text (text) | YES |  |
| `land_use` | text (text) | YES |  |
| `impr_land_value` | text (text) | YES |  |
| `unimpr_land_value` | text (text) | YES |  |
| `timber_land_value` | text (text) | YES |  |
| `assessed_value` | text (text) | YES |  |
| `taxable_value` | text (text) | YES |  |
| `total_market_value` | text (text) | YES |  |
| `acres` | text (text) | YES |  |
| `sale_date` | text (text) | YES |  |
| `sale_price` | text (text) | YES |  |
| `sale_deed_type` | text (text) | YES |  |
| `total_taxes` | text (text) | YES |  |
| `year_built` | text (text) | YES |  |
| `living_area` | text (text) | YES |  |
| `tot_special_assessments` | text (text) | YES |  |
| `general_taxes` | text (text) | YES |  |
| `inactive_date` | text (text) | YES |  |
| `buildingstyle` | text (text) | YES |  |
| `foundation` | text (text) | YES |  |
| `exterior_walls` | text (text) | YES |  |
| `roof_covering` | text (text) | YES |  |
| `roof_style` | text (text) | YES |  |
| `floor_covering` | text (text) | YES |  |
| `floor_construction` | text (text) | YES |  |
| `interior_finish` | text (text) | YES |  |
| `plumbing` | text (text) | YES |  |
| `garagesqft` | text (text) | YES |  |
| `heat_air_cond` | text (text) | YES |  |
| `fireplace` | text (text) | YES |  |
| `finishedbasement` | text (text) | YES |  |
| `number_of_bedrooms` | text (text) | YES |  |
| `eff_year_built` | text (text) | YES |  |
| `unfinishedbasement` | text (text) | YES |  |
| `fire_district` | text (text) | YES |  |
| `school_district` | text (text) | YES |  |
| `city_district` | text (text) | YES |  |
| `unit` | text (text) | YES |  |
| `levy_code` | text (text) | YES |  |
| `current_use_adjustment` | text (text) | YES |  |
| `tide_land_value` | text (text) | YES |  |
| `senior_exemption_adjustment` | text (text) | YES |  |
| `township` | text (text) | YES |  |
| `range` | text (text) | YES |  |
| `section` | text (text) | YES |  |
| `quarter_section` | text (text) | YES |  |
| `tax_year` | text (text) | YES |  |
| `appraisal_year` | text (text) | YES |  |
| `utilities` | text (text) | YES |  |
| `tax_statement_taxable_value` | text (text) | YES |  |
| `proptype` | text (text) | YES |  |
| `hasseptic` | text (text) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `aid` | 21773 |
| `parcel_number` | P100003 |
| `account_number` | 70798 |
| `legal_description` | EQUIPMENT AND SUPPLIES  LC 0900 |
| `situs_street_number` | 702 |
| `situs_street_name` | R AVENUE |
| `situs_city_state_zip` | ANACORTES, WA 98221 |
| `old_street_number` | NULL |
| `old_street_name` | NULL |
| `old_city_state_zip` | NULL |
| `owner_name` | TRANSPAC MARINAS INC |
| `owner_add_1` | C/O RYTAND DAVID H |
| `owner_add_2` | PO BOX 1169 |
| `owner_add_3` | NULL |
| `owner_city` | ANACORTES |
| `owner_state` | WA |
| `owner_zip` | 98221 |
| `exemptions` | NULL |
| `neighborhood_code` | NULL |
| `building_value` | 0 |
| `land_use` | (0) Personal Property |
| `impr_land_value` | 0 |
| `unimpr_land_value` | 0 |
| `timber_land_value` | 0 |
| `assessed_value` | 698900 |
| `taxable_value` | 698900 |
| `total_market_value` | 698900 |
| `acres` | 0 |
| `sale_date` | NULL |
| `sale_price` | 0 |
| `sale_deed_type` | NULL |
| `total_taxes` | 5947.11 |
| `year_built` | NULL |
| `living_area` | 0 |
| `tot_special_assessments` | NULL |
| `general_taxes` | NULL |
| `inactive_date` | NULL |
| `buildingstyle` | COMMERICAL PERSONAL PROPERTY |
| `foundation` | NULL |
| `exterior_walls` | NULL |
| `roof_covering` | NULL |
| `roof_style` | NULL |
| `floor_covering` | NULL |
| `floor_construction` | NULL |
| `interior_finish` | NULL |
| `plumbing` | NULL |
| `garagesqft` | 0 |
| `heat_air_cond` | NULL |
| `fireplace` | NULL |
| `finishedbasement` | 0 |
| `number_of_bedrooms` | NULL |
| `eff_year_built` | 0 |
| `unfinishedbasement` | 0 |
| `fire_district` | NULL |
| `school_district` | SD103 |
| `city_district` | Anacortes |
| `unit` | NULL |
| `levy_code` | 0900 |
| `current_use_adjustment` | NULL |
| `tide_land_value` | 0 |
| `senior_exemption_adjustment` | 0 |
| `township` | NULL |
| `range` | NULL |
| `section` | NULL |
| `quarter_section` | NULL |
| `tax_year` | 2025 |
| `appraisal_year` | 2026 |
| `utilities` | NULL |
| `tax_statement_taxable_value` | 698900 |
| `proptype` | P |
| `hasseptic` | False |

---

## `public.auth_group` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `name` | character varying(150) (varchar) | NO |  |

### Indexes

- `auth_group_name_a6ea08ec_like`
  ```sql
  CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops)
  ```
- `auth_group_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_group_pkey ON public.auth_group USING btree (id)
  ```
- `auth_group_name_key`
  ```sql
  CREATE UNIQUE INDEX auth_group_name_key ON public.auth_group USING btree (name)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.auth_group_permissions` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `group_id` | integer (int4) | NO |  |
| `permission_id` | integer (int4) | NO |  |

### Foreign Keys

- `group_id` → `public.auth_group.id`
- `permission_id` → `public.auth_permission.id`

### Indexes

- `auth_group_permissions_group_id_b120cbf9`
  ```sql
  CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id)
  ```
- `auth_group_permissions_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_group_permissions_pkey ON public.auth_group_permissions USING btree (id)
  ```
- `auth_group_permissions_group_id_permission_id_0cd325b0_uniq`
  ```sql
  CREATE UNIQUE INDEX auth_group_permissions_group_id_permission_id_0cd325b0_uniq ON public.auth_group_permissions USING btree (group_id, permission_id)
  ```
- `auth_group_permissions_permission_id_84c5c92e`
  ```sql
  CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.auth_permission` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `content_type_id` | integer (int4) | NO |  |
| `codename` | character varying(100) (varchar) | NO |  |

### Foreign Keys

- `content_type_id` → `public.django_content_type.id`

### Indexes

- `auth_permission_content_type_id_2f476e4b`
  ```sql
  CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id)
  ```
- `auth_permission_content_type_id_codename_01ab375a_uniq`
  ```sql
  CREATE UNIQUE INDEX auth_permission_content_type_id_codename_01ab375a_uniq ON public.auth_permission USING btree (content_type_id, codename)
  ```
- `auth_permission_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_permission_pkey ON public.auth_permission USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `name` | Can add log entry |
| `content_type_id` | 1 |
| `codename` | add_logentry |

---

## `public.auth_user` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `password` | character varying(128) (varchar) | NO |  |
| `last_login` | timestamp with time zone (timestamptz) | YES |  |
| `is_superuser` | boolean (bool) | NO |  |
| `username` | character varying(150) (varchar) | NO |  |
| `first_name` | character varying(150) (varchar) | NO |  |
| `last_name` | character varying(150) (varchar) | NO |  |
| `email` | character varying(254) (varchar) | NO |  |
| `is_staff` | boolean (bool) | NO |  |
| `is_active` | boolean (bool) | NO |  |
| `date_joined` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `auth_user_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_user_pkey ON public.auth_user USING btree (id)
  ```
- `auth_user_username_key`
  ```sql
  CREATE UNIQUE INDEX auth_user_username_key ON public.auth_user USING btree (username)
  ```
- `auth_user_username_6821ab7c_like`
  ```sql
  CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `password` | pbkdf2_sha256$720000$qksUgW2lZhtV1rYwwdTf9C$IIrVUTshHXcHoG/dORvOCT7uOazaagXxzou4hJkAQ6A= |
| `last_login` | NULL |
| `is_superuser` | True |
| `username` | ianl |
| `first_name` |  |
| `last_name` |  |
| `email` |  |
| `is_staff` | True |
| `is_active` | True |
| `date_joined` | 2025-10-10 17:37:19.118399+00:00 |

---

## `public.auth_user_groups` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `user_id` | integer (int4) | NO |  |
| `group_id` | integer (int4) | NO |  |

### Foreign Keys

- `user_id` → `public.auth_user.id`
- `group_id` → `public.auth_group.id`

### Indexes

- `auth_user_groups_user_id_group_id_94350c0c_uniq`
  ```sql
  CREATE UNIQUE INDEX auth_user_groups_user_id_group_id_94350c0c_uniq ON public.auth_user_groups USING btree (user_id, group_id)
  ```
- `auth_user_groups_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_user_groups_pkey ON public.auth_user_groups USING btree (id)
  ```
- `auth_user_groups_group_id_97559544`
  ```sql
  CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id)
  ```
- `auth_user_groups_user_id_6a12ed8b`
  ```sql
  CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.auth_user_user_permissions` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `user_id` | integer (int4) | NO |  |
| `permission_id` | integer (int4) | NO |  |

### Foreign Keys

- `user_id` → `public.auth_user.id`
- `permission_id` → `public.auth_permission.id`

### Indexes

- `auth_user_user_permissions_user_id_a95ead1b`
  ```sql
  CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id)
  ```
- `auth_user_user_permissions_user_id_permission_id_14a6b632_uniq`
  ```sql
  CREATE UNIQUE INDEX auth_user_user_permissions_user_id_permission_id_14a6b632_uniq ON public.auth_user_user_permissions USING btree (user_id, permission_id)
  ```
- `auth_user_user_permissions_pkey`
  ```sql
  CREATE UNIQUE INDEX auth_user_user_permissions_pkey ON public.auth_user_user_permissions USING btree (id)
  ```
- `auth_user_user_permissions_permission_id_1fbb5f2c`
  ```sql
  CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.ballot_to_parcel` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ballot_id` | character varying(50) (varchar) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `neighborhood_code` | character varying (varchar) | YES |  |
| `is_ambiguous` | boolean (bool) | YES |  |
| `match_source` | text (text) | YES |  |

### Indexes

- `ballot_to_parcel_ballot_idx`
  ```sql
  CREATE UNIQUE INDEX ballot_to_parcel_ballot_idx ON public.ballot_to_parcel USING btree (ballot_id, election_year)
  ```
- `ballot_to_parcel_election_neighborhood_idx`
  ```sql
  CREATE INDEX ballot_to_parcel_election_neighborhood_idx ON public.ballot_to_parcel USING btree (election_year, neighborhood_code)
  ```
- `ballot_to_parcel_ballot_only_idx`
  ```sql
  CREATE INDEX ballot_to_parcel_ballot_only_idx ON public.ballot_to_parcel USING btree (ballot_id)
  ```
- `ballot_to_parcel_parcel_idx`
  ```sql
  CREATE INDEX ballot_to_parcel_parcel_idx ON public.ballot_to_parcel USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ballot_id` | 1-143851926 |
| `election_year` | 2024 |
| `parcel_number` | P59632 |
| `neighborhood_code` | 22ASKY |
| `is_ambiguous` | False |
| `match_source` | situs |

---

## `public.civic_balance_map` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `tax_year` | integer (int4) | YES |  |
| `total_tax_paid` | numeric (numeric) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `tax_per_ballot` | numeric (numeric) | YES |  |
| `tax_burden_quartile` | integer (int4) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Indexes

- `idx_cbm_geom`
  ```sql
  CREATE INDEX idx_cbm_geom ON public.civic_balance_map USING gist (geom_2926)
  ```
- `idx_cbm_year`
  ```sql
  CREATE INDEX idx_cbm_year ON public.civic_balance_map USING btree (tax_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `tax_year` | 2024 |
| `total_tax_paid` | 3172122.51 |
| `ballots_cast` | 280 |
| `tax_per_ballot` | 11329.008964285714 |
| `tax_burden_quartile` | 2 |
| `geom_2926` | 01060000206E0B000017000000010300000001000000E0000000F18AB8F4D6A033410FAA8ACED5FD1EC133DA560A0AA133419FF5E60A01FE1EC1814ACD964AA133410CFBB910FBFD1EC10C8705438... |

---

## `public.code_set_activation_rule` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `code_set` | character varying(100) (varchar) | NO |  |
| `parcel_intent` | character varying(100) (varchar) | YES |  |
| `zoning_use_class` | character varying(50) (varchar) | YES |  |
| `requires_overlay` | character varying(50) (varchar) | YES |  |

### Indexes

- `code_set_activation_rule_pkey`
  ```sql
  CREATE UNIQUE INDEX code_set_activation_rule_pkey ON public.code_set_activation_rule USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `code_set` | energy_code_residential |
| `parcel_intent` | new_residential_dwelling |
| `zoning_use_class` | residential_low |
| `requires_overlay` | NULL |

---

## `public.comparable_cache` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `parcel_number` | character varying(20) (varchar) | NO |  |
| `roll_year` | integer (int4) | NO |  |
| `radius_meters` | integer (int4) | NO |  |
| `limit` | integer (int4) | NO |  |
| `comparables` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `last_refreshed` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `comparable_cache_pkey`
  ```sql
  CREATE UNIQUE INDEX comparable_cache_pkey ON public.comparable_cache USING btree (id)
  ```
- `comparable_cache_parcel_number_dc3fdb64_like`
  ```sql
  CREATE INDEX comparable_cache_parcel_number_dc3fdb64_like ON public.comparable_cache USING btree (parcel_number varchar_pattern_ops)
  ```
- `comparable_cache_roll_year_8b7a3f12`
  ```sql
  CREATE INDEX comparable_cache_roll_year_8b7a3f12 ON public.comparable_cache USING btree (roll_year)
  ```
- `comparable_cache_parcel_number_roll_year__3f1a1a63_uniq`
  ```sql
  CREATE UNIQUE INDEX comparable_cache_parcel_number_roll_year__3f1a1a63_uniq ON public.comparable_cache USING btree (parcel_number, roll_year, radius_meters, "limit")
  ```
- `comparable_cache_parcel_number_dc3fdb64`
  ```sql
  CREATE INDEX comparable_cache_parcel_number_dc3fdb64 ON public.comparable_cache USING btree (parcel_number)
  ```
- `comparable__parcel__84e718_idx`
  ```sql
  CREATE INDEX comparable__parcel__84e718_idx ON public.comparable_cache USING btree (parcel_number, roll_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 6 |
| `parcel_number` | P77795 |
| `roll_year` | 2025 |
| `radius_meters` | 3218 |
| `limit` | 7 |
| `comparables` | [{"score": {"time_score": "0.9", "total_score": "0.891315108716260480", "location_score": "1.0", "physical_score": "0.7377170290542016"}, "snapshot": {"acres... |
| `created_at` | 2025-12-04 21:10:07.847690+00:00 |
| `last_refreshed` | 2025-12-04 21:38:50.954933+00:00 |

---

## `public.conversation_messages` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `role` | character varying(20) (varchar) | NO |  |
| `content` | text (text) | NO |  |
| `sources` | jsonb (jsonb) | NO |  |
| `model` | character varying(100) (varchar) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `conversation_id` | uuid (uuid) | NO |  |

### Foreign Keys

- `conversation_id` → `public.conversations.id`

### Indexes

- `conversation_messages_pkey`
  ```sql
  CREATE UNIQUE INDEX conversation_messages_pkey ON public.conversation_messages USING btree (id)
  ```
- `conversation_messages_conversation_id_52b02ddd`
  ```sql
  CREATE INDEX conversation_messages_conversation_id_52b02ddd ON public.conversation_messages USING btree (conversation_id)
  ```
- `conversatio_convers_01af31_idx`
  ```sql
  CREATE INDEX conversatio_convers_01af31_idx ON public.conversation_messages USING btree (conversation_id, created_at)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `role` | user |
| `content` | Tsest |
| `sources` | [] |
| `model` | NULL |
| `created_at` | 2025-11-21 16:49:50.918362+00:00 |
| `conversation_id` | ee8d65e4-4606-46d7-bbd2-c9ce27e65487 |

---

## `public.conversations` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | uuid (uuid) | NO |  |
| `session_key` | character varying(255) (varchar) | YES |  |
| `title` | character varying(255) (varchar) | NO |  |
| `context_data` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `conversatio_updated_c163ba_idx`
  ```sql
  CREATE INDEX conversatio_updated_c163ba_idx ON public.conversations USING btree (updated_at DESC)
  ```
- `conversatio_session_69f832_idx`
  ```sql
  CREATE INDEX conversatio_session_69f832_idx ON public.conversations USING btree (session_key, updated_at DESC)
  ```
- `conversations_session_key_4a43491d_like`
  ```sql
  CREATE INDEX conversations_session_key_4a43491d_like ON public.conversations USING btree (session_key varchar_pattern_ops)
  ```
- `conversations_pkey`
  ```sql
  CREATE UNIQUE INDEX conversations_pkey ON public.conversations USING btree (id)
  ```
- `conversations_session_key_4a43491d`
  ```sql
  CREATE INDEX conversations_session_key_4a43491d ON public.conversations USING btree (session_key)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | bc2aa39e-7333-4753-9760-0d7b105f157b |
| `session_key` | 783j5nlmxpm6iet0ujgf08evkq0b4apm |
| `title` | New conversation |
| `context_data` | {} |
| `created_at` | 2025-11-21 15:25:55.361777+00:00 |
| `updated_at` | 2025-11-21 15:25:55.361803+00:00 |

---

## `public.core_analytics_pageview` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `url` | character varying(2048) (varchar) | NO |  |
| `timestamp` | timestamp with time zone (timestamptz) | NO |  |
| `ip_address` | inet (inet) | YES |  |
| `user_agent` | character varying(512) (varchar) | NO |  |
| `user_id` | integer (int4) | YES |  |
| `browser` | character varying(30) (varchar) | NO |  |
| `device_type` | character varying(20) (varchar) | NO |  |
| `is_new_session` | boolean (bool) | NO |  |
| `processing_time` | double precision (float8) | YES |  |
| `referrer` | character varying(2048) (varchar) | YES |  |
| `session_key` | character varying(40) (varchar) | NO |  |
| `db_queries` | integer (int4) | YES |  |
| `status_code` | integer (int4) | YES |  |
| `is_error` | boolean (bool) | NO |  |
| `previous_url` | character varying(2048) (varchar) | YES |  |

### Foreign Keys

- `user_id` → `public.auth_user.id`

### Indexes

- `core_analytics_pageview_timestamp_ee86fd47`
  ```sql
  CREATE INDEX core_analytics_pageview_timestamp_ee86fd47 ON public.core_analytics_pageview USING btree ("timestamp")
  ```
- `core_analytics_pageview_user_id_7d7a817e`
  ```sql
  CREATE INDEX core_analytics_pageview_user_id_7d7a817e ON public.core_analytics_pageview USING btree (user_id)
  ```
- `pageview_ts_url_idx`
  ```sql
  CREATE INDEX pageview_ts_url_idx ON public.core_analytics_pageview USING btree ("timestamp", url)
  ```
- `core_analytics_pageview_url_531e608d_like`
  ```sql
  CREATE INDEX core_analytics_pageview_url_531e608d_like ON public.core_analytics_pageview USING btree (url varchar_pattern_ops)
  ```
- `core_analytics_pageview_session_key_9b77df36`
  ```sql
  CREATE INDEX core_analytics_pageview_session_key_9b77df36 ON public.core_analytics_pageview USING btree (session_key)
  ```
- `core_analytics_pageview_pkey`
  ```sql
  CREATE UNIQUE INDEX core_analytics_pageview_pkey ON public.core_analytics_pageview USING btree (id)
  ```
- `core_analytics_pageview_url_531e608d`
  ```sql
  CREATE INDEX core_analytics_pageview_url_531e608d ON public.core_analytics_pageview USING btree (url)
  ```
- `core_analytics_pageview_session_key_9b77df36_like`
  ```sql
  CREATE INDEX core_analytics_pageview_session_key_9b77df36_like ON public.core_analytics_pageview USING btree (session_key varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `url` | / |
| `timestamp` | 2026-01-03 19:32:14.947393+00:00 |
| `ip_address` | 204.76.203.219 |
| `user_agent` | Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36 Edg/90.0.818.46 |
| `user_id` | NULL |
| `browser` |  |
| `device_type` |  |
| `is_new_session` | False |
| `processing_time` | NULL |
| `referrer` | NULL |
| `session_key` |  |
| `db_queries` | NULL |
| `status_code` | NULL |
| `is_error` | False |
| `previous_url` | NULL |

---

## `public.derived_parcel_centroid` (t)

**Primary Key:** parcel_id

**Geometry Columns:**
- `centroid_2926` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `centroid_2926` | geometry(Point,2926) (geometry) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `derived_parcel_centroid_parcel_id_b52121f6_like`
  ```sql
  CREATE INDEX derived_parcel_centroid_parcel_id_b52121f6_like ON public.derived_parcel_centroid USING btree (parcel_id varchar_pattern_ops)
  ```
- `derived_par_centroi_3213ac_gist`
  ```sql
  CREATE INDEX derived_par_centroi_3213ac_gist ON public.derived_parcel_centroid USING gist (centroid_2926)
  ```
- `derived_parcel_centroid_centroid_2926_250fc013_id`
  ```sql
  CREATE INDEX derived_parcel_centroid_centroid_2926_250fc013_id ON public.derived_parcel_centroid USING gist (centroid_2926)
  ```
- `derived_parcel_centroid_pkey`
  ```sql
  CREATE UNIQUE INDEX derived_parcel_centroid_pkey ON public.derived_parcel_centroid USING btree (parcel_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.derived_parcel_distances` (t)

**Primary Key:** parcel_id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | text (text) | NO |  |
| `dist_major_road` | double precision (float8) | YES |  |
| `dist_minor_road` | double precision (float8) | YES |  |
| `dist_floodway` | double precision (float8) | YES |  |
| `dist_city_center` | double precision (float8) | YES |  |
| `dist_school` | double precision (float8) | YES |  |
| `dist_park` | double precision (float8) | YES |  |
| `dist_supermarket` | double precision (float8) | YES |  |
| `dist_hospital` | double precision (float8) | YES |  |
| `dist_fire_station` | double precision (float8) | YES |  |
| `updated_at` | timestamp without time zone (timestamp) | YES | now() |

### Indexes

- `derived_parcel_distances_pkey`
  ```sql
  CREATE UNIQUE INDEX derived_parcel_distances_pkey ON public.derived_parcel_distances USING btree (parcel_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P100005 |
| `dist_major_road` | NULL |
| `dist_minor_road` | NULL |
| `dist_floodway` | 3776.818051590738 |
| `dist_city_center` | NULL |
| `dist_school` | NULL |
| `dist_park` | NULL |
| `dist_supermarket` | NULL |
| `dist_hospital` | NULL |
| `dist_fire_station` | NULL |
| `updated_at` | 2026-01-19 20:41:36.388663 |

---

## `public.district_tdcode` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `district_type` | text (text) | YES |  |
| `district_code` | text (text) | YES |  |
| `tdcode` | text (text) | NO |  |
| `assessment_year` | integer (int4) | NO |  |

### Indexes

- `district_tdcode_district_type_district_code_idx`
  ```sql
  CREATE INDEX district_tdcode_district_type_district_code_idx ON public.district_tdcode USING btree (district_type, district_code)
  ```
- `district_tdcode_tdcode_idx`
  ```sql
  CREATE INDEX district_tdcode_tdcode_idx ON public.district_tdcode USING btree (tdcode)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `district_type` | countywide |
| `district_code` | 290000000 |
| `tdcode` | 290000000 |
| `assessment_year` | 2024 |

---

## `public.django_admin_log` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `action_time` | timestamp with time zone (timestamptz) | NO |  |
| `object_id` | text (text) | YES |  |
| `object_repr` | character varying(200) (varchar) | NO |  |
| `action_flag` | smallint (int2) | NO |  |
| `change_message` | text (text) | NO |  |
| `content_type_id` | integer (int4) | YES |  |
| `user_id` | integer (int4) | NO |  |

### Foreign Keys

- `content_type_id` → `public.django_content_type.id`
- `user_id` → `public.auth_user.id`

### Indexes

- `django_admin_log_user_id_c564eba6`
  ```sql
  CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id)
  ```
- `django_admin_log_pkey`
  ```sql
  CREATE UNIQUE INDEX django_admin_log_pkey ON public.django_admin_log USING btree (id)
  ```
- `django_admin_log_content_type_id_c4bce8eb`
  ```sql
  CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `action_time` | 2025-11-01 23:27:42.235718+00:00 |
| `object_id` | 1 |
| `object_repr` | 2024 |
| `action_flag` | 1 |
| `change_message` | [{"added": {}}] |
| `content_type_id` | 25 |
| `user_id` | 3 |

---

## `public.django_content_type` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `app_label` | character varying(100) (varchar) | NO |  |
| `model` | character varying(100) (varchar) | NO |  |

### Indexes

- `django_content_type_app_label_model_76bd3d3b_uniq`
  ```sql
  CREATE UNIQUE INDEX django_content_type_app_label_model_76bd3d3b_uniq ON public.django_content_type USING btree (app_label, model)
  ```
- `django_content_type_pkey`
  ```sql
  CREATE UNIQUE INDEX django_content_type_pkey ON public.django_content_type USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `app_label` | admin |
| `model` | logentry |

---

## `public.django_migrations` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `app` | character varying(255) (varchar) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `applied` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `django_migrations_pkey`
  ```sql
  CREATE UNIQUE INDEX django_migrations_pkey ON public.django_migrations USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `app` | contenttypes |
| `name` | 0001_initial |
| `applied` | 2025-10-10 17:33:12.849875+00:00 |

---

## `public.django_session` (t)

**Primary Key:** session_key

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `session_key` | character varying(40) (varchar) | NO |  |
| `session_data` | text (text) | NO |  |
| `expire_date` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `django_session_pkey`
  ```sql
  CREATE UNIQUE INDEX django_session_pkey ON public.django_session USING btree (session_key)
  ```
- `django_session_session_key_c0390e0f_like`
  ```sql
  CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops)
  ```
- `django_session_expire_date_a5c62663`
  ```sql
  CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `session_key` | nmgqan33l08f6v02hzk1q4hlk54k37zy |
| `session_data` | .eJyFjksOwiAURbdi3pgYPi1gF-EGjGke8GxItG0A66Bh71ZHOtHxuTn3rJBw6P00LpQyljiNGboVLCnfWuVC8LbRHJ0mTwcpLzwIF4x9bUosV4IOjvTYfQqAgU-EhUJfNpkwWmjNpVR7bU3bWAb3OfzCN8oZ... |
| `expire_date` | 2025-11-11 14:03:43.726488+00:00 |

---

## `public.fact_neighborhood_participation` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `residential_parcels` | bigint (int8) | YES |  |
| `npi` | double precision (float8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |
| `primary_precinct_code` | bigint (int8) | YES |  |
| `precinct_ballots_cast` | bigint (int8) | YES |  |
| `precinct_residential_parcels` | bigint (int8) | YES |  |
| `precinct_ppi` | double precision (float8) | YES |  |
| `precinct_po_box_pct` | double precision (float8) | YES |  |
| `precinct_po_box_ballots` | bigint (int8) | YES |  |
| `assignment_coverage_precinct` | double precision (float8) | YES |  |
| `ambiguous_ballots` | bigint (int8) | YES |  |

### Indexes

- `fact_neighborhood_participation_geom_idx`
  ```sql
  CREATE INDEX fact_neighborhood_participation_geom_idx ON public.fact_neighborhood_participation USING gist (geom_2926)
  ```
- `fact_neighborhood_participation_year_idx`
  ```sql
  CREATE INDEX fact_neighborhood_participation_year_idx ON public.fact_neighborhood_participation USING btree (election_year)
  ```
- `fact_neighborhood_participation_code_year_idx`
  ```sql
  CREATE UNIQUE INDEX fact_neighborhood_participation_code_year_idx ON public.fact_neighborhood_participation USING btree (neighborhood_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 10CCREC |
| `election_year` | 2024 |
| `ballots_cast` | 2 |
| `residential_parcels` | 150 |
| `npi` | 0.013333333333333334 |
| `geom_2926` | 01060000206E0B00004200000001030000000100000005000000EEBB9C7C35183741B8F28A3AFFE820412A06058E1D1837416EAE040F1FEA204152D8B0EA5018374192D131C138EA2041A6466BD47... |
| `primary_precinct_code` | 107 |
| `precinct_ballots_cast` | 1876 |
| `precinct_residential_parcels` | 1162 |
| `precinct_ppi` | 1.6144578313253013 |
| `precinct_po_box_pct` | 0.17697228144989338 |
| `precinct_po_box_ballots` | 332 |
| `assignment_coverage_precinct` | 0.0010660980810234541 |
| `ambiguous_ballots` | NULL |

---

## `public.fact_precinct_civic_balance` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `tax_year` | integer (int4) | YES |  |
| `total_tax_paid` | numeric (numeric) | YES |  |
| `parcel_count` | bigint (int8) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `tax_per_ballot` | numeric (numeric) | YES |  |
| `tax_per_parcel` | numeric (numeric) | YES |  |
| `ballots_per_parcel` | bigint (int8) | YES |  |

### Indexes

- `idx_fpcb_prec_year`
  ```sql
  CREATE INDEX idx_fpcb_prec_year ON public.fact_precinct_civic_balance USING btree (prec_code, tax_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `tax_year` | 2024 |
| `total_tax_paid` | 3172122.51 |
| `parcel_count` | 1514 |
| `ballots_cast` | 250 |
| `tax_per_ballot` | 12688.490040000000 |
| `tax_per_parcel` | 2095.1932034346103038 |
| `ballots_per_parcel` | 0 |

---

## `public.fact_precinct_tax_burden` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `tax_year` | integer (int4) | YES |  |
| `parcel_count` | bigint (int8) | YES |  |
| `total_tax_paid` | numeric (numeric) | YES |  |
| `avg_tax_paid` | numeric (numeric) | YES |  |
| `median_tax_paid` | double precision (float8) | YES |  |

### Indexes

- `idx_fact_tax_prec_year`
  ```sql
  CREATE INDEX idx_fact_tax_prec_year ON public.fact_precinct_tax_burden USING btree (prec_code, tax_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 21 |
| `tax_year` | 2000 |
| `parcel_count` | 19 |
| `total_tax_paid` | 0.00 |
| `avg_tax_paid` | 0E-20 |
| `median_tax_paid` | 0.0 |

---

## `public.fact_precinct_turnout` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `election_id` | bigint (int8) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |

### Indexes

- `idx_fact_turnout_prec_year`
  ```sql
  CREATE INDEX idx_fact_turnout_prec_year ON public.fact_precinct_turnout USING btree (prec_code, election_year)
  ```
- `idx_fact_turnout_election`
  ```sql
  CREATE INDEX idx_fact_turnout_election ON public.fact_precinct_turnout USING btree (election_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `election_id` | 1 |
| `election_year` | 2024 |
| `ballots_cast` | 250 |

---

## `public.gastronet_crawllog` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `task` | character varying(100) (varchar) | NO |  |
| `scope` | character varying(200) (varchar) | YES |  |
| `started_at` | timestamp with time zone (timestamptz) | NO |  |
| `ended_at` | timestamp with time zone (timestamptz) | YES |  |
| `success_count` | integer (int4) | NO |  |
| `skip_count` | integer (int4) | NO |  |
| `error_count` | integer (int4) | NO |  |
| `api_calls` | integer (int4) | NO |  |
| `est_cost_usd` | double precision (float8) | NO |  |
| `notes` | text (text) | YES |  |
| `response_details` | jsonb (jsonb) | NO |  |

### Indexes

- `gastronet_crawllog_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_crawllog_pkey ON public.gastronet_crawllog USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `task` | seed_places |
| `scope` | restaurants in Seattle, WA |
| `started_at` | 2025-11-09 18:03:00.316084+00:00 |
| `ended_at` | 2025-11-09 18:03:01.414785+00:00 |
| `success_count` | 1 |
| `skip_count` | 0 |
| `error_count` | 0 |
| `api_calls` | 1 |
| `est_cost_usd` | 0.0 |
| `notes` | NULL |
| `response_details` | [] |

---

## `public.gastronet_menuattempt` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `tried_url` | character varying(200) (varchar) | YES |  |
| `source` | character varying(50) (varchar) | YES |  |
| `found` | boolean (bool) | NO |  |
| `parsed` | boolean (bool) | NO |  |
| `status` | character varying(200) (varchar) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `finished_at` | timestamp with time zone (timestamptz) | YES |  |
| `restaurant_id` | bigint (int8) | NO |  |

### Foreign Keys

- `restaurant_id` → `public.gastronet_restaurant.id`

### Indexes

- `gastronet_m_restaur_7a66a6_idx`
  ```sql
  CREATE INDEX gastronet_m_restaur_7a66a6_idx ON public.gastronet_menuattempt USING btree (restaurant_id, created_at)
  ```
- `gastronet_menuattempt_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_menuattempt_pkey ON public.gastronet_menuattempt USING btree (id)
  ```
- `gastronet_menuattempt_restaurant_id_221260a8`
  ```sql
  CREATE INDEX gastronet_menuattempt_restaurant_id_221260a8 ON public.gastronet_menuattempt USING btree (restaurant_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `tried_url` | https://www.granaio.com/menus |
| `source` | discovery |
| `found` | True |
| `parsed` | True |
| `status` | success |
| `created_at` | 2025-12-30 13:59:29.505884+00:00 |
| `finished_at` | 2025-12-30 13:59:52.494473+00:00 |
| `restaurant_id` | 2 |

---

## `public.gastronet_menuitem` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `source_url` | character varying(500) (varchar) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `description` | text (text) | NO |  |
| `price` | numeric(8,2) (numeric) | YES |  |
| `section` | character varying(255) (varchar) | NO |  |
| `dietary_tags` | jsonb (jsonb) | NO |  |
| `currency` | character varying(8) (varchar) | NO |  |
| `scraped_at` | timestamp with time zone (timestamptz) | NO |  |
| `restaurant_id` | bigint (int8) | NO |  |
| `enrichment_v1` | jsonb (jsonb) | YES |  |

### Foreign Keys

- `restaurant_id` → `public.gastronet_restaurant.id`

### Indexes

- `gastronet_menuitem_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_menuitem_pkey ON public.gastronet_menuitem USING btree (id)
  ```
- `gastronet_menuitem_restaurant_id_source_url_name_bb938c2c_uniq`
  ```sql
  CREATE UNIQUE INDEX gastronet_menuitem_restaurant_id_source_url_name_bb938c2c_uniq ON public.gastronet_menuitem USING btree (restaurant_id, source_url, name)
  ```
- `gastronet_menuitem_restaurant_id_fc457c0e`
  ```sql
  CREATE INDEX gastronet_menuitem_restaurant_id_fc457c0e ON public.gastronet_menuitem USING btree (restaurant_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 6859 |
| `source_url` | https://order.toasttab.com/online/the-skagit-table |
| `name` | Chicken Bone Broth |
| `description` | Chicken bones and feet simmered for 48 hours. |
| `price` | 12.00 |
| `section` |  |
| `dietary_tags` | [] |
| `currency` | USD |
| `scraped_at` | 2025-12-26 15:35:15.518518+00:00 |
| `restaurant_id` | 116 |
| `enrichment_v1` | {"cuisine": "unknown", "techniques": ["simmered"], "local_signals": [], "flavor_profile": {"sour": 0.0, "fatty": 0.8, "salty": 0.7, "smoky": 0.0, "spicy": 0.... |

---

## `public.gastronet_menusnapshot` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `fetched_at` | timestamp with time zone (timestamptz) | NO |  |
| `source_url` | character varying(200) (varchar) | NO |  |
| `text` | text (text) | NO |  |
| `hash` | character varying(64) (varchar) | NO |  |
| `parsed_json` | jsonb (jsonb) | YES |  |
| `summary` | text (text) | YES |  |
| `render_method` | character varying(50) (varchar) | YES |  |
| `restaurant_id` | bigint (int8) | NO |  |

### Foreign Keys

- `restaurant_id` → `public.gastronet_restaurant.id`

### Indexes

- `gastronet_m_restaur_ca5a20_idx`
  ```sql
  CREATE INDEX gastronet_m_restaur_ca5a20_idx ON public.gastronet_menusnapshot USING btree (restaurant_id, fetched_at)
  ```
- `gastronet_menusnapshot_restaurant_id_9bf77db9`
  ```sql
  CREATE INDEX gastronet_menusnapshot_restaurant_id_9bf77db9 ON public.gastronet_menusnapshot USING btree (restaurant_id)
  ```
- `gastronet_menusnapshot_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_menusnapshot_pkey ON public.gastronet_menusnapshot USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `fetched_at` | 2025-12-30 13:59:52.483857+00:00 |
| `source_url` | https://www.granaio.com/menus |
| `text` | <div><div>OUR MENUPlanning a party? View ourParty Planning MenuKIDS MENU 12 &amp; UNDERAll kids menu items include a beverage of choice.MENUFRESH HOMEMADE PA... |
| `hash` | 246572d61c45f451398ccdfd20fea84d3e8d0a872bde7bde98f0bdfb0bded412 |
| `parsed_json` | [{"name": "FRESH HOMEMADE PASTA", "error": false, "section": "KIDS MENU 12 & UNDER", "price_text": "$11.00", "description": "Choose tomato sauce, cream sauce... |
| `summary` | NULL |
| `render_method` | llm |
| `restaurant_id` | 2 |

---

## `public.gastronet_restaurant` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `place_id` | character varying(400) (varchar) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `address` | text (text) | YES |  |
| `city` | character varying(100) (varchar) | YES |  |
| `website` | character varying(2000) (varchar) | YES |  |
| `phone` | character varying(50) (varchar) | YES |  |
| `menu_url` | character varying(2000) (varchar) | YES |  |
| `url_checked_at` | timestamp with time zone (timestamptz) | YES |  |
| `url_source` | character varying(100) (varchar) | YES |  |
| `description` | text (text) | YES |  |
| `category` | character varying(500) (varchar) | YES |  |
| `cuisine` | character varying(100) (varchar) | YES |  |
| `rating` | double precision (float8) | YES |  |
| `review_count` | integer (int4) | NO |  |
| `sentiment_score` | double precision (float8) | YES |  |
| `latitude` | double precision (float8) | YES |  |
| `longitude` | double precision (float8) | YES |  |
| `location` | geography(Point,4326) (geography) | YES |  |
| `embedding` | vector(1536) (vector) | YES |  |
| `summary` | text (text) | YES |  |
| `keywords` | jsonb (jsonb) | YES |  |
| `source` | character varying(50) (varchar) | NO |  |
| `last_review_date` | timestamp with time zone (timestamptz) | YES |  |
| `avg_review_gap_days` | double precision (float8) | YES |  |
| `next_fetch_at` | timestamp with time zone (timestamptz) | YES |  |
| `active` | boolean (bool) | NO |  |
| `last_updated` | timestamp with time zone (timestamptz) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `first_seen` | timestamp with time zone (timestamptz) | NO |  |
| `last_seen` | timestamp with time zone (timestamptz) | NO |  |
| `hours` | jsonb (jsonb) | YES |  |
| `about` | jsonb (jsonb) | YES |  |
| `price_range` | character varying(20) (varchar) | YES |  |
| `logo_url` | character varying(2000) (varchar) | YES |  |
| `photo_url` | character varying(2000) (varchar) | YES |  |
| `street_view` | character varying(2000) (varchar) | YES |  |
| `location_link` | character varying(2000) (varchar) | YES |  |
| `booking_appointment_link` | character varying(2000) (varchar) | YES |  |
| `owner_link` | character varying(2000) (varchar) | YES |  |
| `reviews_url` | character varying(2000) (varchar) | YES |  |
| `reservation_links` | jsonb (jsonb) | YES |  |
| `order_links` | jsonb (jsonb) | YES |  |
| `last_crawled_at` | timestamp with time zone (timestamptz) | YES |  |
| `no_menu` | boolean (bool) | NO |  |
| `is_chain` | boolean (bool) | NO |  |
| `google_accessibility_options` | jsonb (jsonb) | YES |  |
| `google_allows_dogs` | boolean (bool) | YES |  |
| `google_business_status` | character varying(100) (varchar) | YES |  |
| `google_curbside_pickup` | boolean (bool) | YES |  |
| `google_delivery` | boolean (bool) | YES |  |
| `google_dine_in` | boolean (bool) | YES |  |
| `google_editorial_summary` | jsonb (jsonb) | YES |  |
| `google_ev_charge_amenity_summary` | jsonb (jsonb) | YES |  |
| `google_ev_charge_options` | jsonb (jsonb) | YES |  |
| `google_formatted_address` | text (text) | YES |  |
| `google_fuel_options` | jsonb (jsonb) | YES |  |
| `google_generative_summary` | jsonb (jsonb) | YES |  |
| `google_good_for_children` | boolean (bool) | YES |  |
| `google_good_for_groups` | boolean (bool) | YES |  |
| `google_good_for_watching_sports` | boolean (bool) | YES |  |
| `google_live_music` | boolean (bool) | YES |  |
| `google_menu_for_children` | boolean (bool) | YES |  |
| `google_neighborhood_summary` | jsonb (jsonb) | YES |  |
| `google_outdoor_seating` | boolean (bool) | YES |  |
| `google_parking_options` | jsonb (jsonb) | YES |  |
| `google_payment_options` | jsonb (jsonb) | YES |  |
| `google_primary_type` | character varying(200) (varchar) | YES |  |
| `google_raw_place` | jsonb (jsonb) | YES |  |
| `google_reservable` | boolean (bool) | YES |  |
| `google_restroom` | boolean (bool) | YES |  |
| `google_review_summary` | jsonb (jsonb) | YES |  |
| `google_routing_summaries` | jsonb (jsonb) | YES |  |
| `google_serves_beer` | boolean (bool) | YES |  |
| `google_serves_breakfast` | boolean (bool) | YES |  |
| `google_serves_brunch` | boolean (bool) | YES |  |
| `google_serves_cocktails` | boolean (bool) | YES |  |
| `google_serves_coffee` | boolean (bool) | YES |  |
| `google_serves_dessert` | boolean (bool) | YES |  |
| `google_serves_dinner` | boolean (bool) | YES |  |
| `google_serves_lunch` | boolean (bool) | YES |  |
| `google_serves_vegetarian_food` | boolean (bool) | YES |  |
| `google_serves_wine` | boolean (bool) | YES |  |
| `google_takeout` | boolean (bool) | YES |  |
| `google_types` | character varying(100)[] (_varchar) | NO |  |
| `google_viewport` | jsonb (jsonb) | YES |  |
| `profiles` | jsonb (jsonb) | YES |  |
| `menu_profile_v1` | jsonb (jsonb) | YES |  |
| `community_acceptance_v1` | jsonb (jsonb) | YES |  |

### Indexes

- `gastronet_r_city_ee9961_idx`
  ```sql
  CREATE INDEX gastronet_r_city_ee9961_idx ON public.gastronet_restaurant USING btree (city, category)
  ```
- `gastronet_restaurant_location_dc46f15c_id`
  ```sql
  CREATE INDEX gastronet_restaurant_location_dc46f15c_id ON public.gastronet_restaurant USING gist (location)
  ```
- `gastronet_restaurant_place_id_6a30946a_like`
  ```sql
  CREATE INDEX gastronet_restaurant_place_id_6a30946a_like ON public.gastronet_restaurant USING btree (place_id varchar_pattern_ops)
  ```
- `gastronet_r_next_fe_eb2f1f_idx`
  ```sql
  CREATE INDEX gastronet_r_next_fe_eb2f1f_idx ON public.gastronet_restaurant USING btree (next_fetch_at)
  ```
- `gastronet_restaurant_place_id_key`
  ```sql
  CREATE UNIQUE INDEX gastronet_restaurant_place_id_key ON public.gastronet_restaurant USING btree (place_id)
  ```
- `gastronet_restaurant_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_restaurant_pkey ON public.gastronet_restaurant USING btree (id)
  ```
- `gastronet_restaurant_name_eb4e9f10_like`
  ```sql
  CREATE INDEX gastronet_restaurant_name_eb4e9f10_like ON public.gastronet_restaurant USING btree (name varchar_pattern_ops)
  ```
- `gastronet_restaurant_is_chain_33d2771b`
  ```sql
  CREATE INDEX gastronet_restaurant_is_chain_33d2771b ON public.gastronet_restaurant USING btree (is_chain)
  ```
- `gastronet_r_city_8e1d35_idx`
  ```sql
  CREATE INDEX gastronet_r_city_8e1d35_idx ON public.gastronet_restaurant USING btree (city, active)
  ```
- `gastronet_restaurant_name_eb4e9f10`
  ```sql
  CREATE INDEX gastronet_restaurant_name_eb4e9f10 ON public.gastronet_restaurant USING btree (name)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 22 |
| `place_id` | ChIJE63i1-B5hVQRRVM0Bx3gQWA |
| `name` | A'Town Bistro |
| `address` | 418 Commercial Ave, Anacortes, WA 98221 |
| `city` | Anacortes |
| `website` | http://www.atownbistro.com/ |
| `phone` | +1 360-899-4001 |
| `menu_url` | https://www.atownbistro.com/menus/ |
| `url_checked_at` | 2025-12-23 01:29:03.226286+00:00 |
| `url_source` | llm |
| `description` | A’Town Bistro is a locally minded bistro in historic downtown Anacortes serving seasonal, from-scratch dishes and craft cocktails. The kitchen highlights pro... |
| `category` | Restaurant |
| `cuisine` | New American, Pacific Northwest |
| `rating` | 4.8 |
| `review_count` | 540 |
| `sentiment_score` | NULL |
| `latitude` | 48.5185106 |
| `longitude` | -122.6127994 |
| `location` | 0101000020E61000008A80F91A38A75EC08ED02A8E5E424840 |
| `embedding` | NULL |
| `summary` | Locally sourced, seasonal bistro with craft cocktails in downtown Anacortes. |
| `keywords` | ["local-ingredients", "seasonal-menu", "craft-cocktails", "lunch", "dinner", "social-hour", "phone-reservations", "downtown-anacortes", "bistro"] |
| `source` | outscraper |
| `last_review_date` | 2025-11-12 05:49:42+00:00 |
| `avg_review_gap_days` | 11.07673859126984 |
| `next_fetch_at` | 2026-01-01 12:26:54.270872+00:00 |
| `active` | True |
| `last_updated` | 2025-12-29 23:27:49.410891+00:00 |
| `created_at` | 2025-11-11 00:03:29.142386+00:00 |
| `first_seen` | 2025-11-11 00:03:29.142391+00:00 |
| `last_seen` | 2025-12-23 01:29:03.226517+00:00 |
| `hours` | {"raw": "Monday: Closed\nTuesday: Lunch 11:30am–3:00pm; Social Hour 3:00pm–5:00pm; Dinner 5:00pm–8:30pm\nWednesday: Lunch 11:30am–3:00pm; Social Hour 3:00pm–... |
| `about` | {"Crowd": {"Groups": true, "Locals": true, "Tourists": true, "Family-friendly": true}, "Parking": {"Parking": true, "Free parking lot": true, "Free street pa... |
| `price_range` | $$$ |
| `logo_url` | https://www.atownbistro.com/wp-content/themes/22ATB001-wordpress-v1.1/images/branded-stack-black%400.5x.png |
| `photo_url` | https://lh3.googleusercontent.com/gps-cs-s/AG0ilSy7WgVOvD3UsdKTWCl6gY785LDdzRtscz8bvaoBHg9y8dQAZSHjwVAAsdXyiB62XwexIHYNF6tz8p8FVQCW4gBO0PQkD5eqVj1OSqF3FdvCyq... |
| `street_view` | NULL |
| `location_link` | https://goo.gl/maps/7aphP9J4vgk |
| `booking_appointment_link` | NULL |
| `owner_link` | https://www.google.com/maps/contrib/101088857039061209038 |
| `reviews_url` | https://search.google.com/local/reviews?placeid=ChIJE63i1-B5hVQRRVM0Bx3gQWA&q=restaurant,+98221,+Anacortes,+WA,+US&authuser=0&hl=en&gl=US |
| `reservation_links` | NULL |
| `order_links` | NULL |
| `last_crawled_at` | NULL |
| `no_menu` | False |
| `is_chain` | False |
| `google_accessibility_options` | {"wheelchairAccessibleParking": true, "wheelchairAccessibleSeating": true, "wheelchairAccessibleEntrance": true, "wheelchairAccessibleRestroom": true} |
| `google_allows_dogs` | False |
| `google_business_status` | OPERATIONAL |
| `google_curbside_pickup` | NULL |
| `google_delivery` | False |
| `google_dine_in` | True |
| `google_editorial_summary` | {"text": "Cozy spot for farm-to-table New American cuisine with an open kitchen & craft beers on tap.", "languageCode": "en"} |
| `google_ev_charge_amenity_summary` | NULL |
| `google_ev_charge_options` | NULL |
| `google_formatted_address` | 418 Commercial Ave, Anacortes, WA 98221, USA |
| `google_fuel_options` | NULL |
| `google_generative_summary` | {"overview": {"text": "Comfort, seafood-inclusive eatery featuring chowder, burgers, steaks and French onion soup.", "languageCode": "en-US"}, "disclosureTex... |
| `google_good_for_children` | True |
| `google_good_for_groups` | True |
| `google_good_for_watching_sports` | False |
| `google_live_music` | False |
| `google_menu_for_children` | True |
| `google_neighborhood_summary` | NULL |
| `google_outdoor_seating` | True |
| `google_parking_options` | {"freeParkingLot": true, "freeStreetParking": true} |
| `google_payment_options` | {"acceptsNfc": true, "acceptsCashOnly": false, "acceptsDebitCards": true, "acceptsCreditCards": true} |
| `google_primary_type` | restaurant |
| `google_raw_place` | {"id": "ChIJE63i1-B5hVQRRVM0Bx3gQWA", "name": "places/ChIJE63i1-B5hVQRRVM0Bx3gQWA", "types": ["american_restaurant", "italian_restaurant", "french_restaurant... |
| `google_reservable` | True |
| `google_restroom` | True |
| `google_review_summary` | {"text": {"text": "People say this bistro serves delicious clam chowder, paella, and duck à l'orange. They highlight the fresh, well-prepared, and beautifull... |
| `google_routing_summaries` | NULL |
| `google_serves_beer` | True |
| `google_serves_breakfast` | NULL |
| `google_serves_brunch` | NULL |
| `google_serves_cocktails` | True |
| `google_serves_coffee` | True |
| `google_serves_dessert` | True |
| `google_serves_dinner` | True |
| `google_serves_lunch` | True |
| `google_serves_vegetarian_food` | True |
| `google_serves_wine` | True |
| `google_takeout` | True |
| `google_types` | ['american_restaurant', 'italian_restaurant', 'french_restaurant', 'restaurant', 'food', 'point_of_interest', 'establishment'] |
| `google_viewport` | {"low": {"latitude": 48.5171779697085, "longitude": -122.61400658029149}, "high": {"latitude": 48.5198759302915, "longitude": -122.6113086197085}} |
| `profiles` | NULL |
| `menu_profile_v1` | {"item_count": 75, "avg_familiarity": 0.742, "flavor_centroid": {"sour": 0.25, "fatty": 0.583, "salty": 0.527, "smoky": 0.162, "spicy": 0.225, "sweet": 0.364... |
| `community_acceptance_v1` | {"summary": {"neutral_mentions": 20, "negative_mentions": 1, "positive_mentions": 25}, "item_acceptance": {"cocktails": 0.65, "scotch egg": 0.65, "salmon cak... |

---

## `public.gastronet_restaurantcrawllog` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `task` | character varying(100) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `restaurant_id` | bigint (int8) | NO |  |

### Foreign Keys

- `restaurant_id` → `public.gastronet_restaurant.id`

### Indexes

- `gastronet_restaurantcrawllog_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_restaurantcrawllog_pkey ON public.gastronet_restaurantcrawllog USING btree (id)
  ```
- `gastronet_restaurantcrawllog_restaurant_id_c3e2ec5a`
  ```sql
  CREATE INDEX gastronet_restaurantcrawllog_restaurant_id_c3e2ec5a ON public.gastronet_restaurantcrawllog USING btree (restaurant_id)
  ```
- `gastronet_restaurantcrawllog_restaurant_id_task_9bdc541b_uniq`
  ```sql
  CREATE UNIQUE INDEX gastronet_restaurantcrawllog_restaurant_id_task_9bdc541b_uniq ON public.gastronet_restaurantcrawllog USING btree (restaurant_id, task)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `task` | enrich_restaurants_v3 |
| `created_at` | 2025-12-23 23:12:35.991816+00:00 |
| `restaurant_id` | 50 |

---

## `public.gastronet_review` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `source` | character varying(50) (varchar) | NO |  |
| `review_id` | character varying(200) (varchar) | NO |  |
| `rating` | double precision (float8) | YES |  |
| `text` | text (text) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `scraped_at` | timestamp with time zone (timestamptz) | NO |  |
| `restaurant_id` | bigint (int8) | NO |  |
| `analysis_payload` | jsonb (jsonb) | NO |  |

### Foreign Keys

- `restaurant_id` → `public.gastronet_restaurant.id`

### Indexes

- `gastronet_review_restaurant_id_source_review_id_4c325e6b_uniq`
  ```sql
  CREATE UNIQUE INDEX gastronet_review_restaurant_id_source_review_id_4c325e6b_uniq ON public.gastronet_review USING btree (restaurant_id, source, review_id)
  ```
- `gastronet_review_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_review_pkey ON public.gastronet_review USING btree (id)
  ```
- `gastronet_review_review_id_16f1ac18`
  ```sql
  CREATE INDEX gastronet_review_review_id_16f1ac18 ON public.gastronet_review USING btree (review_id)
  ```
- `gastronet_review_review_id_16f1ac18_like`
  ```sql
  CREATE INDEX gastronet_review_review_id_16f1ac18_like ON public.gastronet_review USING btree (review_id varchar_pattern_ops)
  ```
- `gastronet_review_restaurant_id_61031e6b`
  ```sql
  CREATE INDEX gastronet_review_restaurant_id_61031e6b ON public.gastronet_review USING btree (restaurant_id)
  ```
- `gastronet_r_restaur_d01639_idx`
  ```sql
  CREATE INDEX gastronet_r_restaur_d01639_idx ON public.gastronet_review USING btree (restaurant_id, created_at)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 617 |
| `source` | google |
| `review_id` | 1720289055 |
| `rating` | 5.0 |
| `text` | We stopped in for breakfast because we needed something substantial but didn't want a greasy spoon.  This place did not disappoint.   We got the crepes and t... |
| `created_at` | 2024-07-06 18:04:15+00:00 |
| `scraped_at` | 2025-12-21 15:02:15.773983+00:00 |
| `restaurant_id` | 122 |
| `analysis_payload` | {"result": {"intents": ["praise"], "ambience": "", "highlights": ["excellent crepes", "amazing homemade salsa", "smooth coffee"], "menu_items": ["crepes", "S... |

---

## `public.gastronet_reviewenrichment` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `sentiment_overall` | character varying(10) (varchar) | YES |  |
| `sentiment_score` | double precision (float8) | YES |  |
| `menu_items` | character varying(255)[] (_varchar) | NO |  |
| `menu_item_sentiments` | character varying(10)[] (_varchar) | NO |  |
| `staff_names` | character varying(255)[] (_varchar) | NO |  |
| `staff_roles` | character varying(100)[] (_varchar) | NO |  |
| `staff_sentiments` | character varying(10)[] (_varchar) | NO |  |
| `value_for_money` | character varying(10) (varchar) | YES |  |
| `ambience` | character varying(10) (varchar) | YES |  |
| `service_speed` | character varying(20) (varchar) | YES |  |
| `service_attitude` | character varying(20) (varchar) | YES |  |
| `wait_time_description` | character varying(255) (varchar) | YES |  |
| `intents` | character varying(50)[] (_varchar) | NO |  |
| `highlights` | character varying(500)[] (_varchar) | NO |  |
| `issue_categories` | character varying(100)[] (_varchar) | NO |  |
| `issue_descriptions` | character varying(500)[] (_varchar) | NO |  |
| `entities` | jsonb (jsonb) | NO |  |
| `key_phrases` | character varying(255)[] (_varchar) | NO |  |
| `review_id` | bigint (int8) | NO |  |

### Foreign Keys

- `review_id` → `public.gastronet_review.id`

### Indexes

- `gastronet_reviewenrichment_review_id_key`
  ```sql
  CREATE UNIQUE INDEX gastronet_reviewenrichment_review_id_key ON public.gastronet_reviewenrichment USING btree (review_id)
  ```
- `gastronet_reviewenrichment_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_reviewenrichment_pkey ON public.gastronet_reviewenrichment USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.gastronet_skagitdishidea` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | uuid (uuid) | NO |  |
| `direction` | character varying(40) (varchar) | NO |  |
| `identity_version` | character varying(20) (varchar) | NO |  |
| `payload` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `image` | character varying(100) (varchar) | YES |  |
| `image_prompt` | text (text) | NO |  |

### Indexes

- `gastronet_skagitdishidea_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_skagitdishidea_pkey ON public.gastronet_skagitdishidea USING btree (id)
  ```
- `gastronet_skagitdishidea_created_at_7b7a9af7`
  ```sql
  CREATE INDEX gastronet_skagitdishidea_created_at_7b7a9af7 ON public.gastronet_skagitdishidea USING btree (created_at)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | f065e79f-a855-43b7-9daa-36af00aab946 |
| `direction` | gently-adventurous |
| `identity_version` | v1 |
| `payload` | {"direction": "Gently adventurous", "dish_name": "Umami Braised Beef Rice Bowl with Basil-Citrus Lift", "description": "Braised beef is served over hot rice ... |
| `created_at` | 2026-01-06 00:56:50.670312+00:00 |
| `image` | NULL |
| `image_prompt` |  |

---

## `public.gastronet_urldiscovery` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `query` | character varying(255) (varchar) | NO |  |
| `result_url` | character varying(200) (varchar) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `hit_count` | integer (int4) | NO |  |

### Indexes

- `gastronet_urldiscovery_pkey`
  ```sql
  CREATE UNIQUE INDEX gastronet_urldiscovery_pkey ON public.gastronet_urldiscovery USING btree (id)
  ```
- `gastronet_urldiscovery_query_key`
  ```sql
  CREATE UNIQUE INDEX gastronet_urldiscovery_query_key ON public.gastronet_urldiscovery USING btree (query)
  ```
- `gastronet_urldiscovery_query_e17d7d24_like`
  ```sql
  CREATE INDEX gastronet_urldiscovery_query_e17d7d24_like ON public.gastronet_urldiscovery USING btree (query varchar_pattern_ops)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.geography_columns` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `f_table_catalog` | name (name) | YES |  |
| `f_table_schema` | name (name) | YES |  |
| `f_table_name` | name (name) | YES |  |
| `f_geography_column` | name (name) | YES |  |
| `coord_dimension` | integer (int4) | YES |  |
| `srid` | integer (int4) | YES |  |
| `type` | text (text) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `f_table_catalog` | skagit |
| `f_table_schema` | public |
| `f_table_name` | assessor |
| `f_geography_column` | centroid_geog |
| `coord_dimension` | 2 |
| `srid` | 4326 |
| `type` | Point |

---

## `public.geometry_columns` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `f_table_catalog` | character varying(256) (varchar) | YES |  |
| `f_table_schema` | name (name) | YES |  |
| `f_table_name` | name (name) | YES |  |
| `f_geometry_column` | name (name) | YES |  |
| `coord_dimension` | integer (int4) | YES |  |
| `srid` | integer (int4) | YES |  |
| `type` | character varying(30) (varchar) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `f_table_catalog` | skagit |
| `f_table_schema` | public |
| `f_table_name` | fact_neighborhood_participation |
| `f_geometry_column` | geom_2926 |
| `coord_dimension` | 2 |
| `srid` | 0 |
| `type` | GEOMETRY |

---

## `public.hood_tax_totals` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `hood_code` | text (text) | NO |  |
| `tax_year` | integer (int4) | NO |  |
| `total_tax` | numeric (numeric) | NO |  |
| `parcel_count` | integer (int4) | NO |  |

### Indexes

- `hood_tax_totals_tax_year_idx`
  ```sql
  CREATE INDEX hood_tax_totals_tax_year_idx ON public.hood_tax_totals USING btree (tax_year)
  ```
- `hood_tax_totals_hood_code_idx`
  ```sql
  CREATE INDEX hood_tax_totals_hood_code_idx ON public.hood_tax_totals USING btree (hood_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `hood_code` | 23ACONDO |
| `tax_year` | 2026 |
| `total_tax` | 2474599.37 |
| `parcel_count` | 552 |

---

## `public.improvement_map_temp` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `improvement_id` | text (text) | YES |  |
| `detail_type_code` | text (text) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `improvement_id` | 49652 |
| `detail_type_code` | MA         |

---

## `public.improvements` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `improvement_id` | bigint (int8) | YES |  |
| `description` | text (text) | YES |  |
| `building_style` | text (text) | YES |  |
| `comment` | text (text) | YES |  |
| `improvement_value` | bigint (int8) | YES |  |
| `new_construction_year` | real (float4) | YES |  |
| `total_living_area` | real (float4) | YES |  |
| `segment_id` | bigint (int8) | YES |  |
| `improvement_detail_type_code` | text (text) | YES |  |
| `improvement_detail_class_code` | text (text) | YES |  |
| `improvement_detail_method_code` | real (float4) | YES |  |
| `condition_code` | text (text) | YES |  |
| `calculated_area` | real (float4) | YES |  |
| `unit_price` | real (float4) | YES |  |
| `depreciation_pct` | real (float4) | YES |  |
| `improvement_detail_value` | bigint (int8) | YES |  |
| `construction_style` | text (text) | YES |  |
| `foundation` | text (text) | YES |  |
| `exterior_wall` | text (text) | YES |  |
| `roof_covering` | text (text) | YES |  |
| `roof_style` | text (text) | YES |  |
| `flooring` | text (text) | YES |  |
| `floor_construction` | text (text) | YES |  |
| `interior_finish` | text (text) | YES |  |
| `plumbing_code` | text (text) | YES |  |
| `appliances` | text (text) | YES |  |
| `heating_cooling` | text (text) | YES |  |
| `fireplace` | text (text) | YES |  |
| `rooms` | real (float4) | YES |  |
| `bedrooms` | real (float4) | YES |  |
| `effective_year_built` | real (float4) | YES |  |
| `actual_year_built` | bigint (int8) | YES |  |
| `sketch_path` | text (text) | YES |  |
| `roll_id` | bigint (int8) | YES |  |
| `id` | bigint (int8) | NO |  |

### Foreign Keys

- `roll_id` → `public.openskagit_assessmentroll.id`

### Indexes

- `improvement_improve_50b038_idx`
  ```sql
  CREATE INDEX improvement_improve_50b038_idx ON public.improvements USING btree (improvement_detail_value)
  ```
- `improvement_improve_ad487d_idx`
  ```sql
  CREATE INDEX improvement_improve_ad487d_idx ON public.improvements USING btree (improvement_detail_type_code)
  ```
- `improvement_roll_id_0d3ef8_idx`
  ```sql
  CREATE INDEX improvement_roll_id_0d3ef8_idx ON public.improvements USING btree (roll_id)
  ```
- `improvement_parcel__57e9d4_idx`
  ```sql
  CREATE INDEX improvement_parcel__57e9d4_idx ON public.improvements USING btree (parcel_number)
  ```
- `improvement_effecti_0e3ddc_idx`
  ```sql
  CREATE INDEX improvement_effecti_0e3ddc_idx ON public.improvements USING btree (effective_year_built)
  ```
- `improvement_conditi_3ee3cc_idx`
  ```sql
  CREATE INDEX improvement_conditi_3ee3cc_idx ON public.improvements USING btree (condition_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P135514 |
| `improvement_id` | 1954278 |
| `description` | NULL |
| `building_style` | TH    |
| `comment` | 9-16-22 LI, NC 100% COMPLETE A/0 7/31.TL.   |
| `improvement_value` | 293300 |
| `new_construction_year` | 2022.0 |
| `total_living_area` | 1542.6 |
| `segment_id` | 329508 |
| `improvement_detail_type_code` | CCP        |
| `improvement_detail_class_code` | MSA        |
| `improvement_detail_method_code` | NULL |
| `condition_code` | E     |
| `calculated_area` | 36.0 |
| `unit_price` | 23.33 |
| `depreciation_pct` | 100.0 |
| `improvement_detail_value` | 800 |
| `construction_style` | NULL |
| `foundation` | NULL |
| `exterior_wall` | NULL |
| `roof_covering` | NULL |
| `roof_style` | NULL |
| `flooring` | NULL |
| `floor_construction` | NULL |
| `interior_finish` | NULL |
| `plumbing_code` | NULL |
| `appliances` | NULL |
| `heating_cooling` | NULL |
| `fireplace` | NULL |
| `rooms` | NULL |
| `bedrooms` | NULL |
| `effective_year_built` | 2022.0 |
| `actual_year_built` | 2021 |
| `sketch_path` | http://skagitcounty.net/Assessor/Images/Photos/4456/3455324.jpg |
| `roll_id` | 1 |
| `id` | 369238 |

---

## `public.jurisdiction_code_set` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `jurisdiction_key` | character varying(50) (varchar) | NO |  |
| `code_set` | character varying(100) (varchar) | NO |  |
| `source` | character varying(200) (varchar) | NO |  |

### Indexes

- `jurisdiction_code_set_jurisdiction_key_code_set_35078e1d_uniq`
  ```sql
  CREATE UNIQUE INDEX jurisdiction_code_set_jurisdiction_key_code_set_35078e1d_uniq ON public.jurisdiction_code_set USING btree (jurisdiction_key, code_set)
  ```
- `jurisdiction_code_set_pkey`
  ```sql
  CREATE UNIQUE INDEX jurisdiction_code_set_pkey ON public.jurisdiction_code_set USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `jurisdiction_key` | unincorporated_skagit |
| `code_set` | skagit_county_code |
| `source` | compiled_research |

---

## `public.kidslab_card` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `title` | character varying(120) (varchar) | NO |  |
| `slug` | character varying(80) (varchar) | NO |  |
| `card_type` | character varying(20) (varchar) | NO |  |
| `direction` | character varying(20) (varchar) | NO |  |
| `order` | integer (int4) | NO |  |
| `is_active` | boolean (bool) | NO |  |
| `image` | character varying(100) (varchar) | YES |  |
| `photo` | character varying(100) (varchar) | YES |  |
| `audio` | character varying(100) (varchar) | YES |  |
| `youtube_url` | character varying(200) (varchar) | YES |  |
| `config` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `kidslab_card_pkey`
  ```sql
  CREATE UNIQUE INDEX kidslab_card_pkey ON public.kidslab_card USING btree (id)
  ```
- `kidslab_card_slug_8cbba573_like`
  ```sql
  CREATE INDEX kidslab_card_slug_8cbba573_like ON public.kidslab_card USING btree (slug varchar_pattern_ops)
  ```
- `kidslab_card_slug_8cbba573`
  ```sql
  CREATE INDEX kidslab_card_slug_8cbba573 ON public.kidslab_card USING btree (slug)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `title` | Donkey |
| `slug` |  |
| `card_type` | ANIMAL_SOUND |
| `direction` | up |
| `order` | 1 |
| `is_active` | True |
| `image` | kidslab/images/images.jpg |
| `photo` |  |
| `audio` | kidslab/audio/mixkit-donkey-scream-1770.wav |
| `youtube_url` | NULL |
| `config` | {} |
| `created_at` | 2026-01-03 21:07:45.157389+00:00 |
| `updated_at` | 2026-01-03 21:15:08.170545+00:00 |

---

## `public.land` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `property_value_year` | real (float4) | YES |  |
| `land_segment_id` | real (float4) | YES |  |
| `land_type` | text (text) | YES |  |
| `appraisal_method` | text (text) | YES |  |
| `size_acres` | real (float4) | YES |  |
| `size_square_feet` | real (float4) | YES |  |
| `land_adjustment_factor` | real (float4) | YES |  |
| `adjusted_value` | real (float4) | YES |  |
| `market_unit_price` | real (float4) | YES |  |
| `market_value` | real (float4) | YES |  |
| `open_space_value` | real (float4) | YES |  |
| `agricultural_unit_price` | real (float4) | YES |  |
| `roll_id` | bigint (int8) | YES |  |
| `id` | bigint (int8) | NO |  |

### Foreign Keys

- `roll_id` → `public.openskagit_assessmentroll.id`

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `property_value_year` | 2025.0 |
| `land_segment_id` | 81153.0 |
| `land_type` | CLEARED |
| `appraisal_method` | LOT |
| `size_acres` | 0.0 |
| `size_square_feet` | 7500.0 |
| `land_adjustment_factor` | 1.0 |
| `adjusted_value` | 180000.0 |
| `market_unit_price` | 260000.0 |
| `market_value` | 362500.0 |
| `open_space_value` | 0.0 |
| `agricultural_unit_price` | 0.0 |
| `roll_id` | 2 |
| `id` | 216845 |

---

## `public.legal_code_jurisdiction` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `name` | character varying(200) (varchar) | NO |  |
| `state` | character varying(2) (varchar) | NO |  |

### Indexes

- `legal_code_jurisdiction_name_key`
  ```sql
  CREATE UNIQUE INDEX legal_code_jurisdiction_name_key ON public.legal_code_jurisdiction USING btree (name)
  ```
- `legal_code_jurisdiction_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_jurisdiction_pkey ON public.legal_code_jurisdiction USING btree (id)
  ```
- `legal_code_jurisdiction_name_e27afbe0_like`
  ```sql
  CREATE INDEX legal_code_jurisdiction_name_e27afbe0_like ON public.legal_code_jurisdiction USING btree (name varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `name` | Concrete |
| `state` | WA |

---

## `public.legal_code_jurisdictionalias` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `alias` | character varying(200) (varchar) | NO |  |
| `alias_normalized` | character varying(200) (varchar) | NO |  |
| `source` | character varying(50) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `jurisdiction_id` | bigint (int8) | NO |  |

### Foreign Keys

- `jurisdiction_id` → `public.legal_code_jurisdiction.id`

### Indexes

- `legal_code_jurisdictionalias_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_jurisdictionalias_pkey ON public.legal_code_jurisdictionalias USING btree (id)
  ```
- `legal_code_jurisdictionalias_jurisdiction_id_4646e9b7`
  ```sql
  CREATE INDEX legal_code_jurisdictionalias_jurisdiction_id_4646e9b7 ON public.legal_code_jurisdictionalias USING btree (jurisdiction_id)
  ```
- `legal_code_jurisdictionalias_alias_normalized_8616d6bf_like`
  ```sql
  CREATE INDEX legal_code_jurisdictionalias_alias_normalized_8616d6bf_like ON public.legal_code_jurisdictionalias USING btree (alias_normalized varchar_pattern_ops)
  ```
- `legal_code_jurisdictionalias_alias_normalized_key`
  ```sql
  CREATE UNIQUE INDEX legal_code_jurisdictionalias_alias_normalized_key ON public.legal_code_jurisdictionalias USING btree (alias_normalized)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `alias` | Concrete |
| `alias_normalized` | concrete |
| `source` | jurisdiction_name |
| `created_at` | 2026-01-20 13:00:52.389022+00:00 |
| `jurisdiction_id` | 1 |

---

## `public.legal_code_lawchapter` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `chapter_number` | character varying(20) (varchar) | NO |  |
| `chapter_name` | character varying(255) (varchar) | NO |  |
| `document_id` | bigint (int8) | NO |  |
| `code_set` | character varying(100) (varchar) | YES |  |

### Foreign Keys

- `document_id` → `public.legal_code_lawdocument.id`

### Indexes

- `legal_code_lawchapter_document_id_chapter_number_c4904d38_uniq`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawchapter_document_id_chapter_number_c4904d38_uniq ON public.legal_code_lawchapter USING btree (document_id, chapter_number)
  ```
- `legal_code_lawchapter_document_id_2b2e872a`
  ```sql
  CREATE INDEX legal_code_lawchapter_document_id_2b2e872a ON public.legal_code_lawchapter USING btree (document_id)
  ```
- `legal_code_lawchapter_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawchapter_pkey ON public.legal_code_lawchapter USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `chapter_number` | 15.04 |
| `chapter_name` | BUILDING CODE |
| `document_id` | 1 |
| `code_set` | concrete_municipal_code |

---

## `public.legal_code_lawdocument` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `title_number` | character varying(20) (varchar) | NO |  |
| `title_name` | character varying(255) (varchar) | NO |  |
| `source_vendor` | character varying(100) (varchar) | NO |  |
| `effective_note` | text (text) | YES |  |
| `jurisdiction_id` | bigint (int8) | NO |  |

### Foreign Keys

- `jurisdiction_id` → `public.legal_code_jurisdiction.id`

### Indexes

- `legal_code_lawdocument_jurisdiction_id_title_nu_1e060ced_uniq`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawdocument_jurisdiction_id_title_nu_1e060ced_uniq ON public.legal_code_lawdocument USING btree (jurisdiction_id, title_number)
  ```
- `legal_code_lawdocument_jurisdiction_id_e21e96fe`
  ```sql
  CREATE INDEX legal_code_lawdocument_jurisdiction_id_e21e96fe ON public.legal_code_lawdocument USING btree (jurisdiction_id)
  ```
- `legal_code_lawdocument_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawdocument_pkey ON public.legal_code_lawdocument USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `title_number` | ALL |
| `title_name` | CodePublishing Corpus |
| `source_vendor` | codepublishing |
| `effective_note` | NULL |
| `jurisdiction_id` | 1 |

---

## `public.legal_code_lawsection` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `section_id` | character varying(50) (varchar) | NO |  |
| `heading` | character varying(500) (varchar) | NO |  |
| `content` | text (text) | NO |  |
| `history` | jsonb (jsonb) | NO |  |
| `tables` | jsonb (jsonb) | NO |  |
| `content_hash` | character varying(64) (varchar) | NO |  |
| `source_url` | character varying(200) (varchar) | NO |  |
| `scraped_at` | timestamp with time zone (timestamptz) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `chapter_id` | bigint (int8) | NO |  |

### Foreign Keys

- `chapter_id` → `public.legal_code_lawchapter.id`

### Indexes

- `legal_code_lawsection_content_hash_096ee213_like`
  ```sql
  CREATE INDEX legal_code_lawsection_content_hash_096ee213_like ON public.legal_code_lawsection USING btree (content_hash varchar_pattern_ops)
  ```
- `legal_code__content_7871cd_idx`
  ```sql
  CREATE INDEX legal_code__content_7871cd_idx ON public.legal_code_lawsection USING btree (content_hash)
  ```
- `legal_code_lawsection_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawsection_pkey ON public.legal_code_lawsection USING btree (id)
  ```
- `legal_code_lawsection_chapter_id_c8205d70`
  ```sql
  CREATE INDEX legal_code_lawsection_chapter_id_c8205d70 ON public.legal_code_lawsection USING btree (chapter_id)
  ```
- `legal_code__section_232be6_idx`
  ```sql
  CREATE INDEX legal_code__section_232be6_idx ON public.legal_code_lawsection USING btree (section_id)
  ```
- `legal_code_lawsection_content_hash_096ee213`
  ```sql
  CREATE INDEX legal_code_lawsection_content_hash_096ee213 ON public.legal_code_lawsection USING btree (content_hash)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `section_id` | 15.04.010 |
| `heading` | Title. |
| `content` | This chapter shall be known as the “Building Code of the Town of Concrete, Washington.” [Ord. 532, 2004] |
| `history` | [] |
| `tables` | [] |
| `content_hash` | f6a56d43e92f593a365a9edbe9309ccc8023de623fe3a6a1d87b323eefe0749b |
| `source_url` | https://www.codepublishing.com/WA/Concrete/ |
| `scraped_at` | 2026-01-19 16:43:05.524338+00:00 |
| `created_at` | 2026-01-19 16:43:07.062130+00:00 |
| `chapter_id` | 1 |

---

## `public.legal_code_lawsectionchunk` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `law_section_ref` | character varying(50) (varchar) | NO |  |
| `heading` | character varying(500) (varchar) | NO |  |
| `source_url` | character varying(200) (varchar) | NO |  |
| `chunk_index` | integer (int4) | NO |  |
| `content` | text (text) | NO |  |
| `content_hash` | character varying(64) (varchar) | NO |  |
| `embedding_model` | character varying(100) (varchar) | NO |  |
| `embedding` | vector(1536) (vector) | YES |  |
| `embedded_at` | timestamp with time zone (timestamptz) | YES |  |
| `jurisdiction_id` | bigint (int8) | NO |  |
| `section_id` | bigint (int8) | NO |  |
| `lane_scores` | jsonb (jsonb) | YES |  |
| `lanes_classified_at` | timestamp with time zone (timestamptz) | YES |  |

### Foreign Keys

- `jurisdiction_id` → `public.legal_code_jurisdiction.id`
- `section_id` → `public.legal_code_lawsection.id`

### Indexes

- `legal_code_lawsectionchunk_jurisdiction_id_f7494e7d`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_jurisdiction_id_f7494e7d ON public.legal_code_lawsectionchunk USING btree (jurisdiction_id)
  ```
- `legal_code_lawsectionchu_section_id_chunk_index_e_18d51984_uniq`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawsectionchu_section_id_chunk_index_e_18d51984_uniq ON public.legal_code_lawsectionchunk USING btree (section_id, chunk_index, embedding_model)
  ```
- `legal_code__content_31e13e_idx`
  ```sql
  CREATE INDEX legal_code__content_31e13e_idx ON public.legal_code_lawsectionchunk USING btree (content_hash)
  ```
- `legal_code_lawsectionchunk_pkey`
  ```sql
  CREATE UNIQUE INDEX legal_code_lawsectionchunk_pkey ON public.legal_code_lawsectionchunk USING btree (id)
  ```
- `legal_code_lawsectionchunk_law_section_ref_bc8eac77`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_law_section_ref_bc8eac77 ON public.legal_code_lawsectionchunk USING btree (law_section_ref)
  ```
- `legal_code__jurisdi_91b4b0_idx`
  ```sql
  CREATE INDEX legal_code__jurisdi_91b4b0_idx ON public.legal_code_lawsectionchunk USING btree (jurisdiction_id, section_id)
  ```
- `legal_code_lawsectionchunk_law_section_ref_bc8eac77_like`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_law_section_ref_bc8eac77_like ON public.legal_code_lawsectionchunk USING btree (law_section_ref varchar_pattern_ops)
  ```
- `legal_code_lawsectionchunk_content_hash_d2e9a0e2`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_content_hash_d2e9a0e2 ON public.legal_code_lawsectionchunk USING btree (content_hash)
  ```
- `legal_code_lawsectionchunk_content_hash_d2e9a0e2_like`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_content_hash_d2e9a0e2_like ON public.legal_code_lawsectionchunk USING btree (content_hash varchar_pattern_ops)
  ```
- `legal_code_lawsectionchunk_section_id_58ba13ee`
  ```sql
  CREATE INDEX legal_code_lawsectionchunk_section_id_58ba13ee ON public.legal_code_lawsectionchunk USING btree (section_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2564 |
| `law_section_ref` | 17.200.100 |
| `heading` | CUP city council authority – Final decision. |
| `source_url` | https://www.codepublishing.com/WA/MountVernon/ |
| `chunk_index` | 0 |
| `content` | A. The designated hearing body, giving substantial weight to the recommendations of the staff report, shall review the application under the following criter... |
| `content_hash` | b652b959e35aeb443dba206113a079f678ec84bdc88e1b5e04fbf3fb780f498f |
| `embedding_model` | text-embedding-3-small |
| `embedding` | [0.005402766,0.005245709,0.05875194,0.036613166,-0.02530505,0.036035195,-0.008832894,-0.018532744,-0.012866123,0.04872541,0.051213197,-0.0051012165,-0.032969... |
| `embedded_at` | 2026-01-20 16:12:28.252781+00:00 |
| `jurisdiction_id` | 3 |
| `section_id` | 2703 |
| `lane_scores` | NULL |
| `lanes_classified_at` | NULL |

---

## `public.master_parcel` (t)

**Primary Key:** parcel_number

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | NO |  |
| `aid` | integer (int4) | YES |  |
| `building_value` | double precision (float8) | YES |  |
| `impr_land_value` | double precision (float8) | YES |  |
| `unimpr_land_value` | double precision (float8) | YES |  |
| `timber_land_value` | double precision (float8) | YES |  |
| `assessed_value` | double precision (float8) | YES |  |
| `taxable_value` | double precision (float8) | YES |  |
| `total_market_value` | double precision (float8) | YES |  |
| `acres` | double precision (float8) | YES |  |
| `sale_price` | double precision (float8) | YES |  |
| `price_per_sqft` | double precision (float8) | YES |  |
| `year_built` | integer (int4) | YES |  |
| `living_area` | integer (int4) | YES |  |
| `buildingstyle` | character varying(100) (varchar) | YES |  |
| `plumbing` | character varying(100) (varchar) | YES |  |
| `garagesqft` | integer (int4) | YES |  |
| `heat_air_cond` | character varying(100) (varchar) | YES |  |
| `fireplace` | character varying(100) (varchar) | YES |  |
| `finishedbasement` | integer (int4) | YES |  |
| `number_of_bedrooms` | integer (int4) | YES |  |
| `eff_year_built` | integer (int4) | YES |  |
| `unfinishedbasement` | integer (int4) | YES |  |
| `fire_district` | character varying(50) (varchar) | YES |  |
| `school_district` | character varying(50) (varchar) | YES |  |
| `city_district` | character varying(50) (varchar) | YES |  |
| `levy_code` | character varying(20) (varchar) | YES |  |
| `proptype` | character varying(10) (varchar) | YES |  |
| `hasseptic` | boolean (bool) | NO |  |
| `land_use_code` | character varying(10) (varchar) | YES |  |
| `land_use_description` | character varying(200) (varchar) | YES |  |
| `hood_code` | character varying(20) (varchar) | YES |  |
| `hood_description` | character varying(200) (varchar) | YES |  |
| `has_unit` | boolean (bool) | NO |  |
| `situs_address` | character varying(300) (varchar) | YES |  |
| `total_baths` | double precision (float8) | YES |  |
| `year_built_max` | integer (int4) | YES |  |
| `year_built_min` | integer (int4) | YES |  |
| `total_living_area` | double precision (float8) | YES |  |
| `total_garage_area` | double precision (float8) | YES |  |
| `total_deck_area` | double precision (float8) | YES |  |
| `total_porch_area` | double precision (float8) | YES |  |
| `total_basement_area` | double precision (float8) | YES |  |
| `total_shop_area` | double precision (float8) | YES |  |
| `total_shed_count` | integer (int4) | YES |  |
| `has_pool` | boolean (bool) | NO |  |
| `quality_score` | double precision (float8) | YES |  |
| `condition_score` | double precision (float8) | YES |  |
| `building_style` | character varying(50) (varchar) | YES |  |
| `effective_yr_blt` | integer (int4) | YES |  |
| `main_structure_count` | integer (int4) | YES |  |
| `flag_multi_structure` | boolean (bool) | NO |  |
| `final_living_area` | double precision (float8) | YES |  |
| `final_year_built` | integer (int4) | YES |  |
| `final_garage_area` | double precision (float8) | YES |  |
| `final_eff_yr_blt` | integer (int4) | YES |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `total_shop_count` | integer (int4) | YES |  |
| `total_shed_area` | double precision (float8) | YES |  |

### Indexes

- `master_parc_parcel__04e153_idx`
  ```sql
  CREATE INDEX master_parc_parcel__04e153_idx ON public.master_parcel USING btree (parcel_number)
  ```
- `master_parcel_pkey`
  ```sql
  CREATE UNIQUE INDEX master_parcel_pkey ON public.master_parcel USING btree (parcel_number)
  ```
- `master_parc_land_us_cc8eeb_idx`
  ```sql
  CREATE INDEX master_parc_land_us_cc8eeb_idx ON public.master_parcel USING btree (land_use_code)
  ```
- `master_parc_hood_co_cdede5_idx`
  ```sql
  CREATE INDEX master_parc_hood_co_cdede5_idx ON public.master_parcel USING btree (hood_code)
  ```
- `master_parcel_parcel_number_e176375e_like`
  ```sql
  CREATE INDEX master_parcel_parcel_number_e176375e_like ON public.master_parcel USING btree (parcel_number varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `aid` | 71352 |
| `building_value` | 314200.0 |
| `impr_land_value` | 362500.0 |
| `unimpr_land_value` | 0.0 |
| `timber_land_value` | 0.0 |
| `assessed_value` | 676700.0 |
| `taxable_value` | 676700.0 |
| `total_market_value` | 676700.0 |
| `acres` | 0.0 |
| `sale_price` | 0.0 |
| `price_per_sqft` | NULL |
| `year_built` | 1992 |
| `living_area` | 2062 |
| `buildingstyle` | NULL |
| `plumbing` | NULL |
| `garagesqft` | NULL |
| `heat_air_cond` | FORCED AIR |
| `fireplace` | S1 - STEEL |
| `finishedbasement` | 0 |
| `number_of_bedrooms` | 2 |
| `eff_year_built` | 2009 |
| `unfinishedbasement` | 0 |
| `fire_district` | NULL |
| `school_district` | SD103 |
| `city_district` | ANACORTES |
| `levy_code` | 900.0 |
| `proptype` | R |
| `hasseptic` | False |
| `land_use_code` | 120 |
| `land_use_description` | HOUSEHOLD, 2-4 UNITS |
| `hood_code` | 30AMF |
| `hood_description` | ANACORTES RESIDENTIAL 2-4 FAMILY |
| `has_unit` | False |
| `situs_address` | 1413-1415 33RD ST ANACORTES, WA 98221 |
| `total_baths` | 1.0 |
| `year_built_max` | 1992 |
| `year_built_min` | 1992 |
| `total_living_area` | 1031.0 |
| `total_garage_area` | 240.0 |
| `total_deck_area` | 140.0 |
| `total_porch_area` | 0.0 |
| `total_basement_area` | 0.0 |
| `total_shop_area` | 0.0 |
| `total_shed_count` | 0 |
| `has_pool` | False |
| `quality_score` | 3.0 |
| `condition_score` | 3.0 |
| `building_style` | NULL |
| `effective_yr_blt` | 2009 |
| `main_structure_count` | 1 |
| `flag_multi_structure` | False |
| `final_living_area` | 2062.0 |
| `final_year_built` | 1992 |
| `final_garage_area` | 240.0 |
| `final_eff_yr_blt` | 2009 |
| `updated_at` | 2026-01-16 20:39:18.524070+00:00 |
| `total_shop_count` | 0 |
| `total_shed_area` | 0.0 |

---

## `public.neighborhood_ballots_by_year` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |

### Indexes

- `neighborhood_ballots_code_only_idx`
  ```sql
  CREATE INDEX neighborhood_ballots_code_only_idx ON public.neighborhood_ballots_by_year USING btree (neighborhood_code)
  ```
- `neighborhood_ballots_year_only_idx`
  ```sql
  CREATE INDEX neighborhood_ballots_year_only_idx ON public.neighborhood_ballots_by_year USING btree (election_year)
  ```
- `neighborhood_ballots_year_idx`
  ```sql
  CREATE UNIQUE INDEX neighborhood_ballots_year_idx ON public.neighborhood_ballots_by_year USING btree (neighborhood_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 10CCREC |
| `election_year` | 2024 |
| `ballots_cast` | 2 |

---

## `public.neighborhood_participation_classification` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `npi` | double precision (float8) | YES |  |
| `quartile` | integer (int4) | YES |  |
| `quartile_label` | text (text) | YES |  |

### Indexes

- `neighborhood_participation_classification_year_idx`
  ```sql
  CREATE INDEX neighborhood_participation_classification_year_idx ON public.neighborhood_participation_classification USING btree (election_year)
  ```
- `neighborhood_participation_classification_idx`
  ```sql
  CREATE UNIQUE INDEX neighborhood_participation_classification_idx ON public.neighborhood_participation_classification USING btree (neighborhood_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 20CCCHORN |
| `election_year` | 2024 |
| `npi` | 0.006711409395973154 |
| `quartile` | 1 |
| `quartile_label` | Lowest participation density |

---

## `public.neighborhood_participation_geometry` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying(20) (varchar) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Indexes

- `neighborhood_participation_geometry_geom_gix`
  ```sql
  CREATE INDEX neighborhood_participation_geometry_geom_gix ON public.neighborhood_participation_geometry USING gist (geom_2926)
  ```
- `neighborhood_participation_geometry_idx`
  ```sql
  CREATE UNIQUE INDEX neighborhood_participation_geometry_idx ON public.neighborhood_participation_geometry USING btree (neighborhood_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 10CCCRP |
| `geom_2926` | 01060000206E0B00001A0000000103000000010000003C000000450C35F3971D3741B33A6FE998F420413CBB32A1A11D3741DAF05A14C0F4204136D7E25E9E1D3741437CB582F9F420415F860A1B8... |

---

## `public.neighborhood_primary_precinct` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `primary_precinct_code` | bigint (int8) | YES |  |
| `precinct_residential_parcels` | bigint (int8) | YES |  |

### Indexes

- `neighborhood_primary_precinct_idx`
  ```sql
  CREATE UNIQUE INDEX neighborhood_primary_precinct_idx ON public.neighborhood_primary_precinct USING btree (neighborhood_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 10CCCRP |
| `primary_precinct_code` | 114 |
| `precinct_residential_parcels` | 280 |

---

## `public.neighborhood_residential_parcels` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `residential_parcels` | bigint (int8) | YES |  |

### Indexes

- `neighborhood_residential_code_idx`
  ```sql
  CREATE INDEX neighborhood_residential_code_idx ON public.neighborhood_residential_parcels USING btree (neighborhood_code)
  ```
- `neighborhood_residential_year_idx`
  ```sql
  CREATE INDEX neighborhood_residential_year_idx ON public.neighborhood_residential_parcels USING btree (election_year)
  ```
- `neighborhood_residential_idx`
  ```sql
  CREATE UNIQUE INDEX neighborhood_residential_idx ON public.neighborhood_residential_parcels USING btree (neighborhood_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 10CCCRP |
| `election_year` | 2025 |
| `residential_parcels` | 280 |

---

## `public.openskagit_adjustmentcoefficient` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `market_group` | character varying(100) (varchar) | NO |  |
| `term` | character varying(200) (varchar) | NO |  |
| `beta` | double precision (float8) | NO |  |
| `beta_se` | double precision (float8) | YES |  |
| `run_id` | character varying(20) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_adjustmentcoefficient_run_id_2a7c2094`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_run_id_2a7c2094 ON public.openskagit_adjustmentcoefficient USING btree (run_id)
  ```
- `openskagit_adjustmentcoefficient_market_group_8c5e2c21`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_market_group_8c5e2c21 ON public.openskagit_adjustmentcoefficient USING btree (market_group)
  ```
- `openskagit_adjustmentcoefficient_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentcoefficient_pkey ON public.openskagit_adjustmentcoefficient USING btree (id)
  ```
- `openskagit_adjustmentcoefficient_run_id_2a7c2094_like`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_run_id_2a7c2094_like ON public.openskagit_adjustmentcoefficient USING btree (run_id varchar_pattern_ops)
  ```
- `openskagit_adjustmentcoefficient_term_4161326c_like`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_term_4161326c_like ON public.openskagit_adjustmentcoefficient USING btree (term varchar_pattern_ops)
  ```
- `openskagit_adjustmentcoe_market_group_term_run_id_affaf948_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentcoe_market_group_term_run_id_affaf948_uniq ON public.openskagit_adjustmentcoefficient USING btree (market_group, term, run_id)
  ```
- `openskagit_adjustmentcoefficient_term_4161326c`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_term_4161326c ON public.openskagit_adjustmentcoefficient USING btree (term)
  ```
- `openskagit_adjustmentcoefficient_market_group_8c5e2c21_like`
  ```sql
  CREATE INDEX openskagit_adjustmentcoefficient_market_group_8c5e2c21_like ON public.openskagit_adjustmentcoefficient USING btree (market_group varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `market_group` | ANACORTES |
| `term` | const |
| `beta` | 11.246721077164688 |
| `beta_se` | 0.10106060416085018 |
| `run_id` | 174223 |
| `created_at` | 2025-11-17 17:53:08.317616+00:00 |

---

## `public.openskagit_adjustmentmodelsegment` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `market_group` | character varying(100) (varchar) | NO |  |
| `value_tier` | character varying(20) (varchar) | NO |  |
| `price_min` | double precision (float8) | NO |  |
| `price_max` | double precision (float8) | NO |  |
| `n_obs` | integer (int4) | NO |  |
| `r2` | double precision (float8) | YES |  |
| `cod` | double precision (float8) | YES |  |
| `prd` | double precision (float8) | YES |  |
| `median_ratio` | double precision (float8) | YES |  |
| `included_predictors` | jsonb (jsonb) | NO |  |
| `run_id` | bigint (int8) | NO |  |

### Foreign Keys

- `run_id` → `public.openskagit_adjustmentrunsummary.id`

### Indexes

- `openskagit_adjustmentmodelsegment_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentmodelsegment_pkey ON public.openskagit_adjustmentmodelsegment USING btree (id)
  ```
- `openskagit_adjustmentmod_run_id_market_group_valu_54592b6f_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentmod_run_id_market_group_valu_54592b6f_uniq ON public.openskagit_adjustmentmodelsegment USING btree (run_id, market_group, value_tier)
  ```
- `openskagit_adjustmentmodelsegment_run_id_f1959065`
  ```sql
  CREATE INDEX openskagit_adjustmentmodelsegment_run_id_f1959065 ON public.openskagit_adjustmentmodelsegment USING btree (run_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_adjustmentrunsummary` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `run_id` | character varying(20) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `stats` | jsonb (jsonb) | NO |  |
| `content` | jsonb (jsonb) | NO |  |

### Indexes

- `openskagit_adjustmentrunsummary_run_id_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentrunsummary_run_id_key ON public.openskagit_adjustmentrunsummary USING btree (run_id)
  ```
- `openskagit_adjustmentrunsummary_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_adjustmentrunsummary_pkey ON public.openskagit_adjustmentrunsummary USING btree (id)
  ```
- `openskagit_adjustmentrunsummary_run_id_c3fff42e_like`
  ```sql
  CREATE INDEX openskagit_adjustmentrunsummary_run_id_c3fff42e_like ON public.openskagit_adjustmentrunsummary USING btree (run_id varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `run_id` | 20251124152551 |
| `created_at` | 2025-11-24 15:26:01.427186+00:00 |
| `stats` | [] |
| `content` | [] |

---

## `public.openskagit_agencyfinancialsnapshot` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `mcag` | character varying(10) (varchar) | NO |  |
| `year` | integer (int4) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `legal_name` | character varying(255) (varchar) | NO |  |
| `gov_type_code` | character varying(4) (varchar) | NO |  |
| `gov_type_desc` | character varying(100) (varchar) | NO |  |
| `county_code` | integer (int4) | YES |  |
| `county_name` | character varying(100) (varchar) | NO |  |
| `is_school` | boolean (bool) | NO |  |
| `dataset_source` | character varying(32) (varchar) | NO |  |
| `website` | character varying(255) (varchar) | NO |  |
| `street_address` | character varying(255) (varchar) | NO |  |
| `city` | character varying(120) (varchar) | NO |  |
| `state` | character varying(2) (varchar) | NO |  |
| `postal_code` | character varying(10) (varchar) | NO |  |
| `latitude` | double precision (float8) | YES |  |
| `longitude` | double precision (float8) | YES |  |
| `fiscal_year_end` | character varying(20) (varchar) | NO |  |
| `financial_summary` | jsonb (jsonb) | NO |  |
| `revenues` | jsonb (jsonb) | NO |  |
| `expenditures` | jsonb (jsonb) | NO |  |
| `indicators` | jsonb (jsonb) | NO |  |
| `rankings` | jsonb (jsonb) | NO |  |
| `metadata` | jsonb (jsonb) | NO |  |
| `raw_payloads` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `revenues_detail` | jsonb (jsonb) | NO |  |
| `expenditures_detail` | jsonb (jsonb) | NO |  |

### Indexes

- `openskagit_agencyfinancialsnapshot_year_a202283c`
  ```sql
  CREATE INDEX openskagit_agencyfinancialsnapshot_year_a202283c ON public.openskagit_agencyfinancialsnapshot USING btree (year)
  ```
- `openskagit_agencyfinancialsnapshot_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_agencyfinancialsnapshot_pkey ON public.openskagit_agencyfinancialsnapshot USING btree (id)
  ```
- `openskagit_agencyfinancialsnapshot_mcag_d0f25ad0_like`
  ```sql
  CREATE INDEX openskagit_agencyfinancialsnapshot_mcag_d0f25ad0_like ON public.openskagit_agencyfinancialsnapshot USING btree (mcag varchar_pattern_ops)
  ```
- `openskagit_agencyfinancialsnapshot_mcag_d0f25ad0`
  ```sql
  CREATE INDEX openskagit_agencyfinancialsnapshot_mcag_d0f25ad0 ON public.openskagit_agencyfinancialsnapshot USING btree (mcag)
  ```
- `uniq_agency_financial_snapshot`
  ```sql
  CREATE UNIQUE INDEX uniq_agency_financial_snapshot ON public.openskagit_agencyfinancialsnapshot USING btree (mcag, year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `mcag` | 1288 |
| `year` | 2024 |
| `name` | Big Lake Fire Department |
| `legal_name` | Skagit County Fire Protection District No. 9 |
| `gov_type_code` | 08 |
| `gov_type_desc` | Fire Protection District |
| `county_code` | 29 |
| `county_name` |  |
| `is_school` | False |
| `dataset_source` | snapshot31 |
| `website` | www.biglakefire.org/ |
| `street_address` | 16822 W Big Lake Blvd |
| `city` | Mount Vernon |
| `state` | WA |
| `postal_code` | 98274 |
| `latitude` | 48.4022 |
| `longitude` | -122.24367 |
| `fiscal_year_end` | 12/31 |
| `financial_summary` | {"sections": [{"label": "Expenditures", "values": {"2021": 314408.0, "2022": 327110.0, "2023": 267312.0, "2024": 317370.0}, "section_id": 30}, {"label": "Oth... |
| `revenues` | [{"code": 6, "label": "Taxes", "values": {"2021": 519716.0, "2022": 522874.0, "2023": 524862.0, "2024": 536432.0}}, {"code": 155, "label": "Intergovernmental... |
| `expenditures` | [{"code": 2082, "label": "2082", "values": {"2021": 314408.0, "2022": 327110.0, "2023": 267312.0, "2024": 317370.0}}] |
| `indicators` | [{"code": "CASH48.CashBalanceSufficiency.Governmental", "mcag": "1288", "year": 2021, "group": "All Governmental Funds", "title": "Cash Balance Sufficiency",... |
| `rankings` | {"financial": [{"mcag": "1288", "rank": 187, "year": 2021, "amount": 314408.0, "fsSectionId": 30, "govTypeCode": "08", "basicAccountId": null, "fundCategoryI... |
| `metadata` | {"filed_funds": [{"fundName": "General", "fundNumber": "001", "fundTypeId": 0, "fundCategoryId": 1}], "local_government": {"rcw": "RCW 52", "zip": "98274", "... |
| `raw_payloads` | {"summary": {"value": [{"id": 0, "fund": null, "mcag": "1288", "year": 2021, "elementId": null, "countyCode": 29, "fundTypeId": null, "fsSectionId": 30, "gov... |
| `created_at` | 2026-01-13 18:48:21.062710+00:00 |
| `updated_at` | 2026-01-13 18:48:21.062738+00:00 |
| `revenues_detail` | [{"year": 2021, "amount": 519716.0, "element": {"id": 5459, "code": "311.10.00", "name": "Property Tax", "parent_id": 7, "fs_section_id": 20}, "fund_code": "... |
| `expenditures_detail` | [{"year": 2021, "amount": 18607.0, "element": {"id": 5382, "code": "522.20", "name": "Fire Suppression and Emergency Medical Services", "parent_id": 2101, "f... |

---

## `public.openskagit_assessmentroll` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `year` | integer (int4) | NO |  |
| `imported_at` | timestamp with time zone (timestamptz) | NO |  |
| `notes` | text (text) | YES |  |

### Indexes

- `openskagit_assessmentroll_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_assessmentroll_pkey ON public.openskagit_assessmentroll USING btree (id)
  ```
- `openskagit_assessmentroll_year_a9872180`
  ```sql
  CREATE INDEX openskagit_assessmentroll_year_a9872180 ON public.openskagit_assessmentroll USING btree (year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `year` | 2024 |
| `imported_at` | 2025-11-01 23:27:42.229382+00:00 |
| `notes` |  |

---

## `public.openskagit_cmaanalysis` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `share_uuid` | uuid (uuid) | NO |  |
| `subject_parcel` | character varying(32) (varchar) | NO |  |
| `subject_snapshot` | jsonb (jsonb) | NO |  |
| `filters` | jsonb (jsonb) | NO |  |
| `manual_adjustments` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `user_id` | integer (int4) | YES |  |

### Foreign Keys

- `user_id` → `public.auth_user.id`

### Indexes

- `openskagit_cmaanalysis_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_cmaanalysis_pkey ON public.openskagit_cmaanalysis USING btree (id)
  ```
- `openskagit_cmaanalysis_user_id_529d6313`
  ```sql
  CREATE INDEX openskagit_cmaanalysis_user_id_529d6313 ON public.openskagit_cmaanalysis USING btree (user_id)
  ```
- `openskagit_cmaanalysis_share_uuid_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_cmaanalysis_share_uuid_key ON public.openskagit_cmaanalysis USING btree (share_uuid)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_cmacomparableselection` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `parcel_number` | character varying(32) (varchar) | NO |  |
| `included` | boolean (bool) | NO |  |
| `rank` | integer (int4) | NO |  |
| `raw_sale_price` | numeric(15,2) (numeric) | NO |  |
| `adjusted_sale_price` | numeric(15,2) (numeric) | NO |  |
| `gross_percentage_adjustment` | numeric(6,2) (numeric) | NO |  |
| `auto_adjustments` | jsonb (jsonb) | NO |  |
| `manual_adjustments` | jsonb (jsonb) | NO |  |
| `metadata` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `analysis_id` | bigint (int8) | NO |  |

### Foreign Keys

- `analysis_id` → `public.openskagit_cmaanalysis.id`

### Indexes

- `openskagit_cmacomparableselection_analysis_id_a2451625`
  ```sql
  CREATE INDEX openskagit_cmacomparableselection_analysis_id_a2451625 ON public.openskagit_cmacomparableselection USING btree (analysis_id)
  ```
- `openskagit_cmacomparable_analysis_id_parcel_numbe_e53a799e_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_cmacomparable_analysis_id_parcel_numbe_e53a799e_uniq ON public.openskagit_cmacomparableselection USING btree (analysis_id, parcel_number)
  ```
- `openskagit_cmacomparableselection_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_cmacomparableselection_pkey ON public.openskagit_cmacomparableselection USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_contactsubmission` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `email` | character varying(254) (varchar) | NO |  |
| `topic` | character varying(32) (varchar) | NO |  |
| `message` | text (text) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_contactsubmission_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_contactsubmission_pkey ON public.openskagit_contactsubmission USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `email` | no.reply.LucasLarsson@gmail.com |
| `topic` | support |
| `message` | Howdy! openskagit.com    Did you know that it is possible to send proposals absolutely legally?  When such business proposals are sent, no personal data i... |
| `created_at` | 2026-01-28 05:04:11.069679+00:00 |

---

## `public.openskagit_dorlocation` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `location_code` | integer (int4) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `location_type` | character varying(20) (varchar) | NO |  |

### Indexes

- `openskagit_dorlocation_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_dorlocation_pkey ON public.openskagit_dorlocation USING btree (id)
  ```
- `openskagit_dorlocation_location_code_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_dorlocation_location_code_key ON public.openskagit_dorlocation USING btree (location_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `location_code` | 2902 |
| `name` | DOR Location 2902 |
| `location_type` | city |

---

## `public.openskagit_dornaicsrecord` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `sector_code` | character varying(10) (varchar) | NO |  |
| `sector_name` | character varying(255) (varchar) | NO |  |
| `naics_code` | character varying(10) (varchar) | YES |  |
| `naics_label` | character varying(255) (varchar) | NO |  |
| `units` | integer (int4) | YES |  |
| `taxable_sales` | bigint (int8) | YES |  |
| `is_total_row` | boolean (bool) | NO |  |
| `source_url` | character varying(500) (varchar) | NO |  |
| `scraped_at` | timestamp with time zone (timestamptz) | NO |  |
| `location_id` | bigint (int8) | NO |  |
| `quarter_id` | bigint (int8) | NO |  |

### Foreign Keys

- `location_id` → `public.openskagit_dorlocation.id`
- `quarter_id` → `public.openskagit_dorquarter.id`

### Indexes

- `openskagit__locatio_6e09f1_idx`
  ```sql
  CREATE INDEX openskagit__locatio_6e09f1_idx ON public.openskagit_dornaicsrecord USING btree (location_id, quarter_id)
  ```
- `openskagit_dornaicsrecord_location_id_75fbb737`
  ```sql
  CREATE INDEX openskagit_dornaicsrecord_location_id_75fbb737 ON public.openskagit_dornaicsrecord USING btree (location_id)
  ```
- `openskagit__naics_c_823cf2_idx`
  ```sql
  CREATE INDEX openskagit__naics_c_823cf2_idx ON public.openskagit_dornaicsrecord USING btree (naics_code)
  ```
- `openskagit__sector__827051_idx`
  ```sql
  CREATE INDEX openskagit__sector__827051_idx ON public.openskagit_dornaicsrecord USING btree (sector_code)
  ```
- `openskagit_dornaicsrecord_quarter_id_5c599f63`
  ```sql
  CREATE INDEX openskagit_dornaicsrecord_quarter_id_5c599f63 ON public.openskagit_dornaicsrecord USING btree (quarter_id)
  ```
- `unique_dor_naics_record`
  ```sql
  CREATE UNIQUE INDEX unique_dor_naics_record ON public.openskagit_dornaicsrecord USING btree (quarter_id, location_id, sector_code, naics_code)
  ```
- `openskagit_dornaicsrecord_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_dornaicsrecord_pkey ON public.openskagit_dornaicsrecord USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `sector_code` | 44-45 |
| `sector_name` | Retail Trade |
| `naics_code` | 4411 |
| `naics_label` | New & Used Auto Dealers |
| `units` | 24 |
| `taxable_sales` | 82454264 |
| `is_total_row` | False |
| `source_url` | https://apps.dor.wa.gov/ResearchStats/Content/QuarterlyBusinessReview/Results3N4.aspx?Period=2025Q2&Location=2902&Type=naics&Format=HTML |
| `scraped_at` | 2025-12-27 14:57:56.857341+00:00 |
| `location_id` | 1 |
| `quarter_id` | 1 |

---

## `public.openskagit_dorquarter` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `period` | character varying(6) (varchar) | NO |  |
| `year` | smallint (int2) | NO |  |
| `quarter` | smallint (int2) | NO |  |

### Indexes

- `openskagit_dorquarter_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_dorquarter_pkey ON public.openskagit_dorquarter USING btree (id)
  ```
- `openskagit_dorquarter_period_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_dorquarter_period_key ON public.openskagit_dorquarter USING btree (period)
  ```
- `openskagit_dorquarter_period_b201285f_like`
  ```sql
  CREATE INDEX openskagit_dorquarter_period_b201285f_like ON public.openskagit_dorquarter USING btree (period varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `period` | 2025Q2 |
| `year` | 2025 |
| `quarter` | 2 |

---

## `public.openskagit_experimentrun` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | uuid (uuid) | NO |  |
| `name` | character varying(200) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `started_at` | timestamp with time zone (timestamptz) | YES |  |
| `completed_at` | timestamp with time zone (timestamptz) | YES |  |
| `status` | character varying(20) (varchar) | NO |  |
| `error_message` | text (text) | NO |  |
| `mode` | character varying(50) (varchar) | NO |  |
| `market_group_col` | character varying(100) (varchar) | NO |  |
| `countywide` | boolean (bool) | NO |  |
| `predictor_profile` | character varying(100) (varchar) | NO |  |
| `interaction_bundle` | character varying(100) (varchar) | NO |  |
| `full_config` | jsonb (jsonb) | NO |  |
| `total_observations` | integer (int4) | YES |  |
| `segment_count` | integer (int4) | YES |  |
| `global_cod` | double precision (float8) | YES |  |
| `global_prd` | double precision (float8) | YES |  |
| `global_prb` | double precision (float8) | YES |  |
| `global_r2` | double precision (float8) | YES |  |
| `global_rmse` | double precision (float8) | YES |  |
| `diagnostics_path` | character varying(500) (varchar) | NO |  |
| `run_id` | character varying(100) (varchar) | NO |  |
| `notes` | text (text) | NO |  |
| `starred` | boolean (bool) | NO |  |
| `tags` | jsonb (jsonb) | NO |  |
| `baseline_run_id` | uuid (uuid) | YES |  |

### Foreign Keys

- `baseline_run_id` → `public.openskagit_experimentrun.id`

### Indexes

- `openskagit_experimentrun_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_experimentrun_pkey ON public.openskagit_experimentrun USING btree (id)
  ```
- `openskagit__starred_d942b3_idx`
  ```sql
  CREATE INDEX openskagit__starred_d942b3_idx ON public.openskagit_experimentrun USING btree (starred, created_at DESC)
  ```
- `openskagit__status_10a108_idx`
  ```sql
  CREATE INDEX openskagit__status_10a108_idx ON public.openskagit_experimentrun USING btree (status, created_at DESC)
  ```
- `openskagit_experimentrun_baseline_run_id_a88efe6b`
  ```sql
  CREATE INDEX openskagit_experimentrun_baseline_run_id_a88efe6b ON public.openskagit_experimentrun USING btree (baseline_run_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_lidartile` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `geom` | geometry(Polygon,2926) (geometry) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `last_processed` | timestamp with time zone (timestamptz) | YES |  |

### Indexes

- `openskagit_lidartile_geom_8d07f8d1_id`
  ```sql
  CREATE INDEX openskagit_lidartile_geom_8d07f8d1_id ON public.openskagit_lidartile USING gist (geom)
  ```
- `openskagit_lidartile_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_lidartile_pkey ON public.openskagit_lidartile USING btree (id)
  ```
- `openskagit__geom_d2e88a_gist`
  ```sql
  CREATE INDEX openskagit__geom_d2e88a_gist ON public.openskagit_lidartile USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 132570 |
| `geom` | 01030000206E0B000001000000050000004A302D96E6FC314160CE2F2D778121414A302D96E6FC314160CE2F2D478921414A302D96CE00324160CE2F2D478921414A302D96CE00324160CE2F2D778... |
| `created_at` | 2025-12-09 19:17:06.087766+00:00 |
| `last_processed` | 2025-12-09 22:07:34.916423+00:00 |

---

## `public.openskagit_lidartile_parcels` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO |  |
| `lidartile_id` | integer (int4) | NO |  |
| `masterparcel_id` | character varying(20) (varchar) | NO |  |

### Foreign Keys

- `lidartile_id` → `public.openskagit_lidartile.id`
- `masterparcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `openskagit_lidartile_parcels_masterparcel_id_50d67b80`
  ```sql
  CREATE INDEX openskagit_lidartile_parcels_masterparcel_id_50d67b80 ON public.openskagit_lidartile_parcels USING btree (masterparcel_id)
  ```
- `openskagit_lidartile_parcels_lidartile_id_2f91b6b9`
  ```sql
  CREATE INDEX openskagit_lidartile_parcels_lidartile_id_2f91b6b9 ON public.openskagit_lidartile_parcels USING btree (lidartile_id)
  ```
- `openskagit_lidartile_parcels_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_lidartile_parcels_pkey ON public.openskagit_lidartile_parcels USING btree (id)
  ```
- `openskagit_lidartile_par_lidartile_id_masterparce_e4df3442_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_lidartile_par_lidartile_id_masterparce_e4df3442_uniq ON public.openskagit_lidartile_parcels USING btree (lidartile_id, masterparcel_id)
  ```
- `openskagit_lidartile_parcels_masterparcel_id_50d67b80_like`
  ```sql
  CREATE INDEX openskagit_lidartile_parcels_masterparcel_id_50d67b80_like ON public.openskagit_lidartile_parcels USING btree (masterparcel_id varchar_pattern_ops)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_neighborhoodgeom` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom_3857` (MULTIPOLYGON, SRID 3857)
- `geom_4326` (MULTIPOLYGON, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `code` | character varying(20) (varchar) | NO |  |
| `name` | character varying(100) (varchar) | NO |  |
| `geom_3857` | geometry(MultiPolygon,3857) (geometry) | NO |  |
| `geom_4326` | geometry(MultiPolygon,4326) (geometry) | NO |  |

### Indexes

- `openskagit_neighborhoodgeom_code_6ec6533f_like`
  ```sql
  CREATE INDEX openskagit_neighborhoodgeom_code_6ec6533f_like ON public.openskagit_neighborhoodgeom USING btree (code varchar_pattern_ops)
  ```
- `openskagit_neighborhoodgeom_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodgeom_pkey ON public.openskagit_neighborhoodgeom USING btree (id)
  ```
- `openskagit_neighborhoodgeom_code_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodgeom_code_key ON public.openskagit_neighborhoodgeom USING btree (code)
  ```
- `openskagit_neighborhoodgeom_geom_4326_1173d657_id`
  ```sql
  CREATE INDEX openskagit_neighborhoodgeom_geom_4326_1173d657_id ON public.openskagit_neighborhoodgeom USING gist (geom_4326)
  ```
- `openskagit_neighborhoodgeom_geom_3857_ccca74e2_id`
  ```sql
  CREATE INDEX openskagit_neighborhoodgeom_geom_3857_ccca74e2_id ON public.openskagit_neighborhoodgeom USING gist (geom_3857)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 69 |
| `code` | 6M14SW |
| `name` |  |
| `geom_3857` | 0106000020110F00000100000001030000000100000007000000DC69EF8CECF069C1ACFAFD5B9583574122E7B5AC77F569C1EB8BAB49F5955741D835EB2DEEF469C1DA9BCB963F9D5741A010EAF69... |
| `geom_4326` | 0106000020E61000000100000001030000000100000007000000A10D2DCF498B5EC08ED4B09CDC2B4840B2996351A3905EC068C036EA393A4840C02EEE6C01905EC0E4A6B4A6EA3F4840BFAEA6E99... |

---

## `public.openskagit_neighborhoodmetrics` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `neighborhood_code` | character varying(20) (varchar) | NO |  |
| `year` | integer (int4) | NO |  |
| `sales_ratio` | double precision (float8) | YES |  |
| `median_ratio` | double precision (float8) | YES |  |
| `cod` | double precision (float8) | YES |  |
| `prd` | double precision (float8) | YES |  |
| `sample_size` | integer (int4) | NO |  |
| `reliability` | character varying(20) (varchar) | NO |  |
| `computed_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_neighborhoodmetrics_neighborhood_code_089beb6a_like`
  ```sql
  CREATE INDEX openskagit_neighborhoodmetrics_neighborhood_code_089beb6a_like ON public.openskagit_neighborhoodmetrics USING btree (neighborhood_code varchar_pattern_ops)
  ```
- `openskagit_neighborhoodmetrics_neighborhood_code_089beb6a`
  ```sql
  CREATE INDEX openskagit_neighborhoodmetrics_neighborhood_code_089beb6a ON public.openskagit_neighborhoodmetrics USING btree (neighborhood_code)
  ```
- `openskagit_neighborhoodmetrics_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodmetrics_pkey ON public.openskagit_neighborhoodmetrics USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 9 |
| `neighborhood_code` | 20LCPLEAS |
| `year` | 2025 |
| `sales_ratio` | 91.29766414141413 |
| `median_ratio` | 0.87775 |
| `cod` | 5.5961926298012825 |
| `prd` | 0.9848966379097958 |
| `sample_size` | 6 |
| `reliability` | Moderate |
| `computed_at` | 2025-11-04 18:10:19.880471+00:00 |

---

## `public.openskagit_neighborhoodprofile` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `hood_id` | character varying(20) (varchar) | NO |  |
| `name` | character varying(200) (varchar) | YES |  |
| `city` | character varying(50) (varchar) | YES |  |
| `json_data` | jsonb (jsonb) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `ai_summary` | text (text) | YES |  |

### Indexes

- `openskagit_neighborhoodprofile_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodprofile_pkey ON public.openskagit_neighborhoodprofile USING btree (id)
  ```
- `openskagit_neighborhoodprofile_hood_id_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodprofile_hood_id_key ON public.openskagit_neighborhoodprofile USING btree (hood_id)
  ```
- `openskagit_neighborhoodprofile_hood_id_5ad1cc14_like`
  ```sql
  CREATE INDEX openskagit_neighborhoodprofile_hood_id_5ad1cc14_like ON public.openskagit_neighborhoodprofile USING btree (hood_id varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `hood_id` | 6O14LACC |
| `name` | NULL |
| `city` | NULL |
| `json_data` | {"sales": {}, "census": {}, "garage": {"median_sqft": 0.0}, "styles": {"DOUBLE WIDE": 2, "SINGLE FAMILY RESIDENCE": 2, "COMMERCIAL REAL PROPERTY": 22}, "lot_... |
| `updated_at` | 2025-11-18 23:57:02.414649+00:00 |
| `ai_summary` | NULL |

---

## `public.openskagit_neighborhoodtrend` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `hood_id` | character varying(20) (varchar) | NO |  |
| `value_year` | integer (int4) | NO |  |
| `median_land_market` | integer (int4) | YES |  |
| `median_building` | integer (int4) | YES |  |
| `median_market_total` | integer (int4) | YES |  |
| `median_tax_amount` | integer (int4) | YES |  |
| `yoy_change_land` | double precision (float8) | YES |  |
| `yoy_change_building` | double precision (float8) | YES |  |
| `yoy_change_total` | double precision (float8) | YES |  |
| `yoy_change_tax` | double precision (float8) | YES |  |
| `stability_score` | double precision (float8) | YES |  |
| `boom_bust_flag` | character varying(20) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_neighborhoodtrend_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodtrend_pkey ON public.openskagit_neighborhoodtrend USING btree (id)
  ```
- `openskagit_neighborhoodtrend_hood_id_a81d2a29_like`
  ```sql
  CREATE INDEX openskagit_neighborhoodtrend_hood_id_a81d2a29_like ON public.openskagit_neighborhoodtrend USING btree (hood_id varchar_pattern_ops)
  ```
- `openskagit__hood_id_52cf7e_idx`
  ```sql
  CREATE INDEX openskagit__hood_id_52cf7e_idx ON public.openskagit_neighborhoodtrend USING btree (hood_id, value_year)
  ```
- `openskagit_neighborhoodtrend_hood_id_a81d2a29`
  ```sql
  CREATE INDEX openskagit_neighborhoodtrend_hood_id_a81d2a29 ON public.openskagit_neighborhoodtrend USING btree (hood_id)
  ```
- `openskagit_neighborhoodtrend_value_year_3e21099c`
  ```sql
  CREATE INDEX openskagit_neighborhoodtrend_value_year_3e21099c ON public.openskagit_neighborhoodtrend USING btree (value_year)
  ```
- `openskagit_neighborhoodtrend_hood_id_value_year_b17e368b_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_neighborhoodtrend_hood_id_value_year_b17e368b_uniq ON public.openskagit_neighborhoodtrend USING btree (hood_id, value_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 452 |
| `hood_id` | 20SWNSKAGT |
| `value_year` | 1991 |
| `median_land_market` | 10100 |
| `median_building` | 27100 |
| `median_market_total` | 22550 |
| `median_tax_amount` | 237 |
| `yoy_change_land` | NULL |
| `yoy_change_building` | NULL |
| `yoy_change_total` | NULL |
| `yoy_change_tax` | NULL |
| `stability_score` | 80.62403864288544 |
| `boom_bust_flag` | steady |
| `created_at` | 2025-11-21 15:50:05.471015+00:00 |
| `updated_at` | 2025-11-21 15:50:05.471073+00:00 |

---

## `public.openskagit_parcelgeometry` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom_2926_valid` (MULTIPOLYGON, SRID 2926)
- `geom` (MULTIPOLYGON, SRID 3857)
- `geom_backup` (GEOMETRY, SRID 3857)
- `geom_2926` (MULTIPOLYGON, SRID 2926)
- `centroid_geog` (POINT, SRID 4326)
- `centroid_2926` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `latitude` | double precision (float8) | YES |  |
| `longitude` | double precision (float8) | YES |  |
| `geom` | geometry(MultiPolygon,3857) (geometry) | YES |  |
| `embedding` | vector(384) (vector) | YES |  |
| `centroid_geog` | geometry(Point,4326) (geometry) | YES |  |
| `elev` | double precision (float8) | YES |  |
| `slope` | double precision (float8) | YES |  |
| `aspect` | double precision (float8) | YES |  |
| `aspect_dir` | text (text) | YES |  |
| `dist_major_road` | double precision (float8) | YES |  |
| `dist_floodway` | double precision (float8) | YES |  |
| `dist_minor_road` | double precision (float8) | YES |  |
| `dist_city_center` | double precision (float8) | YES |  |
| `dist_school` | double precision (float8) | YES |  |
| `dist_park` | double precision (float8) | YES |  |
| `dist_supermarket` | double precision (float8) | YES |  |
| `dist_hospital` | double precision (float8) | YES |  |
| `dist_fire_station` | double precision (float8) | YES |  |
| `dist_trailhead` | double precision (float8) | YES |  |
| `geom_backup` | geometry(Geometry,3857) (geometry) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | YES |  |
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `centroid_2926` | geometry(Point,2926) (geometry) | YES |  |
| `geom_2926_valid` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `openskagit_parcelgeometry_geom_backup_81aaabed_id`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_geom_backup_81aaabed_id ON public.openskagit_parcelgeometry USING gist (geom_backup)
  ```
- `idx_pg_geom_valid`
  ```sql
  CREATE INDEX idx_pg_geom_valid ON public.openskagit_parcelgeometry USING gist (geom_2926_valid)
  ```
- `idx_parcelgeometry_centroid`
  ```sql
  CREATE INDEX idx_parcelgeometry_centroid ON public.openskagit_parcelgeometry USING gist (centroid_2926)
  ```
- `openskagit_parcelgeometry_geom_2926_gix`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_geom_2926_gix ON public.openskagit_parcelgeometry USING gist (geom_2926)
  ```
- `openskagit__centroi_0c7376_gist`
  ```sql
  CREATE INDEX openskagit__centroi_0c7376_gist ON public.openskagit_parcelgeometry USING gist (centroid_geog)
  ```
- `openskagit_parcelgeometry_centroid_geog_5726480f_id`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_centroid_geog_5726480f_id ON public.openskagit_parcelgeometry USING gist (centroid_geog)
  ```
- `openskagit__geom_29_277639_gist`
  ```sql
  CREATE INDEX openskagit__geom_29_277639_gist ON public.openskagit_parcelgeometry USING gist (geom_2926)
  ```
- `openskagit_parcelgeometry_geom_2926_ed9b9dd9_id`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_geom_2926_ed9b9dd9_id ON public.openskagit_parcelgeometry USING gist (geom_2926)
  ```
- `openskagit__geom_05e325_gist`
  ```sql
  CREATE INDEX openskagit__geom_05e325_gist ON public.openskagit_parcelgeometry USING gist (geom)
  ```
- `openskagit_parcelgeometry_centroid_2926_gix`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_centroid_2926_gix ON public.openskagit_parcelgeometry USING gist (centroid_2926)
  ```
- `idx_parcel_geom_valid`
  ```sql
  CREATE INDEX idx_parcel_geom_valid ON public.openskagit_parcelgeometry USING gist (geom_2926_valid)
  ```
- `idx_parcel_geom_2926`
  ```sql
  CREATE INDEX idx_parcel_geom_2926 ON public.openskagit_parcelgeometry USING gist (geom_2926)
  ```
- `openskagit_parcelgeometry_centroid_2926_gist`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_centroid_2926_gist ON public.openskagit_parcelgeometry USING gist (centroid_2926)
  ```
- `openskagit_parcelgeometry_geom_368295ec_id`
  ```sql
  CREATE INDEX openskagit_parcelgeometry_geom_368295ec_id ON public.openskagit_parcelgeometry USING gist (geom)
  ```
- `openskagit_parcelgeometry_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcelgeometry_pkey ON public.openskagit_parcelgeometry USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 119627 |
| `latitude` | NULL |
| `longitude` | NULL |
| `geom` | NULL |
| `embedding` | NULL |
| `centroid_geog` | NULL |
| `elev` | 84.72625732421875 |
| `slope` | 0.2721506655216217 |
| `aspect` | 264.00927734375 |
| `aspect_dir` | W |
| `dist_major_road` | NULL |
| `dist_floodway` | NULL |
| `dist_minor_road` | NULL |
| `dist_city_center` | NULL |
| `dist_school` | NULL |
| `dist_park` | NULL |
| `dist_supermarket` | NULL |
| `dist_hospital` | NULL |
| `dist_fire_station` | NULL |
| `dist_trailhead` | NULL |
| `geom_backup` | NULL |
| `geom_2926` | 01060000206E0B0000010000000103000000010000000900000089BA64ADDDD8354164123199F4E82041CE4075C5DBD835410FE712D45AE82041E11ABDC6ABD835418AEAEF385CE82041969269C38... |
| `parcel_id` | P44467 |
| `centroid_2926` | 01010000206E0B00003CCBEF4F24D8354106B84A7DA4E72041 |
| `geom_2926_valid` | NULL |

---

## `public.openskagit_parcelhistory` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `parcel_number` | character varying(20) (varchar) | NO |  |
| `rows` | jsonb (jsonb) | NO |  |
| `scraped_at` | timestamp with time zone (timestamptz) | NO |  |
| `neighborhood_code` | character varying(20) (varchar) | YES |  |
| `roll_year` | integer (int4) | YES |  |
| `taxes` | jsonb (jsonb) | NO |  |

### Indexes

- `openskagit_parcelhistory_neighborhood_code_91a11ba2`
  ```sql
  CREATE INDEX openskagit_parcelhistory_neighborhood_code_91a11ba2 ON public.openskagit_parcelhistory USING btree (neighborhood_code)
  ```
- `openskagit_parcelhistory_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcelhistory_pkey ON public.openskagit_parcelhistory USING btree (id)
  ```
- `openskagit_parcelhistory_parcel_number_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcelhistory_parcel_number_key ON public.openskagit_parcelhistory USING btree (parcel_number)
  ```
- `openskagit_parcelhistory_parcel_number_c4377126_like`
  ```sql
  CREATE INDEX openskagit_parcelhistory_parcel_number_c4377126_like ON public.openskagit_parcelhistory USING btree (parcel_number varchar_pattern_ops)
  ```
- `openskagit_parcelhistory_roll_year_d9004019`
  ```sql
  CREATE INDEX openskagit_parcelhistory_roll_year_d9004019 ON public.openskagit_parcelhistory USING btree (roll_year)
  ```
- `openskagit_parcelhistory_neighborhood_code_91a11ba2_like`
  ```sql
  CREATE INDEX openskagit_parcelhistory_neighborhood_code_91a11ba2_like ON public.openskagit_parcelhistory USING btree (neighborhood_code varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 60270 |
| `parcel_number` | P59315 |
| `rows` | [{"TAX": "$9,857.73", "BUILDING": "$920,500.00", "ParcelID": "P59315", "TAX YEAR": "2025", "VALUE YEAR": "2024", "LAND MARKET": "$385,000.00", "MARKET TOTAL"... |
| `scraped_at` | 2026-01-24 11:16:49.955304+00:00 |
| `neighborhood_code` | NULL |
| `roll_year` | NULL |
| `taxes` | {"summary": {"Levy Code": "0900", "Levy Rate": "7.8254", "General Tax": "$10,451.63", "Taxable Value": "$1,335,600.00", "2026 Total Due": "$10,456.63", "2026... |

---

## `public.openskagit_parcelintent` (t)

**Primary Key:** key

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `key` | character varying(64) (varchar) | NO |  |
| `label` | character varying(255) (varchar) | NO |  |
| `description` | text (text) | NO |  |
| `triggers_law_classes` | jsonb (jsonb) | NO |  |
| `external_authorities` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_parcelintent_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcelintent_pkey ON public.openskagit_parcelintent USING btree (key)
  ```
- `openskagit_parcelintent_key_53711169_like`
  ```sql
  CREATE INDEX openskagit_parcelintent_key_53711169_like ON public.openskagit_parcelintent USING btree (key varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `key` | new_residential_dwelling |
| `label` | New Residential Dwelling |
| `description` | Construct a new residential dwelling unit. |
| `triggers_law_classes` | ["use_permission", "dimensional_standard", "overlay_constraint", "procedural_requirement"] |
| `external_authorities` | ["building", "health", "fire"] |
| `created_at` | 2026-01-21 17:04:28.655804+00:00 |

---

## `public.openskagit_parcellidarstats` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `min_elevation_ft` | double precision (float8) | NO |  |
| `max_elevation_ft` | double precision (float8) | NO |  |
| `mean_terrain_z_ft` | double precision (float8) | NO |  |
| `terrain_roughness` | double precision (float8) | NO |  |
| `est_canopy_height_ft` | double precision (float8) | NO |  |
| `canopy_cover_percent` | double precision (float8) | YES |  |
| `structure_footprint_sqft` | double precision (float8) | YES |  |
| `max_structure_height_ft` | double precision (float8) | YES |  |
| `mean_intensity` | double precision (float8) | YES |  |
| `slope_hazard_area_sqft` | double precision (float8) | YES |  |
| `point_density_sqft` | double precision (float8) | NO |  |
| `last_calculated` | timestamp with time zone (timestamptz) | NO |  |
| `parcel_id` | bigint (int8) | NO |  |

### Foreign Keys

- `parcel_id` → `public.parcel.id`

### Indexes

- `openskagit_parcellidarstats_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcellidarstats_pkey ON public.openskagit_parcellidarstats USING btree (id)
  ```
- `openskagit_parcellidarstats_parcel_id_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcellidarstats_parcel_id_key ON public.openskagit_parcellidarstats USING btree (parcel_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_parcelwaterfacts` (t)

**Primary Key:** parcel_id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `public_water_available` | boolean (bool) | YES |  |
| `public_water_system_id` | text (text) | YES |  |
| `in_instream_flow_rule_area` | boolean (bool) | YES |  |
| `instream_flow_rule_name` | text (text) | YES |  |
| `low_flow_stream_area` | boolean (bool) | YES |  |
| `in_wellhead_protection_area` | boolean (bool) | YES |  |
| `surface_water_limited` | boolean (bool) | YES |  |
| `water_feasibility_rating` | text (text) | YES |  |
| `nearest_well_distance_m` | double precision (float8) | YES |  |
| `nearest_well_id` | text (text) | YES |  |
| `nearest_well_depth` | double precision (float8) | YES |  |
| `nearest_well_yield` | double precision (float8) | YES |  |
| `has_pou_water_right` | boolean (bool) | YES |  |
| `pou_right_numbers` | text[] (_text) | YES |  |
| `nearest_diversion_right` | text (text) | YES |  |
| `nearest_diversion_distance_m` | double precision (float8) | YES |  |
| `nearest_right_priority_date` | date (date) | YES |  |
| `aquifer_yield_category` | text (text) | YES |  |
| `well_drilling_feasible` | boolean (bool) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | YES |  |
| `updated_at` | timestamp with time zone (timestamptz) | YES |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `openskagit_parcelwaterfacts_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_parcelwaterfacts_pkey ON public.openskagit_parcelwaterfacts USING btree (parcel_id)
  ```
- `openskagit_parcelwaterfacts_public_water_available_idx`
  ```sql
  CREATE INDEX openskagit_parcelwaterfacts_public_water_available_idx ON public.openskagit_parcelwaterfacts USING btree (public_water_available)
  ```
- `openskagit_parcelwaterfacts_has_pou_water_right_idx`
  ```sql
  CREATE INDEX openskagit_parcelwaterfacts_has_pou_water_right_idx ON public.openskagit_parcelwaterfacts USING btree (has_pou_water_right)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P123982 |
| `public_water_available` | True |
| `public_water_system_id` | 79500 |
| `in_instream_flow_rule_area` | NULL |
| `instream_flow_rule_name` | NULL |
| `low_flow_stream_area` | NULL |
| `in_wellhead_protection_area` | NULL |
| `surface_water_limited` | NULL |
| `water_feasibility_rating` | NULL |
| `nearest_well_distance_m` | 267.16974099878854 |
| `nearest_well_id` | 83755 |
| `nearest_well_depth` | 151.0 |
| `nearest_well_yield` | NULL |
| `has_pou_water_right` | NULL |
| `pou_right_numbers` | NULL |
| `nearest_diversion_right` | NULL |
| `nearest_diversion_distance_m` | NULL |
| `nearest_right_priority_date` | NULL |
| `aquifer_yield_category` | UNKNOWN |
| `well_drilling_feasible` | NULL |
| `created_at` | 2026-01-18 15:09:20.535673+00:00 |
| `updated_at` | 2026-01-18 15:09:20.535673+00:00 |

---

## `public.openskagit_permittype` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `category` | character varying(255) (varchar) | NO |  |
| `description` | text (text) | NO |  |

### Indexes

- `openskagit_permittype_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_permittype_pkey ON public.openskagit_permittype USING btree (id)
  ```
- `openskagit_permittype_name_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_permittype_name_key ON public.openskagit_permittype USING btree (name)
  ```
- `openskagit_permittype_name_8c1b5da2_like`
  ```sql
  CREATE INDEX openskagit_permittype_name_8c1b5da2_like ON public.openskagit_permittype USING btree (name varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `name` | Single Family Residence |
| `category` | unknown |
| `description` |  |

---

## `public.openskagit_permittypeintentmap` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `intent_id` | character varying(64) (varchar) | NO |  |
| `permit_type_id` | bigint (int8) | NO |  |

### Foreign Keys

- `intent_id` → `public.openskagit_parcelintent.key`
- `permit_type_id` → `public.openskagit_permittype.id`

### Indexes

- `openskagit_permittypeintentmap_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_permittypeintentmap_pkey ON public.openskagit_permittypeintentmap USING btree (id)
  ```
- `openskagit_permittypeintentmap_intent_id_f19a444d_like`
  ```sql
  CREATE INDEX openskagit_permittypeintentmap_intent_id_f19a444d_like ON public.openskagit_permittypeintentmap USING btree (intent_id varchar_pattern_ops)
  ```
- `openskagit_permittypeintentmap_intent_id_f19a444d`
  ```sql
  CREATE INDEX openskagit_permittypeintentmap_intent_id_f19a444d ON public.openskagit_permittypeintentmap USING btree (intent_id)
  ```
- `openskagit_permittypeint_permit_type_id_intent_id_7db2e8b4_uniq`
  ```sql
  CREATE UNIQUE INDEX openskagit_permittypeint_permit_type_id_intent_id_7db2e8b4_uniq ON public.openskagit_permittypeintentmap USING btree (permit_type_id, intent_id)
  ```
- `openskagit_permittypeintentmap_permit_type_id_ecdb023a`
  ```sql
  CREATE INDEX openskagit_permittypeintentmap_permit_type_id_ecdb023a ON public.openskagit_permittypeintentmap USING btree (permit_type_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `intent_id` | new_residential_dwelling |
| `permit_type_id` | 1 |

---

## `public.openskagit_referencedataimportlog` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `dataset_name` | character varying(100) (varchar) | NO |  |
| `source_path` | character varying(500) (varchar) | NO |  |
| `table_name` | character varying(100) (varchar) | NO |  |
| `success` | boolean (bool) | NO |  |
| `error_message` | text (text) | YES |  |
| `row_count` | integer (int4) | NO |  |
| `srid` | integer (int4) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_referencedataimportlog_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_referencedataimportlog_pkey ON public.openskagit_referencedataimportlog USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_regressionadjustment` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `variable` | character varying(100) (varchar) | NO |  |
| `adjustment_pct` | double precision (float8) | NO |  |
| `model_version` | character varying(50) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_regressionadjustment_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_regressionadjustment_pkey ON public.openskagit_regressionadjustment USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 218 |
| `variable` | bathrooms |
| `adjustment_pct` | 6.3851 |
| `model_version` | 2025Q4 \| AdjR2=0.850 |
| `created_at` | 2025-11-04 23:38:01.314752+00:00 |

---

## `public.openskagit_surveyconversation` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `conversation_id` | uuid (uuid) | NO |  |
| `status` | character varying(16) (varchar) | NO |  |
| `question_count` | integer (int4) | NO |  |
| `implicit_insights` | jsonb (jsonb) | NO |  |
| `metadata` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_surveyconversation_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_surveyconversation_pkey ON public.openskagit_surveyconversation USING btree (id)
  ```
- `openskagit_surveyconversation_conversation_id_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_surveyconversation_conversation_id_key ON public.openskagit_surveyconversation USING btree (conversation_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `conversation_id` | 2e45c94e-f640-4a31-8c5e-3e1696a0cdf9 |
| `status` | open |
| `question_count` | 1 |
| `implicit_insights` | [] |
| `metadata` | {"asked": ["role"], "last_topic": "role", "still_needed": ["Frustrations", "Missing support", "Feature interests", "Property & development", "Business & rest... |
| `created_at` | 2026-01-06 18:30:48.152725+00:00 |
| `updated_at` | 2026-01-06 18:30:48.161076+00:00 |

---

## `public.openskagit_surveyinteraction` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `role` | character varying(8) (varchar) | NO |  |
| `question_id` | character varying(64) (varchar) | YES |  |
| `question_label` | text (text) | NO |  |
| `topic` | character varying(64) (varchar) | NO |  |
| `content` | text (text) | NO |  |
| `metadata` | jsonb (jsonb) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `conversation_id` | bigint (int8) | NO |  |

### Foreign Keys

- `conversation_id` → `public.openskagit_surveyconversation.id`

### Indexes

- `openskagit_surveyinteraction_conversation_id_bfaddf47`
  ```sql
  CREATE INDEX openskagit_surveyinteraction_conversation_id_bfaddf47 ON public.openskagit_surveyinteraction USING btree (conversation_id)
  ```
- `openskagit_surveyinteraction_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_surveyinteraction_pkey ON public.openskagit_surveyinteraction USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `role` | user |
| `question_id` | role |
| `question_label` | Role or relationship to Skagit |
| `topic` | role |
| `content` | Teest |
| `metadata` | {"asked": ["role"], "implicit": [], "still_needed": ["Frustrations", "Missing support", "Feature interests", "Property & development", "Business & restaurant... |
| `created_at` | 2026-01-06 18:30:48.168521+00:00 |
| `conversation_id` | 1 |

---

## `public.openskagit_taxationwithoutrepresentation` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `tax_year` | integer (int4) | YES |  |
| `tax_amount` | bigint (int8) | YES |  |
| `ballots_cast` | integer (int4) | NO |  |
| `flag_reason` | character varying(255) (varchar) | NO |  |
| `metadata` | jsonb (jsonb) | NO |  |
| `generated_at` | timestamp with time zone (timestamptz) | NO |  |
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `election_id` | bigint (int8) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`
- `election_id` → `public.openskagit_voterelection.id`

### Indexes

- `openskagit_taxationwithoutrepresentation_parcel_id_f53431af`
  ```sql
  CREATE INDEX openskagit_taxationwithoutrepresentation_parcel_id_f53431af ON public.openskagit_taxationwithoutrepresentation USING btree (parcel_id)
  ```
- `unique_taxation_report_per_parcel_election`
  ```sql
  CREATE UNIQUE INDEX unique_taxation_report_per_parcel_election ON public.openskagit_taxationwithoutrepresentation USING btree (parcel_id, election_id)
  ```
- `openskagit_taxationwithoutrepresentation_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_taxationwithoutrepresentation_pkey ON public.openskagit_taxationwithoutrepresentation USING btree (id)
  ```
- `openskagit_taxationwithoutrepresentation_election_id_6b1ab0c7`
  ```sql
  CREATE INDEX openskagit_taxationwithoutrepresentation_election_id_6b1ab0c7 ON public.openskagit_taxationwithoutrepresentation USING btree (election_id)
  ```
- `openskagit_taxationwitho_parcel_id_f53431af_like`
  ```sql
  CREATE INDEX openskagit_taxationwitho_parcel_id_f53431af_like ON public.openskagit_taxationwithoutrepresentation USING btree (parcel_id varchar_pattern_ops)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_taxcodearea` (t)

**Primary Key:** code

**Geometry Columns:**
- `geom` (GEOMETRY, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `code` | character varying(64) (varchar) | NO |  |
| `county_name` | character varying(64) (varchar) | YES |  |
| `levy_rate_total` | double precision (float8) | YES |  |
| `geom` | geometry(Geometry,4326) (geometry) | NO |  |

### Indexes

- `openskagit_taxcodearea_code_5a337982_like`
  ```sql
  CREATE INDEX openskagit_taxcodearea_code_5a337982_like ON public.openskagit_taxcodearea USING btree (code varchar_pattern_ops)
  ```
- `openskagit_taxcodearea_geom_96e8622c_id`
  ```sql
  CREATE INDEX openskagit_taxcodearea_geom_96e8622c_id ON public.openskagit_taxcodearea USING gist (geom)
  ```
- `openskagit__code_b65b0a_idx`
  ```sql
  CREATE INDEX openskagit__code_b65b0a_idx ON public.openskagit_taxcodearea USING btree (code)
  ```
- `openskagit_taxcodearea_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_taxcodearea_pkey ON public.openskagit_taxcodearea USING btree (code)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_taxingdistrict` (t)

**Primary Key:** district_code

**Geometry Columns:**
- `geom` (GEOMETRY, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `district_type` | character varying(32) (varchar) | NO |  |
| `district_code` | character varying(64) (varchar) | NO |  |
| `name` | character varying(128) (varchar) | NO |  |
| `levy_rate` | double precision (float8) | YES |  |
| `geom` | geometry(Geometry,4326) (geometry) | NO |  |

### Indexes

- `openskagit_taxingdistrict_geom_ecd781bd_id`
  ```sql
  CREATE INDEX openskagit_taxingdistrict_geom_ecd781bd_id ON public.openskagit_taxingdistrict USING gist (geom)
  ```
- `openskagit_taxingdistrict_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_taxingdistrict_pkey ON public.openskagit_taxingdistrict USING btree (district_code)
  ```
- `openskagit_taxingdistrict_district_code_2b0395e3_like`
  ```sql
  CREATE INDEX openskagit_taxingdistrict_district_code_2b0395e3_like ON public.openskagit_taxingdistrict USING btree (district_code varchar_pattern_ops)
  ```
- `openskagit__distric_cdc703_idx`
  ```sql
  CREATE INDEX openskagit__distric_cdc703_idx ON public.openskagit_taxingdistrict USING btree (district_type, district_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `district_type` | unknown |
| `district_code` | unknown_20.0_12 |
| `name` | 12 |
| `levy_rate` | NULL |
| `geom` | 0106000020E610000002000000010300000002000000A3000000E8B2BCE04D435EC0962605B073EB464013565A184E435EC0E19A5280FEEA4640001EF64F4E435EC03F809F5089EA4640DA2328BF4... |

---

## `public.openskagit_voterelection` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `category` | character varying(50) (varchar) | NO |  |
| `election_date` | date (date) | NO |  |
| `slug` | character varying(255) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `unique_voter_election_name_date`
  ```sql
  CREATE UNIQUE INDEX unique_voter_election_name_date ON public.openskagit_voterelection USING btree (name, election_date)
  ```
- `openskagit_voterelection_slug_2b9c1458_like`
  ```sql
  CREATE INDEX openskagit_voterelection_slug_2b9c1458_like ON public.openskagit_voterelection USING btree (slug varchar_pattern_ops)
  ```
- `openskagit_voterelection_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterelection_pkey ON public.openskagit_voterelection USING btree (id)
  ```
- `openskagit_voterelection_slug_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterelection_slug_key ON public.openskagit_voterelection USING btree (slug)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `name` | Presidential Primary |
| `category` | Presidential |
| `election_date` | 2024-03-12 |
| `slug` | presidential-primary-2024-03-12 |
| `created_at` | 2026-01-02 14:50:19.373065+00:00 |
| `updated_at` | 2026-01-02 14:50:19.373099+00:00 |

---

## `public.openskagit_voterparcelmatch` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `match_type` | character varying(50) (varchar) | NO |  |
| `confidence` | double precision (float8) | YES |  |
| `matched_at` | timestamp with time zone (timestamptz) | NO |  |
| `metadata` | jsonb (jsonb) | NO |  |
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `turnout_id` | bigint (int8) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`
- `turnout_id` → `public.openskagit_voterturnoutraw.id`

### Indexes

- `openskagit_voterparcelmatch_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterparcelmatch_pkey ON public.openskagit_voterparcelmatch USING btree (id)
  ```
- `openskagit_voterparcelmatch_parcel_id_69b6b440_like`
  ```sql
  CREATE INDEX openskagit_voterparcelmatch_parcel_id_69b6b440_like ON public.openskagit_voterparcelmatch USING btree (parcel_id varchar_pattern_ops)
  ```
- `openskagit_voterparcelmatch_parcel_id_69b6b440`
  ```sql
  CREATE INDEX openskagit_voterparcelmatch_parcel_id_69b6b440 ON public.openskagit_voterparcelmatch USING btree (parcel_id)
  ```
- `openskagit__parcel__00186f_idx`
  ```sql
  CREATE INDEX openskagit__parcel__00186f_idx ON public.openskagit_voterparcelmatch USING btree (parcel_id)
  ```
- `openskagit__match_t_8fa212_idx`
  ```sql
  CREATE INDEX openskagit__match_t_8fa212_idx ON public.openskagit_voterparcelmatch USING btree (match_type)
  ```
- `openskagit_voterparcelmatch_turnout_id_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterparcelmatch_turnout_id_key ON public.openskagit_voterparcelmatch USING btree (turnout_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_voterreturnlocation` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `name` | character varying(255) (varchar) | NO |  |
| `method` | character varying(100) (varchar) | NO |  |
| `normalized_name` | character varying(255) (varchar) | NO |  |
| `normalized_method` | character varying(100) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_voterreturnlocation_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterreturnlocation_pkey ON public.openskagit_voterreturnlocation USING btree (id)
  ```
- `openskagit_voterreturnlocation_normalized_name_dcf5b95b_like`
  ```sql
  CREATE INDEX openskagit_voterreturnlocation_normalized_name_dcf5b95b_like ON public.openskagit_voterreturnlocation USING btree (normalized_name varchar_pattern_ops)
  ```
- `unique_voter_return_location`
  ```sql
  CREATE UNIQUE INDEX unique_voter_return_location ON public.openskagit_voterreturnlocation USING btree (normalized_name, normalized_method)
  ```
- `openskagit_voterreturnlocation_normalized_name_dcf5b95b`
  ```sql
  CREATE INDEX openskagit_voterreturnlocation_normalized_name_dcf5b95b ON public.openskagit_voterreturnlocation USING btree (normalized_name)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `name` | Mail |
| `method` | Mail |
| `normalized_name` |  |
| `normalized_method` | MAIL |
| `created_at` | 2026-01-02 14:50:19.393053+00:00 |

---

## `public.openskagit_voterturnoutraw` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `ballot_id` | character varying(50) (varchar) | NO |  |
| `voter_id` | character varying(50) (varchar) | NO |  |
| `county` | character varying(50) (varchar) | NO |  |
| `first_name` | character varying(100) (varchar) | NO |  |
| `last_name` | character varying(100) (varchar) | NO |  |
| `gender` | character varying(10) (varchar) | NO |  |
| `ballot_status` | character varying(50) (varchar) | NO |  |
| `challenge_reason` | character varying(255) (varchar) | NO |  |
| `sent_date` | timestamp with time zone (timestamptz) | YES |  |
| `received_date` | timestamp with time zone (timestamptz) | YES |  |
| `address` | character varying(255) (varchar) | NO |  |
| `normalized_address` | character varying(255) (varchar) | NO |  |
| `is_po_box` | boolean (bool) | NO |  |
| `city` | character varying(100) (varchar) | NO |  |
| `state` | character varying(10) (varchar) | NO |  |
| `zip5` | character varying(5) (varchar) | NO |  |
| `zip4` | character varying(4) (varchar) | NO |  |
| `country` | character varying(50) (varchar) | NO |  |
| `split` | character varying(50) (varchar) | NO |  |
| `precinct` | character varying(100) (varchar) | NO |  |
| `normalized_precinct` | character varying(100) (varchar) | NO |  |
| `return_method` | character varying(100) (varchar) | NO |  |
| `return_location_name` | character varying(255) (varchar) | NO |  |
| `party` | character varying(20) (varchar) | NO |  |
| `source_file` | character varying(255) (varchar) | NO |  |
| `source_row` | integer (int4) | YES |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `election_id` | bigint (int8) | NO |  |
| `return_location_id` | bigint (int8) | YES |  |

### Foreign Keys

- `election_id` → `public.openskagit_voterelection.id`
- `return_location_id` → `public.openskagit_voterreturnlocation.id`

### Indexes

- `openskagit__precinc_249c8d_idx`
  ```sql
  CREATE INDEX openskagit__precinc_249c8d_idx ON public.openskagit_voterturnoutraw USING btree (precinct)
  ```
- `openskagit_voterturnoutraw_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_voterturnoutraw_pkey ON public.openskagit_voterturnoutraw USING btree (id)
  ```
- `openskagit__ballot__af30c9_idx`
  ```sql
  CREATE INDEX openskagit__ballot__af30c9_idx ON public.openskagit_voterturnoutraw USING btree (ballot_id, election_id)
  ```
- `openskagit__normali_4eaf15_idx`
  ```sql
  CREATE INDEX openskagit__normali_4eaf15_idx ON public.openskagit_voterturnoutraw USING btree (normalized_address)
  ```
- `unique_ballot_per_election`
  ```sql
  CREATE UNIQUE INDEX unique_ballot_per_election ON public.openskagit_voterturnoutraw USING btree (ballot_id, election_id)
  ```
- `openskagit_voterturnoutraw_return_location_id_50b5c5fd`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_return_location_id_50b5c5fd ON public.openskagit_voterturnoutraw USING btree (return_location_id)
  ```
- `openskagit_voterturnoutraw_election_id_40b45db1`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_election_id_40b45db1 ON public.openskagit_voterturnoutraw USING btree (election_id)
  ```
- `openskagit_voterturnoutraw_normalized_precinct_e1d9dcc7_like`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_normalized_precinct_e1d9dcc7_like ON public.openskagit_voterturnoutraw USING btree (normalized_precinct varchar_pattern_ops)
  ```
- `openskagit_voterturnoutraw_normalized_precinct_e1d9dcc7`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_normalized_precinct_e1d9dcc7 ON public.openskagit_voterturnoutraw USING btree (normalized_precinct)
  ```
- `openskagit_voterturnoutraw_normalized_address_4f069b05_like`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_normalized_address_4f069b05_like ON public.openskagit_voterturnoutraw USING btree (normalized_address varchar_pattern_ops)
  ```
- `openskagit_voterturnoutraw_normalized_address_4f069b05`
  ```sql
  CREATE INDEX openskagit_voterturnoutraw_normalized_address_4f069b05 ON public.openskagit_voterturnoutraw USING btree (normalized_address)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `ballot_id` | 138513225 |
| `voter_id` | 53684 |
| `county` | Skagit |
| `first_name` | CURTIS |
| `last_name` | SCHROEDER |
| `gender` | M |
| `ballot_status` | Accepted |
| `challenge_reason` |  |
| `sent_date` | 2024-01-26 00:00:00+00:00 |
| `received_date` | 2024-03-18 00:00:00+00:00 |
| `address` | 12183 BAYHILL DR |
| `normalized_address` | 12183 BAYHILL DR |
| `is_po_box` | False |
| `city` | BURLINGTON |
| `state` | WA |
| `zip5` | 98233 |
| `zip4` |  |
| `country` | USA |
| `split` | 159.02 |
| `precinct` | TERRACE |
| `normalized_precinct` | TERRACE |
| `return_method` | Mail |
| `return_location_name` |  |
| `party` |  |
| `source_file` | Skagit (5).csv |
| `source_row` | 28512 |
| `created_at` | 2026-01-02 14:50:19.719848+00:00 |
| `updated_at` | 2026-01-02 14:50:19.719868+00:00 |
| `election_id` | 1 |
| `return_location_id` | 1 |

---

## `public.openskagit_weeklybriefingsection` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `title` | character varying(120) (varchar) | NO |  |
| `summary` | text (text) | NO |  |
| `badge` | character varying(80) (varchar) | NO |  |
| `highlight` | character varying(80) (varchar) | NO |  |
| `order` | integer (int4) | NO |  |
| `template_id` | bigint (int8) | NO |  |

### Foreign Keys

- `template_id` → `public.openskagit_weeklybriefingtemplate.id`

### Indexes

- `openskagit_weeklybriefingsection_template_id_a8120762`
  ```sql
  CREATE INDEX openskagit_weeklybriefingsection_template_id_a8120762 ON public.openskagit_weeklybriefingsection USING btree (template_id)
  ```
- `openskagit_weeklybriefingsection_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_weeklybriefingsection_pkey ON public.openskagit_weeklybriefingsection USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `title` | Weekly data refresh |
| `summary` | Parcels, sales, and permit updates are pulled each Monday to keep you ahead of the latest county numbers. |
| `badge` | Updated |
| `highlight` | New every Monday |
| `order` | 0 |
| `template_id` | 1 |

---

## `public.openskagit_weeklybriefingsendlog` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `subject` | character varying(200) (varchar) | NO |  |
| `sent_count` | integer (int4) | NO |  |
| `error_count` | integer (int4) | NO |  |
| `error_snapshot` | text (text) | NO |  |
| `sent_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_weeklybriefingsendlog_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_weeklybriefingsendlog_pkey ON public.openskagit_weeklybriefingsendlog USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.openskagit_weeklybriefingsubscriber` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `email` | character varying(254) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_weeklybriefingsubscriber_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_weeklybriefingsubscriber_pkey ON public.openskagit_weeklybriefingsubscriber USING btree (id)
  ```
- `openskagit_weeklybriefingsubscriber_email_key`
  ```sql
  CREATE UNIQUE INDEX openskagit_weeklybriefingsubscriber_email_key ON public.openskagit_weeklybriefingsubscriber USING btree (email)
  ```
- `openskagit_weeklybriefingsubscriber_email_9ade2d40_like`
  ```sql
  CREATE INDEX openskagit_weeklybriefingsubscriber_email_9ade2d40_like ON public.openskagit_weeklybriefingsubscriber USING btree (email varchar_pattern_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `email` | ian.larsen.1976@gmail.com |
| `created_at` | 2026-01-12 15:40:10.247795+00:00 |

---

## `public.openskagit_weeklybriefingtemplate` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `subject` | character varying(200) (varchar) | NO |  |
| `preheader` | character varying(255) (varchar) | NO |  |
| `hero_title` | character varying(200) (varchar) | NO |  |
| `hero_lede` | text (text) | NO |  |
| `hero_stat_label` | character varying(100) (varchar) | NO |  |
| `hero_stat_value` | character varying(50) (varchar) | NO |  |
| `cta_label` | character varying(100) (varchar) | NO |  |
| `cta_url` | character varying(200) (varchar) | NO |  |
| `footer_note` | text (text) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `openskagit_weeklybriefingtemplate_pkey`
  ```sql
  CREATE UNIQUE INDEX openskagit_weeklybriefingtemplate_pkey ON public.openskagit_weeklybriefingtemplate USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `subject` | Weekly Briefing · OpenSkagit |
| `preheader` | County data, stories, and updates curated for you. |
| `hero_title` | Skagit County by the numbers |
| `hero_lede` | Fresh data, approachable context, and stories that help Skagit neighborhoods move forward. |
| `hero_stat_label` | County updates |
| `hero_stat_value` | Up next |
| `cta_label` | View the portal |
| `cta_url` | https://openskagit.com |
| `footer_note` | You are receiving this because you signed up for the OpenSkagit Weekly Briefing. |
| `updated_at` | 2026-01-12 16:01:21.863573+00:00 |

---

## `public.osm2pgsql_properties` (t)

**Primary Key:** property

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `property` | text (text) | NO |  |
| `value` | text (text) | NO |  |

### Indexes

- `osm2pgsql_properties_pkey`
  ```sql
  CREATE UNIQUE INDEX osm2pgsql_properties_pkey ON public.osm2pgsql_properties USING btree (property)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `property` | attributes |
| `value` | false |

---

## `public.owner_residency_by_neighborhood` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `neighborhood_code` | character varying (varchar) | YES |  |
| `residential_parcels` | bigint (int8) | YES |  |
| `owner_mailing_count` | bigint (int8) | YES |  |
| `owner_within_neighborhood_count` | bigint (int8) | YES |  |
| `owner_outside_neighborhood_count` | bigint (int8) | YES |  |
| `owner_outside_skagit_count` | bigint (int8) | YES |  |
| `owner_po_box_count` | bigint (int8) | YES |  |
| `owner_po_box_pct` | double precision (float8) | YES |  |

### Indexes

- `owner_residency_neighborhood_idx`
  ```sql
  CREATE UNIQUE INDEX owner_residency_neighborhood_idx ON public.owner_residency_by_neighborhood USING btree (neighborhood_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `neighborhood_code` | 22CCERIV |
| `residential_parcels` | 60 |
| `owner_mailing_count` | 60 |
| `owner_within_neighborhood_count` | 60 |
| `owner_outside_neighborhood_count` | 0 |
| `owner_outside_skagit_count` | 0 |
| `owner_po_box_count` | 0 |
| `owner_po_box_pct` | 0.0 |

---

## `public.parcel` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `parcel_number` | character varying(20) (varchar) | NO |  |
| `address` | character varying(255) (varchar) | YES |  |
| `neighborhood_code` | character varying(100) (varchar) | YES |  |
| `land_use_code` | character varying(100) (varchar) | YES |  |
| `property_type` | character varying(1) (varchar) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |
| `neighborhood_description` | character varying(255) (varchar) | YES |  |

### Indexes

- `idx_parcel_address_upper_trgm`
  ```sql
  CREATE INDEX idx_parcel_address_upper_trgm ON public.parcel USING gin (upper((address)::text) gin_trgm_ops)
  ```
- `idx_parcel_upper_parcel_number`
  ```sql
  CREATE INDEX idx_parcel_upper_parcel_number ON public.parcel USING btree (upper((parcel_number)::text))
  ```
- `parcel_property_type_a160f34f_like`
  ```sql
  CREATE INDEX parcel_property_type_a160f34f_like ON public.parcel USING btree (property_type varchar_pattern_ops)
  ```
- `parcel_property_type_a160f34f`
  ```sql
  CREATE INDEX parcel_property_type_a160f34f ON public.parcel USING btree (property_type)
  ```
- `parcel_parcel_number_23494c57_like`
  ```sql
  CREATE INDEX parcel_parcel_number_23494c57_like ON public.parcel USING btree (parcel_number varchar_pattern_ops)
  ```
- `parcel_parcel_number_key`
  ```sql
  CREATE UNIQUE INDEX parcel_parcel_number_key ON public.parcel USING btree (parcel_number)
  ```
- `parcel_pkey`
  ```sql
  CREATE UNIQUE INDEX parcel_pkey ON public.parcel USING btree (id)
  ```
- `parcel_land_use_code_35c86882_like`
  ```sql
  CREATE INDEX parcel_land_use_code_35c86882_like ON public.parcel USING btree (land_use_code varchar_pattern_ops)
  ```
- `parcel_neighborhood_code_fa50805d`
  ```sql
  CREATE INDEX parcel_neighborhood_code_fa50805d ON public.parcel USING btree (neighborhood_code)
  ```
- `parcel_neighborhood_code_fa50805d_like`
  ```sql
  CREATE INDEX parcel_neighborhood_code_fa50805d_like ON public.parcel USING btree (neighborhood_code varchar_pattern_ops)
  ```
- `parcel_land_use_code_35c86882`
  ```sql
  CREATE INDEX parcel_land_use_code_35c86882 ON public.parcel USING btree (land_use_code)
  ```
- `idx_parcel_address_trgm`
  ```sql
  CREATE INDEX idx_parcel_address_trgm ON public.parcel USING gin (address gin_trgm_ops)
  ```
- `idx_parcel_number_trgm`
  ```sql
  CREATE INDEX idx_parcel_number_trgm ON public.parcel USING gin (parcel_number gin_trgm_ops)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `parcel_number` | P100003 |
| `address` | 702 R AVENUE ANACORTES, WA 98221 |
| `neighborhood_code` | NULL |
| `land_use_code` | NULL |
| `property_type` | P |
| `created_at` | 2025-11-02 18:02:36.859776+00:00 |
| `updated_at` | 2025-11-02 21:20:11.480496+00:00 |
| `neighborhood_description` | NULL |

---

## `public.parcel_address_norm` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `normalized_address` | text (text) | YES |  |
| `neighborhood_code` | character varying (varchar) | YES |  |
| `is_residential` | boolean (bool) | YES |  |
| `roll_year` | integer (int4) | YES |  |
| `situs_city` | text (text) | YES |  |
| `zip5` | text (text) | YES |  |

### Indexes

- `parcel_address_norm_parcel_number_key`
  ```sql
  CREATE UNIQUE INDEX parcel_address_norm_parcel_number_key ON public.parcel_address_norm USING btree (parcel_number)
  ```
- `parcel_address_norm_neighborhood_idx`
  ```sql
  CREATE INDEX parcel_address_norm_neighborhood_idx ON public.parcel_address_norm USING btree (neighborhood_code)
  ```
- `parcel_address_norm_is_residential_idx`
  ```sql
  CREATE INDEX parcel_address_norm_is_residential_idx ON public.parcel_address_norm USING btree (is_residential)
  ```
- `parcel_address_norm_address_idx`
  ```sql
  CREATE INDEX parcel_address_norm_address_idx ON public.parcel_address_norm USING btree (normalized_address)
  ```
- `parcel_address_norm_roll_year_idx`
  ```sql
  CREATE INDEX parcel_address_norm_roll_year_idx ON public.parcel_address_norm USING btree (roll_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100321 |
| `normalized_address` | 4002 PETERS LANE |
| `neighborhood_code` | 20ASOUTH |
| `is_residential` | True |
| `roll_year` | NULL |
| `situs_city` | WA 98221 |
| `zip5` | 98221 |

---

## `public.parcel_authority` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | YES |  |
| `jurisdiction` | character varying(50) (varchar) | YES |  |
| `zone_code` | character varying(50) (varchar) | YES |  |
| `zoning_general_class` | character varying(30) (varchar) | YES |  |
| `zoning_specific_class` | character varying(100) (varchar) | YES |  |
| `reference_url` | character varying(500) (varchar) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P100005 |
| `jurisdiction` | Anacortes |
| `zone_code` | R3 |
| `zoning_general_class` | LIR |
| `zoning_specific_class` | SR5-12 |
| `reference_url` | https://anacortes.municipal.codes/AMC/19.42.020 |

---

## `public.parcel_coverage` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `has_geometry` | boolean (bool) | YES |  |
| `has_planning` | boolean (bool) | YES |  |
| `has_water` | boolean (bool) | YES |  |
| `completeness_score` | integer (int4) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `has_geometry` | True |
| `has_planning` | True |
| `has_water` | True |
| `completeness_score` | 3 |

---

## `public.parcel_development_profile` (t)

**Primary Key:** parcel_id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `primary_development_form` | character varying(32) (varchar) | NO |  |
| `confidence` | character varying(16) (varchar) | NO |  |
| `reasons` | jsonb (jsonb) | NO |  |
| `generated_at` | timestamp with time zone (timestamptz) | NO |  |
| `development_constraints` | jsonb (jsonb) | NO |  |
| `development_context` | character varying(16) (varchar) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `parcel_development_profile_pkey`
  ```sql
  CREATE UNIQUE INDEX parcel_development_profile_pkey ON public.parcel_development_profile USING btree (parcel_id)
  ```
- `parcel_development_profile_parcel_id_cfc608e4_like`
  ```sql
  CREATE INDEX parcel_development_profile_parcel_id_cfc608e4_like ON public.parcel_development_profile USING btree (parcel_id varchar_pattern_ops)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.parcel_geo_diagnostics` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `check_name` | text (text) | YES |  |
| `severity` | text (text) | YES |  |
| `detail` | text (text) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `check_name` | row_count_2025 |
| `severity` | INFO |
| `detail` | assessor_2025_geo has 83539 rows |

---

## `public.parcel_jurisdiction` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | YES |  |
| `jurisdiction_id` | bigint (int8) | YES |  |
| `jurisdiction_name` | character varying(200) (varchar) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P53559 |
| `jurisdiction_id` | 3 |
| `jurisdiction_name` | MountVernon |

---

## `public.parcel_owner_address_norm` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `normalized_address` | text (text) | YES |  |
| `neighborhood_code` | text (text) | YES |  |
| `neighborhood_description` | text (text) | YES |  |
| `owner_state` | text (text) | YES |  |
| `owner_zip` | text (text) | YES |  |
| `source` | text (text) | YES |  |

### Indexes

- `parcel_owner_address_parcel_idx`
  ```sql
  CREATE UNIQUE INDEX parcel_owner_address_parcel_idx ON public.parcel_owner_address_norm USING btree (parcel_number)
  ```
- `parcel_owner_address_neighborhood_idx`
  ```sql
  CREATE INDEX parcel_owner_address_neighborhood_idx ON public.parcel_owner_address_norm USING btree (neighborhood_code)
  ```
- `parcel_owner_address_norm_idx`
  ```sql
  CREATE INDEX parcel_owner_address_norm_idx ON public.parcel_owner_address_norm USING btree (normalized_address)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `normalized_address` | 2308 FOREST VIEW LN |
| `neighborhood_code` | 30AMF |
| `neighborhood_description` | ANACORTES RESIDENTIAL 2-4 FAMILY |
| `owner_state` | WA |
| `owner_zip` | 98221 |
| `source` | owner_mailing |

---

## `public.parcel_planning_facts` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `zone_code` | character varying(50) (varchar) | YES |  |
| `zoning_jurisdiction` | character varying(50) (varchar) | YES |  |
| `in_wetland` | boolean (bool) | YES |  |
| `pct_area_in_wetland` | double precision (float8) | YES |  |
| `in_stream_buffer` | boolean (bool) | YES |  |
| `pct_area_in_stream_buffer` | double precision (float8) | YES |  |
| `dist_to_nearest_stream_ft` | double precision (float8) | YES |  |
| `stream_type` | character varying(20) (varchar) | YES |  |
| `stream_buffer_required_ft` | double precision (float8) | YES |  |
| `in_sfha` | boolean (bool) | YES |  |
| `pct_area_in_sfha` | double precision (float8) | YES |  |
| `in_floodway` | boolean (bool) | YES |  |
| `pct_area_in_floodway` | double precision (float8) | YES |  |
| `in_shoreline_jurisdiction` | boolean (bool) | YES |  |
| `shoreline_env_designation` | character varying(50) (varchar) | YES |  |
| `dist_to_shoreline_ft` | double precision (float8) | YES |  |
| `buildable_area_sqft` | double precision (float8) | YES |  |
| `dist_to_water_main_ft` | double precision (float8) | YES |  |
| `public_sewer_available` | boolean (bool) | YES |  |
| `sewer_district_id` | character varying(100) (varchar) | YES |  |
| `dist_to_sewer_main_ft` | double precision (float8) | YES |  |
| `nearest_well_distance_ft` | double precision (float8) | YES |  |
| `well_density_per_acre` | double precision (float8) | YES |  |
| `in_wellhead_protection_zone` | boolean (bool) | YES |  |
| `wellhead_zone_category` | character varying(20) (varchar) | YES |  |
| `primary_access_type` | character varying(50) (varchar) | YES |  |
| `dist_to_public_road_ft` | double precision (float8) | YES |  |
| `dist_to_driveable_access_ft` | double precision (float8) | YES |  |
| `fire_district_id` | character varying(50) (varchar) | YES |  |
| `school_district_id` | character varying(50) (varchar) | YES |  |
| `city_jurisdiction` | character varying(50) (varchar) | YES |  |
| `legislative_district_id` | character varying(50) (varchar) | YES |  |
| `voting_district_id` | character varying(50) (varchar) | YES |  |
| `in_npdes_area` | boolean (bool) | YES |  |
| `in_historic_register` | boolean (bool) | YES |  |
| `in_historic_district` | boolean (bool) | YES |  |
| `in_airport_environs` | boolean (bool) | YES |  |
| `airport_environs_zone` | character varying(255) (varchar) | YES |  |
| `has_recent_permits_5yr` | boolean (bool) | YES |  |
| `last_updated` | timestamp with time zone (timestamptz) | NO |  |
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `in_big_lake_mitigation_area` | boolean (bool) | YES |  |
| `pct_area_in_shoreline` | double precision (float8) | YES |  |
| `dist_to_wetland_ft` | double precision (float8) | YES |  |
| `in_wetland_buffer` | boolean (bool) | YES |  |
| `wetland_buffer_intersect_area` | double precision (float8) | YES |  |
| `wetland_intersect_area` | double precision (float8) | YES |  |
| `in_skagit_mitigation_area` | boolean (bool) | YES |  |
| `skagit_mitigation_class` | character varying(20) (varchar) | YES |  |
| `census_block_group_geoid` | character varying(12) (varchar) | YES |  |
| `zoning_general_class` | character varying(30) (varchar) | YES |  |
| `zoning_last_verified` | date (date) | YES |  |
| `zoning_reference_url` | character varying(500) (varchar) | YES |  |
| `zoning_source` | character varying(50) (varchar) | YES |  |
| `zoning_specific_class` | character varying(100) (varchar) | YES |  |
| `zone_id` | text (text) | YES |  |
| `flood_depth` | double precision (float8) | YES |  |
| `flood_distance` | double precision (float8) | YES |  |
| `flood_sfha` | text (text) | YES |  |
| `flood_static_bfe` | double precision (float8) | YES |  |
| `flood_velocity` | double precision (float8) | YES |  |
| `flood_zone` | text (text) | YES |  |
| `flood_zone_id` | text (text) | YES |  |
| `flood_zone_subtype` | text (text) | YES |  |
| `in_flood_zone` | boolean (bool) | YES |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `parcel_plan_in_shor_184cb2_idx`
  ```sql
  CREATE INDEX parcel_plan_in_shor_184cb2_idx ON public.parcel_planning_facts USING btree (in_shoreline_jurisdiction)
  ```
- `parcel_planning_facts_pkey`
  ```sql
  CREATE UNIQUE INDEX parcel_planning_facts_pkey ON public.parcel_planning_facts USING btree (id)
  ```
- `parcel_planning_facts_parcel_id_c5aa5bf1_like`
  ```sql
  CREATE INDEX parcel_planning_facts_parcel_id_c5aa5bf1_like ON public.parcel_planning_facts USING btree (parcel_id varchar_pattern_ops)
  ```
- `parcel_plan_zone_co_94ed8b_idx`
  ```sql
  CREATE INDEX parcel_plan_zone_co_94ed8b_idx ON public.parcel_planning_facts USING btree (zone_code)
  ```
- `parcel_plan_in_sfha_795780_idx`
  ```sql
  CREATE INDEX parcel_plan_in_sfha_795780_idx ON public.parcel_planning_facts USING btree (in_sfha)
  ```
- `idx_ppf_parcel_id`
  ```sql
  CREATE INDEX idx_ppf_parcel_id ON public.parcel_planning_facts USING btree (parcel_id)
  ```
- `parcel_plan_in_floo_def35d_idx`
  ```sql
  CREATE INDEX parcel_plan_in_floo_def35d_idx ON public.parcel_planning_facts USING btree (in_floodway)
  ```
- `parcel_plan_public__324ec8_idx`
  ```sql
  CREATE INDEX parcel_plan_public__324ec8_idx ON public.parcel_planning_facts USING btree (public_sewer_available)
  ```
- `parcel_planning_facts_parcel_id_key`
  ```sql
  CREATE UNIQUE INDEX parcel_planning_facts_parcel_id_key ON public.parcel_planning_facts USING btree (parcel_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 113843 |
| `zone_code` | NULL |
| `zoning_jurisdiction` | NULL |
| `in_wetland` | NULL |
| `pct_area_in_wetland` | NULL |
| `in_stream_buffer` | NULL |
| `pct_area_in_stream_buffer` | NULL |
| `dist_to_nearest_stream_ft` | NULL |
| `stream_type` | NULL |
| `stream_buffer_required_ft` | NULL |
| `in_sfha` | NULL |
| `pct_area_in_sfha` | NULL |
| `in_floodway` | NULL |
| `pct_area_in_floodway` | NULL |
| `in_shoreline_jurisdiction` | NULL |
| `shoreline_env_designation` | NULL |
| `dist_to_shoreline_ft` | NULL |
| `buildable_area_sqft` | NULL |
| `dist_to_water_main_ft` | NULL |
| `public_sewer_available` | NULL |
| `sewer_district_id` | NULL |
| `dist_to_sewer_main_ft` | NULL |
| `nearest_well_distance_ft` | NULL |
| `well_density_per_acre` | NULL |
| `in_wellhead_protection_zone` | NULL |
| `wellhead_zone_category` | NULL |
| `primary_access_type` | NULL |
| `dist_to_public_road_ft` | NULL |
| `dist_to_driveable_access_ft` | NULL |
| `fire_district_id` | NULL |
| `school_district_id` | NULL |
| `city_jurisdiction` | NULL |
| `legislative_district_id` | NULL |
| `voting_district_id` | NULL |
| `in_npdes_area` | NULL |
| `in_historic_register` | NULL |
| `in_historic_district` | NULL |
| `in_airport_environs` | NULL |
| `airport_environs_zone` | NULL |
| `has_recent_permits_5yr` | NULL |
| `last_updated` | 2026-01-18 21:12:18.509706+00:00 |
| `parcel_id` | P105472 |
| `in_big_lake_mitigation_area` | NULL |
| `pct_area_in_shoreline` | NULL |
| `dist_to_wetland_ft` | NULL |
| `in_wetland_buffer` | NULL |
| `wetland_buffer_intersect_area` | NULL |
| `wetland_intersect_area` | NULL |
| `in_skagit_mitigation_area` | NULL |
| `skagit_mitigation_class` | NULL |
| `census_block_group_geoid` | NULL |
| `zoning_general_class` | NULL |
| `zoning_last_verified` | NULL |
| `zoning_reference_url` | NULL |
| `zoning_source` | NULL |
| `zoning_specific_class` | NULL |
| `zone_id` | NULL |
| `flood_depth` | NULL |
| `flood_distance` | NULL |
| `flood_sfha` | NULL |
| `flood_static_bfe` | NULL |
| `flood_velocity` | NULL |
| `flood_zone` | NULL |
| `flood_zone_id` | NULL |
| `flood_zone_subtype` | NULL |
| `in_flood_zone` | False |

---

## `public.parcel_precinct` (t)

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 2285)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `geometry` | geometry(MultiPolygon,2285) (geometry) | YES |  |
| `PREC_NO` | double precision (float8) | YES |  |
| `PRECINCT` | text (text) | YES |  |
| `multi_precinct_count` | bigint (int8) | YES |  |
| `has_multi_precincts` | boolean (bool) | YES |  |

### Indexes

- `idx_parcel_precinct_geometry`
  ```sql
  CREATE INDEX idx_parcel_precinct_geometry ON public.parcel_precinct USING gist (geometry)
  ```
- `idx_parcel_precinct_multi`
  ```sql
  CREATE INDEX idx_parcel_precinct_multi ON public.parcel_precinct USING btree (parcel_number) WHERE (has_multi_precincts = true)
  ```
- `idx_parcel_precinct_parcel`
  ```sql
  CREATE INDEX idx_parcel_precinct_parcel ON public.parcel_precinct USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P60695 |
| `geometry` | 0106000020ED0800000100000001030000000100000008000000EE422130378732410D19BA574D842041269D856B3B8732416ACB57074D84204116454C17CD873241E941166742842041D99604F6C... |
| `PREC_NO` | 164.0 |
| `PRECINCT` | FIDALGO |
| `multi_precinct_count` | 1 |
| `has_multi_precincts` | False |

---

## `public.parcel_tax_district` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | text (text) | NO |  |
| `district_type` | text (text) | NO |  |
| `district_code` | text (text) | NO |  |

### Indexes

- `parcel_tax_district_district_type_district_code_idx`
  ```sql
  CREATE INDEX parcel_tax_district_district_type_district_code_idx ON public.parcel_tax_district USING btree (district_type, district_code)
  ```
- `parcel_tax_district_parcel_id_idx`
  ```sql
  CREATE INDEX parcel_tax_district_parcel_id_idx ON public.parcel_tax_district USING btree (parcel_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P100005 |
| `district_type` | city |
| `district_code` | ANACORTES |

---

## `public.parcel_tax_history` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `tax_year` | integer (int4) | YES |  |
| `tax_paid` | numeric (numeric) | YES |  |

### Indexes

- `idx_pth_parcel`
  ```sql
  CREATE INDEX idx_pth_parcel ON public.parcel_tax_history USING btree (parcel_number)
  ```
- `idx_pth_year`
  ```sql
  CREATE INDEX idx_pth_year ON public.parcel_tax_history USING btree (tax_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100003 |
| `tax_year` | 2025 |
| `tax_paid` | 5947.11 |

---

## `public.parcel_tax_levy_breakdown` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | text (text) | NO |  |
| `tax_year` | integer (int4) | NO |  |
| `tdcode` | text (text) | NO |  |
| `district_type` | text (text) | NO |  |
| `district_code` | text (text) | NO |  |
| `levy_rate` | numeric (numeric) | YES |  |
| `tax_paid` | numeric (numeric) | YES |  |
| `total_levy_rate` | numeric (numeric) | YES |  |
| `levy_share` | numeric (numeric) | YES |  |
| `allocated_tax` | numeric (numeric) | YES |  |

### Indexes

- `parcel_tax_levy_breakdown_tdcode_idx`
  ```sql
  CREATE INDEX parcel_tax_levy_breakdown_tdcode_idx ON public.parcel_tax_levy_breakdown USING btree (tdcode)
  ```
- `parcel_tax_levy_breakdown_parcel_id_idx`
  ```sql
  CREATE INDEX parcel_tax_levy_breakdown_parcel_id_idx ON public.parcel_tax_levy_breakdown USING btree (parcel_id)
  ```
- `parcel_tax_levy_breakdown_tax_year_idx`
  ```sql
  CREATE INDEX parcel_tax_levy_breakdown_tax_year_idx ON public.parcel_tax_levy_breakdown USING btree (tax_year)
  ```
- `parcel_tax_levy_breakdown_district_type_district_code_idx`
  ```sql
  CREATE INDEX parcel_tax_levy_breakdown_district_type_district_code_idx ON public.parcel_tax_levy_breakdown USING btree (district_type, district_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P100496 |
| `tax_year` | 2024 |
| `tdcode` | 290600140 |
| `district_type` | hospital |
| `district_code` | 1 |
| `levy_rate` | 0.56612 |
| `tax_paid` | 5306.26 |
| `total_levy_rate` | 9.73845 |
| `levy_share` | 0.05813245434335032782 |
| `allocated_tax` | 308.4659171839461104981532 |

---

## `public.parcel_to_precinct` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | text (text) | YES |  |
| `prec_code` | bigint (int8) | YES |  |

### Indexes

- `idx_ptp_prec`
  ```sql
  CREATE INDEX idx_ptp_prec ON public.parcel_to_precinct USING btree (prec_code)
  ```
- `idx_ptp_parcel`
  ```sql
  CREATE INDEX idx_ptp_parcel ON public.parcel_to_precinct USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P30855 |
| `prec_code` | 148 |

---

## `public.parcel_zoning` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `intersect_area_sqft` | double precision (float8) | NO |  |
| `pct_of_parcel` | double precision (float8) | NO |  |
| `is_primary` | boolean (bool) | NO |  |
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `zone_id` | bigint (int8) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`
- `zone_id` → `public.zoning_zone.id`

### Indexes

- `parcel_zoning_parcel_id_b2f7a3f3_like`
  ```sql
  CREATE INDEX parcel_zoning_parcel_id_b2f7a3f3_like ON public.parcel_zoning USING btree (parcel_id varchar_pattern_ops)
  ```
- `parcel_zoni_parcel__79d248_idx`
  ```sql
  CREATE INDEX parcel_zoni_parcel__79d248_idx ON public.parcel_zoning USING btree (parcel_id)
  ```
- `parcel_zoning_zone_id_9ec7d862`
  ```sql
  CREATE INDEX parcel_zoning_zone_id_9ec7d862 ON public.parcel_zoning USING btree (zone_id)
  ```
- `parcel_zoning_parcel_id_b2f7a3f3`
  ```sql
  CREATE INDEX parcel_zoning_parcel_id_b2f7a3f3 ON public.parcel_zoning USING btree (parcel_id)
  ```
- `parcel_zoning_parcel_id_zone_id_a0df6ba2_uniq`
  ```sql
  CREATE UNIQUE INDEX parcel_zoning_parcel_id_zone_id_a0df6ba2_uniq ON public.parcel_zoning USING btree (parcel_id, zone_id)
  ```
- `parcel_zoning_pkey`
  ```sql
  CREATE UNIQUE INDEX parcel_zoning_pkey ON public.parcel_zoning USING btree (id)
  ```
- `parcel_zoni_is_prim_85ac67_idx`
  ```sql
  CREATE INDEX parcel_zoni_is_prim_85ac67_idx ON public.parcel_zoning USING btree (is_primary)
  ```
- `parcel_zoni_zone_id_c4520e_idx`
  ```sql
  CREATE INDEX parcel_zoni_zone_id_c4520e_idx ON public.parcel_zoning USING btree (zone_id)
  ```
- `idx_parcel_zoning_primary`
  ```sql
  CREATE INDEX idx_parcel_zoning_primary ON public.parcel_zoning USING btree (parcel_id) WHERE (is_primary = true)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 646107 |
| `intersect_area_sqft` | 0.009600587429149935 |
| `pct_of_parcel` | 1.5482574202547289e-09 |
| `is_primary` | False |
| `parcel_id` | P100022 |
| `zone_id` | 25762 |

---

## `public.parcels` (t)

**Primary Key:** gid

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `gid` | integer (int4) | NO |  |
| `parcelid` | character varying(10) (varchar) | YES |  |
| `parceltype` | numeric (numeric) | YES |  |
| `globalid` | character varying(38) (varchar) | YES |  |
| `shape_star` | numeric (numeric) | YES |  |
| `shape_stle` | numeric (numeric) | YES |  |
| `geom` | geometry(MultiPolygon,4326) (geometry) | YES |  |

### Indexes

- `parcels_pkey`
  ```sql
  CREATE UNIQUE INDEX parcels_pkey ON public.parcels USING btree (gid)
  ```
- `parcels_geom_idx`
  ```sql
  CREATE INDEX parcels_geom_idx ON public.parcels USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `gid` | 1 |
| `parcelid` | P74512 |
| `parceltype` | 1.00000000 |
| `globalid` | {F1E46655-95AB-4CD5-A890-6A1A3E784714} |
| `shape_star` | 197616.087268 |
| `shape_stle` | 4210.55515426 |
| `geom` | 0106000020E6100000010000000103000000010000000F000000F9E518D0369F5EC0DCEBCAE5E23048409DBA7176459F5EC01488C167D9304840990EBEA7549F5EC09908BA62C2304840FAFF9E7D5... |

---

## `public.planet_osm_line` (t)

**Geometry Columns:**
- `way` (LINESTRING, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `osm_id` | bigint (int8) | YES |  |
| `access` | text (text) | YES |  |
| `addr:housename` | text (text) | YES |  |
| `addr:housenumber` | text (text) | YES |  |
| `addr:interpolation` | text (text) | YES |  |
| `admin_level` | text (text) | YES |  |
| `aerialway` | text (text) | YES |  |
| `aeroway` | text (text) | YES |  |
| `amenity` | text (text) | YES |  |
| `area` | text (text) | YES |  |
| `barrier` | text (text) | YES |  |
| `bicycle` | text (text) | YES |  |
| `brand` | text (text) | YES |  |
| `bridge` | text (text) | YES |  |
| `boundary` | text (text) | YES |  |
| `building` | text (text) | YES |  |
| `construction` | text (text) | YES |  |
| `covered` | text (text) | YES |  |
| `culvert` | text (text) | YES |  |
| `cutting` | text (text) | YES |  |
| `denomination` | text (text) | YES |  |
| `disused` | text (text) | YES |  |
| `embankment` | text (text) | YES |  |
| `foot` | text (text) | YES |  |
| `generator:source` | text (text) | YES |  |
| `harbour` | text (text) | YES |  |
| `highway` | text (text) | YES |  |
| `historic` | text (text) | YES |  |
| `horse` | text (text) | YES |  |
| `intermittent` | text (text) | YES |  |
| `junction` | text (text) | YES |  |
| `landuse` | text (text) | YES |  |
| `layer` | text (text) | YES |  |
| `leisure` | text (text) | YES |  |
| `lock` | text (text) | YES |  |
| `man_made` | text (text) | YES |  |
| `military` | text (text) | YES |  |
| `motorcar` | text (text) | YES |  |
| `name` | text (text) | YES |  |
| `natural` | text (text) | YES |  |
| `office` | text (text) | YES |  |
| `oneway` | text (text) | YES |  |
| `operator` | text (text) | YES |  |
| `place` | text (text) | YES |  |
| `population` | text (text) | YES |  |
| `power` | text (text) | YES |  |
| `power_source` | text (text) | YES |  |
| `public_transport` | text (text) | YES |  |
| `railway` | text (text) | YES |  |
| `ref` | text (text) | YES |  |
| `religion` | text (text) | YES |  |
| `route` | text (text) | YES |  |
| `service` | text (text) | YES |  |
| `shop` | text (text) | YES |  |
| `sport` | text (text) | YES |  |
| `surface` | text (text) | YES |  |
| `toll` | text (text) | YES |  |
| `tourism` | text (text) | YES |  |
| `tower:type` | text (text) | YES |  |
| `tracktype` | text (text) | YES |  |
| `tunnel` | text (text) | YES |  |
| `water` | text (text) | YES |  |
| `waterway` | text (text) | YES |  |
| `wetland` | text (text) | YES |  |
| `width` | text (text) | YES |  |
| `wood` | text (text) | YES |  |
| `z_order` | integer (int4) | YES |  |
| `way_area` | real (float4) | YES |  |
| `tags` | hstore (hstore) | YES |  |
| `way` | geometry(LineString,2926) (geometry) | YES |  |

### Indexes

- `planet_osm_line_osm_id_idx`
  ```sql
  CREATE INDEX planet_osm_line_osm_id_idx ON public.planet_osm_line USING btree (osm_id)
  ```
- `planet_osm_line_way_idx`
  ```sql
  CREATE INDEX planet_osm_line_way_idx ON public.planet_osm_line USING gist (way)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_nodes` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `lat` | integer (int4) | NO |  |
| `lon` | integer (int4) | NO |  |

### Indexes

- `planet_osm_nodes_pkey`
  ```sql
  CREATE UNIQUE INDEX planet_osm_nodes_pkey ON public.planet_osm_nodes USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_point` (t)

**Geometry Columns:**
- `way` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `osm_id` | bigint (int8) | YES |  |
| `access` | text (text) | YES |  |
| `addr:housename` | text (text) | YES |  |
| `addr:housenumber` | text (text) | YES |  |
| `addr:interpolation` | text (text) | YES |  |
| `admin_level` | text (text) | YES |  |
| `aerialway` | text (text) | YES |  |
| `aeroway` | text (text) | YES |  |
| `amenity` | text (text) | YES |  |
| `area` | text (text) | YES |  |
| `barrier` | text (text) | YES |  |
| `bicycle` | text (text) | YES |  |
| `brand` | text (text) | YES |  |
| `bridge` | text (text) | YES |  |
| `boundary` | text (text) | YES |  |
| `building` | text (text) | YES |  |
| `capital` | text (text) | YES |  |
| `construction` | text (text) | YES |  |
| `covered` | text (text) | YES |  |
| `culvert` | text (text) | YES |  |
| `cutting` | text (text) | YES |  |
| `denomination` | text (text) | YES |  |
| `disused` | text (text) | YES |  |
| `ele` | text (text) | YES |  |
| `embankment` | text (text) | YES |  |
| `foot` | text (text) | YES |  |
| `generator:source` | text (text) | YES |  |
| `harbour` | text (text) | YES |  |
| `highway` | text (text) | YES |  |
| `historic` | text (text) | YES |  |
| `horse` | text (text) | YES |  |
| `intermittent` | text (text) | YES |  |
| `junction` | text (text) | YES |  |
| `landuse` | text (text) | YES |  |
| `layer` | text (text) | YES |  |
| `leisure` | text (text) | YES |  |
| `lock` | text (text) | YES |  |
| `man_made` | text (text) | YES |  |
| `military` | text (text) | YES |  |
| `motorcar` | text (text) | YES |  |
| `name` | text (text) | YES |  |
| `natural` | text (text) | YES |  |
| `office` | text (text) | YES |  |
| `oneway` | text (text) | YES |  |
| `operator` | text (text) | YES |  |
| `place` | text (text) | YES |  |
| `population` | text (text) | YES |  |
| `power` | text (text) | YES |  |
| `power_source` | text (text) | YES |  |
| `public_transport` | text (text) | YES |  |
| `railway` | text (text) | YES |  |
| `ref` | text (text) | YES |  |
| `religion` | text (text) | YES |  |
| `route` | text (text) | YES |  |
| `service` | text (text) | YES |  |
| `shop` | text (text) | YES |  |
| `sport` | text (text) | YES |  |
| `surface` | text (text) | YES |  |
| `toll` | text (text) | YES |  |
| `tourism` | text (text) | YES |  |
| `tower:type` | text (text) | YES |  |
| `tunnel` | text (text) | YES |  |
| `water` | text (text) | YES |  |
| `waterway` | text (text) | YES |  |
| `wetland` | text (text) | YES |  |
| `width` | text (text) | YES |  |
| `wood` | text (text) | YES |  |
| `z_order` | integer (int4) | YES |  |
| `tags` | hstore (hstore) | YES |  |
| `way` | geometry(Point,2926) (geometry) | YES |  |

### Indexes

- `planet_osm_point_osm_id_idx`
  ```sql
  CREATE INDEX planet_osm_point_osm_id_idx ON public.planet_osm_point USING btree (osm_id)
  ```
- `planet_osm_point_way_idx`
  ```sql
  CREATE INDEX planet_osm_point_way_idx ON public.planet_osm_point USING gist (way)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_polygon` (t)

**Geometry Columns:**
- `way` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `osm_id` | bigint (int8) | YES |  |
| `access` | text (text) | YES |  |
| `addr:housename` | text (text) | YES |  |
| `addr:housenumber` | text (text) | YES |  |
| `addr:interpolation` | text (text) | YES |  |
| `admin_level` | text (text) | YES |  |
| `aerialway` | text (text) | YES |  |
| `aeroway` | text (text) | YES |  |
| `amenity` | text (text) | YES |  |
| `area` | text (text) | YES |  |
| `barrier` | text (text) | YES |  |
| `bicycle` | text (text) | YES |  |
| `brand` | text (text) | YES |  |
| `bridge` | text (text) | YES |  |
| `boundary` | text (text) | YES |  |
| `building` | text (text) | YES |  |
| `construction` | text (text) | YES |  |
| `covered` | text (text) | YES |  |
| `culvert` | text (text) | YES |  |
| `cutting` | text (text) | YES |  |
| `denomination` | text (text) | YES |  |
| `disused` | text (text) | YES |  |
| `embankment` | text (text) | YES |  |
| `foot` | text (text) | YES |  |
| `generator:source` | text (text) | YES |  |
| `harbour` | text (text) | YES |  |
| `highway` | text (text) | YES |  |
| `historic` | text (text) | YES |  |
| `horse` | text (text) | YES |  |
| `intermittent` | text (text) | YES |  |
| `junction` | text (text) | YES |  |
| `landuse` | text (text) | YES |  |
| `layer` | text (text) | YES |  |
| `leisure` | text (text) | YES |  |
| `lock` | text (text) | YES |  |
| `man_made` | text (text) | YES |  |
| `military` | text (text) | YES |  |
| `motorcar` | text (text) | YES |  |
| `name` | text (text) | YES |  |
| `natural` | text (text) | YES |  |
| `office` | text (text) | YES |  |
| `oneway` | text (text) | YES |  |
| `operator` | text (text) | YES |  |
| `place` | text (text) | YES |  |
| `population` | text (text) | YES |  |
| `power` | text (text) | YES |  |
| `power_source` | text (text) | YES |  |
| `public_transport` | text (text) | YES |  |
| `railway` | text (text) | YES |  |
| `ref` | text (text) | YES |  |
| `religion` | text (text) | YES |  |
| `route` | text (text) | YES |  |
| `service` | text (text) | YES |  |
| `shop` | text (text) | YES |  |
| `sport` | text (text) | YES |  |
| `surface` | text (text) | YES |  |
| `toll` | text (text) | YES |  |
| `tourism` | text (text) | YES |  |
| `tower:type` | text (text) | YES |  |
| `tracktype` | text (text) | YES |  |
| `tunnel` | text (text) | YES |  |
| `water` | text (text) | YES |  |
| `waterway` | text (text) | YES |  |
| `wetland` | text (text) | YES |  |
| `width` | text (text) | YES |  |
| `wood` | text (text) | YES |  |
| `z_order` | integer (int4) | YES |  |
| `way_area` | real (float4) | YES |  |
| `tags` | hstore (hstore) | YES |  |
| `way` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `planet_osm_polygon_osm_id_idx`
  ```sql
  CREATE INDEX planet_osm_polygon_osm_id_idx ON public.planet_osm_polygon USING btree (osm_id)
  ```
- `planet_osm_polygon_way_idx`
  ```sql
  CREATE INDEX planet_osm_polygon_way_idx ON public.planet_osm_polygon USING gist (way)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_rels` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `way_off` | smallint (int2) | YES |  |
| `rel_off` | smallint (int2) | YES |  |
| `parts` | bigint[] (_int8) | YES |  |
| `members` | text[] (_text) | YES |  |
| `tags` | text[] (_text) | YES |  |

### Indexes

- `planet_osm_rels_pkey`
  ```sql
  CREATE UNIQUE INDEX planet_osm_rels_pkey ON public.planet_osm_rels USING btree (id)
  ```
- `planet_osm_rels_parts_idx`
  ```sql
  CREATE INDEX planet_osm_rels_parts_idx ON public.planet_osm_rels USING gin (parts) WITH (fastupdate=off)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_roads` (t)

**Geometry Columns:**
- `way` (LINESTRING, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `osm_id` | bigint (int8) | YES |  |
| `access` | text (text) | YES |  |
| `addr:housename` | text (text) | YES |  |
| `addr:housenumber` | text (text) | YES |  |
| `addr:interpolation` | text (text) | YES |  |
| `admin_level` | text (text) | YES |  |
| `aerialway` | text (text) | YES |  |
| `aeroway` | text (text) | YES |  |
| `amenity` | text (text) | YES |  |
| `area` | text (text) | YES |  |
| `barrier` | text (text) | YES |  |
| `bicycle` | text (text) | YES |  |
| `brand` | text (text) | YES |  |
| `bridge` | text (text) | YES |  |
| `boundary` | text (text) | YES |  |
| `building` | text (text) | YES |  |
| `construction` | text (text) | YES |  |
| `covered` | text (text) | YES |  |
| `culvert` | text (text) | YES |  |
| `cutting` | text (text) | YES |  |
| `denomination` | text (text) | YES |  |
| `disused` | text (text) | YES |  |
| `embankment` | text (text) | YES |  |
| `foot` | text (text) | YES |  |
| `generator:source` | text (text) | YES |  |
| `harbour` | text (text) | YES |  |
| `highway` | text (text) | YES |  |
| `historic` | text (text) | YES |  |
| `horse` | text (text) | YES |  |
| `intermittent` | text (text) | YES |  |
| `junction` | text (text) | YES |  |
| `landuse` | text (text) | YES |  |
| `layer` | text (text) | YES |  |
| `leisure` | text (text) | YES |  |
| `lock` | text (text) | YES |  |
| `man_made` | text (text) | YES |  |
| `military` | text (text) | YES |  |
| `motorcar` | text (text) | YES |  |
| `name` | text (text) | YES |  |
| `natural` | text (text) | YES |  |
| `office` | text (text) | YES |  |
| `oneway` | text (text) | YES |  |
| `operator` | text (text) | YES |  |
| `place` | text (text) | YES |  |
| `population` | text (text) | YES |  |
| `power` | text (text) | YES |  |
| `power_source` | text (text) | YES |  |
| `public_transport` | text (text) | YES |  |
| `railway` | text (text) | YES |  |
| `ref` | text (text) | YES |  |
| `religion` | text (text) | YES |  |
| `route` | text (text) | YES |  |
| `service` | text (text) | YES |  |
| `shop` | text (text) | YES |  |
| `sport` | text (text) | YES |  |
| `surface` | text (text) | YES |  |
| `toll` | text (text) | YES |  |
| `tourism` | text (text) | YES |  |
| `tower:type` | text (text) | YES |  |
| `tracktype` | text (text) | YES |  |
| `tunnel` | text (text) | YES |  |
| `water` | text (text) | YES |  |
| `waterway` | text (text) | YES |  |
| `wetland` | text (text) | YES |  |
| `width` | text (text) | YES |  |
| `wood` | text (text) | YES |  |
| `z_order` | integer (int4) | YES |  |
| `way_area` | real (float4) | YES |  |
| `tags` | hstore (hstore) | YES |  |
| `way` | geometry(LineString,2926) (geometry) | YES |  |

### Indexes

- `planet_osm_roads_way_idx`
  ```sql
  CREATE INDEX planet_osm_roads_way_idx ON public.planet_osm_roads USING gist (way)
  ```
- `planet_osm_roads_osm_id_idx`
  ```sql
  CREATE INDEX planet_osm_roads_osm_id_idx ON public.planet_osm_roads USING btree (osm_id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.planet_osm_ways` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `nodes` | bigint[] (_int8) | NO |  |
| `tags` | text[] (_text) | YES |  |

### Indexes

- `planet_osm_ways_nodes_bucket_idx`
  ```sql
  CREATE INDEX planet_osm_ways_nodes_bucket_idx ON public.planet_osm_ways USING gin (planet_osm_index_bucket(nodes)) WITH (fastupdate=off)
  ```
- `planet_osm_ways_pkey`
  ```sql
  CREATE UNIQUE INDEX planet_osm_ways_pkey ON public.planet_osm_ways USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.precinct_ballots_by_year` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `po_box_ballots` | bigint (int8) | YES |  |
| `po_box_pct` | double precision (float8) | YES |  |

### Indexes

- `precinct_ballots_prec_year_idx`
  ```sql
  CREATE UNIQUE INDEX precinct_ballots_prec_year_idx ON public.precinct_ballots_by_year USING btree (prec_code, election_year)
  ```
- `precinct_ballots_year_idx`
  ```sql
  CREATE INDEX precinct_ballots_year_idx ON public.precinct_ballots_by_year USING btree (election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `election_year` | 2024 |
| `ballots_cast` | 1265 |
| `po_box_ballots` | 47 |
| `po_box_pct` | 0.03715415019762846 |

---

## `public.precinct_civic_classification` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `tax_year` | integer (int4) | YES |  |
| `total_tax_paid` | numeric (numeric) | YES |  |
| `parcel_count` | bigint (int8) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `tax_per_ballot` | numeric (numeric) | YES |  |
| `tax_per_parcel` | numeric (numeric) | YES |  |
| `ballots_per_parcel` | bigint (int8) | YES |  |
| `tax_burden_quartile` | integer (int4) | YES |  |

### Indexes

- `idx_pcc_prec_year`
  ```sql
  CREATE INDEX idx_pcc_prec_year ON public.precinct_civic_classification USING btree (prec_code, tax_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 405 |
| `tax_year` | 2024 |
| `total_tax_paid` | 79312.23 |
| `parcel_count` | 38 |
| `ballots_cast` | 968 |
| `tax_per_ballot` | 81.9341219008264463 |
| `tax_per_parcel` | 2087.1639473684210526 |
| `ballots_per_parcel` | 25 |
| `tax_burden_quartile` | 1 |

---

## `public.precinct_participation_index` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `ballots_cast` | bigint (int8) | YES |  |
| `po_box_ballots` | bigint (int8) | YES |  |
| `po_box_pct` | double precision (float8) | YES |  |
| `residential_parcels` | bigint (int8) | YES |  |
| `ppi` | double precision (float8) | YES |  |

### Indexes

- `precinct_participation_year_idx`
  ```sql
  CREATE INDEX precinct_participation_year_idx ON public.precinct_participation_index USING btree (election_year)
  ```
- `precinct_participation_prec_year_idx`
  ```sql
  CREATE UNIQUE INDEX precinct_participation_prec_year_idx ON public.precinct_participation_index USING btree (prec_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `election_year` | 2025 |
| `ballots_cast` | 411 |
| `po_box_ballots` | 25 |
| `po_box_pct` | 0.06082725060827251 |
| `residential_parcels` | 483 |
| `ppi` | 0.8509316770186336 |

---

## `public.precinct_residential_parcels` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `residential_parcels` | bigint (int8) | YES |  |

### Indexes

- `precinct_residential_year_idx`
  ```sql
  CREATE INDEX precinct_residential_year_idx ON public.precinct_residential_parcels USING btree (election_year)
  ```
- `precinct_residential_prec_year_idx`
  ```sql
  CREATE UNIQUE INDEX precinct_residential_prec_year_idx ON public.precinct_residential_parcels USING btree (prec_code, election_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 101 |
| `election_year` | 2025 |
| `residential_parcels` | 483 |

---

## `public.precinct_split_clipped` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 211 |
| `geom_2926` | 01030000206E0B000001000000360100002EE26555A2C54141EB7BA4DC603AEDC09FC1E22786C54141E82AAA1F8485EEC05DEE1854F5CF414149D49C07FF7FEEC0AD97166E5DDA41412A2606512F7... |

---

## `public.precinct_split_dissolved` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Indexes

- `idx_psd_geom`
  ```sql
  CREATE INDEX idx_psd_geom ON public.precinct_split_dissolved USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 0 |
| `geom_2926` | 01030000206E0B00000100000009000000A96E7AF5750F3241305B190B95732641EE84CD3CAC0E324189B44541A2732641FEE932C92D0E32411297DEA9AA732641460B93DEA80D3241BE50C085B37... |

---

## `public.precinct_split_ratio` (m)

**Geometry Columns:**
- `split_geom` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `split_geom` | geometry (geometry) | YES |  |
| `area_ratio` | double precision (float8) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 0 |
| `split_geom` | 01030000206E0B00000100000009000000A96E7AF5750F3241305B190B95732641EE84CD3CAC0E324189B44541A2732641FEE932C92D0E32411297DEA9AA732641460B93DEA80D3241BE50C085B37... |
| `area_ratio` | 1.0000000000000002 |

---

## `public.property_features` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `address` | text (text) | YES |  |
| `neighborhood_code` | text (text) | YES |  |
| `land_use_code` | text (text) | YES |  |
| `assessed_value` | bigint (int8) | YES |  |
| `land_acres` | real (float4) | YES |  |
| `land_market_value` | real (float4) | YES |  |

### Indexes

- `idx_property_features_parcel`
  ```sql
  CREATE UNIQUE INDEX idx_property_features_parcel ON public.property_features USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100003 |
| `address` | 702 R AVENUE ANACORTES, WA 98221 |
| `neighborhood_code` | NULL |
| `land_use_code` | NULL |
| `assessed_value` | 788000 |
| `land_acres` | NULL |
| `land_market_value` | NULL |

---

## `public.property_improvement_features` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `improvement_type` | text (text) | YES |  |
| `total_area` | real (float4) | YES |  |
| `structure_count` | bigint (int8) | YES |  |

### Indexes

- `idx_property_improvement_features_parcel`
  ```sql
  CREATE INDEX idx_property_improvement_features_parcel ON public.property_improvement_features USING btree (parcel_number)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `improvement_type` | DUPLEX |
| `total_area` | 5680.0 |
| `structure_count` | 16 |

---

## `public.raster_columns` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `r_table_catalog` | name (name) | YES |  |
| `r_table_schema` | name (name) | YES |  |
| `r_table_name` | name (name) | YES |  |
| `r_raster_column` | name (name) | YES |  |
| `srid` | integer (int4) | YES |  |
| `scale_x` | double precision (float8) | YES |  |
| `scale_y` | double precision (float8) | YES |  |
| `blocksize_x` | integer (int4) | YES |  |
| `blocksize_y` | integer (int4) | YES |  |
| `same_alignment` | boolean (bool) | YES |  |
| `regular_blocking` | boolean (bool) | YES |  |
| `num_bands` | integer (int4) | YES |  |
| `pixel_types` | text[] (_text) | YES |  |
| `nodata_values` | double precision[] (_float8) | YES |  |
| `out_db` | boolean[] (_bool) | YES |  |
| `extent` | geometry (geometry) | YES |  |
| `spatial_index` | boolean (bool) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `r_table_catalog` | skagit |
| `r_table_schema` | public |
| `r_table_name` | reference_elevation |
| `r_raster_column` | rast |
| `srid` | 2926 |
| `scale_x` | NULL |
| `scale_y` | NULL |
| `blocksize_x` | 204 |
| `blocksize_y` | 305 |
| `same_alignment` | False |
| `regular_blocking` | False |
| `num_bands` | 1 |
| `pixel_types` | ['32BF'] |
| `nodata_values` | [-999999.0] |
| `out_db` | [False] |
| `extent` | 01030000206E0B00000100000005000000AC35D78B73EE3041DC9E197B9B3A1641AC35D78B73EE304102B9A09CF681264111EB37B81E6D384102B9A09CF681264111EB37B81E6D3841DC9E197B9B3... |
| `spatial_index` | True |

---

## `public.raster_overviews` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `o_table_catalog` | name (name) | YES |  |
| `o_table_schema` | name (name) | YES |  |
| `o_table_name` | name (name) | YES |  |
| `o_raster_column` | name (name) | YES |  |
| `r_table_catalog` | name (name) | YES |  |
| `r_table_schema` | name (name) | YES |  |
| `r_table_name` | name (name) | YES |  |
| `r_raster_column` | name (name) | YES |  |
| `overview_factor` | integer (int4) | YES |  |

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.reference_active_permits_5yr` (t)

**Geometry Columns:**
- `geometry` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Point,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `PermitNumber` | text (text) | YES |  |
| `ParcelNumber` | text (text) | YES |  |
| `PermitType` | text (text) | YES |  |
| `PermitDescription` | text (text) | YES |  |
| `Approved` | double precision (float8) | YES |  |
| `ApprovedText` | text (text) | YES |  |
| `Issued` | bigint (int8) | YES |  |
| `IssuedText` | text (text) | YES |  |
| `XCoordinate` | double precision (float8) | YES |  |
| `YCoordinate` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_active_permits_5yr_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_active_permits_5yr_geometry_gist ON public.reference_active_permits_5yr USING gist (geometry)
  ```
- `idx_reference_active_permits_5yr_geometry`
  ```sql
  CREATE INDEX idx_reference_active_permits_5yr_geometry ON public.reference_active_permits_5yr USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01010000206E0B0000A01074C29DC23541293F304C23D42041 |
| `OBJECTID` | 1 |
| `PermitNumber` | AC21-0082  |
| `ParcelNumber` | P100027 |
| `PermitType` | Access |
| `PermitDescription` | Access Permit |
| `Approved` | 1642550400000.0 |
| `ApprovedText` | 01/19/2022 |
| `Issued` | 1642550400000 |
| `IssuedText` | 01/19/2022 |
| `XCoordinate` | 1426077.7756 |
| `YCoordinate` | 551441.671 |

---

## `public.reference_airport_environs` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `PARCELID` | text (text) | YES |  |
| `SitusStNo` | text (text) | YES |  |
| `SitusStName` | text (text) | YES |  |
| `SitusCSZ` | text (text) | YES |  |
| `OwnerName` | text (text) | YES |  |
| `OwnerAdd1` | text (text) | YES |  |
| `OwnerAdd2` | text (text) | YES |  |
| `OwnerAdd3` | text (text) | YES |  |
| `OwnerCity` | text (text) | YES |  |
| `OwnerState` | text (text) | YES |  |
| `OwnerZip` | text (text) | YES |  |
| `Exemptions` | text (text) | YES |  |
| `NeighborCode` | text (text) | YES |  |
| `BuildingValue` | text (text) | YES |  |
| `LandUse` | text (text) | YES |  |
| `ImprLandValue` | text (text) | YES |  |
| `UnimprLandValue` | text (text) | YES |  |
| `TimberLandValue` | text (text) | YES |  |
| `AssessedValue` | text (text) | YES |  |
| `TaxableValue` | text (text) | YES |  |
| `TotalMktValue` | text (text) | YES |  |
| `Acres` | double precision (float8) | YES |  |
| `SaleDate` | double precision (float8) | YES |  |
| `SalePrice` | text (text) | YES |  |
| `SaleDeedType` | text (text) | YES |  |
| `TotalTaxes` | text (text) | YES |  |
| `YearBuilt` | text (text) | YES |  |
| `LivingArea` | text (text) | YES |  |
| `TotalSpcAssmts` | text (text) | YES |  |
| `GeneralTaxes` | text (text) | YES |  |
| `InactiveDate` | text (text) | YES |  |
| `Foundation` | text (text) | YES |  |
| `ExteriorWalls` | text (text) | YES |  |
| `RoofCovering` | text (text) | YES |  |
| `RoofStyle` | text (text) | YES |  |
| `FloorCover` | text (text) | YES |  |
| `FloorConstr` | text (text) | YES |  |
| `InteriorFinish` | text (text) | YES |  |
| `Plumbing` | text (text) | YES |  |
| `HeatAirCond` | text (text) | YES |  |
| `Fireplace` | text (text) | YES |  |
| `NoOfBedrooms` | text (text) | YES |  |
| `EffYearBuilt` | text (text) | YES |  |
| `FireDistrict` | text (text) | YES |  |
| `SchoolDistrict` | text (text) | YES |  |
| `CityDistrict` | text (text) | YES |  |
| `Unit` | text (text) | YES |  |
| `LevyCode` | text (text) | YES |  |
| `CurrentUseAdj` | text (text) | YES |  |
| `TideLandValue` | text (text) | YES |  |
| `SeniorExAdj` | text (text) | YES |  |
| `Township` | text (text) | YES |  |
| `Range` | text (text) | YES |  |
| `Section` | text (text) | YES |  |
| `QtrSection` | text (text) | YES |  |
| `TaxYear` | bigint (int8) | YES |  |
| `AppraisalYear` | bigint (int8) | YES |  |
| `Utilities` | text (text) | YES |  |
| `TaxStmtTaxableValue` | text (text) | YES |  |
| `PropType` | text (text) | YES |  |
| `HasSeptic` | bigint (int8) | YES |  |
| `BuildingStyle` | text (text) | YES |  |
| `GarageSqFt` | text (text) | YES |  |
| `FinishedBasement` | text (text) | YES |  |
| `UnfinishedBasement` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |
| `STArea__` | text (text) | YES |  |
| `STLength__` | text (text) | YES |  |

### Indexes

- `idx_reference_airport_environs_geometry`
  ```sql
  CREATE INDEX idx_reference_airport_environs_geometry ON public.reference_airport_environs USING gist (geometry)
  ```
- `idx_reference_airport_environs_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_airport_environs_geometry_gist ON public.reference_airport_environs USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B0000010000000F000000D95747B493E53241D1E6BE75E9071F4133E088B492E5324139009EC5790C1F4113A57EDD44E53241B103733E900B1F4119784B2A8BE43241A1B1E150480... |
| `OBJECTID` | 1 |
| `PARCELID` | P74512 |
| `SitusStNo` | NULL |
| `SitusStName` | NULL |
| `SitusCSZ` | NULL |
| `OwnerName` | ELIZABETH KOUDAL LLC |
| `OwnerAdd1` | NULL |
| `OwnerAdd2` | NULL |
| `OwnerAdd3` | 12275 VALLEY ROAD |
| `OwnerCity` | MOUNT VERNON |
| `OwnerState` | WA |
| `OwnerZip` | 98273 |
| `Exemptions` | U500 |
| `NeighborCode` | (11TIDE) ALL COUNTY TIDELANDS |
| `BuildingValue` | 0 |
| `LandUse` | (930) WATER AREAS |
| `ImprLandValue` | 100 |
| `UnimprLandValue` | 0 |
| `TimberLandValue` | 0 |
| `AssessedValue` | 100 |
| `TaxableValue` | 0 |
| `TotalMktValue` | 100 |
| `Acres` | 0.0 |
| `SaleDate` | 1558396800000.0 |
| `SalePrice` | 775000 |
| `SaleDeedType` | WARRANTY DEED |
| `TotalTaxes` | 0.00 |
| `YearBuilt` | NULL |
| `LivingArea` | 0 |
| `TotalSpcAssmts` | NULL |
| `GeneralTaxes` | NULL |
| `InactiveDate` | NULL |
| `Foundation` | NULL |
| `ExteriorWalls` | NULL |
| `RoofCovering` | NULL |
| `RoofStyle` | NULL |
| `FloorCover` | NULL |
| `FloorConstr` | NULL |
| `InteriorFinish` | NULL |
| `Plumbing` | NULL |
| `HeatAirCond` | NULL |
| `Fireplace` | NULL |
| `NoOfBedrooms` | NULL |
| `EffYearBuilt` | 0 |
| `FireDistrict` | F13 |
| `SchoolDistrict` | SD311 |
| `CityDistrict` | Skagit County |
| `Unit` | NULL |
| `LevyCode` | 1595 |
| `CurrentUseAdj` | 0 |
| `TideLandValue` | 0 |
| `SeniorExAdj` | 0 |
| `Township` | 33 |
| `Range` | 02 |
| `Section` | 01 |
| `QtrSection` | 02 |
| `TaxYear` | 2025 |
| `AppraisalYear` | 2026 |
| `Utilities` | NULL |
| `TaxStmtTaxableValue` | 0 |
| `PropType` | R |
| `HasSeptic` | 0 |
| `BuildingStyle` | SINGLE FAMILY RESIDENCE |
| `GarageSqFt` | 0 |
| `FinishedBasement` | 0 |
| `UnfinishedBasement` | 0 |
| `Shape.STArea()` | 197616.087268 |
| `Shape.STLength()` | 4210.555154256641 |
| `STArea__` | NULL |
| `STLength__` | NULL |

---

## `public.reference_ana_zoning` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `OBJECTID_1` | bigint (int8) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Layer` | text (text) | YES |  |
| `SFR` | bigint (int8) | YES |  |
| `MFR` | bigint (int8) | YES |  |
| `Other` | bigint (int8) | YES |  |
| `sqft` | bigint (int8) | YES |  |
| `Zone` | text (text) | YES |  |
| `Shape_Leng` | double precision (float8) | YES |  |
| `Shape_Le_1` | double precision (float8) | YES |  |
| `created_user` | text (text) | YES |  |
| `created_date` | double precision (float8) | YES |  |
| `last_edited_user` | text (text) | YES |  |
| `last_edited_date` | bigint (int8) | YES |  |
| `Shape__Area` | double precision (float8) | YES |  |
| `Shape__Length` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_ana_zoning_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_ana_zoning_geometry_gist ON public.reference_ana_zoning USING gist (geometry)
  ```
- `idx_reference_ana_zoning_geometry`
  ```sql
  CREATE INDEX idx_reference_ana_zoning_geometry ON public.reference_ana_zoning USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B0000010000002200000026C2DB658A763241D77BAF45FC082141C7B390B88076324150672686AA062141B5854AFE8275324107BAAF33BB0621412623120B297532419BC4AA32C10... |
| `OBJECTID_1` | 1 |
| `OBJECTID` | 1 |
| `Layer` | Commercial Marine - Cap Sante Marina |
| `SFR` | 0 |
| `MFR` | 0 |
| `Other` | 10 |
| `sqft` | 4418852 |
| `Zone` | CM |
| `Shape_Leng` | 10009.612065 |
| `Shape_Le_1` | 10009.612065 |
| `created_user` | NULL |
| `created_date` | NULL |
| `last_edited_user` | ROBH |
| `last_edited_date` | 1765581525000 |
| `Shape__Area` | 934348.810473555 |
| `Shape__Length` | 4605.571301335289 |

---

## `public.reference_big_lake_mitigation` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Planning.SDEADM.BigLakeMitigationBoundary.AREA` | double precision (float8) | YES |  |
| `PERIMETER` | bigint (int8) | YES |  |
| `SUBBASINS_` | bigint (int8) | YES |  |
| `SUBBASINS1` | bigint (int8) | YES |  |
| `BASIN_NM` | text (text) | YES |  |
| `SUBBASIN_N` | text (text) | YES |  |
| `SYMBOL` | bigint (int8) | YES |  |
| `Area_sq_Mi` | bigint (int8) | YES |  |
| `Reserv` | bigint (int8) | YES |  |
| `Acreage` | bigint (int8) | YES |  |
| `SqMi` | bigint (int8) | YES |  |
| `PermPerMi` | bigint (int8) | YES |  |
| `Mit_Area` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_big_lake_mitigation_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_big_lake_mitigation_geometry_gist ON public.reference_big_lake_mitigation USING gist (geometry)
  ```
- `idx_reference_big_lake_mitigation_geometry`
  ```sql
  CREATE INDEX idx_reference_big_lake_mitigation_geometry ON public.reference_big_lake_mitigation USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B00000100000073010000B129D12E21CF334138CE9045CC591F41C1B39EEEFDCF3341692C4E6F2E591F4158CF8BF664D03341A8A57CE7E0591F41A117C2E932D133414BE0ABC8BB5... |
| `OBJECTID` | 1 |
| `Planning.SDEADM.BigLakeMitigationBoundary.AREA` | 8.0165596 |
| `PERIMETER` | 0 |
| `SUBBASINS_` | 0 |
| `SUBBASINS1` | 0 |
| `BASIN_NM` |   |
| `SUBBASIN_N` |   |
| `SYMBOL` | 0 |
| `Area_sq_Mi` | 0 |
| `Reserv` | 0 |
| `Acreage` | 0 |
| `SqMi` | 0 |
| `PermPerMi` | 0 |
| `Mit_Area` | Area Approved for Future Mitigation |
| `GlobalID` | {09BD78DA-D8E4-4B90-9E13-334D7DF362FB} |
| `Shape.STArea()` | 223272479.8069064 |
| `Shape.STLength()` | 121348.06555572675 |

---

## `public.reference_cem2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_cem2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_cem2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_cem2025_district_raw_pkey ON public.reference_cem2025_district_raw USING btree (id)
  ```
- `reference_cem2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_cem2025_district_raw_geom_geom_idx ON public.reference_cem2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ADAMS |
| `countynum` | 1.0 |
| `distattrib` | 1 |
| `shape_leng` | 368181.824367 |
| `shape_area` | 5062269860.08 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B00000100000001030000000100000002010000492F254F0A9D414179216F7DE61BD6C0F450C7B7C29C4141272E287BDCC0D8C065D3FF497F9241413A24003F04B9D8C07739EE3E2... |

---

## `public.reference_census_acs` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `name` | text (text) | YES |  |
| `median_income` | numeric (numeric) | YES |  |
| `edu_bachelors` | numeric (numeric) | YES |  |
| `edu_masters` | numeric (numeric) | YES |  |
| `edu_professional` | numeric (numeric) | YES |  |
| `edu_doctorate` | numeric (numeric) | YES |  |
| `population` | numeric (numeric) | YES |  |
| `median_home_value` | numeric (numeric) | YES |  |
| `median_rent` | numeric (numeric) | YES |  |
| `state_fips` | text (text) | YES |  |
| `county_fips` | text (text) | YES |  |
| `tract_ce` | text (text) | YES |  |
| `block_group_ce` | text (text) | YES |  |
| `geoid` | text (text) | YES |  |
| `year` | integer (int4) | YES |  |

### Indexes

- `idx_reference_census_acs_geoid`
  ```sql
  CREATE INDEX idx_reference_census_acs_geoid ON public.reference_census_acs USING btree (geoid)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `name` | Block Group 1; Census Tract 9402.01; Skagit County; Washington |
| `median_income` | 96094.0 |
| `edu_bachelors` | 354.0 |
| `edu_masters` | 201.0 |
| `edu_professional` | 40.0 |
| `edu_doctorate` | 18.0 |
| `population` | 1495.0 |
| `median_home_value` | 709400.0 |
| `median_rent` | 1796.0 |
| `state_fips` | 53 |
| `county_fips` | 057 |
| `tract_ce` | 940201 |
| `block_group_ce` | 1 |
| `geoid` | 530579402011 |
| `year` | 2023 |

---

## `public.reference_census_block_groups` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `statefp` | text (text) | YES |  |
| `countyfp` | text (text) | YES |  |
| `tractce` | text (text) | YES |  |
| `blkgrpce` | text (text) | YES |  |
| `geoid` | text (text) | YES |  |
| `geoidfq` | text (text) | YES |  |
| `namelsad` | text (text) | YES |  |
| `mtfcc` | text (text) | YES |  |
| `funcstat` | text (text) | YES |  |
| `aland` | bigint (int8) | YES |  |
| `awater` | bigint (int8) | YES |  |
| `intptlat` | text (text) | YES |  |
| `intptlon` | text (text) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `census_year` | bigint (int8) | YES |  |

### Indexes

- `idx_reference_census_block_groups_geoid`
  ```sql
  CREATE INDEX idx_reference_census_block_groups_geoid ON public.reference_census_block_groups USING btree (geoid)
  ```
- `idx_reference_census_block_groups_geometry`
  ```sql
  CREATE INDEX idx_reference_census_block_groups_geometry ON public.reference_census_block_groups USING gist (geometry)
  ```
- `idx_reference_census_block_groups_countyfp`
  ```sql
  CREATE INDEX idx_reference_census_block_groups_countyfp ON public.reference_census_block_groups USING btree (countyfp)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `statefp` | 53 |
| `countyfp` | 057 |
| `tractce` | 952200 |
| `blkgrpce` | 1 |
| `geoid` | 530579522001 |
| `geoidfq` | 1500000US530579522001 |
| `namelsad` | Block Group 1 |
| `mtfcc` | G5030 |
| `funcstat` | S |
| `aland` | 4946801 |
| `awater` | 619278 |
| `intptlat` | +48.4384760 |
| `intptlon` | -122.3590079 |
| `geometry` | 01030000206E0B00000100000007010000B1590B79DB523341E71A65C7AF232041E1B2D347E9523341794AA666B72420413DE83D45EE523341DAA53E4A56252041FF08E70AF9523341F7CA937CD82... |
| `census_year` | 2023 |

---

## `public.reference_citylimits` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `NAME` | text (text) | YES |  |
| `CITY` | integer (int4) | YES |  |
| `ACRES` | double precision (float8) | YES |  |
| `scgis_SDEA` | double precision (float8) | YES |  |
| `scgis_SD_1` | double precision (float8) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape_STAr` | double precision (float8) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_citylimits_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_citylimits_geometry_gist ON public.reference_citylimits USING gist (geometry)
  ```
- `idx_reference_citylimits_geometry`
  ```sql
  CREATE INDEX idx_reference_citylimits_geometry ON public.reference_citylimits USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `NAME` | CONCRETE |
| `CITY` | 1 |
| `ACRES` | 766.28 |
| `scgis_SDEA` | 0.0 |
| `scgis_SD_1` | 0.0 |
| `GlobalID` | {B80C8A22-132E-4844-9B67-A7787429CD8E} |
| `Shape_STAr` | 33379269.8959 |
| `Shape_STLe` | 34185.8419189 |
| `geometry` | 01030000206E0B00000100000028010000FF5890A23D953541E4247AFAA9342141709F24C69996354113912BAD8F34214111D463DBE99635417EFDDB9F89342141E2101F1B7C9A354167CB708D443... |

---

## `public.reference_data_referencedataimportlog` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `dataset_name` | character varying(100) (varchar) | NO |  |
| `source_path` | character varying(500) (varchar) | NO |  |
| `table_name` | character varying(100) (varchar) | NO |  |
| `success` | boolean (bool) | NO |  |
| `error_message` | text (text) | YES |  |
| `row_count` | integer (int4) | NO |  |
| `srid` | integer (int4) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `reference_data_referencedataimportlog_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_data_referencedataimportlog_pkey ON public.reference_data_referencedataimportlog USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `dataset_name` | Skagit County Parcels |
| `source_path` | /home/django/django_project/reference_data/source_files/shape_files/skagit_parcels.zip |
| `table_name` | reference_parcels |
| `success` | True |
| `error_message` | NULL |
| `row_count` | 83085 |
| `srid` | 2926 |
| `created_at` | 2025-12-08 23:35:22.364973+00:00 |

---

## `public.reference_elevation` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `rid` | integer (int4) | YES |  |
| `filename` | text (text) | YES |  |
| `rast` | raster (raster) | YES |  |

### Indexes

- `idx_reference_elevation_rast`
  ```sql
  CREATE INDEX idx_reference_elevation_rast ON public.reference_elevation USING gist (st_convexhull(rast))
  ```
- `idx_reference_elevation_rast_gist`
  ```sql
  CREATE INDEX idx_reference_elevation_rast_gist ON public.reference_elevation USING gist (st_convexhull(rast))
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `rid` | 1 |
| `filename` | USGS_1_n49w122_20220919.tif |
| `rast` | 0100000100A1C5D42ADE735540A1C5D42ADE7355C0D9AFF7F0BDBE3441D52E341A4F592641000000000000000000000000000000006E0B0000CC0031014AF02374C9F02374C9F02374C9F02374C9F... |

---

## `public.reference_elevation_aspect` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `rid` | integer (int4) | YES |  |
| `rast` | raster (raster) | YES |  |

### Indexes

- `reference_elevation_aspect_st_convexhull_idx`
  ```sql
  CREATE INDEX reference_elevation_aspect_st_convexhull_idx ON public.reference_elevation_aspect USING gist (st_convexhull(rast))
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `rid` | 1 |
| `rast` | 0100000100A1C5D42ADE735540A1C5D42ADE7355C0D9AFF7F0BDBE3441D52E341A4F592641000000000000000000000000000000006E0B0000CC0031014AF02374C9F02374C9F02374C9F02374C9F... |

---

## `public.reference_elevation_slope` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `rid` | integer (int4) | YES |  |
| `rast` | raster (raster) | YES |  |

### Indexes

- `reference_elevation_slope_st_convexhull_idx`
  ```sql
  CREATE INDEX reference_elevation_slope_st_convexhull_idx ON public.reference_elevation_slope USING gist (st_convexhull(rast))
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `rid` | 1 |
| `rast` | 0100000100A1C5D42ADE735540A1C5D42ADE7355C0D9AFF7F0BDBE3441D52E341A4F592641000000000000000000000000000000006E0B0000CC0031014AF02374C9F02374C9F02374C9F02374C9F... |

---

## `public.reference_ems2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_ems2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_ems2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_ems2025_district_raw_geom_geom_idx ON public.reference_ems2025_district_raw USING gist (geom)
  ```
- `reference_ems2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_ems2025_district_raw_pkey ON public.reference_ems2025_district_raw USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ASOTIN |
| `countynum` | 2.0 |
| `distattrib` | 1 |
| `shape_leng` | 433548.162729 |
| `shape_area` | 3737922948.09 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000020000000103000000010000000400000009874ABF64174341D3CECC8C5B770AC1BCAB79E9631743418EA1C80C5E770AC1742150E56317434196B2B28D5A770AC109874ABF6... |

---

## `public.reference_fema_flood_zones` (t)

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 4269)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `objectid` | integer (int4) | YES |  |
| `dfirm_id` | character varying(6) (varchar) | YES |  |
| `version_id` | character varying(11) (varchar) | YES |  |
| `fld_ar_id` | character varying(32) (varchar) | YES |  |
| `study_typ` | character varying(38) (varchar) | YES |  |
| `fld_zone` | character varying(17) (varchar) | YES |  |
| `zone_subty` | character varying(76) (varchar) | YES |  |
| `sfha_tf` | character varying(1) (varchar) | YES |  |
| `static_bfe` | double precision (float8) | YES |  |
| `v_datum` | character varying(17) (varchar) | YES |  |
| `depth` | double precision (float8) | YES |  |
| `len_unit` | character varying(16) (varchar) | YES |  |
| `velocity` | double precision (float8) | YES |  |
| `vel_unit` | character varying(20) (varchar) | YES |  |
| `ar_revert` | character varying(17) (varchar) | YES |  |
| `ar_subtrv` | character varying(57) (varchar) | YES |  |
| `bfe_revert` | double precision (float8) | YES |  |
| `dep_revert` | double precision (float8) | YES |  |
| `dual_zone` | character varying(1) (varchar) | YES |  |
| `source_cit` | character varying(21) (varchar) | YES |  |
| `gfid` | character varying(36) (varchar) | YES |  |
| `shape_length` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `geom` | geometry(MultiPolygon,4269) (geometry) | YES |  |

### Indexes

- `reference_fema_flood_zones_geom_idx`
  ```sql
  CREATE INDEX reference_fema_flood_zones_geom_idx ON public.reference_fema_flood_zones USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `objectid` | 2667 |
| `dfirm_id` | 530317 |
| `version_id` | 1.1.1.0 |
| `fld_ar_id` | 530317_4210 |
| `study_typ` | NP |
| `fld_zone` | AE |
| `zone_subty` | NULL |
| `sfha_tf` | T |
| `static_bfe` | 7.0 |
| `v_datum` | NGVD29 |
| `depth` | -9999.0 |
| `len_unit` | Feet |
| `velocity` | -9999.0 |
| `vel_unit` | NULL |
| `ar_revert` | NULL |
| `ar_subtrv` | NULL |
| `bfe_revert` | -9999.0 |
| `dep_revert` | -9999.0 |
| `dual_zone` | NULL |
| `source_cit` | 530317_STUDY1 |
| `gfid` | NULL |
| `shape_length` | 0.225329773113998 |
| `shape_area` | 0.000861760784835667 |
| `geom` | 0106000020AD10000001000000010300000001000000220200000CF7704D2AA65EC0D8BC885B2A3E4840CCE9516F28A65EC0702159A42F3E4840409D756A27A65EC090CDAB60323E4840D04484F12... |

---

## `public.reference_fema_flood_zones_raw` (t)

**Primary Key:** objectid

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 4269)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `objectid` | integer (int4) | NO | nextval('reference_fema_flood_zones_raw_objectid_seq'::regclass) |
| `dfirm_id` | character varying(6) (varchar) | YES |  |
| `version_id` | character varying(11) (varchar) | YES |  |
| `fld_ar_id` | character varying(32) (varchar) | YES |  |
| `study_typ` | character varying(38) (varchar) | YES |  |
| `fld_zone` | character varying(17) (varchar) | YES |  |
| `zone_subty` | character varying(76) (varchar) | YES |  |
| `sfha_tf` | character varying(1) (varchar) | YES |  |
| `static_bfe` | double precision (float8) | YES |  |
| `v_datum` | character varying(17) (varchar) | YES |  |
| `depth` | double precision (float8) | YES |  |
| `len_unit` | character varying(16) (varchar) | YES |  |
| `velocity` | double precision (float8) | YES |  |
| `vel_unit` | character varying(20) (varchar) | YES |  |
| `ar_revert` | character varying(17) (varchar) | YES |  |
| `ar_subtrv` | character varying(57) (varchar) | YES |  |
| `bfe_revert` | double precision (float8) | YES |  |
| `dep_revert` | double precision (float8) | YES |  |
| `dual_zone` | character varying(1) (varchar) | YES |  |
| `source_cit` | character varying(21) (varchar) | YES |  |
| `gfid` | character varying(36) (varchar) | YES |  |
| `shape_length` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `geom` | geometry(MultiPolygon,4269) (geometry) | YES |  |

### Indexes

- `reference_fema_flood_zones_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_fema_flood_zones_raw_pkey ON public.reference_fema_flood_zones_raw USING btree (objectid)
  ```
- `reference_fema_flood_zones_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_fema_flood_zones_raw_geom_geom_idx ON public.reference_fema_flood_zones_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `objectid` | 1 |
| `dfirm_id` | 53025C |
| `version_id` | 1.1.1.0 |
| `fld_ar_id` | 53025C_3888 |
| `study_typ` | NP |
| `fld_zone` | A |
| `zone_subty` | NULL |
| `sfha_tf` | T |
| `static_bfe` | -9999.0 |
| `v_datum` | NULL |
| `depth` | -9999.0 |
| `len_unit` | NULL |
| `velocity` | -9999.0 |
| `vel_unit` | NULL |
| `ar_revert` | NULL |
| `ar_subtrv` | NULL |
| `bfe_revert` | -9999.0 |
| `dep_revert` | -9999.0 |
| `dual_zone` | NULL |
| `source_cit` | 53025C_FIRM1 |
| `gfid` | NULL |
| `shape_length` | 0.0225886790216156 |
| `shape_area` | 2.38934009231395e-05 |
| `geom` | 0106000020AD100000010000000103000000010000006C000000C8A7108D23EC5DC030DCBAE735984740C8D3A3BD22EC5DC0C82C9BD63998474030F6673721EC5DC0F8411CAC3E984740E0BB482C1... |

---

## `public.reference_fir2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_fir2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_fir2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_fir2025_district_raw_geom_geom_idx ON public.reference_fir2025_district_raw USING gist (geom)
  ```
- `reference_fir2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_fir2025_district_raw_pkey ON public.reference_fir2025_district_raw USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | SPOKANE |
| `countynum` | 32.0 |
| `distattrib` | /10GO |
| `shape_leng` | 106918.34016 |
| `shape_area` | 264927428.77 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000010000000103000000010000007E01000073E264AD48C342419391375E65F30E41C6F7A4364EC3424179F84BE736EB0E41FDC8D0D52DC44241B9D516FB95EB0E4140D08DDB9... |

---

## `public.reference_fire_districts` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `DISTRICT` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_fire_districts_geometry`
  ```sql
  CREATE INDEX idx_reference_fire_districts_geometry ON public.reference_fire_districts USING gist (geometry)
  ```
- `idx_reference_fire_districts_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_fire_districts_geometry_gist ON public.reference_fire_districts USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B0000010000007C0300004319AC1847933241C87C24879B6D2041426FA9897D9332410BC9FFAD966D204195EE5700B493324144DC205A936D2041204A53C1E69332412A9BADF5906... |
| `OBJECTID` | 1 |
| `DISTRICT` | AN |
| `GlobalID` | {75BBA0EC-C6DA-46C0-B54F-CFBCA2FF5D8F} |
| `Shape.STArea()` | 437680510.8382084 |
| `Shape.STLength()` | 180635.45963476392 |

---

## `public.reference_flood_zones` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | YES |  |
| `dfirm_id` | character varying(6) (varchar) | YES |  |
| `version_id` | character varying(11) (varchar) | YES |  |
| `fld_ar_id` | character varying(32) (varchar) | YES |  |
| `study_typ` | character varying(28) (varchar) | YES |  |
| `fld_zone` | character varying(17) (varchar) | YES |  |
| `zone_subty` | character varying(57) (varchar) | YES |  |
| `sfha_tf` | character varying(1) (varchar) | YES |  |
| `static_bfe` | numeric(31,15) (numeric) | YES |  |
| `v_datum` | character varying(17) (varchar) | YES |  |
| `depth` | numeric(31,15) (numeric) | YES |  |
| `len_unit` | character varying(16) (varchar) | YES |  |
| `velocity` | numeric(31,15) (numeric) | YES |  |
| `vel_unit` | character varying(20) (varchar) | YES |  |
| `ar_revert` | character varying(17) (varchar) | YES |  |
| `ar_subtrv` | character varying(57) (varchar) | YES |  |
| `bfe_revert` | numeric(31,15) (numeric) | YES |  |
| `dep_revert` | numeric(31,15) (numeric) | YES |  |
| `dual_zone` | character varying(1) (varchar) | YES |  |
| `source_cit` | character varying(21) (varchar) | YES |  |
| `geometry` | geometry (geometry) | YES |  |

### Indexes

- `idx_reference_flood_zones_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_flood_zones_geometry_gist ON public.reference_flood_zones USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 1 |
| `dfirm_id` | 530317 |
| `version_id` | 1.1.1.0 |
| `fld_ar_id` | 01213S1_4210 |
| `study_typ` | NP |
| `fld_zone` | AE |
| `zone_subty` | NULL |
| `sfha_tf` | T |
| `static_bfe` | 7.000000000000000 |
| `v_datum` | NGVD29 |
| `depth` | -9999.000000000000000 |
| `len_unit` | Feet |
| `velocity` | -9999.000000000000000 |
| `vel_unit` | NULL |
| `ar_revert` | NULL |
| `ar_subtrv` | NULL |
| `bfe_revert` | -9999.000000000000000 |
| `dep_revert` | -9999.000000000000000 |
| `dual_zone` | NULL |
| `source_cit` | 01213S1_STUDY1 |
| `geometry` | 01030000206E0B00000100000022020000789FE000E481324180F37A4C21B02041E83B3EFD00823241EB90B5AA95B020411CAF1AC4108232413B8A76DFD1B02041269D6457188232417B453B8B04B... |

---

## `public.reference_floodways` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | YES |  |
| `dfirm_id` | character varying(6) (varchar) | YES |  |
| `version_id` | character varying(11) (varchar) | YES |  |
| `fld_ln_id` | character varying(32) (varchar) | YES |  |
| `ln_typ` | character varying(26) (varchar) | YES |  |
| `source_cit` | character varying(21) (varchar) | YES |  |
| `geometry` | geometry (geometry) | YES |  |

### Indexes

- `idx_reference_floodways_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_floodways_geometry_gist ON public.reference_floodways USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 1 |
| `dfirm_id` | 530317 |
| `version_id` | 1.1.1.0 |
| `fld_ln_id` | 01213S1_13508 |
| `ln_typ` | SFHA / Flood Zone Boundary |
| `source_cit` | NP |
| `geometry` | 01020000206E0B00007C00000091DE803B0E7D32417F54041E591521415F4A6FE41B7D3241E84204AF3215214187A8717F347D324174A2ADD7FB1421413D9721B5867D3241AA9A563495142141F0E... |

---

## `public.reference_fzn2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_fzn2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_fzn2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_fzn2025_district_raw_pkey ON public.reference_fzn2025_district_raw USING btree (id)
  ```
- `reference_fzn2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_fzn2025_district_raw_geom_geom_idx ON public.reference_fzn2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | PACIFIC |
| `countynum` | 25.0 |
| `distattrib` | 1 |
| `shape_leng` | 341072.782848 |
| `shape_area` | 3853082944.2 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000030000000103000000010000000800000011FFA3C07A7D29419CE353D3A04D04C15B6A2D7ABB7C294111EF48B23A5704C17FDA9567E87929410C6098F3BB5604C1405069D8E... |

---

## `public.reference_historical` (t)

**Geometry Columns:**
- `geometry` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `OBJECTID` | bigint (int8) | YES |  |
| `Type` | integer (int4) | YES |  |
| `Name` | text (text) | YES |  |
| `FileName` | text (text) | YES |  |
| `HistoryID` | bigint (int8) | YES |  |
| `geometry` | geometry(Point,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_historical_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_historical_geometry_gist ON public.reference_historical USING gist (geometry)
  ```
- `idx_reference_historical_geometry`
  ```sql
  CREATE INDEX idx_reference_historical_geometry ON public.reference_historical USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `OBJECTID` | 1 |
| `Type` | 2 |
| `Name` | RIDGEWAY |
| `FileName` | NULL |
| `HistoryID` | 1 |
| `geometry` | 01010000206E0B00006794A858F0413341E408056B8E112041 |

---

## `public.reference_hsp2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_hsp2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_hsp2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_hsp2025_district_raw_pkey ON public.reference_hsp2025_district_raw USING btree (id)
  ```
- `reference_hsp2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_hsp2025_district_raw_geom_geom_idx ON public.reference_hsp2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | CHELAN |
| `countynum` | 4.0 |
| `distattrib` | 1 |
| `shape_leng` | 1072070.87755 |
| `shape_area` | 32640743974.2 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000001000000010300000001000000CD1D00007EE379B1B7EC384100314B5272491A41ED9E7C7EDCED3841CB23E69789441A41432DBA0AF1EF38417DE58D2DBD451A418F5F28806... |

---

## `public.reference_legislative_districts` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `DISTRICT` | bigint (int8) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `SENATOR` | text (text) | YES |  |
| `SEN_WEBSITE` | text (text) | YES |  |
| `REP1` | text (text) | YES |  |
| `REP1_WEBSITE` | text (text) | YES |  |
| `REP2` | text (text) | YES |  |
| `REP2_WEBSITE` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_legislative_districts_geometry`
  ```sql
  CREATE INDEX idx_reference_legislative_districts_geometry ON public.reference_legislative_districts USING gist (geometry)
  ```
- `idx_reference_legislative_districts_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_legislative_districts_geometry_gist ON public.reference_legislative_districts USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B000001000000930A00007AD8EEFBDCBA33411C591E5B040620417873B3BCF2BA3341F88FD22356062041BC41AB9003BB3341C8B959BA92062041F365B1F111BB33418E51F353C90... |
| `OBJECTID` | 6 |
| `DISTRICT` | 39 |
| `GlobalID` | {0E640A45-C748-4CE5-946F-1EB0673F442B} |
| `SENATOR` | Senator, District 39 |
| `SEN_WEBSITE` | http://leg.wa.gov/Senate/Senators/Pages/default.aspx |
| `REP1` | Representative, Position 1 |
| `REP1_WEBSITE` | http://leg.wa.gov/House/Representatives/Pages/default.aspx |
| `REP2` | Representative, Position 2 |
| `REP2_WEBSITE` | http://leg.wa.gov/House/Representatives/Pages/default.aspx |
| `Shape.STArea()` | 42457759146.024994 |
| `Shape.STLength()` | 1233447.763005022 |

---

## `public.reference_lib2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_lib2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_lib2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_lib2025_district_raw_pkey ON public.reference_lib2025_district_raw USING btree (id)
  ```
- `reference_lib2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_lib2025_district_raw_geom_geom_idx ON public.reference_lib2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | YAKIMA |
| `countynum` | 39.0 |
| `distattrib` | 1 |
| `shape_leng` | 83372.8791309 |
| `shape_area` | 28297186.7523 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000090000000103000000010000007B0000008B14278CBF1C3A413B598C0EB73603C14D200B20C51C3A412E18D81BC53603C1A58D2775C51C3A415BF06233DE3703C1BA3055E6B... |

---

## `public.reference_municipal_boundaries` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `area` | double precision (float8) | YES |  |
| `len` | double precision (float8) | YES |  |
| `city` | bigint (int8) | YES |  |
| `name` | text (text) | YES |  |
| `globalid` | text (text) | YES |  |
| `acres` | double precision (float8) | YES |  |
| `SHAPE__Length` | double precision (float8) | YES |  |
| `objectid` | bigint (int8) | YES |  |
| `SHAPE__Area` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_municipal_boundaries_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_municipal_boundaries_geometry_gist ON public.reference_municipal_boundaries USING gist (geometry)
  ```
- `idx_reference_municipal_boundaries_geometry`
  ```sql
  CREATE INDEX idx_reference_municipal_boundaries_geometry ON public.reference_municipal_boundaries USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B000001000000990300003CF2BE92E8BE3241054F59904B6B204119892D0500BF3241A6A6673D156B2041DF1B464918BF32419656AF5EE06A20413844A25831BF32418A3D8001AD6... |
| `area` | 0.0 |
| `len` | 0.0 |
| `city` | 1 |
| `name` | ANACORTES |
| `globalid` | {2389A6C9-8455-4963-956F-C25710060F41} |
| `acres` | 10058.48 |
| `SHAPE__Length` | 180637.9188718256 |
| `objectid` | 6 |
| `SHAPE__Area` | 437680768.5336885 |

---

## `public.reference_npdes_area` (t)

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(MultiPolygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_npdes_area_geometry`
  ```sql
  CREATE INDEX idx_reference_npdes_area_geometry ON public.reference_npdes_area USING gist (geometry)
  ```
- `idx_reference_npdes_area_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_npdes_area_geometry_gist ON public.reference_npdes_area USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01060000206E0B00001400000001030000000100000005000000FB0708568C7A3341F7BB788DBDF81E41E17B9DB97A793341726DA243BDFA1E41C87109F6957833411036D253B7F71E4127B6064B9... |
| `OBJECTID` | 66 |
| `Shape.STArea()` | 556318187.4535404 |
| `Shape.STLength()` | 600686.0933654781 |

---

## `public.reference_parcels` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `PARCELID` | text (text) | YES |  |
| `PARCELTYPE` | double precision (float8) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `shape_length` | double precision (float8) | YES |  |
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_parcels_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_parcels_geometry_gist ON public.reference_parcels USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `PARCELID` | P74512 |
| `PARCELTYPE` | 1.0 |
| `GlobalID` | {F1E46655-95AB-4CD5-A890-6A1A3E784714} |
| `shape_area` | 197616.087268 |
| `shape_length` | 4210.55515426 |
| `geometry` | 01030000206E0B0000010000000F000000B962BA5497E532415738F3EAE0071F4141F72BD2BBE432417FC167FE4C061F410459DD04D5E33241456B8E845F021F418F2965FB5DE33241C09B1AF1580... |

---

## `public.reference_pkr2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_pkr2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_pkr2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_pkr2025_district_raw_pkey ON public.reference_pkr2025_district_raw USING btree (id)
  ```
- `reference_pkr2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_pkr2025_district_raw_geom_geom_idx ON public.reference_pkr2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ADAMS |
| `countynum` | 1.0 |
| `distattrib` | 1 |
| `shape_leng` | 320654.808723 |
| `shape_area` | 6131454600.34 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000001000000010300000001000000C7000000C579D5BD6E0B4041177160ECC126DAC0E5AC6481960B4041E53FBE93D8BBDCC095DFCA8CA50B40410884CAC6BE58DFC0DF925D3EB... |

---

## `public.reference_precinct_lookup` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `norm_prec_name` | text (text) | YES |  |
| `norm_county` | text (text) | YES |  |
| `prec_code` | bigint (int8) | YES |  |

### Indexes

- `idx_rpl_name_county`
  ```sql
  CREATE UNIQUE INDEX idx_rpl_name_county ON public.reference_precinct_lookup USING btree (norm_prec_name, norm_county)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `norm_prec_name` | MOUNT VERNON 15 |
| `norm_county` | SKAGIT |
| `prec_code` | 315 |

---

## `public.reference_prt2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_prt2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_prt2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_prt2025_district_raw_geom_geom_idx ON public.reference_prt2025_district_raw USING gist (geom)
  ```
- `reference_prt2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_prt2025_district_raw_pkey ON public.reference_prt2025_district_raw USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ADAMS |
| `countynum` | 1.0 |
| `distattrib` | 1 |
| `shape_leng` | 320654.808723 |
| `shape_area` | 6131454600.34 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000001000000010300000001000000C7000000C579D5BD6E0B4041177160ECC126DAC0E5AC6481960B4041E53FBE93D8BBDCC095DFCA8CA50B40410884CAC6BE58DFC07F925D3EB... |

---

## `public.reference_ptcty2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_ptcty2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_ptcty2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_ptcty2025_district_raw_pkey ON public.reference_ptcty2025_district_raw USING btree (id)
  ```
- `reference_ptcty2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_ptcty2025_district_raw_geom_geom_idx ON public.reference_ptcty2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | GRAYS HARBOR |
| `countynum` | 14.0 |
| `distattrib` | ABERDEEN |
| `shape_leng` | 159883.875536 |
| `shape_area` | 350146465.746 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000030000000103000000010000004800000087124C89A9FD2B4177313CADD39DC3403FE15C32B1FD2B415EF9E8824DFAC240387E35B243F42B419082B2835811C340192A275CF... |

---

## `public.reference_public_water_systems` (t)

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(MultiPolygon,4326) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Water_System_Name` | text (text) | YES |  |
| `PWS_ID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_public_water_systems_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_public_water_systems_geometry_gist ON public.reference_public_water_systems USING gist (geometry)
  ```
- `idx_reference_public_water_systems_geometry`
  ```sql
  CREATE INDEX idx_reference_public_water_systems_geometry ON public.reference_public_water_systems USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 0106000020E610000001000000010300000002000000A7010000C06C7DB0EA715EC04730B25C5A4548401A69FDA916725EC0336BE7975A45484078A2418516725EC0FFC10A283A454840D2119163F... |
| `OBJECTID` | 1 |
| `Water_System_Name` | TOWN OF CONCRETE |
| `PWS_ID` | 03950 |
| `Shape.STArea()` | 41348717.287315115 |
| `Shape.STLength()` | 44806.66733919776 |

---

## `public.reference_public_water_systems_2926` (v)

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 4326)
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(MultiPolygon,4326) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Water_System_Name` | text (text) | YES |  |
| `PWS_ID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 0106000020E610000001000000010300000002000000A7010000C06C7DB0EA715EC04730B25C5A4548401A69FDA916725EC0336BE7975A45484078A2418516725EC0FFC10A283A454840D2119163F... |
| `OBJECTID` | 1 |
| `Water_System_Name` | TOWN OF CONCRETE |
| `PWS_ID` | 03950 |
| `Shape.STArea()` | 41348717.287315115 |
| `Shape.STLength()` | 44806.66733919776 |
| `geom_2926` | 01060000206E0B000001000000010300000002000000A7010000B94EEF0D23883541A42639E5EE3421417F9D02EF98853541A3A71D1004352141FAD6B899968535415046D1CB31322141346EACAF9... |

---

## `public.reference_pud2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_pud2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_pud2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_pud2025_district_raw_pkey ON public.reference_pud2025_district_raw USING btree (id)
  ```
- `reference_pud2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_pud2025_district_raw_geom_geom_idx ON public.reference_pud2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ASOTIN |
| `countynum` | 2.0 |
| `distattrib` | 1 |
| `shape_leng` | 110632.385982 |
| `shape_area` | 539663596.747 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B00000100000001030000000100000096000000B611AEE31BD3434143B804F4DA1A07C171D0F4330CD343419438F53A893507C16AFC6B5D1ED343417529A77A0C5407C1A5D820C11... |

---

## `public.reference_roads` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ROAD_NO` | text (text) | YES |  |
| `ROAD_NM` | text (text) | YES |  |
| `ROAD_DES` | text (text) | YES |  |
| `TYPE` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_roads_geometry`
  ```sql
  CREATE INDEX idx_reference_roads_geometry ON public.reference_roads USING gist (geometry)
  ```
- `reference_roads_geom_gist`
  ```sql
  CREATE INDEX reference_roads_geom_gist ON public.reference_roads USING gist (geometry)
  ```
- `idx_reference_roads_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_roads_geometry_gist ON public.reference_roads USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ROAD_NO` | 00111 |
| `ROAD_NM` | BENJAMIN |
| `ROAD_DES` | Street |
| `TYPE` | I |
| `GlobalID` | {B1DB157B-B3A5-440A-BC9C-12705E4EFB12} |
| `Shape_STLe` | 640.785612083 |
| `geometry` | 01020000206E0B00000300000095B23B96FFA63541513A94380E1C2141519CBDD644A83541D9015AD9FF1B2141AE18813780A9354104D3A2FAF11B2141 |

---

## `public.reference_roads_major` (v)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ROAD_NO` | text (text) | YES |  |
| `ROAD_NM` | text (text) | YES |  |
| `ROAD_DES` | text (text) | YES |  |
| `TYPE` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `ROAD_NO` | 00519 |
| `ROAD_NM` | AVALON HIDEAWAY |
| `ROAD_DES` | Lane |
| `TYPE` | P |
| `GlobalID` | {299B047F-709F-4E23-B309-D204E06A2623} |
| `Shape_STLe` | 7291.3673892 |
| `geometry` | 01020000206E0B0000D00000008510B26639EB3341E97E55444C651D416010B26639EB334133F513644D651D410FF3B1263BEB33416AE2DD053A661D41C3ECB1A63CEB3341F3471FE664661D41FCE... |

---

## `public.reference_roads_minor` (v)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ROAD_NO` | text (text) | YES |  |
| `ROAD_NM` | text (text) | YES |  |
| `ROAD_DES` | text (text) | YES |  |
| `TYPE` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `ROAD_NO` | 00111 |
| `ROAD_NM` | BENJAMIN |
| `ROAD_DES` | Street |
| `TYPE` | I |
| `GlobalID` | {B1DB157B-B3A5-440A-BC9C-12705E4EFB12} |
| `Shape_STLe` | 640.785612083 |
| `geometry` | 01020000206E0B00000300000095B23B96FFA63541513A94380E1C2141519CBDD644A83541D9015AD9FF1B2141AE18813780A9354104D3A2FAF11B2141 |

---

## `public.reference_sch2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_sch2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_sch2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_sch2025_district_raw_pkey ON public.reference_sch2025_district_raw USING btree (id)
  ```
- `reference_sch2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_sch2025_district_raw_geom_geom_idx ON public.reference_sch2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | FRANKLIN |
| `countynum` | 11.0 |
| `distattrib` | 1 |
| `shape_leng` | 454122.374938 |
| `shape_area` | 8453589335.58 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000002000000010300000001000000040000006D4C4D512D953F41BE972477142F07C1CAF9A11425953F41D01A8635912E07C1A0A8D1D737953F418062A6A3902F07C16D4C4D512... |

---

## `public.reference_school_districts` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `DIST_NUM` | bigint (int8) | YES |  |
| `NAME` | text (text) | YES |  |
| `COUNTY` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_school_districts_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_school_districts_geometry_gist ON public.reference_school_districts USING gist (geometry)
  ```
- `idx_reference_school_districts_geometry`
  ```sql
  CREATE INDEX idx_reference_school_districts_geometry ON public.reference_school_districts USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B0000010000001402000047102F3400E73541CFF125DF93AC2241F098703410E73541E47867FFE3AC2241E49770342DE7354131122CE02BAD2241829670345BE73541879C6DC009A... |
| `OBJECTID` | 1 |
| `DIST_NUM` | 11 |
| `NAME` | CONCRETE |
| `COUNTY` | WHATCOM |
| `GlobalID` | {6EC61EE6-4FCF-48FD-9D1B-A4E0E84B3034} |
| `Shape.STArea()` | 1973336019.1740148 |
| `Shape.STLength()` | 255695.018567758 |

---

## `public.reference_sew2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_sew2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_sew2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_sew2025_district_raw_geom_geom_idx ON public.reference_sew2025_district_raw USING gist (geom)
  ```
- `reference_sew2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_sew2025_district_raw_pkey ON public.reference_sew2025_district_raw USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | CHELAN |
| `countynum` | 4.0 |
| `distattrib` | 1 |
| `shape_leng` | 37247.9811382 |
| `shape_area` | 46632601.0556 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000001000000010300000001000000B3010000A73A7A00DDCB3B4127854A2C52D9124170A6A15E11CC3B41430FCBC4EDD81241B2028D1972CC3B419A818F6AF2D81241DE32B8BE6... |

---

## `public.reference_sewer_districts` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Health.SDEADM.Sewer_District_Areas.AREA` | text (text) | YES |  |
| `PERIMETER` | text (text) | YES |  |
| `SEW_DIST_` | text (text) | YES |  |
| `SEW_DIST_ID` | text (text) | YES |  |
| `BNDRY` | text (text) | YES |  |
| `RISK` | text (text) | YES |  |
| `SEWER_DIST` | bigint (int8) | YES |  |
| `ACRES` | double precision (float8) | YES |  |
| `PERCENT_` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_sewer_districts_geometry`
  ```sql
  CREATE INDEX idx_reference_sewer_districts_geometry ON public.reference_sewer_districts USING gist (geometry)
  ```
- `idx_reference_sewer_districts_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_sewer_districts_geometry_gist ON public.reference_sewer_districts USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B00000200000025020000AD6106370FDE3341389B7538B76B1F4150BB7FAA8EDB3341C52DDF41B76B1F4147530F601ADB33411F2C3542B76B1F41E5FC520AF8DA33412D212389646... |
| `OBJECTID` | 26 |
| `Health.SDEADM.Sewer_District_Areas.AREA` | NULL |
| `PERIMETER` | NULL |
| `SEW_DIST_` | NULL |
| `SEW_DIST_ID` | NULL |
| `BNDRY` | NULL |
| `RISK` | NULL |
| `SEWER_DIST` | 2 |
| `ACRES` | 1121.15 |
| `PERCENT_` | NULL |
| `GlobalID` | {B96C5583-8B50-42F8-A187-3E25296C9682} |
| `Shape.STArea()` | 48858208.36047718 |
| `Shape.STLength()` | 89339.49627876168 |

---

## `public.reference_shoreline_jurisdiction` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Magt_unit_` | bigint (int8) | YES |  |
| `Reach_no` | bigint (int8) | YES |  |
| `Waterbody` | text (text) | YES |  |
| `Hydrologic` | double precision (float8) | YES |  |
| `Hyporheic` | double precision (float8) | YES |  |
| `Vegetation` | double precision (float8) | YES |  |
| `Habitat` | double precision (float8) | YES |  |
| `Env_Des` | text (text) | YES |  |
| `Total_avg` | double precision (float8) | YES |  |
| `COUNT_Reac` | bigint (int8) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_shoreline_jurisdiction_geometry`
  ```sql
  CREATE INDEX idx_reference_shoreline_jurisdiction_geometry ON public.reference_shoreline_jurisdiction USING gist (geometry)
  ```
- `idx_reference_shoreline_jurisdiction_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_shoreline_jurisdiction_geometry_gist ON public.reference_shoreline_jurisdiction USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B0000010000007C020000C2094758BE0333417CB7E7B5A63C2241B6C46833B80333419E0FB1DBB73C22416325E4E5AF0333413D57A617CC3C2241219EC480AF0333417BD19CFDCC3... |
| `OBJECTID` | 1 |
| `Magt_unit_` | 1 |
| `Reach_no` | 1 |
| `Waterbody` | Puget Sound |
| `Hydrologic` | 3.29999995 |
| `Hyporheic` | 0.0 |
| `Vegetation` | 3.5 |
| `Habitat` | 3.79999995 |
| `Env_Des` | Rural Conservancy |
| `Total_avg` | 3.5 |
| `COUNT_Reac` | 1 |
| `Shape.STArea()` | 1851479.6822586928 |
| `Shape.STLength()` | 18949.504106711895 |

---

## `public.reference_skagit_mitigation` (t)

**Primary Key:** id

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO | nextval('reference_skagit_mitigation_id_seq'::regclass) |
| `layer_id` | integer (int4) | YES |  |
| `layer_name` | text (text) | YES |  |
| `mitigation_class` | text (text) | YES |  |
| `source_layer` | text (text) | YES |  |
| `attributes` | jsonb (jsonb) | YES |  |
| `imported_at` | timestamp with time zone (timestamptz) | YES | now() |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `reference_skagit_mitigation_class_idx`
  ```sql
  CREATE INDEX reference_skagit_mitigation_class_idx ON public.reference_skagit_mitigation USING btree (mitigation_class)
  ```
- `reference_skagit_mitigation_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_skagit_mitigation_pkey ON public.reference_skagit_mitigation USING btree (id)
  ```
- `reference_skagit_mitigation_layer_idx`
  ```sql
  CREATE INDEX reference_skagit_mitigation_layer_idx ON public.reference_skagit_mitigation USING btree (layer_id)
  ```
- `reference_skagit_mitigation_geom_gix`
  ```sql
  CREATE INDEX reference_skagit_mitigation_geom_gix ON public.reference_skagit_mitigation USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `layer_id` | 4 |
| `layer_name` | RedZoneParcels |
| `mitigation_class` | RED |
| `source_layer` | RedZoneParcels |
| `attributes` | NULL |
| `imported_at` | 2025-12-12 18:53:57.422164+00:00 |
| `geometry` | 01030000206E0B0000010000002B0000009627EE38153B3641F1219576E742204144343ADA003B364108E24BBEC342204123252F84EF3A36419CEF65439F422041B32BD389D93A3641824AA3F3644... |

---

## `public.reference_skagit_mitigation_poly` (v)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | YES |  |
| `layer_id` | integer (int4) | YES |  |
| `layer_name` | text (text) | YES |  |
| `mitigation_class` | text (text) | YES |  |
| `source_layer` | text (text) | YES |  |
| `attributes` | jsonb (jsonb) | YES |  |
| `imported_at` | timestamp with time zone (timestamptz) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `mitigation_rank` | integer (int4) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 2 |
| `layer_id` | 4 |
| `layer_name` | RedZoneParcels |
| `mitigation_class` | RED |
| `source_layer` | RedZoneParcels |
| `attributes` | NULL |
| `imported_at` | 2025-12-12 18:53:57.422164+00:00 |
| `geometry` | 01030000206E0B0000010000002B0000009627EE38153B3641F1219576E742204144343ADA003B364108E24BBEC342204123252F84EF3A36419CEF65439F422041B32BD389D93A3641824AA3F3644... |
| `mitigation_rank` | 1 |

---

## `public.reference_skagit_mitigation_zones` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `Id` | bigint (int8) | YES |  |
| `Shape__Area` | double precision (float8) | YES |  |
| `Shape__Length` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_skagit_mitigation_zones_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_skagit_mitigation_zones_geometry_gist ON public.reference_skagit_mitigation_zones USING gist (geometry)
  ```
- `idx_reference_skagit_mitigation_zones_geometry`
  ```sql
  CREATE INDEX idx_reference_skagit_mitigation_zones_geometry ON public.reference_skagit_mitigation_zones USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01030000206E0B000001000000D0010000CD084C09C95A5EC01F1CF70B854748406F4EF2E8B15A5EC068F71774834748409925C80C935A5EC04048139884474840D495AF067C5A5EC0A6A998E4874... |
| `OBJECTID` | 1 |
| `Id` | 0 |
| `Shape__Area` | 117699131.99914551 |
| `Shape__Length` | 76303.37422374156 |

---

## `public.reference_swsl_streams` (t)

**Geometry Columns:**
- `geometry` (LINESTRING, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(LineString,2926) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `TYPE` | text (text) | YES |  |
| `WRIA_STRM_NO` | bigint (int8) | YES |  |
| `Name` | text (text) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_swsl_streams_geometry`
  ```sql
  CREATE INDEX idx_reference_swsl_streams_geometry ON public.reference_swsl_streams USING gist (geometry)
  ```
- `idx_reference_swsl_streams_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_swsl_streams_geometry_gist ON public.reference_swsl_streams USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 01020000206E0B00008A00000078075AF66E3F3341A08529C34D21224173BE78B6CC3F33417D70E502C520224173B2ADD62440334155122923AD2022413BBAF3B69E40334146CE302372202241968... |
| `OBJECTID` | 1 |
| `TYPE` | LFS |
| `WRIA_STRM_NO` | 10650 |
| `Name` | Whitehall Creek |
| `Shape.STLength()` | 13119.380933811048 |

---

## `public.reference_tax_district` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_tax_district_id_seq'::regclass) |
| `district_type` | text (text) | NO |  |
| `district_code` | text (text) | NO |  |
| `district_name` | text (text) | YES |  |
| `county_name` | text (text) | YES |  |
| `county_num` | integer (int4) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_tax_district_geom_idx`
  ```sql
  CREATE INDEX reference_tax_district_geom_idx ON public.reference_tax_district USING gist (geom)
  ```
- `reference_tax_district_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_tax_district_pkey ON public.reference_tax_district USING btree (id)
  ```
- `reference_tax_district_district_type_district_code_idx`
  ```sql
  CREATE INDEX reference_tax_district_district_type_district_code_idx ON public.reference_tax_district USING btree (district_type, district_code)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `district_type` | cemetery |
| `district_code` | 1 |
| `district_name` | NULL |
| `county_name` | ADAMS |
| `county_num` | 1 |
| `geom` | 01060000206E0B00000100000001030000000100000002010000492F254F0A9D414179216F7DE61BD6C0F450C7B7C29C4141272E287BDCC0D8C065D3FF497F9241413A24003F04B9D8C07739EE3E2... |

---

## `public.reference_tca2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_tca2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_tca2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_tca2025_district_raw_pkey ON public.reference_tca2025_district_raw USING btree (id)
  ```
- `reference_tca2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_tca2025_district_raw_geom_geom_idx ON public.reference_tca2025_district_raw USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ADAMS |
| `countynum` | 1.0 |
| `distattrib` | 0001 |
| `shape_leng` | 74401.2754482 |
| `shape_area` | 61279656.9152 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B000001000000010300000001000000AB0000000B787A52D13041418398DA43F2AFEC40843596A6C8304141554E0C68EE75EC4023B9BEB5C8304141E99D999AEE75EC406BB3CFC3C... |

---

## `public.reference_voting` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `PRECINCT` | text (text) | YES |  |
| `STATUS` | text (text) | YES |  |
| `PREC_NO` | bigint (int8) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape_STAr` | double precision (float8) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_voting_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_voting_geometry_gist ON public.reference_voting USING gist (geometry)
  ```
- `idx_reference_voting_geometry`
  ```sql
  CREATE INDEX idx_reference_voting_geometry ON public.reference_voting USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `PRECINCT` | MINKLER |
| `STATUS` | COUNTY |
| `PREC_NO` | 139 |
| `GlobalID` | {1B4175C5-D577-4943-B3E7-189D8DF3B9FD} |
| `Shape_STAr` | 1111994167.67 |
| `Shape_STLe` | 190317.373342 |
| `geometry` | 01030000206E0B000001000000F7030000B838825A26A0344141A71689D139224177CAD751559F34419B2F874071102241B4DFAF49FE9E344137CC03FAC5E7214151EC87418E9E344106584494C3B... |

---

## `public.reference_votingprecinct` (t)

**Primary Key:** ogc_fid

**Geometry Columns:**
- `geom_2926` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | NO | nextval('reference_votingprecinct_ogc_fid_seq'::regclass) |
| `prec_code` | bigint (int8) | YES |  |
| `prec_name` | character varying(50) (varchar) | YES |  |
| `county_fips` | integer (int4) | YES |  |
| `county_name` | character varying(20) (varchar) | YES |  |
| `county_code` | character varying(2) (varchar) | YES |  |
| `state_code` | character varying(10) (varchar) | YES |  |
| `geom_2926` | geometry(Polygon,2926) (geometry) | YES |  |
| `area_sq_m` | double precision (float8) | YES |  |

### Indexes

- `idx_vp_prec`
  ```sql
  CREATE INDEX idx_vp_prec ON public.reference_votingprecinct USING btree (prec_code)
  ```
- `reference_votingprecinct_geom_2926_geom_idx`
  ```sql
  CREATE INDEX reference_votingprecinct_geom_2926_geom_idx ON public.reference_votingprecinct USING gist (geom_2926)
  ```
- `reference_votingprecinct_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_votingprecinct_pkey ON public.reference_votingprecinct USING btree (ogc_fid)
  ```
- `idx_vp_county`
  ```sql
  CREATE INDEX idx_vp_county ON public.reference_votingprecinct USING btree (county_fips)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 7826 |
| `prec_code` | 211 |
| `prec_name` | 211 |
| `county_fips` | 53073 |
| `county_name` | Whatcom |
| `county_code` | WM |
| `state_code` | WM00000211 |
| `geom_2926` | 01030000206E0B0000010000009B000000AC9EF4A16E303341D10373A3BA0A2441096CF40B4C3033419AF0EE12250A244103D8825F45303341CD54174B150A24416E142B93BB2B3341DF4F5F37E3F... |
| `area_sq_m` | 3443525131.2137947 |

---

## `public.reference_votingprecinct_base` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |
| `area_sq_m` | double precision (float8) | YES |  |

### Indexes

- `idx_vpb_prec`
  ```sql
  CREATE UNIQUE INDEX idx_vpb_prec ON public.reference_votingprecinct_base USING btree (prec_code)
  ```
- `idx_vpb_geom`
  ```sql
  CREATE INDEX idx_vpb_geom ON public.reference_votingprecinct_base USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 0 |
| `geom_2926` | 01030000206E0B000001000000090000006D5A84717D0F324193CA3F9A05762641A96E7AF5750F3241305B190B95732641EE84CD3CAC0E324189B44541A2732641FEE932C92D0E32411297DEA9AA7... |
| `area_sq_m` | 168603.44073102708 |

---

## `public.reference_votingprecinct_norm` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `norm_prec_name` | text (text) | YES |  |
| `norm_county` | text (text) | YES |  |

### Indexes

- `idx_rvp_name_county`
  ```sql
  CREATE INDEX idx_rvp_name_county ON public.reference_votingprecinct_norm USING btree (norm_prec_name, norm_county)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 211 |
| `norm_prec_name` | BENGE |
| `norm_county` | ADAMS |

---

## `public.reference_votingprecinct_split` (t)

**Primary Key:** ogc_fid

**Geometry Columns:**
- `geom_2926` (POLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ogc_fid` | integer (int4) | NO | nextval('reference_votingprecinct_split_ogc_fid_seq'::regclass) |
| `prec_part_name` | character varying(50) (varchar) | YES |  |
| `county_fips` | integer (int4) | YES |  |
| `county_name` | character varying(20) (varchar) | YES |  |
| `county_code` | character varying(2) (varchar) | YES |  |
| `prec_code` | bigint (int8) | YES |  |
| `state_code` | character varying(10) (varchar) | YES |  |
| `geom_2926` | geometry(Polygon,2926) (geometry) | YES |  |
| `area_sq_m` | double precision (float8) | YES |  |

### Indexes

- `idx_vps_county`
  ```sql
  CREATE INDEX idx_vps_county ON public.reference_votingprecinct_split USING btree (county_fips)
  ```
- `idx_vps_prec`
  ```sql
  CREATE INDEX idx_vps_prec ON public.reference_votingprecinct_split USING btree (prec_code)
  ```
- `reference_votingprecinct_split_geom_2926_geom_idx`
  ```sql
  CREATE INDEX reference_votingprecinct_split_geom_2926_geom_idx ON public.reference_votingprecinct_split USING gist (geom_2926)
  ```
- `reference_votingprecinct_split_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_votingprecinct_split_pkey ON public.reference_votingprecinct_split USING btree (ogc_fid)
  ```
- `idx_vps_geom`
  ```sql
  CREATE INDEX idx_vps_geom ON public.reference_votingprecinct_split USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ogc_fid` | 29 |
| `prec_part_name` | 0002.03 |
| `county_fips` | 53013 |
| `county_name` | Columbia |
| `county_code` | CU |
| `prec_code` | 2 |
| `state_code` | CU00000002 |
| `geom_2926` | 01030000206E0B0000030000006300000035E53897EDE04141F9D3E1E5C47C0EC108B742018AE3414152B281FC357B0EC1EC734A7411E641419E5C3D83B3790EC1388B330EA3E841411220EEEC2A7... |
| `area_sq_m` | -42322449.49962844 |

---

## `public.reference_votingprecinct_valid` (m)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `prec_code` | bigint (int8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Indexes

- `idx_vpv_geom`
  ```sql
  CREATE INDEX idx_vpv_geom ON public.reference_votingprecinct_valid USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `prec_code` | 211 |
| `geom_2926` | 01030000206E0B000001000000590200009200FFF566FD414191CBF556D60799C0C994A307D0FD414106CCA67A7508BBC0F9AFF4AF26FE41416DB008F288A5C6C08D17F93A33FE4141C395D4DFE7F... |

---

## `public.reference_wat2025_district_raw` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | integer (int4) | NO | nextval('reference_wat2025_district_raw_id_seq'::regclass) |
| `countyname` | character varying (varchar) | YES |  |
| `countynum` | double precision (float8) | YES |  |
| `distattrib` | character varying (varchar) | YES |  |
| `shape_leng` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `descriptio` | character varying (varchar) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `reference_wat2025_district_raw_geom_geom_idx`
  ```sql
  CREATE INDEX reference_wat2025_district_raw_geom_geom_idx ON public.reference_wat2025_district_raw USING gist (geom)
  ```
- `reference_wat2025_district_raw_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_wat2025_district_raw_pkey ON public.reference_wat2025_district_raw USING btree (id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `countyname` | ADAMS |
| `countynum` | 1.0 |
| `distattrib` | 1 |
| `shape_leng` | 23245.3175934 |
| `shape_area` | 14773744.7558 |
| `descriptio` | NULL |
| `geom` | 01060000206E0B0000010000000103000000010000009400000098843D1EF6513F41E0DF8013480CEDC082EEC8F5E2513F41AF699F6FE40CEDC0328E1D55CD513F416ED29FB8E70CEDC0D77FBB4CC... |

---

## `public.reference_water_diversions` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `d_point_id` | double precision (float8) | YES |  |
| `d_point_type_cd` | text (text) | YES |  |
| `location_cd` | text (text) | YES |  |
| `assoc_fl` | text (text) | YES |  |
| `misc_cd` | text (text) | YES |  |
| `position_with_cd` | text (text) | YES |  |
| `active_dt` | timestamp without time zone (timestamp) | YES |  |
| `inactive_dt` | timestamp without time zone (timestamp) | YES |  |
| `update_td` | timestamp without time zone (timestamp) | YES |  |
| `update_user_id` | text (text) | YES |  |
| `comment_ds` | text (text) | YES |  |
| `eventdate` | timestamp without time zone (timestamp) | YES |  |
| `created_user_id` | text (text) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |
| `d_point_wr_doc_id` | double precision (float8) | YES |  |
| `wr_doc_nr` | text (text) | YES |  |
| `wr_doc_id` | double precision (float8) | YES |  |
| `active_dt_attr` | timestamp without time zone (timestamp) | YES |  |
| `inactive_dt_attr` | timestamp without time zone (timestamp) | YES |  |
| `update_td_attr` | timestamp without time zone (timestamp) | YES |  |
| `update_user_id_attr` | text (text) | YES |  |
| `created_td_attr` | timestamp without time zone (timestamp) | YES |  |
| `created_user_id_attr` | text (text) | YES |  |

### Indexes

- `idx_reference_water_diversions_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_water_diversions_geometry_gist ON public.reference_water_diversions USING gist (geometry)
  ```
- `idx_reference_water_diversions_geometry`
  ```sql
  CREATE INDEX idx_reference_water_diversions_geometry ON public.reference_water_diversions USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `d_point_id` | 200801.0 |
| `d_point_type_cd` | WL |
| `location_cd` | U |
| `assoc_fl` | N |
| `misc_cd` |   |
| `position_with_cd` | S |
| `active_dt` | NULL |
| `inactive_dt` | NULL |
| `update_td` | 2013-03-28 09:58:00 |
| `update_user_id` | "ECY\DKRO461" |
| `comment_ds` | NULL |
| `eventdate` | NULL |
| `created_user_id` | NULL |
| `geometry` | 01010000206E0B00007DC52329E3B23A411C05824A28A102C1 |
| `d_point_wr_doc_id` | NULL |
| `wr_doc_nr` | NULL |
| `wr_doc_id` | NULL |
| `active_dt_attr` | NULL |
| `inactive_dt_attr` | NULL |
| `update_td_attr` | NULL |
| `update_user_id_attr` | NULL |
| `created_td_attr` | NULL |
| `created_user_id_attr` | NULL |

---

## `public.reference_water_pou` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `wr_doc_id` | double precision (float8) | YES |  |
| `wr_doc_pou_id` | double precision (float8) | YES |  |
| `fill_cd` | double precision (float8) | YES |  |
| `wr_doc_nr` | text (text) | YES |  |
| `wr_doc_type_cd` | text (text) | YES |  |
| `quality_cd` | text (text) | YES |  |
| `misc_cd` | text (text) | YES |  |
| `position_with_cd` | text (text) | YES |  |
| `active_dt` | timestamp without time zone (timestamp) | YES |  |
| `inactive_dt` | timestamp without time zone (timestamp) | YES |  |
| `update_td` | timestamp without time zone (timestamp) | YES |  |
| `update_user_id` | text (text) | YES |  |
| `comment_ds` | text (text) | YES |  |
| `created_td` | timestamp without time zone (timestamp) | YES |  |
| `created_user_id` | text (text) | YES |  |
| `shape_length` | double precision (float8) | YES |  |
| `shape_area` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_water_pou_geometry`
  ```sql
  CREATE INDEX idx_reference_water_pou_geometry ON public.reference_water_pou USING gist (geometry)
  ```
- `idx_reference_water_pou_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_water_pou_geometry_gist ON public.reference_water_pou USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `wr_doc_id` | 2084118.0 |
| `wr_doc_pou_id` | NULL |
| `fill_cd` | 7.0 |
| `wr_doc_nr` | GWC01066-D |
| `wr_doc_type_cd` | CE |
| `quality_cd` | G |
| `misc_cd` | RECHECKED\WWT |
| `position_with_cd` | S |
| `active_dt` | NULL |
| `inactive_dt` | NULL |
| `update_td` | 2009-01-23 11:18:38 |
| `update_user_id` | "ECY\DKRO461" |
| `comment_ds` | NULL |
| `created_td` | NULL |
| `created_user_id` | NULL |
| `shape_length` | 32011.934921794436 |
| `shape_area` | 35404849.05028143 |
| `geometry` | 01060000206E0B0000010000000103000000010000000A0000003AB090BF723B3D41182830C9E1EF01C1AF3CD3C6AF3B3D410A3654D2E64501C118648BF20D463D4115F2BBA6944501C17DAB878CA... |

---

## `public.reference_wellhead_protection` (t)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,4326) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `TYPE` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |

### Indexes

- `idx_reference_wellhead_protection_geometry`
  ```sql
  CREATE INDEX idx_reference_wellhead_protection_geometry ON public.reference_wellhead_protection USING gist (geometry)
  ```
- `idx_reference_wellhead_protection_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_wellhead_protection_geometry_gist ON public.reference_wellhead_protection USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 0103000020E610000001000000690100004B3A2EF969955EC0FE95B7E90A4F4840F4AC7F9E68955EC0B9958FF50A4F484083FBF64367955EC0D13D750B0B4F4840881BB4EB65955EC0697E7C280B4... |
| `OBJECTID` | 1 |
| `TYPE` | WELL |
| `GlobalID` | {41F35099-AAD7-419D-B043-94D2F3AB55E3} |
| `Shape.STArea()` | 4121466.028507806 |
| `Shape.STLength()` | 7196.762685806 |

---

## `public.reference_wellhead_protection_2926` (v)

**Geometry Columns:**
- `geometry` (POLYGON, SRID 4326)
- `geom_2926` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geometry` | geometry(Polygon,4326) (geometry) | YES |  |
| `OBJECTID` | bigint (int8) | YES |  |
| `TYPE` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `Shape.STArea()` | double precision (float8) | YES |  |
| `Shape.STLength()` | double precision (float8) | YES |  |
| `geom_2926` | geometry (geometry) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `geometry` | 0103000020E610000001000000690100004B3A2EF969955EC0FE95B7E90A4F4840F4AC7F9E68955EC0B9958FF50A4F484083FBF64367955EC0D13D750B0B4F4840881BB4EB65955EC0697E7C280B4... |
| `OBJECTID` | 1 |
| `TYPE` | WELL |
| `GlobalID` | {41F35099-AAD7-419D-B043-94D2F3AB55E3} |
| `Shape.STArea()` | 4121466.028507806 |
| `Shape.STLength()` | 7196.762685806 |
| `geom_2926` | 01030000206E0B0000010000006901000085D9F6DB737D3341DD2FB9D4581D2241DB39F4DB877D33416528B914591D22413A9AF1DB9B7D33414482A3345A1D2241A0FEEEBBAF7D33416847A3F45B1... |

---

## `public.reference_wells` (t)

**Geometry Columns:**
- `geometry` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `well_log_id` | integer (int4) | YES |  |
| `well_tag_id` | text (text) | YES |  |
| `project_tag_nr` | text (text) | YES |  |
| `nit_id_nr` | text (text) | YES |  |
| `county_id` | double precision (float8) | YES |  |
| `region_cd` | double precision (float8) | YES |  |
| `well_log_recv_dt` | text (text) | YES |  |
| `well_log_img_nm` | text (text) | YES |  |
| `well_diameter_qt` | double precision (float8) | YES |  |
| `well_depth` | double precision (float8) | YES |  |
| `well_comp_dt` | text (text) | YES |  |
| `well_owner_nm` | text (text) | YES |  |
| `use_type` | text (text) | YES |  |
| `well_address_ds` | text (text) | YES |  |
| `driller_nr` | text (text) | YES |  |
| `township_nr` | text (text) | YES |  |
| `township_fraction_nr` | text (text) | YES |  |
| `township_dir_cd` | text (text) | YES |  |
| `range_nr` | text (text) | YES |  |
| `range_fraction_nr` | text (text) | YES |  |
| `range_dir_cd` | text (text) | YES |  |
| `section_nr` | text (text) | YES |  |
| `qtr_section_cd` | text (text) | YES |  |
| `qtr_qtr_section_cd` | text (text) | YES |  |
| `st_plane_xcoord_nr` | integer (int4) | YES |  |
| `st_plane_ycoord_nr` | integer (int4) | YES |  |
| `tax_parcel_nr` | text (text) | YES |  |
| `horz_coll_meth_cd` | double precision (float8) | YES |  |
| `record_creation_td` | timestamp with time zone (timestamptz) | YES |  |
| `last_update_td` | timestamp with time zone (timestamptz) | YES |  |
| `welllog_static_lvl_qt` | double precision (float8) | YES |  |
| `yield_gpm` | double precision (float8) | YES |  |
| `welllog_flow_type_cd` | text (text) | YES |  |
| `welllog_psi_nr` | double precision (float8) | YES |  |
| `welllog_well_test_cd` | text (text) | YES |  |
| `welllog_city_nm` | text (text) | YES |  |
| `welllog_zip_postl_cd` | text (text) | YES |  |
| `horzcoll_ds` | text (text) | YES |  |
| `wria_nr` | double precision (float8) | YES |  |
| `nad83latitude_qt` | double precision (float8) | YES |  |
| `nad83longitude_qt` | double precision (float8) | YES |  |
| `geometry` | geometry(Point,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_wells_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_wells_geometry_gist ON public.reference_wells USING gist (geometry)
  ```
- `idx_reference_wells_geometry`
  ```sql
  CREATE INDEX idx_reference_wells_geometry ON public.reference_wells USING gist (geometry)
  ```
- `idx_reference_wells_use_type`
  ```sql
  CREATE INDEX idx_reference_wells_use_type ON public.reference_wells USING btree (use_type)
  ```
- `idx_reference_wells_well_tag_id`
  ```sql
  CREATE INDEX idx_reference_wells_well_tag_id ON public.reference_wells USING btree (well_tag_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `well_log_id` | 1 |
| `well_tag_id` | NULL |
| `project_tag_nr` | NULL |
| `nit_id_nr` | NULL |
| `county_id` | 6.0 |
| `region_cd` | 4.0 |
| `well_log_recv_dt` | NULL |
| `well_log_img_nm` | 00000001.pdf |
| `well_diameter_qt` | 6.0 |
| `well_depth` | 140.0 |
| `well_comp_dt` | 1984/08/07 00:00:00+00 |
| `well_owner_nm` | NULL |
| `use_type` | W |
| `well_address_ds` | 20218 NE 174TH ST, BRUSH PRAIRIE |
| `driller_nr` | NULL |
| `township_nr` | 03 |
| `township_fraction_nr` | NULL |
| `township_dir_cd` | N |
| `range_nr` | 03 |
| `range_fraction_nr` | NULL |
| `range_dir_cd` | E |
| `section_nr` | 17 |
| `qtr_section_cd` | NE |
| `qtr_qtr_section_cd` | NW |
| `st_plane_xcoord_nr` | 1139276 |
| `st_plane_ycoord_nr` | 158197 |
| `tax_parcel_nr` | NULL |
| `horz_coll_meth_cd` | NULL |
| `record_creation_td` | NULL |
| `last_update_td` | NULL |
| `welllog_static_lvl_qt` | NULL |
| `yield_gpm` | NULL |
| `welllog_flow_type_cd` | NULL |
| `welllog_psi_nr` | NULL |
| `welllog_well_test_cd` | NULL |
| `welllog_city_nm` | NULL |
| `welllog_zip_postl_cd` | NULL |
| `horzcoll_ds` | NULL |
| `wria_nr` | 28.0 |
| `nad83latitude_qt` | 45.75004 |
| `nad83longitude_qt` | -122.46322 |
| `geometry` | 01010000206E0B00003D95409E63AD3241FA462622C2901BC1 |

---

## `public.reference_wetlands` (t)

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `RASTER` | integer (int4) | YES |  |
| `FOOTPRINT_Length` | double precision (float8) | YES |  |
| `FOOTPRINT_Area` | double precision (float8) | YES |  |
| `geometry` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_wetlands_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_wetlands_geometry_gist ON public.reference_wetlands USING gist (geometry)
  ```
- `idx_reference_wetlands_geometry`
  ```sql
  CREATE INDEX idx_reference_wetlands_geometry ON public.reference_wetlands USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `RASTER` | 1 |
| `FOOTPRINT_Length` | 6475051.8000000715 |
| `FOOTPRINT_Area` | 2620390851144.1157 |
| `geometry` | 01060000206E0B00000100000001030000000100000005000000525AB5741EBD21412A8C3EC3DA3324C1D4B14A52C7982141CEB142D1C33F2D416B83C4AC54B9404142668874CA702D4172A5FDE3F... |

---

## `public.reference_zoning` (t)

**Geometry Columns:**
- `geometry` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ACRES` | double precision (float8) | YES |  |
| `FEDERAL` | text (text) | YES |  |
| `FEAT_TYPE` | text (text) | YES |  |
| `LUD` | text (text) | YES |  |
| `LUD_ZONING` | text (text) | YES |  |
| `GlobalID` | text (text) | YES |  |
| `ZONING_LAB` | text (text) | YES |  |
| `ZONING_COD` | text (text) | YES |  |
| `Shape_STAr` | double precision (float8) | YES |  |
| `Shape_STLe` | double precision (float8) | YES |  |
| `geometry` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_zoning_geometry_gist`
  ```sql
  CREATE INDEX idx_reference_zoning_geometry_gist ON public.reference_zoning USING gist (geometry)
  ```
- `idx_reference_zoning_geometry`
  ```sql
  CREATE INDEX idx_reference_zoning_geometry ON public.reference_zoning USING gist (geometry)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ACRES` | 7713.83 |
| `FEDERAL` | NULL |
| `FEAT_TYPE` | NULL |
| `LUD` | RRV |
| `LUD_ZONING` | RRv |
| `GlobalID` | {39DE76E9-59F2-4230-9722-085492E17DE8} |
| `ZONING_LAB` | [RRv] Rural Reserve |
| `ZONING_COD` | 14.11.200 |
| `Shape_STAr` | 336014609.834 |
| `Shape_STLe` | 183690.667634 |
| `geometry` | 01030000206E0B000005000000D705000067BCEFD172E2334143C920E9672B2141AC0348AB34E2334138278F7B6A2B21411C0CBBF3D0E13341689430C16E2B214130EA430AE9DF3341F67FCA45742... |

---

## `public.reference_zoning_envelope` (t)

**Primary Key:** id

**Geometry Columns:**
- `geometry` (MULTIPOLYGON, SRID 3857)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `source` | character varying(50) (varchar) | NO |  |
| `jurisdiction` | character varying(100) (varchar) | NO |  |
| `county_name` | character varying(100) (varchar) | YES |  |
| `zone_code` | character varying(100) (varchar) | NO |  |
| `zone_name` | character varying(255) (varchar) | YES |  |
| `zoning_general_class` | character varying(30) (varchar) | YES |  |
| `zoning_specific_class` | character varying(100) (varchar) | YES |  |
| `allows_residential` | boolean (bool) | YES |  |
| `allows_duplex` | boolean (bool) | YES |  |
| `allows_multifamily` | boolean (bool) | YES |  |
| `allows_retail` | boolean (bool) | YES |  |
| `allows_office` | boolean (bool) | YES |  |
| `allows_industrial` | boolean (bool) | YES |  |
| `allows_heavy_industrial` | boolean (bool) | YES |  |
| `allows_agriculture` | boolean (bool) | YES |  |
| `allows_forestry` | boolean (bool) | YES |  |
| `allows_green_energy` | boolean (bool) | YES |  |
| `allows_data_center` | boolean (bool) | YES |  |
| `allows_warehouse` | boolean (bool) | YES |  |
| `min_lot_size_sqft` | double precision (float8) | YES |  |
| `max_lot_coverage_pct` | double precision (float8) | YES |  |
| `max_height_ft` | double precision (float8) | YES |  |
| `max_stories` | double precision (float8) | YES |  |
| `max_far` | double precision (float8) | YES |  |
| `min_far` | double precision (float8) | YES |  |
| `max_density_du_ac` | double precision (float8) | YES |  |
| `min_density_du_ac` | double precision (float8) | YES |  |
| `max_units_per_lot` | integer (int4) | YES |  |
| `adus_allowed_count` | integer (int4) | YES |  |
| `adu_owner_occupancy_required` | boolean (bool) | YES |  |
| `parking_min_residential` | double precision (float8) | YES |  |
| `parking_min_middle_housing` | double precision (float8) | YES |  |
| `parking_min_apartment` | double precision (float8) | YES |  |
| `parking_min_retail` | double precision (float8) | YES |  |
| `parking_min_restaurant` | double precision (float8) | YES |  |
| `parking_min_office` | double precision (float8) | YES |  |
| `reference_url` | character varying(500) (varchar) | YES |  |
| `source_last_verified` | date (date) | YES |  |
| `geometry` | geometry(MultiPolygon,3857) (geometry) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `reference_z_geometr_eeadcf_gist`
  ```sql
  CREATE INDEX reference_z_geometr_eeadcf_gist ON public.reference_zoning_envelope USING gist (geometry)
  ```
- `reference_z_jurisdi_8160de_idx`
  ```sql
  CREATE INDEX reference_z_jurisdi_8160de_idx ON public.reference_zoning_envelope USING btree (jurisdiction)
  ```
- `reference_zoning_envelope_geometry_dec82255_id`
  ```sql
  CREATE INDEX reference_zoning_envelope_geometry_dec82255_id ON public.reference_zoning_envelope USING gist (geometry)
  ```
- `reference_zoning_envelope_pkey`
  ```sql
  CREATE UNIQUE INDEX reference_zoning_envelope_pkey ON public.reference_zoning_envelope USING btree (id)
  ```
- `reference_z_zone_co_bbab36_idx`
  ```sql
  CREATE INDEX reference_z_zone_co_bbab36_idx ON public.reference_zoning_envelope USING btree (zone_code)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.reference_zoning_zones` (t)

**Geometry Columns:**
- `geom` (MULTIPOLYGON, SRID 2926)
- `geom_valid` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `objectid` | integer (int4) | YES |  |
| `geoid` | text (text) | YES |  |
| `jurisdiction` | text (text) | YES |  |
| `countyfp` | text (text) | YES |  |
| `countyname` | text (text) | YES |  |
| `zoneid` | text (text) | YES |  |
| `zonename` | text (text) | YES |  |
| `wazazonegeneral` | text (text) | YES |  |
| `wazazonespecific` | text (text) | YES |  |
| `useresidential` | text (text) | YES |  |
| `useretail` | text (text) | YES |  |
| `useoffice` | text (text) | YES |  |
| `usemanufacturing` | text (text) | YES |  |
| `useheavyindustrial` | text (text) | YES |  |
| `usegreenenergy` | text (text) | YES |  |
| `usedatacenter` | text (text) | YES |  |
| `usewarehouse` | text (text) | YES |  |
| `useforestry` | text (text) | YES |  |
| `useagriculture` | text (text) | YES |  |
| `usemining` | text (text) | YES |  |
| `dimmaxheight` | double precision (float8) | YES |  |
| `dimmaxstories` | double precision (float8) | YES |  |
| `dimbonusmaxheight` | double precision (float8) | YES |  |
| `dimbonusmaxstories` | double precision (float8) | YES |  |
| `dimminheight` | double precision (float8) | YES |  |
| `dimminstories` | double precision (float8) | YES |  |
| `dimmaxfar` | double precision (float8) | YES |  |
| `dimbonusmaxfar` | double precision (float8) | YES |  |
| `dimminfar` | double precision (float8) | YES |  |
| `dimmaxlotcoverbuildings` | double precision (float8) | YES |  |
| `dimmaxlotcoverbuildingsandimpsu` | double precision (float8) | YES |  |
| `denminlotsizesqft` | double precision (float8) | YES |  |
| `denmaxdensity` | double precision (float8) | YES |  |
| `denbonusmaxdensity` | double precision (float8) | YES |  |
| `denmindensity` | double precision (float8) | YES |  |
| `denmaxprimaryunitsperlot` | double precision (float8) | YES |  |
| `denbonusmaxprimaryunitsperlot` | double precision (float8) | YES |  |
| `dennumadusallowed` | double precision (float8) | YES |  |
| `denaduoccupancyrequirement` | text (text) | YES |  |
| `bonusah` | text (text) | YES |  |
| `bonustdr` | text (text) | YES |  |
| `minparkingressur` | double precision (float8) | YES |  |
| `minparkingresmh` | double precision (float8) | YES |  |
| `minparkingresapt` | double precision (float8) | YES |  |
| `minparkingretail` | double precision (float8) | YES |  |
| `minparkingrestaraunt` | double precision (float8) | YES |  |
| `minparkingoffice` | double precision (float8) | YES |  |
| `info` | text (text) | YES |  |
| `referenceurl` | text (text) | YES |  |
| `wazaspatialnormalizationdate` | timestamp without time zone (timestamp) | YES |  |
| `minparkingresmeasure_deprecated` | text (text) | YES |  |
| `minparkingresidential_deprecate` | double precision (float8) | YES |  |
| `shape__area` | double precision (float8) | YES |  |
| `shape__length` | double precision (float8) | YES |  |
| `geom` | geometry(MultiPolygon,2926) (geometry) | YES |  |
| `geom_valid` | geometry(MultiPolygon,2926) (geometry) | YES |  |

### Indexes

- `idx_reference_zoning_geom_valid`
  ```sql
  CREATE INDEX idx_reference_zoning_geom_valid ON public.reference_zoning_zones USING gist (geom_valid)
  ```
- `idx_rz_geom_valid`
  ```sql
  CREATE INDEX idx_rz_geom_valid ON public.reference_zoning_zones USING gist (geom_valid)
  ```
- `idx_reference_zoning_zones_geom`
  ```sql
  CREATE INDEX idx_reference_zoning_zones_geom ON public.reference_zoning_zones USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `objectid` | 289786 |
| `geoid` | 53057 |
| `jurisdiction` | Unincorporated Skagit County |
| `countyfp` | 057 |
| `countyname` | Skagit |
| `zoneid` | RRv |
| `zonename` | Rural Reserve |
| `wazazonegeneral` | RUR |
| `wazazonespecific` | RR5+ |
| `useresidential` | P |
| `useretail` | X |
| `useoffice` | X |
| `usemanufacturing` | X |
| `useheavyindustrial` | X |
| `usegreenenergy` | LA |
| `usedatacenter` | X |
| `usewarehouse` | X |
| `useforestry` | X |
| `useagriculture` | P |
| `usemining` | X |
| `dimmaxheight` | 40.0 |
| `dimmaxstories` | NULL |
| `dimbonusmaxheight` | NULL |
| `dimbonusmaxstories` | NULL |
| `dimminheight` | NULL |
| `dimminstories` | NULL |
| `dimmaxfar` | NULL |
| `dimbonusmaxfar` | NULL |
| `dimminfar` | NULL |
| `dimmaxlotcoverbuildings` | 20.0 |
| `dimmaxlotcoverbuildingsandimpsu` | NULL |
| `denminlotsizesqft` | 435600.0 |
| `denmaxdensity` | 0.1 |
| `denbonusmaxdensity` | NULL |
| `denmindensity` | NULL |
| `denmaxprimaryunitsperlot` | 1.0 |
| `denbonusmaxprimaryunitsperlot` | 1.0 |
| `dennumadusallowed` | 1.0 |
| `denaduoccupancyrequirement` | Y |
| `bonusah` | N |
| `bonustdr` | N |
| `minparkingressur` | 2.0 |
| `minparkingresmh` | NULL |
| `minparkingresapt` | NULL |
| `minparkingretail` | 3.3 |
| `minparkingrestaraunt` | 13.3 |
| `minparkingoffice` | 3.3 |
| `info` | NULL |
| `referenceurl` | https://www.codepublishing.com/WA/SkagitCounty/#!/SkagitCounty14/SkagitCounty1416.html#14.16.320 |
| `wazaspatialnormalizationdate` | 2024-12-02 00:00:00 |
| `minparkingresmeasure_deprecated` | DU |
| `minparkingresidential_deprecate` | 2.0 |
| `shape__area` | 71196611.28125 |
| `shape__length` | 84551.71829818845 |
| `geom` | 01060000206E0B00000100000001030000000500000008060000D4CDD23CD6C2334176AA1C67EF0C21417C446608D4C23341A153555F670A21415B1EE728D1C43341FE725AF6430A214164C60B9F6... |
| `geom_valid` | 01060000206E0B00000100000001030000000500000008060000D4CDD23CD6C2334176AA1C67EF0C21417C446608D4C23341A153555F670A21415B1EE728D1C43341FE725AF6430A214164C60B9F6... |

---

## `public.regression_results` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `model_type` | character varying(50) (varchar) | NO |  |
| `run_date` | timestamp with time zone (timestamptz) | NO |  |
| `n_obs` | integer (int4) | NO |  |
| `r_squared` | double precision (float8) | NO |  |
| `adj_r_squared` | double precision (float8) | NO |  |
| `coefficients` | jsonb (jsonb) | NO |  |
| `notes` | text (text) | NO |  |
| `roll_id` | bigint (int8) | NO |  |

### Foreign Keys

- `roll_id` → `public.openskagit_assessmentroll.id`

### Indexes

- `regression_results_roll_id_3939bed7`
  ```sql
  CREATE INDEX regression_results_roll_id_3939bed7 ON public.regression_results USING btree (roll_id)
  ```
- `regression_results_pkey`
  ```sql
  CREATE UNIQUE INDEX regression_results_pkey ON public.regression_results USING btree (id)
  ```

### Sample Row

_No sample data available (table is empty or unreadable)._

---

## `public.sales` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `sale_id` | bigint (int8) | YES |  |
| `parcel_number` | text (text) | YES |  |
| `account_number` | text (text) | YES |  |
| `seller_name` | text (text) | YES |  |
| `buyer_name` | text (text) | YES |  |
| `sale_price` | bigint (int8) | YES |  |
| `sale_date` | timestamp without time zone (timestamp) | YES |  |
| `sale_type` | text (text) | YES |  |
| `recording_number` | text (text) | YES |  |
| `deed_type` | text (text) | YES |  |
| `deed_date` | timestamp without time zone (timestamp) | YES |  |
| `revaluation_area` | real (float4) | YES |  |
| `excise_number` | real (float4) | YES |  |
| `roll_id` | bigint (int8) | YES |  |
| `id` | bigint (int8) | NO |  |

### Foreign Keys

- `roll_id` → `public.openskagit_assessmentroll.id`

### Indexes

- `sales_parcel_number_idx`
  ```sql
  CREATE INDEX sales_parcel_number_idx ON public.sales USING btree (parcel_number)
  ```
- `sales_sale_date_idx`
  ```sql
  CREATE INDEX sales_sale_date_idx ON public.sales USING btree (sale_date)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `sale_id` | 1948294 |
| `parcel_number` | P126344 |
| `account_number` | 4933-000-003-0000 |
| `seller_name` | COACH CORRAL INC |
| `buyer_name` | ZIMMERMAN JIM E |
| `sale_price` | 507000 |
| `sale_date` | NULL |
| `sale_type` | VALID SALE |
| `recording_number` | 202008250092 |
| `deed_type` | WARRANTY DEED |
| `deed_date` | 2020-08-24 00:00:00 |
| `revaluation_area` | 100.0 |
| `excise_number` | 20203314.0 |
| `roll_id` | 1 |
| `id` | 1 |

---

## `public.sales_search` (t)

**Primary Key:** sale_id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `sale_id` | bigint (int8) | NO |  |
| `parcel_number` | character varying(20) (varchar) | NO |  |
| `sale_date` | date (date) | NO |  |
| `sale_price` | double precision (float8) | NO |  |
| `market_value` | double precision (float8) | YES |  |
| `assessed_value` | double precision (float8) | YES |  |
| `sale_to_market_ratio` | double precision (float8) | YES |  |
| `living_area` | double precision (float8) | YES |  |
| `lot_size_acres` | double precision (float8) | YES |  |
| `zoning_jurisdiction` | character varying(50) (varchar) | YES |  |
| `zone_id` | character varying(50) (varchar) | YES |  |
| `is_arms_length` | boolean (bool) | NO |  |
| `exclude_from_analysis` | boolean (bool) | NO |  |
| `ratio_trim_bucket` | character varying(20) (varchar) | NO |  |
| `qa_flags` | jsonb (jsonb) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `sales_search_ratio_trim_bucket_072c2db0`
  ```sql
  CREATE INDEX sales_search_ratio_trim_bucket_072c2db0 ON public.sales_search USING btree (ratio_trim_bucket)
  ```
- `sales_search_parcel_number_1358a665_like`
  ```sql
  CREATE INDEX sales_search_parcel_number_1358a665_like ON public.sales_search USING btree (parcel_number varchar_pattern_ops)
  ```
- `sales_search_parcel_number_1358a665`
  ```sql
  CREATE INDEX sales_search_parcel_number_1358a665 ON public.sales_search USING btree (parcel_number)
  ```
- `sales_searc_parcel__84600f_idx`
  ```sql
  CREATE INDEX sales_searc_parcel__84600f_idx ON public.sales_search USING btree (parcel_number, sale_date)
  ```
- `sales_searc_exclude_7d43e8_idx`
  ```sql
  CREATE INDEX sales_searc_exclude_7d43e8_idx ON public.sales_search USING btree (exclude_from_analysis)
  ```
- `sales_searc_ratio_t_8fdff9_idx`
  ```sql
  CREATE INDEX sales_searc_ratio_t_8fdff9_idx ON public.sales_search USING btree (ratio_trim_bucket)
  ```
- `sales_searc_sale_pr_9443a8_idx`
  ```sql
  CREATE INDEX sales_searc_sale_pr_9443a8_idx ON public.sales_search USING btree (sale_price)
  ```
- `sales_searc_sale_da_065dee_idx`
  ```sql
  CREATE INDEX sales_searc_sale_da_065dee_idx ON public.sales_search USING btree (sale_date)
  ```
- `sales_search_pkey`
  ```sql
  CREATE UNIQUE INDEX sales_search_pkey ON public.sales_search USING btree (sale_id)
  ```
- `sales_search_ratio_trim_bucket_072c2db0_like`
  ```sql
  CREATE INDEX sales_search_ratio_trim_bucket_072c2db0_like ON public.sales_search USING btree (ratio_trim_bucket varchar_pattern_ops)
  ```
- `sales_search_sale_date_4134ad60`
  ```sql
  CREATE INDEX sales_search_sale_date_4134ad60 ON public.sales_search USING btree (sale_date)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `sale_id` | 33486 |
| `parcel_number` | P100026 |
| `sale_date` | 2021-07-09 |
| `sale_price` | 8500.0 |
| `market_value` | 4500.0 |
| `assessed_value` | 4500.0 |
| `sale_to_market_ratio` | 1.8888888888888888 |
| `living_area` | 0.0 |
| `lot_size_acres` | 0.34999999 |
| `zoning_jurisdiction` | RRv |
| `zone_id` | RRv |
| `is_arms_length` | False |
| `exclude_from_analysis` | True |
| `ratio_trim_bucket` | outside_iaao |
| `qa_flags` | ["low_price", "non_valid_sale"] |
| `created_at` | 2025-12-19 19:43:27.501581+00:00 |

---

## `public.sales_search_mv` (m)

**Geometry Columns:**
- `centroid_geog` (POINT, SRID 4326)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `sale_id` | bigint (int8) | YES |  |
| `parcel_number` | text (text) | YES |  |
| `sale_date` | date (date) | YES |  |
| `sale_year` | integer (int4) | YES |  |
| `sale_price` | numeric (numeric) | YES |  |
| `property_type` | text (text) | YES |  |
| `is_manufactured` | boolean (bool) | YES |  |
| `is_vacant_land` | boolean (bool) | YES |  |
| `living_area` | numeric (numeric) | YES |  |
| `lot_size_acres` | numeric (numeric) | YES |  |
| `year_built` | integer (int4) | YES |  |
| `address_simple` | text (text) | YES |  |
| `city` | text (text) | YES |  |
| `city_jurisdiction` | text (text) | YES |  |
| `zip5` | text (text) | YES |  |
| `neighborhood_id` | character varying(20) (varchar) | YES |  |
| `neighborhood_name` | character varying(200) (varchar) | YES |  |
| `centroid_geog` | geometry(Point,4326) (geometry) | YES |  |
| `price_per_sqft` | numeric (numeric) | YES |  |
| `price_per_acre` | numeric (numeric) | YES |  |
| `is_arms_length` | boolean (bool) | YES |  |
| `is_warranty_deed` | boolean (bool) | YES |  |
| `qa_flags` | text[] (_text) | YES |  |
| `ratio_trim_bucket` | text (text) | YES |  |
| `sale_to_market_ratio` | numeric (numeric) | YES |  |
| `exclude_from_analysis` | boolean (bool) | YES |  |
| `raw_sale_type` | text (text) | YES |  |
| `raw_deed_type` | text (text) | YES |  |
| `recording_number` | text (text) | YES |  |
| `excise_number` | real (float4) | YES |  |

### Indexes

- `idx_sales_search_mv_property_partial`
  ```sql
  CREATE INDEX idx_sales_search_mv_property_partial ON public.sales_search_mv USING btree (sale_date, sale_price) WHERE (property_type = ANY (ARRAY['SFR'::text, 'Manufactured/Mobile'::text]))
  ```
- `idx_sales_search_mv_centroid`
  ```sql
  CREATE INDEX idx_sales_search_mv_centroid ON public.sales_search_mv USING gist (centroid_geog)
  ```
- `idx_sales_search_mv_sale_id`
  ```sql
  CREATE UNIQUE INDEX idx_sales_search_mv_sale_id ON public.sales_search_mv USING btree (sale_id)
  ```
- `idx_sales_search_mv_sale_date`
  ```sql
  CREATE INDEX idx_sales_search_mv_sale_date ON public.sales_search_mv USING btree (sale_date DESC)
  ```
- `idx_sales_search_mv_property_type`
  ```sql
  CREATE INDEX idx_sales_search_mv_property_type ON public.sales_search_mv USING btree (property_type)
  ```
- `idx_sales_search_mv_city`
  ```sql
  CREATE INDEX idx_sales_search_mv_city ON public.sales_search_mv USING btree (city_jurisdiction)
  ```
- `idx_sales_search_mv_neighborhood`
  ```sql
  CREATE INDEX idx_sales_search_mv_neighborhood ON public.sales_search_mv USING btree (neighborhood_id)
  ```
- `idx_sales_search_mv_sale_price`
  ```sql
  CREATE INDEX idx_sales_search_mv_sale_price ON public.sales_search_mv USING btree (sale_price)
  ```
- `idx_sales_search_mv_year_built`
  ```sql
  CREATE INDEX idx_sales_search_mv_year_built ON public.sales_search_mv USING btree (year_built)
  ```
- `idx_sales_search_mv_arms_length`
  ```sql
  CREATE INDEX idx_sales_search_mv_arms_length ON public.sales_search_mv USING btree (is_arms_length, sale_date)
  ```

### Sample Row

_Unable to load sample data: materialized view "sales_search_mv" has not been populated
HINT:  Use the REFRESH MATERIALIZED VIEW command.._

---

## `public.skagit_county_boundary` (t)

**Geometry Columns:**
- `geom_2926` (GEOMETRY, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geom_2926` | geometry(Geometry,2926) (geometry) | YES |  |

### Indexes

- `idx_skagit_boundary_geom`
  ```sql
  CREATE INDEX idx_skagit_boundary_geom ON public.skagit_county_boundary USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geom_2926` | 01060000206E0B00006B1C000001030000000100000021000000A4B17268511E3241F70B1B592C6A204101787B68511E3241B51250592C6A204140438968511E324136AA80592C6A2041C28B9B685... |

---

## `public.skagit_county_boundary_flood_srid` (t)

**Geometry Columns:**
- `geom` (GEOMETRY, SRID 0)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `geom` | geometry (geometry) | YES |  |

### Indexes

- `skagit_county_boundary_flood_srid_geom_idx`
  ```sql
  CREATE INDEX skagit_county_boundary_flood_srid_geom_idx ON public.skagit_county_boundary_flood_srid USING gist (geom)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `geom` | 0106000020AD1000006B1C000001030000000100000021000000E092622FD5AC5EC0E774C141D03A48405B06622FD5AC5EC045DBC341D03A48402D22612FD5AC5EC07711C641D03A484017EF5F2FD... |

---

## `public.spatial_ref_sys` (t)

**Primary Key:** srid

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `srid` | integer (int4) | NO |  |
| `auth_name` | character varying(256) (varchar) | YES |  |
| `auth_srid` | integer (int4) | YES |  |
| `srtext` | character varying(2048) (varchar) | YES |  |
| `proj4text` | character varying(2048) (varchar) | YES |  |

### Indexes

- `spatial_ref_sys_pkey`
  ```sql
  CREATE UNIQUE INDEX spatial_ref_sys_pkey ON public.spatial_ref_sys USING btree (srid)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `srid` | 3819 |
| `auth_name` | EPSG |
| `auth_srid` | 3819 |
| `srtext` | GEOGCS["HD1909",DATUM["Hungarian_Datum_1909",SPHEROID["Bessel 1841",6377397.155,299.1528128,AUTHORITY["EPSG","7004"]],TOWGS84[595.48,121.69,515.35,4.115,-2.9... |
| `proj4text` | +proj=longlat +ellps=bessel +towgs84=595.48,121.69,515.35,4.115,-2.9383,0.853,-3.408 +no_defs  |

---

## `public.stg_parcel_geometry` (t)

**Primary Key:** parcel_id

**Geometry Columns:**
- `geom_2926` (MULTIPOLYGON, SRID 2926)
- `centroid_2926` (POINT, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_id` | character varying(20) (varchar) | NO |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | NO |  |
| `centroid_2926` | geometry(Point,2926) (geometry) | YES |  |
| `source_geom_count` | integer (int4) | NO |  |
| `rule_used` | character varying(50) (varchar) | NO |  |
| `updated_at` | timestamp with time zone (timestamptz) | NO |  |

### Foreign Keys

- `parcel_id` → `public.master_parcel.parcel_number`

### Indexes

- `stg_parcel_geometry_geom_2926_eec79ec8_id`
  ```sql
  CREATE INDEX stg_parcel_geometry_geom_2926_eec79ec8_id ON public.stg_parcel_geometry USING gist (geom_2926)
  ```
- `stg_parcel_geometry_parcel_id_98add608_like`
  ```sql
  CREATE INDEX stg_parcel_geometry_parcel_id_98add608_like ON public.stg_parcel_geometry USING btree (parcel_id varchar_pattern_ops)
  ```
- `stg_parcel_geometry_centroid_2926_b459e366_id`
  ```sql
  CREATE INDEX stg_parcel_geometry_centroid_2926_b459e366_id ON public.stg_parcel_geometry USING gist (centroid_2926)
  ```
- `stg_parcel__geom_29_0263d6_gist`
  ```sql
  CREATE INDEX stg_parcel__geom_29_0263d6_gist ON public.stg_parcel_geometry USING gist (geom_2926)
  ```
- `stg_parcel__centroi_0a3021_gist`
  ```sql
  CREATE INDEX stg_parcel__centroi_0a3021_gist ON public.stg_parcel_geometry USING gist (centroid_2926)
  ```
- `stg_parcel_geometry_pkey`
  ```sql
  CREATE UNIQUE INDEX stg_parcel_geometry_pkey ON public.stg_parcel_geometry USING btree (parcel_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_id` | P100005 |
| `geom_2926` | 01060000206E0B00000100000001030000000100000005000000B3C57439F76B32414D21ACD438CD2041031950F3F36B32410B9ECFEF70CC20418F942F23A96B3241DE136FCA75CC204151CA9569A... |
| `centroid_2926` | 01010000206E0B0000A6AF622ED06B3241969A8D4FD7CC2041 |
| `source_geom_count` | 1 |
| `rule_used` | largest_area_2926 |
| `updated_at` | 2026-01-16 20:56:18.985172+00:00 |

---

## `public.taxing_district_levy` (t)

**Primary Key:** id

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `tdcode` | character varying(9) (varchar) | NO |  |
| `district_name` | character varying(255) (varchar) | NO |  |
| `locally_assessed_value` | bigint (int8) | YES |  |
| `levy_rate` | numeric(10,5) (numeric) | YES |  |
| `district_levy` | bigint (int8) | YES |  |
| `highest_prior_levy` | bigint (int8) | YES |  |
| `new_construction_assessed_value` | bigint (int8) | YES |  |
| `levy_rate_2024` | numeric(10,5) (numeric) | YES |  |
| `state_assessed_property_2024` | bigint (int8) | YES |  |
| `state_assessed_property_2023` | bigint (int8) | YES |  |
| `annexation_assessed_value_2023` | bigint (int8) | YES |  |
| `annex_tax_due_2023` | bigint (int8) | YES |  |
| `refund_tax_due_2023` | bigint (int8) | YES |  |
| `max_allowable_levy` | bigint (int8) | YES |  |
| `statutory_max_rate` | numeric(6,4) (numeric) | YES |  |
| `levy_limit_percent_increase` | numeric(6,4) (numeric) | YES |  |
| `assessment_year` | smallint (int2) | NO |  |
| `created_at` | timestamp with time zone (timestamptz) | NO |  |

### Indexes

- `taxing_dist_tdcode_60a920_idx`
  ```sql
  CREATE INDEX taxing_dist_tdcode_60a920_idx ON public.taxing_district_levy USING btree (tdcode)
  ```
- `taxing_district_levy_tdcode_c3e23ba1`
  ```sql
  CREATE INDEX taxing_district_levy_tdcode_c3e23ba1 ON public.taxing_district_levy USING btree (tdcode)
  ```
- `taxing_district_levy_tdcode_c3e23ba1_like`
  ```sql
  CREATE INDEX taxing_district_levy_tdcode_c3e23ba1_like ON public.taxing_district_levy USING btree (tdcode varchar_pattern_ops)
  ```
- `taxing_district_levy_assessment_year_ba2ea9ff`
  ```sql
  CREATE INDEX taxing_district_levy_assessment_year_ba2ea9ff ON public.taxing_district_levy USING btree (assessment_year)
  ```
- `taxing_dist_assessm_45e479_idx`
  ```sql
  CREATE INDEX taxing_dist_assessm_45e479_idx ON public.taxing_district_levy USING btree (assessment_year)
  ```
- `taxing_district_levy_pkey`
  ```sql
  CREATE UNIQUE INDEX taxing_district_levy_pkey ON public.taxing_district_levy USING btree (id)
  ```
- `taxing_district_levy_tdcode_assessment_year_357e41a6_uniq`
  ```sql
  CREATE UNIQUE INDEX taxing_district_levy_tdcode_assessment_year_357e41a6_uniq ON public.taxing_district_levy USING btree (tdcode, assessment_year)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 1 |
| `tdcode` | 290000000 |
| `district_name` | State School Part 1 |
| `locally_assessed_value` | 33448468408 |
| `levy_rate` | 1.46739 |
| `district_levy` | 49082076 |
| `highest_prior_levy` | 0 |
| `new_construction_assessed_value` | 0 |
| `levy_rate_2024` | 0.00000 |
| `state_assessed_property_2024` | 0 |
| `state_assessed_property_2023` | 0 |
| `annexation_assessed_value_2023` | 0 |
| `annex_tax_due_2023` | 0 |
| `refund_tax_due_2023` | 0 |
| `max_allowable_levy` | 0 |
| `statutory_max_rate` | 0.0000 |
| `levy_limit_percent_increase` | 0.0000 |
| `assessment_year` | 2024 |
| `created_at` | 2026-01-14 00:53:47.336364+00:00 |

---

## `public.temp_slope_updates` (t)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | YES |  |
| `slope_val` | double precision (float8) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 192409 |
| `slope_val` | 13.920707702636719 |

---

## `public.v_parcel_active_code_sets` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `code_set` | character varying(100) (varchar) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P104423 |
| `code_set` | skagit_county_code |

---

## `public.v_parcel_code_sets` (v)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `parcel_number` | character varying(20) (varchar) | YES |  |
| `jurisdiction_name` | character varying (varchar) | YES |  |
| `code_set` | character varying(100) (varchar) | YES |  |

### Sample Row

| Column | Value |
|--------|-------|
| `parcel_number` | P100005 |
| `jurisdiction_name` | Anacortes |
| `code_set` | anacortes_municipal_code |

---

## `public.voter_ballots_skagit` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `ballot_id` | character varying(50) (varchar) | YES |  |
| `election_id` | bigint (int8) | YES |  |
| `election_year` | integer (int4) | YES |  |
| `normalized_address` | character varying(255) (varchar) | YES |  |

### Indexes

- `voter_ballots_skagit_year_idx`
  ```sql
  CREATE INDEX voter_ballots_skagit_year_idx ON public.voter_ballots_skagit USING btree (election_year)
  ```
- `voter_ballots_skagit_addr_year_idx`
  ```sql
  CREATE INDEX voter_ballots_skagit_addr_year_idx ON public.voter_ballots_skagit USING btree (normalized_address, election_year)
  ```
- `voter_ballots_skagit_ballot_idx`
  ```sql
  CREATE UNIQUE INDEX voter_ballots_skagit_ballot_idx ON public.voter_ballots_skagit USING btree (ballot_id, election_id)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `ballot_id` | 138513225 |
| `election_id` | 1 |
| `election_year` | 2024 |
| `normalized_address` | 12183 BAYHILL DR |

---

## `public.voter_precinct_norm` (m)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `norm_prec_name` | text (text) | YES |  |
| `norm_county` | text (text) | YES |  |

### Indexes

- `idx_vpn_name_county`
  ```sql
  CREATE INDEX idx_vpn_name_county ON public.voter_precinct_norm USING btree (norm_prec_name, norm_county)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `norm_prec_name` | SEDRO WOOLLEY 5 |
| `norm_county` | SKAGIT |

---

## `public.zoning_zone` (t)

**Primary Key:** id

**Geometry Columns:**
- `geom_2926` (MULTIPOLYGON, SRID 2926)

### Columns

| Column | Type | Nullable | Default |
|-------|------|----------|---------|
| `id` | bigint (int8) | NO |  |
| `jurisdiction` | character varying(50) (varchar) | NO |  |
| `zone_code` | character varying(50) (varchar) | NO |  |
| `zoning_general_class` | character varying(30) (varchar) | YES |  |
| `zoning_specific_class` | character varying(100) (varchar) | YES |  |
| `source` | character varying(50) (varchar) | NO |  |
| `reference_url` | character varying(500) (varchar) | YES |  |
| `geom_2926` | geometry(MultiPolygon,2926) (geometry) | NO |  |
| `zoning_use_class` | character varying(30) (varchar) | YES |  |
| `jurisdiction_key` | character varying(50) (varchar) | YES |  |

### Indexes

- `zoning_zone_pkey`
  ```sql
  CREATE UNIQUE INDEX zoning_zone_pkey ON public.zoning_zone USING btree (id)
  ```
- `zoning_zone_zone_co_7b8a44_idx`
  ```sql
  CREATE INDEX zoning_zone_zone_co_7b8a44_idx ON public.zoning_zone USING btree (zone_code)
  ```
- `zoning_zone_jurisdi_677cbc_idx`
  ```sql
  CREATE INDEX zoning_zone_jurisdi_677cbc_idx ON public.zoning_zone USING btree (jurisdiction)
  ```
- `zoning_zone_geom_29_928713_gist`
  ```sql
  CREATE INDEX zoning_zone_geom_29_928713_gist ON public.zoning_zone USING gist (geom_2926)
  ```
- `idx_zoning_geom_2926`
  ```sql
  CREATE INDEX idx_zoning_geom_2926 ON public.zoning_zone USING gist (geom_2926)
  ```
- `zoning_zone_geom_2926_199212dd_id`
  ```sql
  CREATE INDEX zoning_zone_geom_2926_199212dd_id ON public.zoning_zone USING gist (geom_2926)
  ```

### Sample Row

| Column | Value |
|--------|-------|
| `id` | 25732 |
| `jurisdiction` | Mount Vernon |
| `zone_code` | P-O |
| `zoning_general_class` | COM |
| `zoning_specific_class` | COMOFFI |
| `source` | WAZA |
| `reference_url` | https://www.codepublishing.com/WA/MountVernon/#!/MountVernon17/MountVernon1736.html#17.36 |
| `geom_2926` | 01060000206E0B000001000000010300000001000000050000001F2D325C3581334167DB952E10C01F414BFDEF7233813341F540BDF1A7BE1F415E528677CF803341DB2D34BEAFBE1F41F4CD4560D... |
| `zoning_use_class` | commercial |
| `jurisdiction_key` | mount_vernon |

---

