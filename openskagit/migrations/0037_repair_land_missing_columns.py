from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("openskagit", "0036_property_record_alert_subscription_and_parcelhistory_recording_fields"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE land
                    ADD COLUMN IF NOT EXISTS effective_front double precision,
                    ADD COLUMN IF NOT EXISTS actual_front double precision,
                    ADD COLUMN IF NOT EXISTS open_space_use_code_desc double precision,
                    ADD COLUMN IF NOT EXISTS open_space_appraisal_method text,
                    ADD COLUMN IF NOT EXISTS land_segment_comment text;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
