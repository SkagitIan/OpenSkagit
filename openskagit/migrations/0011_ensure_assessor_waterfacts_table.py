from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0010_remove_planningfacts_duplicate_water_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = 'openskagit_parcelwaterfacts'
                ) THEN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public'
                          AND table_name = 'assessor_waterfacts'
                    ) THEN
                        ALTER TABLE public.assessor_waterfacts
                            RENAME TO openskagit_parcelwaterfacts;
                    ELSE
                        CREATE TABLE public.openskagit_parcelwaterfacts (
                            parcel_id varchar(20) PRIMARY KEY
                                REFERENCES public.master_parcel(parcel_number)
                                ON DELETE CASCADE,
                            public_water_available boolean,
                            public_water_system_id text,
                            in_instream_flow_rule_area boolean,
                            instream_flow_rule_name text,
                            low_flow_stream_area boolean,
                            in_wellhead_protection_area boolean,
                            surface_water_limited boolean,
                            water_feasibility_rating text,
                            nearest_well_distance_m double precision,
                            nearest_well_id text,
                            nearest_well_depth double precision,
                            nearest_well_yield double precision,
                            has_pou_water_right boolean,
                            pou_right_numbers text[],
                            nearest_diversion_right text,
                            nearest_diversion_distance_m double precision,
                            nearest_right_priority_date date,
                            aquifer_yield_category text,
                            well_drilling_feasible boolean,
                            created_at timestamptz,
                            updated_at timestamptz
                        );
                    END IF;
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'openskagit_parcelwaterfacts'
                      AND indexname = 'openskagit_parcelwaterfacts_public_water_available_idx'
                ) THEN
                    CREATE INDEX openskagit_parcelwaterfacts_public_water_available_idx
                        ON public.openskagit_parcelwaterfacts (public_water_available);
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'openskagit_parcelwaterfacts'
                      AND indexname = 'openskagit_parcelwaterfacts_has_pou_water_right_idx'
                ) THEN
                    CREATE INDEX openskagit_parcelwaterfacts_has_pou_water_right_idx
                        ON public.openskagit_parcelwaterfacts (has_pou_water_right);
                END IF;
            END $$;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
