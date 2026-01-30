from textwrap import dedent

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


VALID_BALLOT_STATUSES = ("ACCEPTED", "COUNTED", "RECEIVED")
PRIVACY_MIN_RESIDENTIAL = 25

QUARTILE_LABELS = {
    4: "Highest participation density",
    3: "Above-average",
    2: "Below-average",
    1: "Lowest participation density",
}

HOOD_CODE_PREFIXES = [
    "20B", "21B", "22B", "23B", "26B", "27B",
    "20LC", "21LC", "22LC", "23LC", "20CON", "22CON",
    "20A", "21A", "22A", "23A", "20FID", "22FID", "20GUEM", "22GUEM",
    "20SW", "21SW", "22SW", "23SW",
    "20CC", "22CC", "10CC",
    "20MV", "21MV", "22MV", "23MV",
]


def hood_code_where_clause(column: str) -> str:
    clauses = " OR ".join(f"{column} LIKE '{prefix}%'" for prefix in HOOD_CODE_PREFIXES)
    return f"({clauses})"


def normalized_address_sql(column_expr: str) -> str:
    """
    Reproduce the Python normalize_address logic used when loading voter turnout data.
    """
    return dedent(
        f"""
        btrim(
            regexp_replace(
                regexp_replace(
                    regexp_replace(
                        upper(btrim(coalesce(({column_expr})::text, ''))),
                        '\\s+',
                        ' ',
                        'g'
                    ),
                    '[^A-Z0-9#/ ]',
                    ' ',
                    'g'
                ),
                '\\s+',
                ' ',
                'g'
            )
        )
        """
    ).strip()


def street_only_sql(column_expr: str) -> str:
    """
    Extract just the street portion (up to the street-type suffix) from a raw address string.
    """
    suffixes = (
        "AVE(?:NUE)?|BLVD(?:EVARD)?|CIR(?:CLE)?|COURT|CT|DR(?:IVE)?|HWY|HIGHWAY|LANE|LN|LOOP|PL|PLACE|PLZ|PLAZA|PKWY|PARKWAY|RD|ROAD|SQ|SQUARE|ST|STREET|TER|TERRACE|TRL|TRAIL|WAY"
    )
    return dedent(
        f"""
        regexp_replace(
            coalesce(({column_expr})::text, ''),
            '^\\s*(\\d+\\s+[A-Z0-9#/ ]+?(?:\\s+(?:{suffixes})))(?:\\s+.*)?$',
            '\\1',
            'i'
        )
        """
    ).strip()


def abbreviate_suffixes_sql(column_expr: str) -> str:
    """
    Replace long-form street suffixes with the abbreviated variants used in normalized ballots.
    """
    replacements = [
        ("AVENUE", "AVE"),
        ("AV", "AVE"),
        ("BOULEVARD", "BLVD"),
        ("COURT", "CT"),
        ("DRIVE", "DR"),
        ("HIGHWAY", "HWY"),
        ("LANE", "LN"),
        ("PLACE", "PL"),
        ("PARKWAY", "PKWY"),
        ("ROAD", "RD"),
        ("SQUARE", "SQ"),
        ("STREET", "ST"),
        ("TERRACE", "TER"),
        ("TRAIL", "TRL"),
    ]

    expr = column_expr
    for long, short in replacements:
        expr = (
            "regexp_replace("
            f"{expr}, "
            f"'\\\\y{long}\\\\y', "
            f"'{short}', "
            "'gi'"
            ")"
        )
    return expr


class Command(BaseCommand):
    help = "Create/refresh the materialized views that power /votevector queries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-ballots",
            action="store_true",
            help="Skip rebuilding the voter_ballots_skagit materialized view.",
        )
        parser.add_argument(
            "--skip-parcels",
            action="store_true",
            help="Skip rebuilding the parcel_address_norm materialized view.",
        )
        parser.add_argument(
            "--skip-mapping",
            action="store_true",
            help="Skip rebuilding the ballot_to_parcel materialized view.",
        )
        parser.add_argument(
            "--skip-neighborhoods",
            action="store_true",
            help="Skip rebuilding the neighborhood_ballots_by_year materialized view.",
        )
        parser.add_argument(
            "--skip-residential",
            action="store_true",
            help="Skip rebuilding the neighborhood_residential_parcels materialized view.",
        )
        parser.add_argument(
            "--skip-geometry",
            action="store_true",
            help="Skip rebuilding the neighborhood_participation_geometry materialized view.",
        )
        parser.add_argument(
            "--skip-owner-addresses",
            action="store_true",
            help="Skip rebuilding the parcel_owner_address_norm materialized view.",
        )
        parser.add_argument(
            "--skip-owner-residency",
            action="store_true",
            help="Skip rebuilding the owner_residency_by_neighborhood materialized view.",
        )
        parser.add_argument(
            "--skip-fact",
            action="store_true",
            help="Skip rebuilding the fact_neighborhood_participation materialized view.",
        )
        parser.add_argument(
            "--skip-quartiles",
            action="store_true",
            help="Skip rebuilding the neighborhood_participation_classification materialized view.",
        )
        parser.add_argument(
            "--skip-precinct-rollups",
            action="store_true",
            help="Skip rebuilding precinct-level rollup materialized views.",
        )
        parser.add_argument(
            "--skip-diagnostics",
            action="store_true",
            help="Skip printing ballot-to-parcel diagnostics after rebuild.",
        )

    def handle(self, *args, **options):
        skip_ballots = options["skip_ballots"]
        skip_parcels = options["skip_parcels"]
        skip_mapping = options["skip_mapping"]
        skip_neighborhoods = options["skip_neighborhoods"]
        skip_residential = options["skip_residential"]
        skip_geometry = options["skip_geometry"]
        skip_owner_addresses = options["skip_owner_addresses"]
        skip_owner_residency = options["skip_owner_residency"]
        skip_fact = options["skip_fact"]
        skip_quartiles = options["skip_quartiles"]
        skip_precinct_rollups = options["skip_precinct_rollups"]
        skip_diagnostics = options["skip_diagnostics"]

        if (
            skip_ballots
            and skip_parcels
            and skip_mapping
            and skip_neighborhoods
            and skip_residential
            and skip_geometry
            and skip_owner_addresses
            and skip_owner_residency
            and skip_fact
            and skip_quartiles
            and skip_precinct_rollups
        ):
            raise CommandError(
                "Nothing to do – all rebuild steps were skipped."
            )

        owner_view_ready = False
        with transaction.atomic():
            with connection.cursor() as cursor:
                if not skip_ballots:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding voter_ballots_skagit"))
                    self.rebuild_ballot_view(cursor)

                if not skip_parcels:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding parcel_address_norm"))
                    self.rebuild_parcel_view(cursor)

                if not skip_owner_addresses:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding parcel_owner_address_norm"))
                    self.rebuild_owner_address_view(cursor)
                    owner_view_ready = True

                if not skip_owner_residency:
                    if not owner_view_ready:
                        owner_view_ready = self._relation_has_column(
                            cursor,
                            "public",
                            "parcel_owner_address_norm",
                            "source",
                        )
                    if not owner_view_ready:
                        warning = (
                            "parcel_owner_address_norm is missing the `source` column required for owner residency rollups"
                        )
                        if skip_owner_addresses:
                            warning += "; rebuilding despite --skip-owner-addresses"
                        self.stdout.write(self.style.WARNING(warning))
                        self.rebuild_owner_address_view(cursor)
                        owner_view_ready = True

                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding owner_residency_by_neighborhood"))
                    self.rebuild_owner_residency_view(cursor)

                if not skip_mapping:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding ballot_to_parcel"))
                    self.rebuild_ballot_mapping_view(cursor)
                    if not skip_diagnostics:
                        self.stdout.write(self.style.MIGRATE_HEADING("Ballot-to-parcel diagnostics"))
                        self.print_mapping_diagnostics(cursor)

                if not skip_neighborhoods:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding neighborhood_ballots_by_year"))
                    self.rebuild_neighborhood_view(cursor)

                if not skip_residential:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding neighborhood_residential_parcels"))
                    self.rebuild_neighborhood_residential_view(cursor)

                if not skip_precinct_rollups:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding precinct_ballots_by_year"))
                    self.rebuild_precinct_ballots_view(cursor)
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding precinct_residential_parcels"))
                    self.rebuild_precinct_residential_view(cursor)
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding precinct_participation_index"))
                    self.rebuild_precinct_participation_view(cursor)
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding neighborhood_primary_precinct"))
                    self.rebuild_neighborhood_primary_precinct_view(cursor)

                if not skip_geometry:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding neighborhood_participation_geometry"))
                    self.rebuild_neighborhood_geometry_view(cursor)

                if not skip_fact:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding fact_neighborhood_participation"))
                    self.rebuild_fact_view(cursor)

                if not skip_quartiles:
                    self.stdout.write(self.style.MIGRATE_HEADING("Rebuilding neighborhood_participation_classification"))
                    self.rebuild_quartile_view(cursor)

        self.stdout.write(self.style.SUCCESS("VoteVector support views refreshed"))

    def _relation_has_column(self, cursor, schema_name: str, relation_name: str, column_name: str) -> bool:
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
              AND column_name = %s
            LIMIT 1
            """,
            [schema_name, relation_name, column_name],
        )
        return cursor.fetchone() is not None

    # ------------------------------------------------------------------
    # VIEW BUILDERS
    # ------------------------------------------------------------------
    def rebuild_ballot_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.voter_ballots_skagit CASCADE;")

        status_list = ", ".join(f"'{status}'" for status in VALID_BALLOT_STATUSES)
        ballot_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.voter_ballots_skagit AS
            SELECT
                vtr.ballot_id,
                vtr.election_id,
                COALESCE(
                    DATE_PART('year', ve.election_date)::int,
                    CASE
                        WHEN vtr.received_date IS NOT NULL THEN DATE_PART('year', vtr.received_date)::int
                    END,
                    NULLIF(substring(ve.name FROM '((?:19|20)[0-9]{{2}})'), '')::int
                ) AS election_year,
                vtr.normalized_address
            FROM public.openskagit_voterturnoutraw vtr
            JOIN public.openskagit_voterelection ve ON ve.id = vtr.election_id
            WHERE
                vtr.ballot_id IS NOT NULL
                AND vtr.ballot_id <> ''
                AND vtr.normalized_address IS NOT NULL
                AND vtr.normalized_address <> ''
                AND upper(coalesce(vtr.county, '')) = 'SKAGIT'
                AND (
                    upper(coalesce(vtr.ballot_status, '')) IN ({status_list})
                    OR vtr.received_date IS NOT NULL
                );
            """
        ).strip()
        cursor.execute(ballot_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX voter_ballots_skagit_ballot_idx "
            "ON public.voter_ballots_skagit (ballot_id, election_id);"
        )
        cursor.execute(
            "CREATE INDEX voter_ballots_skagit_addr_year_idx "
            "ON public.voter_ballots_skagit (normalized_address, election_year);"
        )
        cursor.execute(
            "CREATE INDEX voter_ballots_skagit_year_idx "
            "ON public.voter_ballots_skagit (election_year);"
        )

    def rebuild_parcel_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.parcel_address_norm CASCADE;")

        situs_street = "NULLIF(btrim(split_part(mp.situs_address, ',', 1)), '')"
        parcel_street = "NULLIF(btrim(split_part(p.address, ',', 1)), '')"
        street_line = street_only_sql(f"COALESCE({situs_street}, {parcel_street})")
        street_line = abbreviate_suffixes_sql(street_line)
        normalized_expr = normalized_address_sql(street_line)
        neighborhood_expr = "COALESCE(p.neighborhood_code, mp.hood_code)"
        property_expr = "upper(coalesce(p.property_type, mp.proptype, ''))"
        is_res_expr = (
            f"CASE WHEN {property_expr} IN ('R', 'M', 'MH', 'SFR', 'RES', 'RESIDENTIAL') "
            "THEN TRUE ELSE FALSE END"
        )
        city_expr = "NULLIF(btrim(split_part(p.address, ',', 2)), '')"
        zip_expr = "NULLIF(substring(p.address FROM '([0-9]{5})(?:-[0-9]{4})?$'), '')"

        parcel_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.parcel_address_norm AS
            SELECT
                mp.parcel_number,
                {normalized_expr} AS normalized_address,
                {neighborhood_expr} AS neighborhood_code,
                {is_res_expr} AS is_residential,
                ph.roll_year,
                {city_expr} AS situs_city,
                {zip_expr} AS zip5
            FROM public.master_parcel mp
            LEFT JOIN public.parcel p ON p.parcel_number = mp.parcel_number
            LEFT JOIN public.openskagit_parcelhistory ph ON ph.parcel_number = mp.parcel_number
            WHERE
                {normalized_expr} IS NOT NULL
                AND {normalized_expr} <> '';
            """
        ).strip()
        cursor.execute(parcel_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX parcel_address_norm_parcel_number_key "
            "ON public.parcel_address_norm (parcel_number);"
        )
        cursor.execute(
            "CREATE INDEX parcel_address_norm_address_idx "
            "ON public.parcel_address_norm (normalized_address);"
        )
        cursor.execute(
            "CREATE INDEX parcel_address_norm_neighborhood_idx "
            "ON public.parcel_address_norm (neighborhood_code);"
        )
        cursor.execute(
            "CREATE INDEX parcel_address_norm_is_residential_idx "
            "ON public.parcel_address_norm (is_residential);"
        )
        cursor.execute(
            "CREATE INDEX parcel_address_norm_roll_year_idx "
            "ON public.parcel_address_norm (roll_year);"
        )

    def rebuild_owner_address_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.parcel_owner_address_norm CASCADE;")

        situs_street = "NULLIF(btrim(split_part(aos.owner_add_1, ',', 1)), '')"
        street_line = street_only_sql(situs_street)
        street_line = abbreviate_suffixes_sql(street_line)
        normalized_expr = normalized_address_sql(street_line)
        code_expr = """
            COALESCE(
                NULLIF(regexp_replace(COALESCE(aos.neighborhood_code, ''), '^\\s*\\(([^)]+)\\).*$','\\1'), ''),
                NULLIF(btrim(aos.neighborhood_code), '')
            )
        """.strip()
        desc_expr = """
            NULLIF(
                btrim(
                    regexp_replace(COALESCE(aos.neighborhood_code, ''), '^\\s*\\([^)]+\\)\\s*', '')
                ),
                ''
            )
        """.strip()

        owner_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.parcel_owner_address_norm AS
            WITH staged AS (
                SELECT
                    TRIM(aos.parcel_number) AS parcel_number,
                    {normalized_expr} AS owner_normalized_address,
                    {code_expr} AS owner_neighborhood_code,
                    {desc_expr} AS owner_neighborhood_description,
                    NULLIF(btrim(aos.owner_state), '') AS owner_state,
                    NULLIF(btrim(aos.owner_zip), '') AS owner_zip,
                    CASE
                        WHEN UPPER(COALESCE(aos.owner_add_1, '')) ~ '^(PO BOX|P ?O BOX|ATTN|PERSONAL PROPERTY)'
                            OR UPPER(COALESCE(aos.owner_name, '')) LIKE '%PERSONAL PROPERTY%'
                            OR UPPER(COALESCE(aos.proptype, '')) = 'P'
                            THEN TRUE
                        ELSE FALSE
                    END AS is_suspect
                FROM public.assessor_owner_stage aos
            ),
            ranked AS (
                SELECT
                    parcel_number,
                    owner_normalized_address,
                    owner_neighborhood_code,
                    owner_neighborhood_description,
                    owner_state,
                    owner_zip,
                    ROW_NUMBER() OVER (
                        PARTITION BY parcel_number
                        ORDER BY
                            (owner_normalized_address IS NULL),
                            is_suspect,
                            owner_normalized_address NULLS LAST,
                            owner_state,
                            owner_zip
                    ) AS rn
                FROM staged
            ),
            owner_dedup AS (
                SELECT
                    parcel_number,
                    owner_normalized_address,
                    owner_neighborhood_code,
                    owner_neighborhood_description,
                    owner_state,
                    owner_zip
                FROM ranked
                WHERE rn = 1
            )
            SELECT
                pan.parcel_number,
                COALESCE(owner.owner_normalized_address, pan.normalized_address) AS normalized_address,
                COALESCE(owner.owner_neighborhood_code, pan.neighborhood_code) AS neighborhood_code,
                COALESCE(owner.owner_neighborhood_description, pan.neighborhood_code) AS neighborhood_description,
                owner.owner_state,
                owner.owner_zip,
                CASE
                    WHEN owner.owner_normalized_address IS NOT NULL THEN 'owner_mailing'
                    ELSE 'situs_fallback'
                END AS source
            FROM public.parcel_address_norm pan
            LEFT JOIN owner_dedup owner ON owner.parcel_number = pan.parcel_number
            WHERE COALESCE(owner.owner_normalized_address, pan.normalized_address) IS NOT NULL;
            """
        ).strip()
        cursor.execute(owner_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX parcel_owner_address_parcel_idx "
            "ON public.parcel_owner_address_norm (parcel_number);"
        )
        cursor.execute(
            "CREATE INDEX parcel_owner_address_norm_idx "
            "ON public.parcel_owner_address_norm (normalized_address);"
        )
        cursor.execute(
            "CREATE INDEX parcel_owner_address_neighborhood_idx "
            "ON public.parcel_owner_address_norm (neighborhood_code);"
        )
        cursor.execute("ANALYZE public.parcel_owner_address_norm;")

    def rebuild_owner_residency_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.owner_residency_by_neighborhood CASCADE;")

        hood_filter = hood_code_where_clause("pan.neighborhood_code")
        owner_hood_filter = hood_code_where_clause("owner_base.owner_neighborhood_code")
        owner_residency_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.owner_residency_by_neighborhood AS
            WITH owner_base AS (
                SELECT
                    pan.neighborhood_code AS neighborhood_code,
                    COALESCE(po.source, 'situs_fallback') AS source,
                    CASE WHEN po.source = 'owner_mailing' THEN po.neighborhood_code END AS owner_neighborhood_code,
                    CASE WHEN po.source = 'owner_mailing' THEN po.normalized_address END AS owner_mailing_address
                FROM public.parcel_address_norm pan
                LEFT JOIN public.parcel_owner_address_norm po
                  ON po.parcel_number = pan.parcel_number
                WHERE pan.is_residential IS TRUE
                  AND pan.neighborhood_code IS NOT NULL
                  AND {hood_filter}
            )
            SELECT
                neighborhood_code,
                COUNT(*) AS residential_parcels,
                COUNT(*) FILTER (WHERE source = 'owner_mailing') AS owner_mailing_count,
                COUNT(*) FILTER (
                    WHERE source = 'owner_mailing'
                      AND owner_neighborhood_code IS NOT NULL
                      AND owner_neighborhood_code = neighborhood_code
                ) AS owner_within_neighborhood_count,
                COUNT(*) FILTER (
                    WHERE source = 'owner_mailing'
                      AND owner_neighborhood_code IS NOT NULL
                      AND owner_neighborhood_code <> neighborhood_code
                ) AS owner_outside_neighborhood_count,
                COUNT(*) FILTER (
                    WHERE source = 'owner_mailing'
                      AND (owner_neighborhood_code IS NULL OR NOT {owner_hood_filter})
                ) AS owner_outside_skagit_count,
                COUNT(*) FILTER (
                    WHERE source = 'owner_mailing'
                      AND owner_mailing_address ~ '(PO BOX|P ?O BOX|P ?M ?B|POSTAL BOX)'
                ) AS owner_po_box_count,
                CASE
                    WHEN COUNT(*) FILTER (WHERE source = 'owner_mailing') = 0 THEN NULL
                    ELSE COUNT(*) FILTER (
                        WHERE source = 'owner_mailing'
                          AND owner_mailing_address ~ '(PO BOX|P ?O BOX|P ?M ?B|POSTAL BOX)'
                    )::float / NULLIF(COUNT(*) FILTER (WHERE source = 'owner_mailing'), 0)
                END AS owner_po_box_pct
            FROM owner_base
            GROUP BY neighborhood_code;
            """
        ).strip()
        cursor.execute(owner_residency_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX owner_residency_neighborhood_idx "
            "ON public.owner_residency_by_neighborhood (neighborhood_code);"
        )

    def rebuild_ballot_mapping_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.ballot_to_parcel CASCADE;")

        mapping_sql = dedent(
            """
            CREATE MATERIALIZED VIEW public.ballot_to_parcel AS
            WITH ranked AS (
                SELECT
                    vb.ballot_id,
                    vb.election_year,
                    pan.parcel_number,
                    pan.neighborhood_code,
                    'situs' AS match_source,
                    ROW_NUMBER() OVER (
                        PARTITION BY vb.ballot_id, vb.election_year
                        ORDER BY pan.parcel_number ASC
                    ) AS match_rank,
                    COUNT(*) OVER (
                        PARTITION BY vb.ballot_id, vb.election_year
                    ) AS match_count
                FROM public.voter_ballots_skagit vb
                JOIN public.parcel_address_norm pan
                  ON vb.normalized_address = pan.normalized_address
            )
            SELECT
                ballot_id,
                election_year,
                parcel_number,
                neighborhood_code,
                (match_count > 1) AS is_ambiguous,
                match_source
            FROM ranked
            WHERE match_rank = 1;
            """
        ).strip()
        cursor.execute(mapping_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX ballot_to_parcel_ballot_idx "
            "ON public.ballot_to_parcel (ballot_id, election_year);"
        )
        cursor.execute(
            "CREATE INDEX ballot_to_parcel_election_neighborhood_idx "
            "ON public.ballot_to_parcel (election_year, neighborhood_code);"
        )
        cursor.execute(
            "CREATE INDEX ballot_to_parcel_parcel_idx "
            "ON public.ballot_to_parcel (parcel_number);"
        )
        cursor.execute(
            "CREATE INDEX ballot_to_parcel_ballot_only_idx "
            "ON public.ballot_to_parcel (ballot_id);"
        )

    def rebuild_neighborhood_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.neighborhood_ballots_by_year CASCADE;")

        hood_filter_bp = hood_code_where_clause("bp.neighborhood_code")
        neighborhood_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.neighborhood_ballots_by_year AS
            SELECT
                bp.neighborhood_code,
                bp.election_year,
                COUNT(DISTINCT bp.ballot_id) AS ballots_cast
            FROM public.ballot_to_parcel bp
            WHERE bp.neighborhood_code IS NOT NULL
              AND bp.is_ambiguous IS FALSE
              AND {hood_filter_bp}
            GROUP BY bp.neighborhood_code, bp.election_year;
            """
        ).strip()
        cursor.execute(neighborhood_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX neighborhood_ballots_year_idx "
            "ON public.neighborhood_ballots_by_year (neighborhood_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_ballots_year_only_idx "
            "ON public.neighborhood_ballots_by_year (election_year);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_ballots_code_only_idx "
            "ON public.neighborhood_ballots_by_year (neighborhood_code);"
        )

    def rebuild_neighborhood_residential_view(self, cursor):
        """
        Build a materialized view that captures the number of residential parcels per neighborhood
        and repeats that stable count for every election year (simpler option outlined in the spec).
        """
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.neighborhood_residential_parcels CASCADE;")

        hood_filter_res = hood_code_where_clause("neighborhood_code")
        residential_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.neighborhood_residential_parcels AS
            WITH residential_counts AS (
                SELECT
                    neighborhood_code,
                    COUNT(DISTINCT parcel_number) AS residential_parcels
                FROM public.parcel_address_norm
                WHERE is_residential IS TRUE
                  AND neighborhood_code IS NOT NULL
                  AND {hood_filter_res}
                GROUP BY neighborhood_code
            ),
            election_years AS (
                SELECT DISTINCT election_year
                FROM public.voter_ballots_skagit
                WHERE election_year IS NOT NULL
            )
            SELECT
                rc.neighborhood_code,
                ey.election_year,
                rc.residential_parcels
            FROM residential_counts rc
            CROSS JOIN election_years ey;
            """
        ).strip()
        cursor.execute(residential_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX neighborhood_residential_idx "
            "ON public.neighborhood_residential_parcels (neighborhood_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_residential_year_idx "
            "ON public.neighborhood_residential_parcels (election_year);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_residential_code_idx "
            "ON public.neighborhood_residential_parcels (neighborhood_code);"
        )

    def rebuild_precinct_ballots_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.precinct_ballots_by_year CASCADE;")

        precinct_sql = dedent(
            """
            CREATE MATERIALIZED VIEW public.precinct_ballots_by_year AS
            SELECT
                rpl.prec_code,
                vb.election_year,
                COUNT(*) AS ballots_cast,
                COUNT(*) FILTER (WHERE vtr.is_po_box IS TRUE) AS po_box_ballots,
                CASE
                    WHEN COUNT(*) = 0 THEN NULL
                    ELSE COUNT(*) FILTER (WHERE vtr.is_po_box IS TRUE)::float / COUNT(*)::float
                END AS po_box_pct
            FROM public.openskagit_voterturnoutraw vtr
            JOIN public.voter_ballots_skagit vb
              ON vb.ballot_id = vtr.ballot_id
             AND vb.election_id = vtr.election_id
            JOIN public.reference_precinct_lookup rpl
              ON rpl.norm_prec_name = vtr.normalized_precinct
             AND rpl.norm_county = UPPER(COALESCE(vtr.county, ''))
            WHERE vtr.normalized_precinct IS NOT NULL
              AND vtr.normalized_precinct <> ''
              AND rpl.prec_code IS NOT NULL
            GROUP BY rpl.prec_code, vb.election_year;
            """
        ).strip()
        cursor.execute(precinct_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX precinct_ballots_prec_year_idx "
            "ON public.precinct_ballots_by_year (prec_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX precinct_ballots_year_idx "
            "ON public.precinct_ballots_by_year (election_year);"
        )

    def rebuild_precinct_residential_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.precinct_residential_parcels CASCADE;")

        residential_sql = dedent(
            """
            CREATE MATERIALIZED VIEW public.precinct_residential_parcels AS
            WITH residential_counts AS (
                SELECT
                    ptp.prec_code,
                    COUNT(DISTINCT pan.parcel_number) AS residential_parcels
                FROM public.parcel_address_norm pan
                JOIN public.parcel_to_precinct ptp
                  ON ptp.parcel_number = pan.parcel_number
                WHERE pan.is_residential IS TRUE
                GROUP BY ptp.prec_code
            ),
            election_years AS (
                SELECT DISTINCT election_year
                FROM public.voter_ballots_skagit
                WHERE election_year IS NOT NULL
            )
            SELECT
                rc.prec_code,
                ey.election_year,
                rc.residential_parcels
            FROM residential_counts rc
            CROSS JOIN election_years ey;
            """
        ).strip()
        cursor.execute(residential_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX precinct_residential_prec_year_idx "
            "ON public.precinct_residential_parcels (prec_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX precinct_residential_year_idx "
            "ON public.precinct_residential_parcels (election_year);"
        )

    def rebuild_precinct_participation_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.precinct_participation_index CASCADE;")

        participation_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.precinct_participation_index AS
            SELECT
                pb.prec_code,
                pb.election_year,
                pb.ballots_cast,
                pb.po_box_ballots,
                pb.po_box_pct,
                pr.residential_parcels,
                CASE
                    WHEN pr.residential_parcels >= {PRIVACY_MIN_RESIDENTIAL}
                        THEN pb.ballots_cast::float / NULLIF(pr.residential_parcels, 0)
                    ELSE NULL
                END AS ppi
            FROM public.precinct_ballots_by_year pb
            JOIN public.precinct_residential_parcels pr
              ON pr.prec_code = pb.prec_code
             AND pr.election_year = pb.election_year;
            """
        ).strip()
        cursor.execute(participation_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX precinct_participation_prec_year_idx "
            "ON public.precinct_participation_index (prec_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX precinct_participation_year_idx "
            "ON public.precinct_participation_index (election_year);"
        )

    def rebuild_neighborhood_primary_precinct_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.neighborhood_primary_precinct CASCADE;")

        hood_filter = hood_code_where_clause("pan.neighborhood_code")
        primary_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.neighborhood_primary_precinct AS
            WITH neighborhood_precincts AS (
                SELECT
                    pan.neighborhood_code,
                    ptp.prec_code,
                    COUNT(DISTINCT pan.parcel_number) AS residential_parcels
                FROM public.parcel_address_norm pan
                JOIN public.parcel_to_precinct ptp
                  ON ptp.parcel_number = pan.parcel_number
                WHERE pan.is_residential IS TRUE
                  AND pan.neighborhood_code IS NOT NULL
                  AND {hood_filter}
                GROUP BY pan.neighborhood_code, ptp.prec_code
            ),
            ranked AS (
                SELECT
                    neighborhood_code,
                    prec_code,
                    residential_parcels,
                    ROW_NUMBER() OVER (
                        PARTITION BY neighborhood_code
                        ORDER BY residential_parcels DESC, prec_code
                    ) AS rn
                FROM neighborhood_precincts
            )
            SELECT
                neighborhood_code,
                prec_code AS primary_precinct_code,
                residential_parcels AS precinct_residential_parcels
            FROM ranked
            WHERE rn = 1;
            """
        ).strip()
        cursor.execute(primary_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX neighborhood_primary_precinct_idx "
            "ON public.neighborhood_primary_precinct (neighborhood_code);"
        )

    def rebuild_neighborhood_geometry_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.neighborhood_participation_geometry CASCADE;")

        hood_filter_geom = hood_code_where_clause("mp.hood_code")
        geometry_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.neighborhood_participation_geometry AS
            WITH parcel_geoms AS (
                SELECT
                    mp.hood_code AS neighborhood_code,
                    ST_UnaryUnion(ST_Collect(pg.geom_2926)) AS geom_collection
                FROM public.master_parcel mp
                JOIN public.openskagit_parcelgeometry pg
                  ON pg.parcel_id = mp.parcel_number
                WHERE mp.hood_code IS NOT NULL
                  AND pg.geom_2926 IS NOT NULL
                  AND UPPER(COALESCE(mp.proptype, '')) = 'R'
                  AND {hood_filter_geom}
                GROUP BY mp.hood_code
            )
            SELECT
                neighborhood_code,
                ST_Multi(
                    ST_SimplifyPreserveTopology(
                        ST_Buffer(
                            ST_MakeValid(geom_collection),
                            0
                        ),
                        5
                    )
                ) AS geom_2926
            FROM parcel_geoms;
            """
        ).strip()
        cursor.execute(geometry_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX neighborhood_participation_geometry_idx "
            "ON public.neighborhood_participation_geometry (neighborhood_code);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_participation_geometry_geom_gix "
            "ON public.neighborhood_participation_geometry USING GIST (geom_2926);"
        )

    def rebuild_fact_view(self, cursor):
        cursor.execute("DROP MATERIALIZED VIEW IF EXISTS public.fact_neighborhood_participation CASCADE;")

        fact_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.fact_neighborhood_participation AS
            WITH ambiguous AS (
                SELECT
                    neighborhood_code,
                    election_year,
                    COUNT(DISTINCT ballot_id) AS ambiguous_ballots
                FROM public.ballot_to_parcel
                WHERE is_ambiguous IS TRUE
                GROUP BY neighborhood_code, election_year
            )
            SELECT
                nb.neighborhood_code,
                nb.election_year,
                nb.ballots_cast,
                nr.residential_parcels,
                CASE
                    WHEN nr.residential_parcels >= {PRIVACY_MIN_RESIDENTIAL}
                        THEN nb.ballots_cast::float / NULLIF(nr.residential_parcels, 0)
                    ELSE NULL
                END AS npi,
                ng.geom_2926,
                npp.primary_precinct_code,
                ppi.ballots_cast AS precinct_ballots_cast,
                ppi.residential_parcels AS precinct_residential_parcels,
                ppi.ppi AS precinct_ppi,
                ppi.po_box_pct AS precinct_po_box_pct,
                ppi.po_box_ballots AS precinct_po_box_ballots,
                CASE
                    WHEN ppi.ballots_cast > 0
                        THEN nb.ballots_cast::float / NULLIF(ppi.ballots_cast, 0)
                    ELSE NULL
                END AS assignment_coverage_precinct,
                amb.ambiguous_ballots
            FROM public.neighborhood_ballots_by_year nb
            JOIN public.neighborhood_residential_parcels nr
              ON nb.neighborhood_code = nr.neighborhood_code
             AND nb.election_year = nr.election_year
            JOIN public.neighborhood_participation_geometry ng
              ON ng.neighborhood_code = nb.neighborhood_code
            LEFT JOIN public.neighborhood_primary_precinct npp
              ON npp.neighborhood_code = nb.neighborhood_code
            LEFT JOIN public.precinct_participation_index ppi
              ON ppi.prec_code = npp.primary_precinct_code
             AND ppi.election_year = nb.election_year
            LEFT JOIN ambiguous amb
              ON amb.neighborhood_code = nb.neighborhood_code
             AND amb.election_year = nb.election_year
            WHERE nr.residential_parcels >= {PRIVACY_MIN_RESIDENTIAL};
            """
        ).strip()
        cursor.execute(fact_sql)

        cursor.execute(
            "CREATE INDEX fact_neighborhood_participation_year_idx "
            "ON public.fact_neighborhood_participation (election_year);"
        )
        cursor.execute(
            "CREATE UNIQUE INDEX fact_neighborhood_participation_code_year_idx "
            "ON public.fact_neighborhood_participation (neighborhood_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX fact_neighborhood_participation_geom_idx "
            "ON public.fact_neighborhood_participation USING GIST (geom_2926);"
        )

    def rebuild_quartile_view(self, cursor):
        cursor.execute(
            "DROP MATERIALIZED VIEW IF EXISTS public.neighborhood_participation_classification CASCADE;"
        )

        quartile_cases = " ".join(
            f"WHEN quartile = {q} THEN '{label}'"
            for q, label in sorted(QUARTILE_LABELS.items(), reverse=True)
        )

        quartile_sql = dedent(
            f"""
            CREATE MATERIALIZED VIEW public.neighborhood_participation_classification AS
            WITH ranked AS (
                SELECT
                    neighborhood_code,
                    election_year,
                    npi,
                    NTILE(4) OVER (PARTITION BY election_year ORDER BY npi) AS quartile
                FROM public.fact_neighborhood_participation
            )
            SELECT
                neighborhood_code,
                election_year,
                npi,
                quartile,
                CASE
                    {quartile_cases}
                    ELSE 'Unclassified'
                END AS quartile_label
            FROM ranked;
            """
        ).strip()
        cursor.execute(quartile_sql)

        cursor.execute(
            "CREATE UNIQUE INDEX neighborhood_participation_classification_idx "
            "ON public.neighborhood_participation_classification (neighborhood_code, election_year);"
        )
        cursor.execute(
            "CREATE INDEX neighborhood_participation_classification_year_idx "
            "ON public.neighborhood_participation_classification (election_year);"
        )

    def print_mapping_diagnostics(self, cursor):
        cursor.execute("SELECT COUNT(*) FROM public.voter_ballots_skagit;")
        total_ballots = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM public.ballot_to_parcel;")
        matched_ballots = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM public.ballot_to_parcel WHERE is_ambiguous IS TRUE;"
        )
        ambiguous_matches = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT vb.ballot_id, vb.normalized_address
            FROM public.voter_ballots_skagit vb
            LEFT JOIN public.ballot_to_parcel bp
              ON vb.ballot_id = bp.ballot_id AND vb.election_year = bp.election_year
            WHERE bp.ballot_id IS NULL
            ORDER BY vb.election_year DESC, vb.ballot_id
            LIMIT 10;
            """
        )
        unmatched_sample = cursor.fetchall()

        cursor.execute(
            """
            WITH unmatched AS (
                SELECT
                    vb.election_year,
                    vb.ballot_id,
                    vb.normalized_address,
                    CASE
                        WHEN vb.normalized_address ~ '(PO BOX|P ?O BOX|P ?M ?B|POSTAL BOX|BOX [0-9]+)'
                            THEN 'PO_BOX'
                        WHEN vb.normalized_address IS NULL OR vb.normalized_address = ''
                            THEN 'MISSING_ADDRESS'
                        WHEN vb.normalized_address ~ '^[0-9]+ [A-Z0-9# ./-]+$'
                            THEN 'STREET_LIKE'
                        ELSE 'OTHER'
                    END AS bucket
                FROM public.voter_ballots_skagit vb
                LEFT JOIN public.ballot_to_parcel bp
                  ON vb.ballot_id = bp.ballot_id AND vb.election_year = bp.election_year
                WHERE bp.ballot_id IS NULL
            )
            SELECT
                election_year,
                COUNT(*) FILTER (WHERE bucket = 'PO_BOX') AS unmatched_po_box,
                COUNT(*) FILTER (WHERE bucket = 'MISSING_ADDRESS') AS unmatched_missing,
                COUNT(*) FILTER (WHERE bucket = 'STREET_LIKE') AS unmatched_street_like,
                COUNT(*) FILTER (WHERE bucket = 'OTHER') AS unmatched_other,
                COUNT(*) AS total_unmatched
            FROM unmatched
            GROUP BY election_year
            ORDER BY election_year DESC;
            """
        )
        unmatched_stats = cursor.fetchall()

        self.stdout.write(f"  Total ballots: {total_ballots:,}")
        self.stdout.write(f"  Matched ballots: {matched_ballots:,}")
        coverage = (matched_ballots / total_ballots * 100) if total_ballots else 0
        self.stdout.write(f"  Coverage: {coverage:.2f}%")
        self.stdout.write(f"  Ambiguous matches: {ambiguous_matches:,}")

        if unmatched_stats:
            self.stdout.write("  Unmatched breakdown by election year:")
            for row in unmatched_stats:
                year, bucket_po, bucket_missing, bucket_street, bucket_other, total_unmatched = row
                self.stdout.write(
                    f"    • {year}: total_unmatched={total_unmatched:,}, "
                    f"po_box={bucket_po:,}, missing={bucket_missing:,}, "
                    f"street_like={bucket_street:,}, other={bucket_other:,}"
                )

        if unmatched_sample:
            self.stdout.write("  Unmatched sample:")
            for ballot_id, address in unmatched_sample:
                self.stdout.write(f"    • {ballot_id} @ {address}")
        else:
            self.stdout.write("  Unmatched sample: none 🎉")
