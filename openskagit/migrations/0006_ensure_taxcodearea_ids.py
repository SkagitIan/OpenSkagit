from django.db import migrations


def ensure_bigserial_pk(table_name: str) -> str:
    return f"""
    DO $$
    DECLARE
        existing_pk text;
    BEGIN
        SELECT conname
        INTO existing_pk
        FROM pg_constraint
        WHERE conrelid = 'public.{table_name}'::regclass
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
