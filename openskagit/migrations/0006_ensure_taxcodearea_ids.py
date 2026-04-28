from django.db import migrations


def ensure_bigserial_pk(table_name: str) -> str:
    return f"""
    DO $$
    DECLARE
        target_table regclass;
        existing_pk text;
    BEGIN
        target_table := to_regclass('public.{table_name}');
        IF target_table IS NULL THEN
            -- Legacy installs may never have created these physical tables.
            -- Keep migration idempotent for fresh test databases.
            RETURN;
        END IF;

        SELECT conname
        INTO existing_pk
        FROM pg_constraint
        WHERE conrelid = target_table
          AND contype = 'p';

        IF existing_pk IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE public.%I DROP CONSTRAINT %I',
                '{table_name}',
                existing_pk
            );
        END IF;

        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = '{table_name}'
              AND column_name = 'id'
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD COLUMN id BIGSERIAL',
                '{table_name}'
            );
        END IF;

        EXECUTE format(
            'ALTER TABLE public.%I ADD PRIMARY KEY (id)',
            '{table_name}'
        );
    END $$;
    """


class Migration(migrations.Migration):

    dependencies = [
        ("openskagit", "0005_taxcodearea"),
    ]

    operations = [
        migrations.RunSQL(ensure_bigserial_pk("openskagit_taxcodearea")),
        migrations.RunSQL(ensure_bigserial_pk("openskagit_taxcodeareadistrict")),
    ]
