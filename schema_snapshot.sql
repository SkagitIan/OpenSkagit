--
-- PostgreSQL database dump
--

\restrict ay5KnE4yFmnHhZkiGh3rRQKszyeTh52bHdRj37z2h3kd7lNfdZc5d8kl8XEv4Nh

-- Dumped from database version 14.19 (Ubuntu 14.19-0ubuntu0.22.04.1)
-- Dumped by pg_dump version 14.19 (Ubuntu 14.19-0ubuntu0.22.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: census; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA census;


--
-- Name: fema; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA fema;


--
-- Name: osm; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA osm;


--
-- Name: usgs; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA usgs;


--
-- Name: wa_gis; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA wa_gis;


--
-- Name: hstore; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS hstore WITH SCHEMA public;


--
-- Name: EXTENSION hstore; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION hstore IS 'data type for storing sets of (key, value) pairs';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: postgis; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public;


--
-- Name: EXTENSION postgis; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis IS 'PostGIS geometry and geography spatial types and functions';


--
-- Name: postgis_raster; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS postgis_raster WITH SCHEMA public;


--
-- Name: EXTENSION postgis_raster; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION postgis_raster IS 'PostGIS raster types and functions';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: planet_osm_line_osm2pgsql_valid(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.planet_osm_line_osm2pgsql_valid() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF ST_IsValid(NEW.way) THEN 
    RETURN NEW;
  END IF;
  RETURN NULL;
END;$$;


--
-- Name: planet_osm_point_osm2pgsql_valid(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.planet_osm_point_osm2pgsql_valid() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF ST_IsValid(NEW.way) THEN 
    RETURN NEW;
  END IF;
  RETURN NULL;
END;$$;


--
-- Name: planet_osm_polygon_osm2pgsql_valid(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.planet_osm_polygon_osm2pgsql_valid() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF ST_IsValid(NEW.way) THEN 
    RETURN NEW;
  END IF;
  RETURN NULL;
END;$$;


--
-- Name: planet_osm_roads_osm2pgsql_valid(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.planet_osm_roads_osm2pgsql_valid() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF ST_IsValid(NEW.way) THEN 
    RETURN NEW;
  END IF;
  RETURN NULL;
END;$$;


--
-- Name: update_centroid_geog(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_centroid_geog() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.centroid_geog :=
        ST_Centroid(ST_Transform(NEW.geom, 4326))::geography;
    RETURN NEW;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: acs_bg_skagit; Type: TABLE; Schema: census; Owner: -
--

CREATE TABLE census.acs_bg_skagit (
    name text,
    median_income numeric,
    edu_bachelor numeric,
    edu_master numeric,
    edu_professional numeric,
    edu_doctorate numeric,
    population numeric,
    statefp text,
    countyfp text,
    tractce text,
    blkgrpce text,
    geoid text
);


--
-- Name: bg_skagit; Type: TABLE; Schema: census; Owner: -
--

CREATE TABLE census.bg_skagit (
    ogc_fid integer,
    statefp character varying(2),
    countyfp character varying(3),
    tractce character varying(6),
    blkgrpce character varying(1),
    geoid character varying(12),
    geoidfq character varying(21),
    namelsad character varying(13),
    mtfcc character varying(5),
    funcstat character varying(1),
    aland numeric(14,0),
    awater numeric(14,0),
    intptlat character varying(11),
    intptlon character varying(12),
    geom public.geometry(MultiPolygon,2285),
    geom_2926 public.geometry(MultiPolygon,2926)
);


--
-- Name: bg_wa_raw; Type: TABLE; Schema: census; Owner: -
--

CREATE TABLE census.bg_wa_raw (
    ogc_fid integer NOT NULL,
    statefp character varying(2),
    countyfp character varying(3),
    tractce character varying(6),
    blkgrpce character varying(1),
    geoid character varying(12),
    geoidfq character varying(21),
    namelsad character varying(13),
    mtfcc character varying(5),
    funcstat character varying(1),
    aland numeric(14,0),
    awater numeric(14,0),
    intptlat character varying(11),
    intptlon character varying(12),
    geom public.geometry(MultiPolygon,4269),
    geom_2926 public.geometry(MultiPolygon,2926)
);


--
-- Name: bg_wa_raw_ogc_fid_seq; Type: SEQUENCE; Schema: census; Owner: -
--

CREATE SEQUENCE census.bg_wa_raw_ogc_fid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: bg_wa_raw_ogc_fid_seq; Type: SEQUENCE OWNED BY; Schema: census; Owner: -
--

ALTER SEQUENCE census.bg_wa_raw_ogc_fid_seq OWNED BY census.bg_wa_raw.ogc_fid;


--
-- Name: planet_osm_line; Type: TABLE; Schema: osm; Owner: -
--

CREATE TABLE osm.planet_osm_line (
    osm_id bigint,
    access text,
    "addr:housename" text,
    "addr:housenumber" text,
    "addr:interpolation" text,
    admin_level text,
    aerialway text,
    aeroway text,
    amenity text,
    area text,
    barrier text,
    bicycle text,
    brand text,
    bridge text,
    boundary text,
    building text,
    construction text,
    covered text,
    culvert text,
    cutting text,
    denomination text,
    disused text,
    embankment text,
    foot text,
    "generator:source" text,
    harbour text,
    highway text,
    historic text,
    horse text,
    intermittent text,
    junction text,
    landuse text,
    layer text,
    leisure text,
    lock text,
    man_made text,
    military text,
    motorcar text,
    name text,
    "natural" text,
    office text,
    oneway text,
    operator text,
    place text,
    population text,
    power text,
    power_source text,
    public_transport text,
    railway text,
    ref text,
    religion text,
    route text,
    service text,
    shop text,
    sport text,
    surface text,
    toll text,
    tourism text,
    "tower:type" text,
    tracktype text,
    tunnel text,
    water text,
    waterway text,
    wetland text,
    width text,
    wood text,
    z_order integer,
    way_area real,
    tags public.hstore,
    way public.geometry(LineString,3857),
    geom_2926 public.geometry(LineString,2926)
);


--
-- Name: planet_osm_point; Type: TABLE; Schema: osm; Owner: -
--

CREATE TABLE osm.planet_osm_point (
    osm_id bigint,
    access text,
    "addr:housename" text,
    "addr:housenumber" text,
    "addr:interpolation" text,
    admin_level text,
    aerialway text,
    aeroway text,
    amenity text,
    area text,
    barrier text,
    bicycle text,
    brand text,
    bridge text,
    boundary text,
    building text,
    capital text,
    construction text,
    covered text,
    culvert text,
    cutting text,
    denomination text,
    disused text,
    ele text,
    embankment text,
    foot text,
    "generator:source" text,
    harbour text,
    highway text,
    historic text,
    horse text,
    intermittent text,
    junction text,
    landuse text,
    layer text,
    leisure text,
    lock text,
    man_made text,
    military text,
    motorcar text,
    name text,
    "natural" text,
    office text,
    oneway text,
    operator text,
    place text,
    population text,
    power text,
    power_source text,
    public_transport text,
    railway text,
    ref text,
    religion text,
    route text,
    service text,
    shop text,
    sport text,
    surface text,
    toll text,
    tourism text,
    "tower:type" text,
    tunnel text,
    water text,
    waterway text,
    wetland text,
    width text,
    wood text,
    z_order integer,
    tags public.hstore,
    way public.geometry(Point,3857),
    geom_2926 public.geometry(Point,2926)
);


--
-- Name: planet_osm_polygon; Type: TABLE; Schema: osm; Owner: -
--

CREATE TABLE osm.planet_osm_polygon (
    osm_id bigint,
    access text,
    "addr:housename" text,
    "addr:housenumber" text,
    "addr:interpolation" text,
    admin_level text,
    aerialway text,
    aeroway text,
    amenity text,
    area text,
    barrier text,
    bicycle text,
    brand text,
    bridge text,
    boundary text,
    building text,
    construction text,
    covered text,
    culvert text,
    cutting text,
    denomination text,
    disused text,
    embankment text,
    foot text,
    "generator:source" text,
    harbour text,
    highway text,
    historic text,
    horse text,
    intermittent text,
    junction text,
    landuse text,
    layer text,
    leisure text,
    lock text,
    man_made text,
    military text,
    motorcar text,
    name text,
    "natural" text,
    office text,
    oneway text,
    operator text,
    place text,
    population text,
    power text,
    power_source text,
    public_transport text,
    railway text,
    ref text,
    religion text,
    route text,
    service text,
    shop text,
    sport text,
    surface text,
    toll text,
    tourism text,
    "tower:type" text,
    tracktype text,
    tunnel text,
    water text,
    waterway text,
    wetland text,
    width text,
    wood text,
    z_order integer,
    way_area real,
    tags public.hstore,
    way public.geometry(Geometry,3857),
    geom_2926 public.geometry(Geometry,2926)
);


--
-- Name: planet_osm_roads; Type: TABLE; Schema: osm; Owner: -
--

CREATE TABLE osm.planet_osm_roads (
    osm_id bigint,
    access text,
    "addr:housename" text,
    "addr:housenumber" text,
    "addr:interpolation" text,
    admin_level text,
    aerialway text,
    aeroway text,
    amenity text,
    area text,
    barrier text,
    bicycle text,
    brand text,
    bridge text,
    boundary text,
    building text,
    construction text,
    covered text,
    culvert text,
    cutting text,
    denomination text,
    disused text,
    embankment text,
    foot text,
    "generator:source" text,
    harbour text,
    highway text,
    historic text,
    horse text,
    intermittent text,
    junction text,
    landuse text,
    layer text,
    leisure text,
    lock text,
    man_made text,
    military text,
    motorcar text,
    name text,
    "natural" text,
    office text,
    oneway text,
    operator text,
    place text,
    population text,
    power text,
    power_source text,
    public_transport text,
    railway text,
    ref text,
    religion text,
    route text,
    service text,
    shop text,
    sport text,
    surface text,
    toll text,
    tourism text,
    "tower:type" text,
    tracktype text,
    tunnel text,
    water text,
    waterway text,
    wetland text,
    width text,
    wood text,
    z_order integer,
    way_area real,
    tags public.hstore,
    way public.geometry(LineString,3857),
    geom_2926 public.geometry(LineString,2926)
);


--
-- Name: assessor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessor (
    parcel_number text,
    address text,
    neighborhood_code text,
    land_use_code text,
    building_value real,
    impr_land_value real,
    unimpr_land_value bigint,
    timber_land_value bigint,
    assessed_value bigint,
    taxable_value bigint,
    total_market_value bigint,
    acres real,
    sale_date timestamp without time zone,
    sale_price real,
    sale_deed_type text,
    total_taxes text,
    year_built bigint,
    eff_year_built bigint,
    living_area bigint,
    building_style text,
    foundation text,
    exterior_walls text,
    roof_covering text,
    roof_style text,
    floor_covering text,
    floor_construction text,
    interior_finish text,
    bathrooms real,
    bedrooms real,
    garage_sqft real,
    heat_air_cond text,
    fireplace text,
    finished_basement real,
    unfinished_basement bigint,
    fire_district text,
    school_district text,
    city_district text,
    levy_code text,
    current_use_adjustment real,
    tide_land_value bigint,
    senior_exemption_adjustment bigint,
    property_type text,
    has_septic text,
    latitude double precision,
    longitude double precision,
    embedding public.vector(384),
    roll_id bigint,
    id bigint NOT NULL,
    land_use_description text,
    neighborhood_code_description text,
    in_flood_zone boolean,
    flood_distance double precision,
    flood_static_bfe double precision,
    flood_depth double precision,
    flood_velocity double precision,
    flood_sfha text,
    flood_zone text,
    flood_zone_subtype text,
    flood_zone_id text,
    elev double precision,
    slope double precision,
    dist_floodway double precision,
    aspect double precision,
    aspect_dir text,
    dist_major_road double precision,
    geom_backup public.geometry(Geometry,3857),
    centroid_geog public.geography(Point,4326),
    geom public.geometry(MultiPolygon,3857),
    geom_4326 public.geometry(MultiPolygon,4326) GENERATED ALWAYS AS (public.st_transform(geom, 4326)) STORED,
    condition_code character varying(10),
    condition_score integer,
    quality_score double precision,
    geom_2926 public.geometry(MultiPolygon,2926),
    elevation double precision,
    dist_city_center double precision,
    dist_fire_station double precision,
    dist_hospital double precision,
    dist_minor_road double precision,
    dist_park double precision,
    dist_school double precision,
    dist_supermarket double precision,
    dist_trailhead double precision,
    age double precision,
    age_bucket character varying(20),
    age_sq double precision,
    full_bathrooms integer,
    half_bathrooms integer,
    has_adu boolean,
    has_deck boolean,
    has_finished_basement boolean,
    has_pool boolean,
    has_shop boolean,
    improvement_year_built bigint,
    land_use_category character varying(100),
    neighborhood_id character varying(50),
    number_of_fireplaces integer,
    number_of_outbuildings integer,
    number_of_sheds integer,
    number_of_shops integer,
    renovation_age double precision,
    total_additional_living_area double precision,
    total_basement_area double precision,
    total_deck_area double precision,
    total_garage_area double precision,
    total_improvement_value bigint,
    total_outbuilding_area double precision,
    total_porch_area double precision
);


--
-- Name: openskagit_assessmentroll; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_assessmentroll (
    id bigint NOT NULL,
    year integer NOT NULL,
    imported_at timestamp with time zone NOT NULL,
    notes text
);


--
-- Name: assessor_2025_geo; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.assessor_2025_geo AS
 SELECT a.parcel_number,
    a.address,
    a.neighborhood_code,
    a.land_use_code,
    a.building_value,
    a.impr_land_value,
    a.unimpr_land_value,
    a.timber_land_value,
    a.assessed_value,
    a.taxable_value,
    a.total_market_value,
    a.acres,
    a.sale_date,
    a.sale_price,
    a.sale_deed_type,
    a.total_taxes,
    a.year_built,
    a.eff_year_built,
    a.living_area,
    a.building_style,
    a.foundation,
    a.exterior_walls,
    a.roof_covering,
    a.roof_style,
    a.floor_covering,
    a.floor_construction,
    a.interior_finish,
    a.bathrooms,
    a.bedrooms,
    a.garage_sqft,
    a.heat_air_cond,
    a.fireplace,
    a.finished_basement,
    a.unfinished_basement,
    a.fire_district,
    a.school_district,
    a.city_district,
    a.levy_code,
    a.current_use_adjustment,
    a.tide_land_value,
    a.senior_exemption_adjustment,
    a.property_type,
    a.has_septic,
    a.latitude,
    a.longitude,
    a.embedding,
    a.roll_id,
    a.id,
    a.land_use_description,
    a.neighborhood_code_description,
    a.in_flood_zone,
    a.flood_distance,
    a.flood_static_bfe,
    a.flood_depth,
    a.flood_velocity,
    a.flood_sfha,
    a.flood_zone,
    a.flood_zone_subtype,
    a.flood_zone_id,
    a.elev,
    a.slope,
    a.dist_floodway,
    a.aspect,
    a.aspect_dir,
    a.dist_major_road,
    a.geom_backup,
    a.centroid_geog,
    a.geom,
    a.geom_4326,
    a.condition_code,
    a.condition_score,
    a.quality_score,
    a.geom_2926
   FROM (public.assessor a
     JOIN public.openskagit_assessmentroll ar ON (((a.roll_id = ar.id) AND (ar.year = 2025))));


--
-- Name: assessor_geom4326_nonnull; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.assessor_geom4326_nonnull AS
 SELECT assessor.id,
    assessor.parcel_number,
    assessor.geom_4326
   FROM public.assessor
  WHERE (assessor.geom_4326 IS NOT NULL);


--
-- Name: assessor_geom_update_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.assessor_geom_update_log (
    batch_start integer,
    batch_end integer,
    updated_count integer,
    run_at timestamp with time zone DEFAULT now()
);


--
-- Name: assessor_geom_utm10; Type: VIEW; Schema: public; Owner: -
--

CREATE VIEW public.assessor_geom_utm10 AS
 SELECT a.id,
    a.parcel_number,
    public.st_transform(a.geom_4326, 26910) AS geom_utm10
   FROM public.assessor a
  WHERE (a.geom_4326 IS NOT NULL);


--
-- Name: assessor_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.assessor ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.assessor_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id integer NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user (
    id integer NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    email character varying(254) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL
);


--
-- Name: auth_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_groups (
    id integer NOT NULL,
    user_id integer NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: auth_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_user_user_permissions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: comparable_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comparable_cache (
    id bigint NOT NULL,
    parcel_number character varying(20) NOT NULL,
    roll_year integer NOT NULL,
    radius_meters integer NOT NULL,
    "limit" integer NOT NULL,
    comparables jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_refreshed timestamp with time zone NOT NULL
);


--
-- Name: comparable_cache_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.comparable_cache ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.comparable_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: conversation_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversation_messages (
    id bigint NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    sources jsonb NOT NULL,
    model character varying(100),
    created_at timestamp with time zone NOT NULL,
    conversation_id uuid NOT NULL
);


--
-- Name: conversation_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.conversation_messages ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.conversation_messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: conversations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.conversations (
    id uuid NOT NULL,
    session_key character varying(255),
    title character varying(255) NOT NULL,
    context_data jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: dem_aspect_tiled; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_aspect_tiled (
    tile_id integer,
    rast public.raster
);


--
-- Name: dem_aspect_tiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_aspect_tiles (
    tile_id integer,
    rast public.raster
);


--
-- Name: dem_aspect_tiles_utm; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_aspect_tiles_utm (
    rast public.raster,
    tile_id integer NOT NULL
);


--
-- Name: dem_aspect_tiles_utm_tile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dem_aspect_tiles_utm_tile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dem_aspect_tiles_utm_tile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dem_aspect_tiles_utm_tile_id_seq OWNED BY public.dem_aspect_tiles_utm.tile_id;


--
-- Name: dem_elev_tiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_elev_tiles (
    rast public.raster,
    tile_id integer NOT NULL
);


--
-- Name: dem_elev_tiles_tile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dem_elev_tiles_tile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dem_elev_tiles_tile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dem_elev_tiles_tile_id_seq OWNED BY public.dem_elev_tiles.tile_id;


--
-- Name: dem_skagit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_skagit (
    rid integer NOT NULL,
    rast public.raster,
    CONSTRAINT enforce_height_rast CHECK ((public.st_height(rast) = 3612)),
    CONSTRAINT enforce_nodata_values_rast CHECK ((public._raster_constraint_nodata_values(rast) = '{-999999.0000000000}'::numeric[])),
    CONSTRAINT enforce_num_bands_rast CHECK ((public.st_numbands(rast) = 1)),
    CONSTRAINT enforce_out_db_rast CHECK ((public._raster_constraint_out_db(rast) = '{f}'::boolean[])),
    CONSTRAINT enforce_pixel_types_rast CHECK ((public._raster_constraint_pixel_types(rast) = '{32BF}'::text[])),
    CONSTRAINT enforce_same_alignment_rast CHECK (public.st_samealignment(rast, '010000000086A09D3A5634323F86A09D3A563432BF80EC10561BC05EC0CF1B80B63680484000000000000000000000000000000000E610000001000100'::public.raster)),
    CONSTRAINT enforce_scalex_rast CHECK ((round((public.st_scalex(rast))::numeric, 10) = round(0.000277777721399371, 10))),
    CONSTRAINT enforce_scaley_rast CHECK ((round((public.st_scaley(rast))::numeric, 10) = round((- 0.000277777721399371), 10))),
    CONSTRAINT enforce_srid_rast CHECK ((public.st_srid(rast) = 4326)),
    CONSTRAINT enforce_width_rast CHECK ((public.st_width(rast) = 7212))
);


--
-- Name: dem_skagit_rid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dem_skagit_rid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dem_skagit_rid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dem_skagit_rid_seq OWNED BY public.dem_skagit.rid;


--
-- Name: dem_slope_tiled; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_slope_tiled (
    tile_id integer,
    rast public.raster
);


--
-- Name: dem_slope_tiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_slope_tiles (
    rast public.raster,
    tile_id integer NOT NULL
);


--
-- Name: dem_slope_tiles_tile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dem_slope_tiles_tile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dem_slope_tiles_tile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dem_slope_tiles_tile_id_seq OWNED BY public.dem_slope_tiles.tile_id;


--
-- Name: dem_tiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_tiles (
    rast public.raster,
    tile_id integer NOT NULL
);


--
-- Name: dem_tiles_tile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.dem_tiles_tile_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dem_tiles_tile_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.dem_tiles_tile_id_seq OWNED BY public.dem_tiles.tile_id;


--
-- Name: dem_utm10; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_utm10 (
    tile_id bigint,
    rast public.raster
);


--
-- Name: dem_utm10_tiled; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dem_utm10_tiled (
    tile_id bigint,
    rast public.raster
);


--
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id integer NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id integer NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: flood_skagit_fema; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.flood_skagit_fema (
    ogc_fid integer NOT NULL,
    dfirm_id character varying(6),
    version_id character varying(11),
    fld_ar_id character varying(32),
    study_typ character varying(28),
    fld_zone character varying(17),
    zone_subty character varying(57),
    sfha_tf character varying(1),
    static_bfe numeric(31,15),
    v_datum character varying(17),
    depth numeric(31,15),
    len_unit character varying(16),
    velocity numeric(31,15),
    vel_unit character varying(20),
    ar_revert character varying(17),
    ar_subtrv character varying(57),
    bfe_revert numeric(31,15),
    dep_revert numeric(31,15),
    dual_zone character varying(1),
    source_cit character varying(21),
    geom public.geometry(Polygon,4326)
);


--
-- Name: flood_skagit_fema_3857; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.flood_skagit_fema_3857 AS
 SELECT f.ogc_fid,
    f.dfirm_id,
    f.version_id,
    f.fld_ar_id,
    f.study_typ,
    f.fld_zone,
    f.zone_subty,
    f.sfha_tf,
    f.static_bfe,
    f.v_datum,
    f.depth,
    f.len_unit,
    f.velocity,
    f.vel_unit,
    f.ar_revert,
    f.ar_subtrv,
    f.bfe_revert,
    f.dep_revert,
    f.dual_zone,
    f.source_cit,
    f.geom,
    public.st_transform(f.geom, 3857) AS geom_3857
   FROM public.flood_skagit_fema f
  WHERE (f.geom IS NOT NULL)
  WITH NO DATA;


--
-- Name: flood_skagit_fema_ogc_fid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.flood_skagit_fema_ogc_fid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: flood_skagit_fema_ogc_fid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.flood_skagit_fema_ogc_fid_seq OWNED BY public.flood_skagit_fema.ogc_fid;


--
-- Name: floodway_skagit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.floodway_skagit (
    ogc_fid integer NOT NULL,
    dfirm_id character varying(6),
    version_id character varying(11),
    fld_ln_id character varying(32),
    ln_typ character varying(26),
    source_cit character varying(21),
    wkb_geometry public.geometry(LineString,4326)
);


--
-- Name: floodway_skagit_ogc_fid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.floodway_skagit_ogc_fid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: floodway_skagit_ogc_fid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.floodway_skagit_ogc_fid_seq OWNED BY public.floodway_skagit.ogc_fid;


--
-- Name: improvement_map_temp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.improvement_map_temp (
    improvement_id text,
    detail_type_code text
);


--
-- Name: improvements; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.improvements (
    parcel_number text,
    improvement_id bigint,
    description text,
    building_style text,
    comment text,
    improvement_value bigint,
    new_construction_year real,
    total_living_area real,
    segment_id bigint,
    improvement_detail_type_code text,
    improvement_detail_class_code text,
    improvement_detail_method_code real,
    condition_code text,
    calculated_area real,
    unit_price real,
    depreciation_pct real,
    improvement_detail_value bigint,
    construction_style text,
    foundation text,
    exterior_wall text,
    roof_covering text,
    roof_style text,
    flooring text,
    floor_construction text,
    interior_finish text,
    plumbing_code text,
    appliances text,
    heating_cooling text,
    fireplace text,
    rooms real,
    bedrooms real,
    effective_year_built real,
    actual_year_built bigint,
    sketch_path text,
    roll_id bigint,
    id bigint NOT NULL
);


--
-- Name: improvements_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.improvements ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.improvements_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: land; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.land (
    parcel_number text,
    property_value_year real,
    land_segment_id real,
    land_type text,
    appraisal_method text,
    size_acres real,
    size_square_feet real,
    land_adjustment_factor real,
    adjusted_value real,
    market_unit_price real,
    market_value real,
    open_space_value real,
    agricultural_unit_price real,
    roll_id bigint,
    id bigint NOT NULL
);


--
-- Name: land_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.land ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.land_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_adjustmentcoefficient; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_adjustmentcoefficient (
    id bigint NOT NULL,
    market_group character varying(100) NOT NULL,
    term character varying(200) NOT NULL,
    beta double precision NOT NULL,
    beta_se double precision,
    run_id character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: openskagit_adjustmentcoefficient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_adjustmentcoefficient ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_adjustmentcoefficient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_adjustmentmodelsegment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_adjustmentmodelsegment (
    id bigint NOT NULL,
    market_group character varying(100) NOT NULL,
    value_tier character varying(20) NOT NULL,
    price_min double precision NOT NULL,
    price_max double precision NOT NULL,
    n_obs integer NOT NULL,
    r2 double precision,
    cod double precision,
    prd double precision,
    median_ratio double precision,
    included_predictors jsonb NOT NULL,
    run_id bigint NOT NULL
);


--
-- Name: openskagit_adjustmentmodelsegment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_adjustmentmodelsegment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_adjustmentmodelsegment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_adjustmentrunsummary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_adjustmentrunsummary (
    id bigint NOT NULL,
    run_id character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    stats jsonb NOT NULL,
    content jsonb NOT NULL
);


--
-- Name: openskagit_adjustmentrunsummary_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_adjustmentrunsummary ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_adjustmentrunsummary_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_assessmentroll_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_assessmentroll ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_assessmentroll_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_cmaanalysis; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_cmaanalysis (
    id bigint NOT NULL,
    share_uuid uuid NOT NULL,
    subject_parcel character varying(32) NOT NULL,
    subject_snapshot jsonb NOT NULL,
    filters jsonb NOT NULL,
    manual_adjustments jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id integer
);


--
-- Name: openskagit_cmaanalysis_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_cmaanalysis ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_cmaanalysis_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_cmacomparableselection; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_cmacomparableselection (
    id bigint NOT NULL,
    parcel_number character varying(32) NOT NULL,
    included boolean NOT NULL,
    rank integer NOT NULL,
    raw_sale_price numeric(15,2) NOT NULL,
    adjusted_sale_price numeric(15,2) NOT NULL,
    gross_percentage_adjustment numeric(6,2) NOT NULL,
    auto_adjustments jsonb NOT NULL,
    manual_adjustments jsonb NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    analysis_id bigint NOT NULL,
    CONSTRAINT openskagit_cmacomparableselection_rank_check CHECK ((rank >= 0))
);


--
-- Name: openskagit_cmacomparableselection_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_cmacomparableselection ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_cmacomparableselection_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_neighborhoodgeom; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_neighborhoodgeom (
    id bigint NOT NULL,
    code character varying(20) NOT NULL,
    name character varying(100) NOT NULL,
    geom_3857 public.geometry(MultiPolygon,3857) NOT NULL,
    geom_4326 public.geometry(MultiPolygon,4326) NOT NULL
);


--
-- Name: openskagit_neighborhoodgeom_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_neighborhoodgeom ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_neighborhoodgeom_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_neighborhoodmetrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_neighborhoodmetrics (
    id bigint NOT NULL,
    neighborhood_code character varying(20) NOT NULL,
    year integer NOT NULL,
    sales_ratio double precision,
    median_ratio double precision,
    cod double precision,
    prd double precision,
    sample_size integer NOT NULL,
    reliability character varying(20) NOT NULL,
    computed_at timestamp with time zone NOT NULL
);


--
-- Name: openskagit_neighborhoodmetrics_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_neighborhoodmetrics ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_neighborhoodmetrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_neighborhoodprofile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_neighborhoodprofile (
    id bigint NOT NULL,
    hood_id character varying(20) NOT NULL,
    name character varying(200),
    city character varying(50),
    json_data jsonb NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    ai_summary text
);


--
-- Name: openskagit_neighborhoodprofile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_neighborhoodprofile ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_neighborhoodprofile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_neighborhoodtrend; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_neighborhoodtrend (
    id bigint NOT NULL,
    hood_id character varying(20) NOT NULL,
    value_year integer NOT NULL,
    median_land_market integer,
    median_building integer,
    median_market_total integer,
    median_tax_amount integer,
    yoy_change_land double precision,
    yoy_change_building double precision,
    yoy_change_total double precision,
    yoy_change_tax double precision,
    stability_score double precision,
    boom_bust_flag character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: openskagit_neighborhoodtrend_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_neighborhoodtrend ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_neighborhoodtrend_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_parcelhistory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_parcelhistory (
    id bigint NOT NULL,
    parcel_number character varying(20) NOT NULL,
    rows jsonb NOT NULL,
    scraped_at timestamp with time zone NOT NULL,
    neighborhood_code character varying(20),
    roll_year integer
);


--
-- Name: openskagit_parcelhistory_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_parcelhistory ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_parcelhistory_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_regressionadjustment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_regressionadjustment (
    id bigint NOT NULL,
    variable character varying(100) NOT NULL,
    adjustment_pct double precision NOT NULL,
    model_version character varying(50) NOT NULL,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: openskagit_regressionadjustment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.openskagit_regressionadjustment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.openskagit_regressionadjustment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: openskagit_taxcodearea; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_taxcodearea (
    code character varying(64) NOT NULL,
    county_name character varying(64),
    levy_rate_total double precision,
    geom public.geometry(Geometry,4326) NOT NULL
);


--
-- Name: openskagit_taxingdistrict; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.openskagit_taxingdistrict (
    district_type character varying(32) NOT NULL,
    district_code character varying(64) NOT NULL,
    name character varying(128) NOT NULL,
    levy_rate double precision,
    geom public.geometry(Geometry,4326) NOT NULL
);


--
-- Name: parcel; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcel (
    id bigint NOT NULL,
    parcel_number character varying(20) NOT NULL,
    address character varying(255),
    neighborhood_code character varying(100),
    land_use_code character varying(100),
    property_type character varying(1) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    neighborhood_description character varying(255)
);


--
-- Name: parcel_geo_diagnostics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcel_geo_diagnostics (
    check_name text,
    severity text,
    detail text
);


--
-- Name: parcel_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.parcel ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.parcel_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: parcel_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcel_points (
    gid integer NOT NULL,
    pnumberid double precision,
    pnumber character varying(10),
    entityhand character varying(25),
    xcoordinat numeric,
    ycoordinat numeric,
    zcoordinat numeric,
    drawingnam character varying(10),
    rotation numeric,
    scale double precision,
    interest double precision,
    accounttyp double precision,
    parentprop character varying(10),
    moddate date,
    moduser character varying(20),
    verified double precision,
    globalid character varying(38),
    geom public.geometry(Point,4326)
);


--
-- Name: parcel_points_gid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.parcel_points_gid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: parcel_points_gid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.parcel_points_gid_seq OWNED BY public.parcel_points.gid;


--
-- Name: parcels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcels (
    gid integer NOT NULL,
    parcelid character varying(10),
    parceltype numeric,
    globalid character varying(38),
    shape_star numeric,
    shape_stle numeric,
    geom public.geometry(MultiPolygon,4326)
);


--
-- Name: parcels_gid_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.parcels_gid_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: parcels_gid_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.parcels_gid_seq OWNED BY public.parcels.gid;


--
-- Name: planet_osm_nodes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.planet_osm_nodes (
    id bigint NOT NULL,
    lat integer NOT NULL,
    lon integer NOT NULL
);


--
-- Name: planet_osm_rels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.planet_osm_rels (
    id bigint NOT NULL,
    way_off smallint,
    rel_off smallint,
    parts bigint[],
    members text[],
    tags text[]
);


--
-- Name: planet_osm_ways; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.planet_osm_ways (
    id bigint NOT NULL,
    nodes bigint[] NOT NULL,
    tags text[]
);


--
-- Name: property_features; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.property_features AS
 SELECT p.parcel_number,
    max((p.address)::text) AS address,
    max((p.neighborhood_code)::text) AS neighborhood_code,
    max((p.land_use_code)::text) AS land_use_code,
    max(a.assessed_value) AS assessed_value,
    sum(l.size_acres) AS land_acres,
    sum(l.market_value) AS land_market_value
   FROM ((public.parcel p
     LEFT JOIN public.assessor a ON (((p.parcel_number)::text = a.parcel_number)))
     LEFT JOIN public.land l ON (((p.parcel_number)::text = l.parcel_number)))
  GROUP BY p.parcel_number
  WITH NO DATA;


--
-- Name: property_improvement_features; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.property_improvement_features AS
 SELECT p.parcel_number,
    TRIM(BOTH FROM upper(i.description)) AS improvement_type,
    sum(i.calculated_area) AS total_area,
    count(*) AS structure_count
   FROM (public.parcel p
     LEFT JOIN public.improvements i ON (((p.parcel_number)::text = i.parcel_number)))
  WHERE ((i.description IS NOT NULL) AND (TRIM(BOTH FROM i.description) <> ''::text))
  GROUP BY p.parcel_number, (TRIM(BOTH FROM upper(i.description)))
  WITH NO DATA;


--
-- Name: regression_results; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regression_results (
    id bigint NOT NULL,
    model_type character varying(50) NOT NULL,
    run_date timestamp with time zone NOT NULL,
    n_obs integer NOT NULL,
    r_squared double precision NOT NULL,
    adj_r_squared double precision NOT NULL,
    coefficients jsonb NOT NULL,
    notes text NOT NULL,
    roll_id bigint NOT NULL
);


--
-- Name: regression_results_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.regression_results ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.regression_results_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: sales; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sales (
    sale_id bigint,
    parcel_number text,
    account_number text,
    seller_name text,
    buyer_name text,
    sale_price bigint,
    sale_date timestamp without time zone,
    sale_type text,
    recording_number text,
    deed_type text,
    deed_date timestamp without time zone,
    revaluation_area real,
    excise_number real,
    roll_id bigint,
    id bigint NOT NULL
);


--
-- Name: sale_regression_dataset; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sale_regression_dataset AS
 SELECT row_number() OVER () AS id,
    s.id AS sale_id,
    s.parcel_number,
    r.year,
    s.sale_price,
    s.sale_date,
    a.assessed_value,
    a.total_market_value,
    a.living_area,
    a.bedrooms,
    a.bathrooms,
    a.acres AS lot_acres,
    a.year_built,
    a.eff_year_built,
    a.condition_code,
    a.condition_score,
    a.quality_score,
        CASE
            WHEN (a.year_built IS NULL) THEN NULL::bigint
            ELSE (2025 - a.year_built)
        END AS age_raw,
    power((
        CASE
            WHEN (a.year_built IS NOT NULL) THEN (2025 - a.year_built)
            ELSE NULL::bigint
        END)::double precision, (2)::double precision) AS age_sq,
    ln((NULLIF(a.living_area, 0))::double precision) AS living_area_log,
    ln((NULLIF(a.acres, (0)::double precision))::double precision) AS lot_acres_log,
    ln((NULLIF(a.total_market_value, 0))::double precision) AS log_total_mv,
    ((a.living_area)::double precision / NULLIF((a.acres * (43560)::double precision), (0)::double precision)) AS floor_area_ratio,
    a.elev,
    a.elevation,
    a.slope,
    a.aspect,
    a.aspect_dir,
        CASE
            WHEN (a.slope < (5)::double precision) THEN 'FLAT'::text
            WHEN (a.slope < (15)::double precision) THEN 'ROLLING'::text
            WHEN (a.slope < (30)::double precision) THEN 'HILLSIDE'::text
            ELSE 'STEEP'::text
        END AS slope_category,
    a.in_flood_zone,
    a.flood_distance,
    a.flood_static_bfe,
    a.flood_depth,
    a.flood_velocity,
    a.flood_sfha,
    a.flood_zone,
    a.flood_zone_subtype,
    a.flood_zone_id,
    a.dist_floodway,
        CASE
            WHEN a.in_flood_zone THEN 1
            WHEN (a.flood_distance < (50)::double precision) THEN 1
            WHEN (a.flood_depth > (0)::double precision) THEN 1
            ELSE 0
        END AS flood_influence,
    a.dist_major_road,
    public.st_x((a.centroid_geog)::public.geometry) AS lon,
    public.st_y((a.centroid_geog)::public.geometry) AS lat,
    public.st_area(a.geom_2926) AS parcel_area_sqft,
    public.st_perimeter(a.geom_2926) AS parcel_perimeter,
    (public.st_perimeter(a.geom_2926) / NULLIF(sqrt(public.st_area(a.geom_2926)), (0)::double precision)) AS parcel_compactness,
    a.neighborhood_code,
    a.land_use_code,
    a.property_type,
        CASE
            WHEN ((a.neighborhood_code ~~ '20B%'::text) OR (a.neighborhood_code ~~ '21B%'::text) OR (a.neighborhood_code ~~ '22B%'::text) OR (a.neighborhood_code ~~ '23B%'::text) OR (a.neighborhood_code ~~ '26B%'::text) OR (a.neighborhood_code ~~ '27B%'::text)) THEN 'BURLINGTON'::text
            WHEN ((a.neighborhood_code ~~ '20LC%'::text) OR (a.neighborhood_code ~~ '21LC%'::text) OR (a.neighborhood_code ~~ '22LC%'::text) OR (a.neighborhood_code ~~ '23LC%'::text) OR (a.neighborhood_code ~~ '20CON%'::text) OR (a.neighborhood_code ~~ '22CON%'::text)) THEN 'LACONNER_CONWAY'::text
            WHEN ((a.neighborhood_code ~~ '20A%'::text) OR (a.neighborhood_code ~~ '21A%'::text) OR (a.neighborhood_code ~~ '22A%'::text) OR (a.neighborhood_code ~~ '23A%'::text) OR (a.neighborhood_code ~~ '20FID%'::text) OR (a.neighborhood_code ~~ '22FID%'::text) OR (a.neighborhood_code ~~ '20GUEM%'::text) OR (a.neighborhood_code ~~ '22GUEM%'::text)) THEN 'ANACORTES'::text
            WHEN ((a.neighborhood_code ~~ '20SW%'::text) OR (a.neighborhood_code ~~ '21SW%'::text) OR (a.neighborhood_code ~~ '22SW%'::text) OR (a.neighborhood_code ~~ '23SW%'::text)) THEN 'SEDRO_WOOLLEY'::text
            WHEN ((a.neighborhood_code ~~ '20CC%'::text) OR (a.neighborhood_code ~~ '22CC%'::text) OR (a.neighborhood_code ~~ '10CC%'::text)) THEN 'CONCRETE'::text
            WHEN ((a.neighborhood_code ~~ '20MV%'::text) OR (a.neighborhood_code ~~ '21MV%'::text) OR (a.neighborhood_code ~~ '22MV%'::text) OR (a.neighborhood_code ~~ '23MV%'::text)) THEN 'MOUNT_VERNON'::text
            ELSE 'OTHER'::text
        END AS valuation_area,
        CASE
            WHEN ((a.neighborhood_code ~~* '%WFT%'::text) OR (a.neighborhood_code ~~* '%WATER%'::text) OR (a.neighborhood_code ~~* '%BAY%'::text) OR (a.neighborhood_code ~~* '%SHORE%'::text)) THEN 1
            WHEN ((a.neighborhood_code ~~* '%FID%'::text) OR (a.neighborhood_code ~~* '%GUEM%'::text) OR (a.neighborhood_code ~~* '%SKY%'::text)) THEN 1
            WHEN ((a.neighborhood_code ~~* '%MVHILL%'::text) OR (a.neighborhood_code ~~* '%MVHIGH%'::text) OR (a.neighborhood_code ~~* '%MVHILCRE%'::text) OR (a.neighborhood_code ~~* '%MVTBIRD%'::text)) THEN 1
            ELSE 0
        END AS is_view,
        CASE
            WHEN ((a.neighborhood_code ~~* '%WFT%'::text) OR (a.neighborhood_code ~~* '%WATER%'::text) OR (a.neighborhood_code ~~* '%BAY%'::text) OR (a.neighborhood_code ~~* '%SHORE%'::text)) THEN 'WATERFRONT'::text
            WHEN ((a.neighborhood_code ~~* '%RURAL%'::text) OR (a.neighborhood_code ~~* '%AGRES%'::text) OR (a.neighborhood_code ~~* '%FARM%'::text) OR (a.neighborhood_code ~~* '%AC%'::text)) THEN 'RURAL'::text
            WHEN ((a.neighborhood_code ~~* '%LEASE%'::text) OR (a.neighborhood_code ~~* '%MOBILE%'::text) OR (a.neighborhood_code ~~* '%MH%'::text)) THEN 'LEASED_LAND'::text
            ELSE 'URBAN_RESIDENTIAL'::text
        END AS valuation_subarea,
    max(
        CASE
            WHEN ((upper(TRIM(BOTH FROM i.improvement_detail_type_code)) ~~ 'AGAR%'::text) OR (upper(TRIM(BOTH FROM i.improvement_detail_type_code)) = 'GBI'::text)) THEN 1
            ELSE 0
        END) AS has_attached_garage,
    max(
        CASE
            WHEN (upper(TRIM(BOTH FROM i.improvement_detail_type_code)) ~~ 'DGAR%'::text) THEN 1
            ELSE 0
        END) AS has_detached_garage,
    GREATEST(max(
        CASE
            WHEN ((upper(TRIM(BOTH FROM i.improvement_detail_type_code)) ~~ 'AGAR%'::text) OR (upper(TRIM(BOTH FROM i.improvement_detail_type_code)) = 'GBI'::text)) THEN 1
            ELSE 0
        END), max(
        CASE
            WHEN (upper(TRIM(BOTH FROM i.improvement_detail_type_code)) ~~ 'DGAR%'::text) THEN 1
            ELSE 0
        END)) AS has_garage,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* ANY (ARRAY['DECK%'::text, 'CWP'::text, 'CP'::text, 'CCP'::text, 'ENP'::text, 'SUN'::text])) THEN 1
            ELSE 0
        END) AS has_deck_porch,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* ANY (ARRAY['MPS'::text, 'GPB%'::text, 'MSHD'::text, 'MCB'::text, 'SHOP'::text, 'SHED'::text])) THEN 1
            ELSE 0
        END) AS has_shop_or_shed,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* ANY (ARRAY['FDB'::text, 'FSB'::text, 'GPB'::text, 'HSTB'::text, 'LB'::text, 'MLKB'::text, 'MP'::text, 'PS'::text, 'PLH'::text, 'HRC'::text])) THEN 1
            ELSE 0
        END) AS has_barn,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* ANY (ARRAY['POOL'::text, 'BBQ'::text, 'OFP'::text, 'OS'::text, 'SUN'::text, 'ARNA'::text])) THEN 1
            ELSE 0
        END) AS has_luxury_feature,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* 'BM%'::text) THEN 1
            ELSE 0
        END) AS has_basement,
    max(
        CASE
            WHEN (i.improvement_detail_type_code ~~* ANY (ARRAY['SW%'::text, 'MW%'::text, 'PM%'::text])) THEN 1
            ELSE 0
        END) AS is_manufactured,
    (COALESCE(a.impr_land_value, (0)::real) + (COALESCE(a.unimpr_land_value, (0)::bigint))::double precision) AS land_market_value
   FROM (((public.sales s
     JOIN public.assessor a ON (((s.parcel_number = a.parcel_number) AND (s.roll_id = a.roll_id))))
     LEFT JOIN public.improvements i ON (((a.parcel_number = i.parcel_number) AND (a.roll_id = i.roll_id))))
     LEFT JOIN public.openskagit_assessmentroll r ON ((a.roll_id = r.id)))
  WHERE ((s.sale_type = 'VALID SALE'::text) AND (s.sale_price > 10000) AND (s.sale_date >= '2015-01-01'::date) AND (a.property_type = 'R'::text) AND (a.living_area > 0))
  GROUP BY s.id, s.parcel_number, r.year, s.sale_price, s.sale_date, a.assessed_value, a.total_market_value, a.living_area, a.bedrooms, a.bathrooms, a.acres, a.year_built, a.eff_year_built, a.condition_code, a.condition_score, a.quality_score, a.latitude, a.longitude, a.neighborhood_code, a.land_use_code, a.property_type, a.impr_land_value, a.unimpr_land_value, a.elev, a.elevation, a.slope, a.aspect, a.aspect_dir, a.in_flood_zone, a.flood_distance, a.flood_static_bfe, a.flood_depth, a.flood_velocity, a.flood_sfha, a.flood_zone, a.flood_zone_subtype, a.flood_zone_id, a.dist_floodway, a.dist_major_road, a.geom_2926, a.centroid_geog
  WITH NO DATA;


--
-- Name: sale_regression_mobile; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sale_regression_mobile AS
 SELECT sale_regression_dataset.id,
    sale_regression_dataset.sale_id,
    sale_regression_dataset.parcel_number,
    sale_regression_dataset.year,
    sale_regression_dataset.sale_price,
    sale_regression_dataset.sale_date,
    sale_regression_dataset.assessed_value,
    sale_regression_dataset.total_market_value,
    sale_regression_dataset.living_area,
    sale_regression_dataset.bedrooms,
    sale_regression_dataset.bathrooms,
    sale_regression_dataset.lot_acres,
    sale_regression_dataset.year_built,
    sale_regression_dataset.eff_year_built,
    sale_regression_dataset.condition_code,
    sale_regression_dataset.condition_score,
    sale_regression_dataset.quality_score,
    sale_regression_dataset.age_raw,
    sale_regression_dataset.age_sq,
    sale_regression_dataset.living_area_log,
    sale_regression_dataset.lot_acres_log,
    sale_regression_dataset.log_total_mv,
    sale_regression_dataset.floor_area_ratio,
    sale_regression_dataset.elev,
    sale_regression_dataset.elevation,
    sale_regression_dataset.slope,
    sale_regression_dataset.aspect,
    sale_regression_dataset.aspect_dir,
    sale_regression_dataset.slope_category,
    sale_regression_dataset.in_flood_zone,
    sale_regression_dataset.flood_distance,
    sale_regression_dataset.flood_static_bfe,
    sale_regression_dataset.flood_depth,
    sale_regression_dataset.flood_velocity,
    sale_regression_dataset.flood_sfha,
    sale_regression_dataset.flood_zone,
    sale_regression_dataset.flood_zone_subtype,
    sale_regression_dataset.flood_zone_id,
    sale_regression_dataset.dist_floodway,
    sale_regression_dataset.flood_influence,
    sale_regression_dataset.dist_major_road,
    sale_regression_dataset.lon,
    sale_regression_dataset.lat,
    sale_regression_dataset.parcel_area_sqft,
    sale_regression_dataset.parcel_perimeter,
    sale_regression_dataset.parcel_compactness,
    sale_regression_dataset.neighborhood_code,
    sale_regression_dataset.land_use_code,
    sale_regression_dataset.property_type,
    sale_regression_dataset.valuation_area,
    sale_regression_dataset.is_view,
    sale_regression_dataset.valuation_subarea,
    sale_regression_dataset.has_attached_garage,
    sale_regression_dataset.has_detached_garage,
    sale_regression_dataset.has_garage,
    sale_regression_dataset.has_deck_porch,
    sale_regression_dataset.has_shop_or_shed,
    sale_regression_dataset.has_barn,
    sale_regression_dataset.has_luxury_feature,
    sale_regression_dataset.has_basement,
    sale_regression_dataset.is_manufactured,
    sale_regression_dataset.land_market_value
   FROM public.sale_regression_dataset
  WHERE ((sale_regression_dataset.is_manufactured = 1) OR ((sale_regression_dataset.land_use_code)::integer = ANY (ARRAY[180, 181])))
  WITH NO DATA;


--
-- Name: sale_regression_mobile_leased; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sale_regression_mobile_leased AS
 SELECT sale_regression_dataset.id,
    sale_regression_dataset.sale_id,
    sale_regression_dataset.parcel_number,
    sale_regression_dataset.year,
    sale_regression_dataset.sale_price,
    sale_regression_dataset.sale_date,
    sale_regression_dataset.assessed_value,
    sale_regression_dataset.total_market_value,
    sale_regression_dataset.living_area,
    sale_regression_dataset.bedrooms,
    sale_regression_dataset.bathrooms,
    sale_regression_dataset.lot_acres,
    sale_regression_dataset.year_built,
    sale_regression_dataset.eff_year_built,
    sale_regression_dataset.condition_code,
    sale_regression_dataset.condition_score,
    sale_regression_dataset.quality_score,
    sale_regression_dataset.age_raw,
    sale_regression_dataset.age_sq,
    sale_regression_dataset.living_area_log,
    sale_regression_dataset.lot_acres_log,
    sale_regression_dataset.log_total_mv,
    sale_regression_dataset.floor_area_ratio,
    sale_regression_dataset.elev,
    sale_regression_dataset.elevation,
    sale_regression_dataset.slope,
    sale_regression_dataset.aspect,
    sale_regression_dataset.aspect_dir,
    sale_regression_dataset.slope_category,
    sale_regression_dataset.in_flood_zone,
    sale_regression_dataset.flood_distance,
    sale_regression_dataset.flood_static_bfe,
    sale_regression_dataset.flood_depth,
    sale_regression_dataset.flood_velocity,
    sale_regression_dataset.flood_sfha,
    sale_regression_dataset.flood_zone,
    sale_regression_dataset.flood_zone_subtype,
    sale_regression_dataset.flood_zone_id,
    sale_regression_dataset.dist_floodway,
    sale_regression_dataset.flood_influence,
    sale_regression_dataset.dist_major_road,
    sale_regression_dataset.lon,
    sale_regression_dataset.lat,
    sale_regression_dataset.parcel_area_sqft,
    sale_regression_dataset.parcel_perimeter,
    sale_regression_dataset.parcel_compactness,
    sale_regression_dataset.neighborhood_code,
    sale_regression_dataset.land_use_code,
    sale_regression_dataset.property_type,
    sale_regression_dataset.valuation_area,
    sale_regression_dataset.is_view,
    sale_regression_dataset.valuation_subarea,
    sale_regression_dataset.has_attached_garage,
    sale_regression_dataset.has_detached_garage,
    sale_regression_dataset.has_garage,
    sale_regression_dataset.has_deck_porch,
    sale_regression_dataset.has_shop_or_shed,
    sale_regression_dataset.has_barn,
    sale_regression_dataset.has_luxury_feature,
    sale_regression_dataset.has_basement,
    sale_regression_dataset.is_manufactured,
    sale_regression_dataset.land_market_value
   FROM public.sale_regression_dataset
  WHERE ((sale_regression_dataset.land_use_code)::integer = 181)
  WITH NO DATA;


--
-- Name: sale_regression_mobile_owned; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sale_regression_mobile_owned AS
 SELECT sale_regression_dataset.id,
    sale_regression_dataset.sale_id,
    sale_regression_dataset.parcel_number,
    sale_regression_dataset.year,
    sale_regression_dataset.sale_price,
    sale_regression_dataset.sale_date,
    sale_regression_dataset.assessed_value,
    sale_regression_dataset.total_market_value,
    sale_regression_dataset.living_area,
    sale_regression_dataset.bedrooms,
    sale_regression_dataset.bathrooms,
    sale_regression_dataset.lot_acres,
    sale_regression_dataset.year_built,
    sale_regression_dataset.eff_year_built,
    sale_regression_dataset.condition_code,
    sale_regression_dataset.condition_score,
    sale_regression_dataset.quality_score,
    sale_regression_dataset.age_raw,
    sale_regression_dataset.age_sq,
    sale_regression_dataset.living_area_log,
    sale_regression_dataset.lot_acres_log,
    sale_regression_dataset.log_total_mv,
    sale_regression_dataset.floor_area_ratio,
    sale_regression_dataset.elev,
    sale_regression_dataset.elevation,
    sale_regression_dataset.slope,
    sale_regression_dataset.aspect,
    sale_regression_dataset.aspect_dir,
    sale_regression_dataset.slope_category,
    sale_regression_dataset.in_flood_zone,
    sale_regression_dataset.flood_distance,
    sale_regression_dataset.flood_static_bfe,
    sale_regression_dataset.flood_depth,
    sale_regression_dataset.flood_velocity,
    sale_regression_dataset.flood_sfha,
    sale_regression_dataset.flood_zone,
    sale_regression_dataset.flood_zone_subtype,
    sale_regression_dataset.flood_zone_id,
    sale_regression_dataset.dist_floodway,
    sale_regression_dataset.flood_influence,
    sale_regression_dataset.dist_major_road,
    sale_regression_dataset.lon,
    sale_regression_dataset.lat,
    sale_regression_dataset.parcel_area_sqft,
    sale_regression_dataset.parcel_perimeter,
    sale_regression_dataset.parcel_compactness,
    sale_regression_dataset.neighborhood_code,
    sale_regression_dataset.land_use_code,
    sale_regression_dataset.property_type,
    sale_regression_dataset.valuation_area,
    sale_regression_dataset.is_view,
    sale_regression_dataset.valuation_subarea,
    sale_regression_dataset.has_attached_garage,
    sale_regression_dataset.has_detached_garage,
    sale_regression_dataset.has_garage,
    sale_regression_dataset.has_deck_porch,
    sale_regression_dataset.has_shop_or_shed,
    sale_regression_dataset.has_barn,
    sale_regression_dataset.has_luxury_feature,
    sale_regression_dataset.has_basement,
    sale_regression_dataset.is_manufactured,
    sale_regression_dataset.land_market_value
   FROM public.sale_regression_dataset
  WHERE ((sale_regression_dataset.land_use_code)::integer = 180)
  WITH NO DATA;


--
-- Name: sale_regression_sfr; Type: MATERIALIZED VIEW; Schema: public; Owner: -
--

CREATE MATERIALIZED VIEW public.sale_regression_sfr AS
 SELECT sale_regression_dataset.id,
    sale_regression_dataset.sale_id,
    sale_regression_dataset.parcel_number,
    sale_regression_dataset.year,
    sale_regression_dataset.sale_price,
    sale_regression_dataset.sale_date,
    sale_regression_dataset.assessed_value,
    sale_regression_dataset.total_market_value,
    sale_regression_dataset.living_area,
    sale_regression_dataset.bedrooms,
    sale_regression_dataset.bathrooms,
    sale_regression_dataset.lot_acres,
    sale_regression_dataset.year_built,
    sale_regression_dataset.eff_year_built,
    sale_regression_dataset.condition_code,
    sale_regression_dataset.condition_score,
    sale_regression_dataset.quality_score,
    sale_regression_dataset.age_raw,
    sale_regression_dataset.age_sq,
    sale_regression_dataset.living_area_log,
    sale_regression_dataset.lot_acres_log,
    sale_regression_dataset.log_total_mv,
    sale_regression_dataset.floor_area_ratio,
    sale_regression_dataset.elev,
    sale_regression_dataset.elevation,
    sale_regression_dataset.slope,
    sale_regression_dataset.aspect,
    sale_regression_dataset.aspect_dir,
    sale_regression_dataset.slope_category,
    sale_regression_dataset.in_flood_zone,
    sale_regression_dataset.flood_distance,
    sale_regression_dataset.flood_static_bfe,
    sale_regression_dataset.flood_depth,
    sale_regression_dataset.flood_velocity,
    sale_regression_dataset.flood_sfha,
    sale_regression_dataset.flood_zone,
    sale_regression_dataset.flood_zone_subtype,
    sale_regression_dataset.flood_zone_id,
    sale_regression_dataset.dist_floodway,
    sale_regression_dataset.flood_influence,
    sale_regression_dataset.dist_major_road,
    sale_regression_dataset.lon,
    sale_regression_dataset.lat,
    sale_regression_dataset.parcel_area_sqft,
    sale_regression_dataset.parcel_perimeter,
    sale_regression_dataset.parcel_compactness,
    sale_regression_dataset.neighborhood_code,
    sale_regression_dataset.land_use_code,
    sale_regression_dataset.property_type,
    sale_regression_dataset.valuation_area,
    sale_regression_dataset.is_view,
    sale_regression_dataset.valuation_subarea,
    sale_regression_dataset.has_attached_garage,
    sale_regression_dataset.has_detached_garage,
    sale_regression_dataset.has_garage,
    sale_regression_dataset.has_deck_porch,
    sale_regression_dataset.has_shop_or_shed,
    sale_regression_dataset.has_barn,
    sale_regression_dataset.has_luxury_feature,
    sale_regression_dataset.has_basement,
    sale_regression_dataset.is_manufactured,
    sale_regression_dataset.land_market_value
   FROM public.sale_regression_dataset
  WHERE ((sale_regression_dataset.is_manufactured = 0) AND ((sale_regression_dataset.land_use_code)::integer = ANY (ARRAY[110, 111, 112, 113])))
  WITH NO DATA;


--
-- Name: sales_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.sales ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.sales_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: temp_slope_updates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temp_slope_updates (
    id bigint,
    slope_val double precision
);


--
-- Name: bg_wa_raw ogc_fid; Type: DEFAULT; Schema: census; Owner: -
--

ALTER TABLE ONLY census.bg_wa_raw ALTER COLUMN ogc_fid SET DEFAULT nextval('census.bg_wa_raw_ogc_fid_seq'::regclass);


--
-- Name: dem_aspect_tiles_utm tile_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_aspect_tiles_utm ALTER COLUMN tile_id SET DEFAULT nextval('public.dem_aspect_tiles_utm_tile_id_seq'::regclass);


--
-- Name: dem_elev_tiles tile_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_elev_tiles ALTER COLUMN tile_id SET DEFAULT nextval('public.dem_elev_tiles_tile_id_seq'::regclass);


--
-- Name: dem_skagit rid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_skagit ALTER COLUMN rid SET DEFAULT nextval('public.dem_skagit_rid_seq'::regclass);


--
-- Name: dem_slope_tiles tile_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_slope_tiles ALTER COLUMN tile_id SET DEFAULT nextval('public.dem_slope_tiles_tile_id_seq'::regclass);


--
-- Name: dem_tiles tile_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_tiles ALTER COLUMN tile_id SET DEFAULT nextval('public.dem_tiles_tile_id_seq'::regclass);


--
-- Name: flood_skagit_fema ogc_fid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flood_skagit_fema ALTER COLUMN ogc_fid SET DEFAULT nextval('public.flood_skagit_fema_ogc_fid_seq'::regclass);


--
-- Name: floodway_skagit ogc_fid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.floodway_skagit ALTER COLUMN ogc_fid SET DEFAULT nextval('public.floodway_skagit_ogc_fid_seq'::regclass);


--
-- Name: parcel_points gid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcel_points ALTER COLUMN gid SET DEFAULT nextval('public.parcel_points_gid_seq'::regclass);


--
-- Name: parcels gid; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels ALTER COLUMN gid SET DEFAULT nextval('public.parcels_gid_seq'::regclass);


--
-- Name: bg_wa_raw bg_wa_raw_pkey; Type: CONSTRAINT; Schema: census; Owner: -
--

ALTER TABLE ONLY census.bg_wa_raw
    ADD CONSTRAINT bg_wa_raw_pkey PRIMARY KEY (ogc_fid);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_pkey PRIMARY KEY (id);


--
-- Name: auth_user_groups auth_user_groups_user_id_group_id_94350c0c_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_group_id_94350c0c_uniq UNIQUE (user_id, group_id);


--
-- Name: auth_user auth_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_permission_id_14a6b632_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_permission_id_14a6b632_uniq UNIQUE (user_id, permission_id);


--
-- Name: auth_user auth_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user
    ADD CONSTRAINT auth_user_username_key UNIQUE (username);


--
-- Name: comparable_cache comparable_cache_parcel_number_roll_year__3f1a1a63_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comparable_cache
    ADD CONSTRAINT comparable_cache_parcel_number_roll_year__3f1a1a63_uniq UNIQUE (parcel_number, roll_year, radius_meters, "limit");


--
-- Name: comparable_cache comparable_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comparable_cache
    ADD CONSTRAINT comparable_cache_pkey PRIMARY KEY (id);


--
-- Name: conversation_messages conversation_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_messages_pkey PRIMARY KEY (id);


--
-- Name: conversations conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);


--
-- Name: dem_aspect_tiles_utm dem_aspect_tiles_utm_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_aspect_tiles_utm
    ADD CONSTRAINT dem_aspect_tiles_utm_pkey PRIMARY KEY (tile_id);


--
-- Name: dem_elev_tiles dem_elev_tiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_elev_tiles
    ADD CONSTRAINT dem_elev_tiles_pkey PRIMARY KEY (tile_id);


--
-- Name: dem_skagit dem_skagit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_skagit
    ADD CONSTRAINT dem_skagit_pkey PRIMARY KEY (rid);


--
-- Name: dem_slope_tiles dem_slope_tiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_slope_tiles
    ADD CONSTRAINT dem_slope_tiles_pkey PRIMARY KEY (tile_id);


--
-- Name: dem_tiles dem_tiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dem_tiles
    ADD CONSTRAINT dem_tiles_pkey PRIMARY KEY (tile_id);


--
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: dem_skagit enforce_max_extent_rast; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.dem_skagit
    ADD CONSTRAINT enforce_max_extent_rast CHECK ((public.st_envelope(rast) OPERATOR(public.@) '0103000020E6100000010000000500000080EC10561BC05EC0CD972E7EC9FF474080EC10561BC05EC0CF1B80B6368048405618C2BAE43F5EC0CF1B80B6368048405618C2BAE43F5EC0CD972E7EC9FF474080EC10561BC05EC0CD972E7EC9FF4740'::public.geometry)) NOT VALID;


--
-- Name: flood_skagit_fema flood_skagit_fema_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.flood_skagit_fema
    ADD CONSTRAINT flood_skagit_fema_pkey PRIMARY KEY (ogc_fid);


--
-- Name: floodway_skagit floodway_skagit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.floodway_skagit
    ADD CONSTRAINT floodway_skagit_pkey PRIMARY KEY (ogc_fid);


--
-- Name: openskagit_adjustmentcoefficient openskagit_adjustmentcoe_market_group_term_run_id_affaf948_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentcoefficient
    ADD CONSTRAINT openskagit_adjustmentcoe_market_group_term_run_id_affaf948_uniq UNIQUE (market_group, term, run_id);


--
-- Name: openskagit_adjustmentcoefficient openskagit_adjustmentcoefficient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentcoefficient
    ADD CONSTRAINT openskagit_adjustmentcoefficient_pkey PRIMARY KEY (id);


--
-- Name: openskagit_adjustmentmodelsegment openskagit_adjustmentmod_run_id_market_group_valu_54592b6f_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentmodelsegment
    ADD CONSTRAINT openskagit_adjustmentmod_run_id_market_group_valu_54592b6f_uniq UNIQUE (run_id, market_group, value_tier);


--
-- Name: openskagit_adjustmentmodelsegment openskagit_adjustmentmodelsegment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentmodelsegment
    ADD CONSTRAINT openskagit_adjustmentmodelsegment_pkey PRIMARY KEY (id);


--
-- Name: openskagit_adjustmentrunsummary openskagit_adjustmentrunsummary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentrunsummary
    ADD CONSTRAINT openskagit_adjustmentrunsummary_pkey PRIMARY KEY (id);


--
-- Name: openskagit_adjustmentrunsummary openskagit_adjustmentrunsummary_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentrunsummary
    ADD CONSTRAINT openskagit_adjustmentrunsummary_run_id_key UNIQUE (run_id);


--
-- Name: openskagit_assessmentroll openskagit_assessmentroll_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_assessmentroll
    ADD CONSTRAINT openskagit_assessmentroll_pkey PRIMARY KEY (id);


--
-- Name: openskagit_cmaanalysis openskagit_cmaanalysis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmaanalysis
    ADD CONSTRAINT openskagit_cmaanalysis_pkey PRIMARY KEY (id);


--
-- Name: openskagit_cmaanalysis openskagit_cmaanalysis_share_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmaanalysis
    ADD CONSTRAINT openskagit_cmaanalysis_share_uuid_key UNIQUE (share_uuid);


--
-- Name: openskagit_cmacomparableselection openskagit_cmacomparable_analysis_id_parcel_numbe_e53a799e_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmacomparableselection
    ADD CONSTRAINT openskagit_cmacomparable_analysis_id_parcel_numbe_e53a799e_uniq UNIQUE (analysis_id, parcel_number);


--
-- Name: openskagit_cmacomparableselection openskagit_cmacomparableselection_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmacomparableselection
    ADD CONSTRAINT openskagit_cmacomparableselection_pkey PRIMARY KEY (id);


--
-- Name: openskagit_neighborhoodgeom openskagit_neighborhoodgeom_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodgeom
    ADD CONSTRAINT openskagit_neighborhoodgeom_code_key UNIQUE (code);


--
-- Name: openskagit_neighborhoodgeom openskagit_neighborhoodgeom_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodgeom
    ADD CONSTRAINT openskagit_neighborhoodgeom_pkey PRIMARY KEY (id);


--
-- Name: openskagit_neighborhoodmetrics openskagit_neighborhoodmetrics_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodmetrics
    ADD CONSTRAINT openskagit_neighborhoodmetrics_pkey PRIMARY KEY (id);


--
-- Name: openskagit_neighborhoodprofile openskagit_neighborhoodprofile_hood_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodprofile
    ADD CONSTRAINT openskagit_neighborhoodprofile_hood_id_key UNIQUE (hood_id);


--
-- Name: openskagit_neighborhoodprofile openskagit_neighborhoodprofile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodprofile
    ADD CONSTRAINT openskagit_neighborhoodprofile_pkey PRIMARY KEY (id);


--
-- Name: openskagit_neighborhoodtrend openskagit_neighborhoodtrend_hood_id_value_year_b17e368b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodtrend
    ADD CONSTRAINT openskagit_neighborhoodtrend_hood_id_value_year_b17e368b_uniq UNIQUE (hood_id, value_year);


--
-- Name: openskagit_neighborhoodtrend openskagit_neighborhoodtrend_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_neighborhoodtrend
    ADD CONSTRAINT openskagit_neighborhoodtrend_pkey PRIMARY KEY (id);


--
-- Name: openskagit_parcelhistory openskagit_parcelhistory_parcel_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_parcelhistory
    ADD CONSTRAINT openskagit_parcelhistory_parcel_number_key UNIQUE (parcel_number);


--
-- Name: openskagit_parcelhistory openskagit_parcelhistory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_parcelhistory
    ADD CONSTRAINT openskagit_parcelhistory_pkey PRIMARY KEY (id);


--
-- Name: openskagit_regressionadjustment openskagit_regressionadjustment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_regressionadjustment
    ADD CONSTRAINT openskagit_regressionadjustment_pkey PRIMARY KEY (id);


--
-- Name: openskagit_taxcodearea openskagit_taxcodearea_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_taxcodearea
    ADD CONSTRAINT openskagit_taxcodearea_pkey PRIMARY KEY (code);


--
-- Name: openskagit_taxingdistrict openskagit_taxingdistrict_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_taxingdistrict
    ADD CONSTRAINT openskagit_taxingdistrict_pkey PRIMARY KEY (district_code);


--
-- Name: parcel parcel_parcel_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcel
    ADD CONSTRAINT parcel_parcel_number_key UNIQUE (parcel_number);


--
-- Name: parcel parcel_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcel
    ADD CONSTRAINT parcel_pkey PRIMARY KEY (id);


--
-- Name: parcel_points parcel_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcel_points
    ADD CONSTRAINT parcel_points_pkey PRIMARY KEY (gid);


--
-- Name: parcels parcels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels
    ADD CONSTRAINT parcels_pkey PRIMARY KEY (gid);


--
-- Name: planet_osm_nodes planet_osm_nodes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.planet_osm_nodes
    ADD CONSTRAINT planet_osm_nodes_pkey PRIMARY KEY (id);


--
-- Name: planet_osm_rels planet_osm_rels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.planet_osm_rels
    ADD CONSTRAINT planet_osm_rels_pkey PRIMARY KEY (id);


--
-- Name: planet_osm_ways planet_osm_ways_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.planet_osm_ways
    ADD CONSTRAINT planet_osm_ways_pkey PRIMARY KEY (id);


--
-- Name: regression_results regression_results_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regression_results
    ADD CONSTRAINT regression_results_pkey PRIMARY KEY (id);


--
-- Name: bg_skagit_geom_2926_idx; Type: INDEX; Schema: census; Owner: -
--

CREATE INDEX bg_skagit_geom_2926_idx ON census.bg_skagit USING gist (geom_2926);


--
-- Name: bg_wa_raw_geom_2926_idx; Type: INDEX; Schema: census; Owner: -
--

CREATE INDEX bg_wa_raw_geom_2926_idx ON census.bg_wa_raw USING gist (geom_2926);


--
-- Name: bg_wa_raw_geom_geom_idx; Type: INDEX; Schema: census; Owner: -
--

CREATE INDEX bg_wa_raw_geom_geom_idx ON census.bg_wa_raw USING gist (geom);


--
-- Name: idx_bg_skagit_geom; Type: INDEX; Schema: census; Owner: -
--

CREATE INDEX idx_bg_skagit_geom ON census.bg_skagit USING gist (geom);


--
-- Name: planet_osm_line_geom_2926_gix; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_line_geom_2926_gix ON osm.planet_osm_line USING gist (geom_2926);


--
-- Name: planet_osm_line_osm_id_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_line_osm_id_idx ON osm.planet_osm_line USING btree (osm_id);


--
-- Name: planet_osm_line_way_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_line_way_idx ON osm.planet_osm_line USING gist (way);


--
-- Name: planet_osm_point_geom_2926_gix; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_point_geom_2926_gix ON osm.planet_osm_point USING gist (geom_2926);


--
-- Name: planet_osm_point_osm_id_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_point_osm_id_idx ON osm.planet_osm_point USING btree (osm_id);


--
-- Name: planet_osm_point_way_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_point_way_idx ON osm.planet_osm_point USING gist (way);


--
-- Name: planet_osm_polygon_geom_2926_gix; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_polygon_geom_2926_gix ON osm.planet_osm_polygon USING gist (geom_2926);


--
-- Name: planet_osm_polygon_osm_id_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_polygon_osm_id_idx ON osm.planet_osm_polygon USING btree (osm_id);


--
-- Name: planet_osm_polygon_way_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_polygon_way_idx ON osm.planet_osm_polygon USING gist (way);


--
-- Name: planet_osm_roads_geom_2926_gix; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_roads_geom_2926_gix ON osm.planet_osm_roads USING gist (geom_2926);


--
-- Name: planet_osm_roads_osm_id_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_roads_osm_id_idx ON osm.planet_osm_roads USING btree (osm_id);


--
-- Name: planet_osm_roads_way_idx; Type: INDEX; Schema: osm; Owner: -
--

CREATE INDEX planet_osm_roads_way_idx ON osm.planet_osm_roads USING gist (way);


--
-- Name: assessor_address_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_address_trgm_idx ON public.assessor USING gin (address public.gin_trgm_ops);


--
-- Name: assessor_centroid_geog_gix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_centroid_geog_gix ON public.assessor USING gist (centroid_geog);


--
-- Name: assessor_geom_2926_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_geom_2926_idx ON public.assessor USING gist (geom_2926);


--
-- Name: assessor_geom_4326_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_geom_4326_idx ON public.assessor USING gist (geom_4326);


--
-- Name: assessor_parcel_number_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_parcel_number_idx ON public.assessor USING btree (parcel_number);


--
-- Name: assessor_property_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX assessor_property_type_idx ON public.assessor USING btree (property_type);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: auth_user_groups_group_id_97559544; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_group_id_97559544 ON public.auth_user_groups USING btree (group_id);


--
-- Name: auth_user_groups_user_id_6a12ed8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_groups_user_id_6a12ed8b ON public.auth_user_groups USING btree (user_id);


--
-- Name: auth_user_user_permissions_permission_id_1fbb5f2c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_permission_id_1fbb5f2c ON public.auth_user_user_permissions USING btree (permission_id);


--
-- Name: auth_user_user_permissions_user_id_a95ead1b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_user_permissions_user_id_a95ead1b ON public.auth_user_user_permissions USING btree (user_id);


--
-- Name: auth_user_username_6821ab7c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_user_username_6821ab7c_like ON public.auth_user USING btree (username varchar_pattern_ops);


--
-- Name: comparable__parcel__84e718_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comparable__parcel__84e718_idx ON public.comparable_cache USING btree (parcel_number, roll_year);


--
-- Name: comparable_cache_parcel_number_dc3fdb64; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comparable_cache_parcel_number_dc3fdb64 ON public.comparable_cache USING btree (parcel_number);


--
-- Name: comparable_cache_parcel_number_dc3fdb64_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comparable_cache_parcel_number_dc3fdb64_like ON public.comparable_cache USING btree (parcel_number varchar_pattern_ops);


--
-- Name: comparable_cache_roll_year_8b7a3f12; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX comparable_cache_roll_year_8b7a3f12 ON public.comparable_cache USING btree (roll_year);


--
-- Name: conversatio_convers_01af31_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversatio_convers_01af31_idx ON public.conversation_messages USING btree (conversation_id, created_at);


--
-- Name: conversatio_session_69f832_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversatio_session_69f832_idx ON public.conversations USING btree (session_key, updated_at DESC);


--
-- Name: conversatio_updated_c163ba_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversatio_updated_c163ba_idx ON public.conversations USING btree (updated_at DESC);


--
-- Name: conversation_messages_conversation_id_52b02ddd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversation_messages_conversation_id_52b02ddd ON public.conversation_messages USING btree (conversation_id);


--
-- Name: conversations_session_key_4a43491d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversations_session_key_4a43491d ON public.conversations USING btree (session_key);


--
-- Name: conversations_session_key_4a43491d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX conversations_session_key_4a43491d_like ON public.conversations USING btree (session_key varchar_pattern_ops);


--
-- Name: dem_aspect_tiles_gix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dem_aspect_tiles_gix ON public.dem_aspect_tiles USING gist (public.st_convexhull(rast));


--
-- Name: dem_skagit_rast_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dem_skagit_rast_gist ON public.dem_skagit USING gist (public.st_convexhull(rast));


--
-- Name: dem_skagit_st_convexhull_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dem_skagit_st_convexhull_idx ON public.dem_skagit USING gist (public.st_convexhull(rast));


--
-- Name: dem_tiles_rast_gix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dem_tiles_rast_gix ON public.dem_tiles USING gist (public.st_convexhull(rast));


--
-- Name: dem_utm10_tiled_st_envelope_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX dem_utm10_tiled_st_envelope_idx ON public.dem_utm10_tiled USING gist (public.st_envelope(rast));


--
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: flood_skagit_fema_geom_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX flood_skagit_fema_geom_geom_idx ON public.flood_skagit_fema USING gist (geom);


--
-- Name: floodway_skagit_wkb_geometry_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX floodway_skagit_wkb_geometry_geom_idx ON public.floodway_skagit USING gist (wkb_geometry);


--
-- Name: idx_assessor_address_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessor_address_trgm ON public.assessor USING gin (address public.gin_trgm_ops);


--
-- Name: idx_assessor_parcel_upper; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_assessor_parcel_upper ON public.assessor USING btree (upper(parcel_number));


--
-- Name: idx_dem_aspect_tiles_utm_rast; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dem_aspect_tiles_utm_rast ON public.dem_aspect_tiles_utm USING gist (public.st_envelope(rast));


--
-- Name: idx_dem_elev_tiles_rast; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dem_elev_tiles_rast ON public.dem_elev_tiles USING gist (public.st_envelope(rast));


--
-- Name: idx_dem_slope_tiles_rast_envelope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_dem_slope_tiles_rast_envelope ON public.dem_slope_tiles USING gist (public.st_envelope(rast));


--
-- Name: idx_flood_skagit_fema_3857_geom; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_flood_skagit_fema_3857_geom ON public.flood_skagit_fema_3857 USING gist (geom_3857);


--
-- Name: idx_floodway_geom_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_floodway_geom_gist ON public.floodway_skagit USING gist (wkb_geometry);


--
-- Name: idx_parcel_address_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parcel_address_trgm ON public.parcel USING gin (address public.gin_trgm_ops);


--
-- Name: idx_parcel_address_upper_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parcel_address_upper_trgm ON public.parcel USING gin (upper((address)::text) public.gin_trgm_ops);


--
-- Name: idx_parcel_number_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parcel_number_trgm ON public.parcel USING gin (parcel_number public.gin_trgm_ops);


--
-- Name: idx_parcel_upper_parcel_number; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parcel_upper_parcel_number ON public.parcel USING btree (upper((parcel_number)::text));


--
-- Name: idx_property_features_parcel; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX idx_property_features_parcel ON public.property_features USING btree (parcel_number);


--
-- Name: idx_property_improvement_features_parcel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_property_improvement_features_parcel ON public.property_improvement_features USING btree (parcel_number);


--
-- Name: openskagit__code_b65b0a_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit__code_b65b0a_idx ON public.openskagit_taxcodearea USING btree (code);


--
-- Name: openskagit__distric_cdc703_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit__distric_cdc703_idx ON public.openskagit_taxingdistrict USING btree (district_type, district_code);


--
-- Name: openskagit__hood_id_52cf7e_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit__hood_id_52cf7e_idx ON public.openskagit_neighborhoodtrend USING btree (hood_id, value_year);


--
-- Name: openskagit_adjustmentcoefficient_market_group_8c5e2c21; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_market_group_8c5e2c21 ON public.openskagit_adjustmentcoefficient USING btree (market_group);


--
-- Name: openskagit_adjustmentcoefficient_market_group_8c5e2c21_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_market_group_8c5e2c21_like ON public.openskagit_adjustmentcoefficient USING btree (market_group varchar_pattern_ops);


--
-- Name: openskagit_adjustmentcoefficient_run_id_2a7c2094; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_run_id_2a7c2094 ON public.openskagit_adjustmentcoefficient USING btree (run_id);


--
-- Name: openskagit_adjustmentcoefficient_run_id_2a7c2094_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_run_id_2a7c2094_like ON public.openskagit_adjustmentcoefficient USING btree (run_id varchar_pattern_ops);


--
-- Name: openskagit_adjustmentcoefficient_term_4161326c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_term_4161326c ON public.openskagit_adjustmentcoefficient USING btree (term);


--
-- Name: openskagit_adjustmentcoefficient_term_4161326c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentcoefficient_term_4161326c_like ON public.openskagit_adjustmentcoefficient USING btree (term varchar_pattern_ops);


--
-- Name: openskagit_adjustmentmodelsegment_run_id_f1959065; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentmodelsegment_run_id_f1959065 ON public.openskagit_adjustmentmodelsegment USING btree (run_id);


--
-- Name: openskagit_adjustmentrunsummary_run_id_c3fff42e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_adjustmentrunsummary_run_id_c3fff42e_like ON public.openskagit_adjustmentrunsummary USING btree (run_id varchar_pattern_ops);


--
-- Name: openskagit_assessmentroll_year_a9872180; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_assessmentroll_year_a9872180 ON public.openskagit_assessmentroll USING btree (year);


--
-- Name: openskagit_cmaanalysis_user_id_529d6313; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_cmaanalysis_user_id_529d6313 ON public.openskagit_cmaanalysis USING btree (user_id);


--
-- Name: openskagit_cmacomparableselection_analysis_id_a2451625; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_cmacomparableselection_analysis_id_a2451625 ON public.openskagit_cmacomparableselection USING btree (analysis_id);


--
-- Name: openskagit_neighborhoodgeom_code_6ec6533f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodgeom_code_6ec6533f_like ON public.openskagit_neighborhoodgeom USING btree (code varchar_pattern_ops);


--
-- Name: openskagit_neighborhoodgeom_geom_3857_ccca74e2_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodgeom_geom_3857_ccca74e2_id ON public.openskagit_neighborhoodgeom USING gist (geom_3857);


--
-- Name: openskagit_neighborhoodgeom_geom_4326_1173d657_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodgeom_geom_4326_1173d657_id ON public.openskagit_neighborhoodgeom USING gist (geom_4326);


--
-- Name: openskagit_neighborhoodmetrics_neighborhood_code_089beb6a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodmetrics_neighborhood_code_089beb6a ON public.openskagit_neighborhoodmetrics USING btree (neighborhood_code);


--
-- Name: openskagit_neighborhoodmetrics_neighborhood_code_089beb6a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodmetrics_neighborhood_code_089beb6a_like ON public.openskagit_neighborhoodmetrics USING btree (neighborhood_code varchar_pattern_ops);


--
-- Name: openskagit_neighborhoodprofile_hood_id_5ad1cc14_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodprofile_hood_id_5ad1cc14_like ON public.openskagit_neighborhoodprofile USING btree (hood_id varchar_pattern_ops);


--
-- Name: openskagit_neighborhoodtrend_hood_id_a81d2a29; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodtrend_hood_id_a81d2a29 ON public.openskagit_neighborhoodtrend USING btree (hood_id);


--
-- Name: openskagit_neighborhoodtrend_hood_id_a81d2a29_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodtrend_hood_id_a81d2a29_like ON public.openskagit_neighborhoodtrend USING btree (hood_id varchar_pattern_ops);


--
-- Name: openskagit_neighborhoodtrend_value_year_3e21099c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_neighborhoodtrend_value_year_3e21099c ON public.openskagit_neighborhoodtrend USING btree (value_year);


--
-- Name: openskagit_parcelhistory_neighborhood_code_91a11ba2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_parcelhistory_neighborhood_code_91a11ba2 ON public.openskagit_parcelhistory USING btree (neighborhood_code);


--
-- Name: openskagit_parcelhistory_neighborhood_code_91a11ba2_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_parcelhistory_neighborhood_code_91a11ba2_like ON public.openskagit_parcelhistory USING btree (neighborhood_code varchar_pattern_ops);


--
-- Name: openskagit_parcelhistory_parcel_number_c4377126_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_parcelhistory_parcel_number_c4377126_like ON public.openskagit_parcelhistory USING btree (parcel_number varchar_pattern_ops);


--
-- Name: openskagit_parcelhistory_roll_year_d9004019; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_parcelhistory_roll_year_d9004019 ON public.openskagit_parcelhistory USING btree (roll_year);


--
-- Name: openskagit_taxcodearea_code_5a337982_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_taxcodearea_code_5a337982_like ON public.openskagit_taxcodearea USING btree (code varchar_pattern_ops);


--
-- Name: openskagit_taxcodearea_geom_96e8622c_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_taxcodearea_geom_96e8622c_id ON public.openskagit_taxcodearea USING gist (geom);


--
-- Name: openskagit_taxingdistrict_district_code_2b0395e3_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_taxingdistrict_district_code_2b0395e3_like ON public.openskagit_taxingdistrict USING btree (district_code varchar_pattern_ops);


--
-- Name: openskagit_taxingdistrict_geom_ecd781bd_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX openskagit_taxingdistrict_geom_ecd781bd_id ON public.openskagit_taxingdistrict USING gist (geom);


--
-- Name: parcel_land_use_code_35c86882; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_land_use_code_35c86882 ON public.parcel USING btree (land_use_code);


--
-- Name: parcel_land_use_code_35c86882_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_land_use_code_35c86882_like ON public.parcel USING btree (land_use_code varchar_pattern_ops);


--
-- Name: parcel_neighborhood_code_fa50805d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_neighborhood_code_fa50805d ON public.parcel USING btree (neighborhood_code);


--
-- Name: parcel_neighborhood_code_fa50805d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_neighborhood_code_fa50805d_like ON public.parcel USING btree (neighborhood_code varchar_pattern_ops);


--
-- Name: parcel_parcel_number_23494c57_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_parcel_number_23494c57_like ON public.parcel USING btree (parcel_number varchar_pattern_ops);


--
-- Name: parcel_points_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_points_geom_idx ON public.parcel_points USING gist (geom);


--
-- Name: parcel_property_type_a160f34f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_property_type_a160f34f ON public.parcel USING btree (property_type);


--
-- Name: parcel_property_type_a160f34f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcel_property_type_a160f34f_like ON public.parcel USING btree (property_type varchar_pattern_ops);


--
-- Name: parcels_geom_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_geom_idx ON public.parcels USING gist (geom);


--
-- Name: planet_osm_rels_parts_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX planet_osm_rels_parts_idx ON public.planet_osm_rels USING gin (parts) WITH (fastupdate=off);


--
-- Name: planet_osm_ways_nodes_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX planet_osm_ways_nodes_idx ON public.planet_osm_ways USING gin (nodes) WITH (fastupdate=off);


--
-- Name: regression_results_roll_id_3939bed7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX regression_results_roll_id_3939bed7 ON public.regression_results USING btree (roll_id);


--
-- Name: sales_parcel_number_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sales_parcel_number_idx ON public.sales USING btree (parcel_number);


--
-- Name: sales_sale_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sales_sale_date_idx ON public.sales USING btree (sale_date);


--
-- Name: planet_osm_line planet_osm_line_osm2pgsql_valid; Type: TRIGGER; Schema: osm; Owner: -
--

CREATE TRIGGER planet_osm_line_osm2pgsql_valid BEFORE INSERT OR UPDATE ON osm.planet_osm_line FOR EACH ROW EXECUTE FUNCTION public.planet_osm_line_osm2pgsql_valid();


--
-- Name: planet_osm_point planet_osm_point_osm2pgsql_valid; Type: TRIGGER; Schema: osm; Owner: -
--

CREATE TRIGGER planet_osm_point_osm2pgsql_valid BEFORE INSERT OR UPDATE ON osm.planet_osm_point FOR EACH ROW EXECUTE FUNCTION public.planet_osm_point_osm2pgsql_valid();


--
-- Name: planet_osm_polygon planet_osm_polygon_osm2pgsql_valid; Type: TRIGGER; Schema: osm; Owner: -
--

CREATE TRIGGER planet_osm_polygon_osm2pgsql_valid BEFORE INSERT OR UPDATE ON osm.planet_osm_polygon FOR EACH ROW EXECUTE FUNCTION public.planet_osm_polygon_osm2pgsql_valid();


--
-- Name: planet_osm_roads planet_osm_roads_osm2pgsql_valid; Type: TRIGGER; Schema: osm; Owner: -
--

CREATE TRIGGER planet_osm_roads_osm2pgsql_valid BEFORE INSERT OR UPDATE ON osm.planet_osm_roads FOR EACH ROW EXECUTE FUNCTION public.planet_osm_roads_osm2pgsql_valid();


--
-- Name: assessor assessor_centroid_geog_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER assessor_centroid_geog_update BEFORE INSERT OR UPDATE ON public.assessor FOR EACH ROW EXECUTE FUNCTION public.update_centroid_geog();


--
-- Name: assessor assessor_roll_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.assessor
    ADD CONSTRAINT assessor_roll_id_fkey FOREIGN KEY (roll_id) REFERENCES public.openskagit_assessmentroll(id);


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_group_id_97559544_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_group_id_97559544_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_groups auth_user_groups_user_id_6a12ed8b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_groups
    ADD CONSTRAINT auth_user_groups_user_id_6a12ed8b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permi_permission_id_1fbb5f2c_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_user_user_permissions auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_user_user_permissions
    ADD CONSTRAINT auth_user_user_permissions_user_id_a95ead1b_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: conversation_messages conversation_message_conversation_id_52b02ddd_fk_conversat; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.conversation_messages
    ADD CONSTRAINT conversation_message_conversation_id_52b02ddd_fk_conversat FOREIGN KEY (conversation_id) REFERENCES public.conversations(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: improvements improvements_roll_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.improvements
    ADD CONSTRAINT improvements_roll_id_fkey FOREIGN KEY (roll_id) REFERENCES public.openskagit_assessmentroll(id);


--
-- Name: land land_roll_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.land
    ADD CONSTRAINT land_roll_id_fkey FOREIGN KEY (roll_id) REFERENCES public.openskagit_assessmentroll(id);


--
-- Name: openskagit_adjustmentmodelsegment openskagit_adjustmen_run_id_f1959065_fk_openskagi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_adjustmentmodelsegment
    ADD CONSTRAINT openskagit_adjustmen_run_id_f1959065_fk_openskagi FOREIGN KEY (run_id) REFERENCES public.openskagit_adjustmentrunsummary(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: openskagit_cmaanalysis openskagit_cmaanalysis_user_id_529d6313_fk_auth_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmaanalysis
    ADD CONSTRAINT openskagit_cmaanalysis_user_id_529d6313_fk_auth_user_id FOREIGN KEY (user_id) REFERENCES public.auth_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: openskagit_cmacomparableselection openskagit_cmacompar_analysis_id_a2451625_fk_openskagi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.openskagit_cmacomparableselection
    ADD CONSTRAINT openskagit_cmacompar_analysis_id_a2451625_fk_openskagi FOREIGN KEY (analysis_id) REFERENCES public.openskagit_cmaanalysis(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: regression_results regression_results_roll_id_3939bed7_fk_openskagi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regression_results
    ADD CONSTRAINT regression_results_roll_id_3939bed7_fk_openskagi FOREIGN KEY (roll_id) REFERENCES public.openskagit_assessmentroll(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: sales sales_roll_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sales
    ADD CONSTRAINT sales_roll_id_fkey FOREIGN KEY (roll_id) REFERENCES public.openskagit_assessmentroll(id);


--
-- PostgreSQL database dump complete
--

\unrestrict ay5KnE4yFmnHhZkiGh3rRQKszyeTh52bHdRj37z2h3kd7lNfdZc5d8kl8XEv4Nh

