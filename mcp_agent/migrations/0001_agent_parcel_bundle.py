from django.db import migrations


CREATE_SCHEMA_AND_FUNCTION = r"""
CREATE SCHEMA IF NOT EXISTS agent;

CREATE OR REPLACE FUNCTION agent.parcel_bundle_v1(p_parcel_id text)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    v_parcel jsonb;
    v_geom jsonb;
    v_planning jsonb;
    v_assessments jsonb;
    v_sales jsonb;
    v_zoning jsonb;
    v_overlays jsonb;
BEGIN
    SELECT to_jsonb(mp) INTO v_parcel
    FROM public.master_parcel mp
    WHERE mp.parcel_number = p_parcel_id;

    IF v_parcel IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT
        COALESCE(
            ST_AsGeoJSON(ST_Transform(pg.geom_2926_valid, 4326))::jsonb,
            ST_AsGeoJSON(ST_Transform(pg.geom_2926, 4326))::jsonb,
            ST_AsGeoJSON(ST_Transform(stg.geom_2926, 4326))::jsonb
        )
    INTO v_geom
    FROM public.openskagit_parcelgeometry pg
    LEFT JOIN public.stg_parcel_geometry stg ON stg.parcel_id = pg.parcel_id
    WHERE pg.parcel_id = p_parcel_id
    LIMIT 1;

    SELECT to_jsonb(ppf) INTO v_planning
    FROM public.parcel_planning_facts ppf
    WHERE ppf.parcel_id = p_parcel_id;

    SELECT jsonb_build_object(
        'valuations',
        jsonb_build_object(
            'assessed_value', mp.assessed_value,
            'taxable_value', mp.taxable_value,
            'total_market_value', mp.total_market_value,
            'acres', mp.acres,
            'sale_price', mp.sale_price,
            'price_per_sqft', mp.price_per_sqft
        ),
        'latest_tax',
        (
            SELECT jsonb_build_object('tax_year', tax_year, 'tax_paid', tax_paid)
            FROM public.parcel_tax_history pth
            WHERE pth.parcel_number = p_parcel_id
            ORDER BY tax_year DESC
            LIMIT 1
        )
    )
    INTO v_assessments
    FROM public.master_parcel mp
    WHERE mp.parcel_number = p_parcel_id;

    SELECT jsonb_agg(
        jsonb_build_object(
            'sale_id', s.sale_id,
            'sale_date', s.sale_date,
            'sale_price', s.sale_price,
            'sale_type', s.sale_type,
            'deed_type', s.deed_type,
            'recording_number', s.recording_number
        )
        ORDER BY s.sale_date DESC
    )
    INTO v_sales
    FROM (
        SELECT *
        FROM public.sales s
        WHERE s.parcel_number = p_parcel_id
        ORDER BY s.sale_date DESC
        LIMIT 10
    ) s;

    SELECT jsonb_agg(
        jsonb_build_object(
            'zone_code', zz.zone_code,
            'jurisdiction', zz.jurisdiction,
            'zoning_general_class', zz.zoning_general_class,
            'zoning_specific_class', zz.zoning_specific_class,
            'is_primary', pz.is_primary,
            'pct_of_parcel', pz.pct_of_parcel,
            'source', zz.source,
            'reference_url', zz.reference_url
        )
        ORDER BY pz.is_primary DESC
    )
    INTO v_zoning
    FROM public.parcel_zoning pz
    JOIN public.zoning_zone zz ON zz.id = pz.zone_id
    WHERE pz.parcel_id = p_parcel_id;

    WITH ppf AS (
        SELECT *
        FROM public.parcel_planning_facts
        WHERE parcel_id = p_parcel_id
        LIMIT 1
    )
    SELECT jsonb_agg(tag) INTO v_overlays
    FROM (
        SELECT jsonb_build_object('tag', 'flood_zone', 'value', ppf.flood_zone) FROM ppf WHERE ppf.flood_zone IS NOT NULL
        UNION ALL
        SELECT jsonb_build_object('tag', 'flood_zone_subtype', 'value', ppf.flood_zone_subtype) FROM ppf WHERE ppf.flood_zone_subtype IS NOT NULL
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_sfha', 'value', true) FROM ppf WHERE ppf.in_sfha IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_floodway', 'value', true) FROM ppf WHERE ppf.in_floodway IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_shoreline_jurisdiction', 'value', true) FROM ppf WHERE ppf.in_shoreline_jurisdiction IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_wetland', 'value', true) FROM ppf WHERE ppf.in_wetland IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_wetland_buffer', 'value', true) FROM ppf WHERE ppf.in_wetland_buffer IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_wellhead_protection_zone', 'value', true) FROM ppf WHERE ppf.in_wellhead_protection_zone IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_npdes_area', 'value', true) FROM ppf WHERE ppf.in_npdes_area IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_historic_register', 'value', true) FROM ppf WHERE ppf.in_historic_register IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_historic_district', 'value', true) FROM ppf WHERE ppf.in_historic_district IS TRUE
        UNION ALL
        SELECT jsonb_build_object('tag', 'in_airport_environs', 'value', true) FROM ppf WHERE ppf.in_airport_environs IS TRUE
    ) tag;

    RETURN jsonb_build_object(
        'parcel', v_parcel,
        'geometry', v_geom,
        'planning_facts', v_planning,
        'assessments', v_assessments,
        'sales', COALESCE(v_sales, '[]'::jsonb),
        'zoning_tags', COALESCE(v_zoning, '[]'::jsonb),
        'overlay_tags', COALESCE(v_overlays, '[]'::jsonb),
        'sources', jsonb_build_object(
            'parcel_table', 'public.master_parcel',
            'geom_table', 'public.openskagit_parcelgeometry',
            'planning_table', 'public.parcel_planning_facts',
            'sales_table', 'public.sales',
            'zoning_table', 'public.parcel_zoning'
        )
    );
END;
$$;
"""

DROP_FUNCTION = """
DROP FUNCTION IF EXISTS agent.parcel_bundle_v1(text);
"""


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("agent", "0003_agent_parcel_bundle_function"),
    ]

    operations = [
        migrations.RunSQL(sql=CREATE_SCHEMA_AND_FUNCTION, reverse_sql=DROP_FUNCTION),
    ]
