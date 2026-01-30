import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    """Normalize Skagit County voter turnout exports into a single CSV."""

    help = (
        "Remove redundant turnout exports, normalize the remaining CSVs, and "
        "write a single file that is ready for database ingestion."
    )

    DEFAULT_PATTERN = "Skagit*.csv"
    DEFAULT_DUPLICATES = ["Skagit (1).csv"]
    DATETIME_FORMATS = (
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    )
    ELECTION_DATE_FORMATS = ("%b %d %Y", "%B %d %Y")
    ZIP_RE = re.compile(r"^(\d{5})(?:[-\s]*(\d{4}))?$")
    PO_BOX_RE = re.compile(r"^P(?:OST)?\.?\s*(?:O(?:FFICE)?\.?\s*)?BOX\b", re.I)
    OUTPUT_COLUMNS = [
        "ballot_id",
        "voter_id",
        "county",
        "first_name",
        "last_name",
        "gender",
        "election_name",
        "election_category",
        "election_date",
        "ballot_status",
        "challenge_reason",
        "sent_date",
        "received_date",
        "address",
        "normalized_address",
        "is_po_box",
        "city",
        "state",
        "zip5",
        "zip4",
        "country",
        "split",
        "precinct",
        "normalized_precinct",
        "return_method",
        "return_location",
        "party",
        "source_file",
        "source_row",
    ]
    HEADER_ALIASES = {
        "County": {".County", "county"},
        "Sent Date": {"SentDate", "sent date"},
        "Received Date": {"ReceivedDate", "received date"},
        "Return Method": {"ReturnMethod", "return method"},
        "Return Location": {"ReturnLocation", "return location"},
    }

    def add_arguments(self, parser):
        default_source = settings.BASE_DIR / "data" / "votingresults"
        default_output = default_source / "skagit_turnout_2024_2025.normalized.csv"
        parser.add_argument(
            "--source-dir",
            type=str,
            default=str(default_source),
            help="Directory that holds the Skagit CSV exports.",
        )
        parser.add_argument(
            "--pattern",
            type=str,
            default=self.DEFAULT_PATTERN,
            help="Glob pattern for files to include (default: %(default)s).",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=str(default_output),
            help="Destination CSV that will receive the normalized data.",
        )
        parser.add_argument(
            "--canonical",
            type=str,
            default="Skagit.csv",
            help="File considered authoritative when evaluating duplicates.",
        )
        parser.add_argument(
            "--duplicates",
            nargs="*",
            default=self.DEFAULT_DUPLICATES,
            help=(
                "Optional list of files that should be removed when they match the "
                "canonical export."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would happen without writing or deleting anything.",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"]).expanduser().resolve()
        output_file = Path(options["output"]).expanduser().resolve()
        pattern = options["pattern"] or self.DEFAULT_PATTERN
        duplicates = options["duplicates"] or []
        canonical = options["canonical"]
        dry_run = options["dry_run"]

        if not source_dir.exists():
            raise CommandError(f"Source directory {source_dir} does not exist")

        removed_files = self.cleanup_duplicate_exports(
            source_dir, canonical, duplicates, dry_run
        )

        records, per_file_counts, skipped_dupes = self.collect_records(
            source_dir, pattern, removed_files
        )

        if not records:
            self.stdout.write(self.style.WARNING("No rows found after normalization."))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: would write {len(records)} rows to {output_file}"
                )
            )
            return

        output_file.parent.mkdir(parents=True, exist_ok=True)
        with output_file.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.OUTPUT_COLUMNS)
            writer.writeheader()
            for record in records:
                writer.writerow(record)

        summary_bits = [f"wrote {len(records)} rows", f"skipped {skipped_dupes} duplicates"]
        if removed_files:
            summary_bits.append(
                f"removed {len(removed_files)} duplicate export(s): {', '.join(removed_files)}"
            )

        for file_name, count in per_file_counts.items():
            self.stdout.write(f"{file_name}: {count} normalized rows")

        self.stdout.write(self.style.SUCCESS("; ".join(summary_bits)))

    def cleanup_duplicate_exports(self, source_dir, canonical_name, duplicates, dry_run):
        removed = []
        canonical_path = source_dir / canonical_name
        if not canonical_path.exists():
            self.stderr.write(
                self.style.WARNING(
                    f"Canonical export {canonical_path} does not exist; skipping duplicate cleanup"
                )
            )
            return removed

        canonical_hash = self.hash_file(canonical_path)
        for dup_name in duplicates:
            dup_path = source_dir / dup_name
            if not dup_path.exists():
                continue
            dup_hash = self.hash_file(dup_path)
            if dup_hash != canonical_hash:
                self.stderr.write(
                    self.style.WARNING(
                        f"{dup_path.name} does not match {canonical_name}; leaving file in place"
                    )
                )
                continue
            if dry_run:
                self.stdout.write(
                    self.style.WARNING(f"Dry run: would remove duplicate {dup_path.name}")
                )
            else:
                dup_path.unlink()
                removed.append(dup_path.name)
        return removed

    def hash_file(self, path):
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def collect_records(self, source_dir, pattern, removed_files):
        combined = []
        per_file_counts = {}
        seen_keys = set()
        skipped = 0

        for csv_path in sorted(source_dir.glob(pattern)):
            if csv_path.name in removed_files or not csv_path.is_file():
                continue
            per_file_counts[csv_path.name] = 0
            for row_number, row in self.iter_rows(csv_path):
                record = self.normalize_row(row, csv_path.name, row_number)
                if not record["ballot_id"] or not record["election_date"]:
                    continue
                dedupe_key = (record["ballot_id"], record["election_date"])
                if dedupe_key in seen_keys:
                    skipped += 1
                    continue
                seen_keys.add(dedupe_key)
                combined.append(record)
                per_file_counts[csv_path.name] += 1

        combined.sort(key=lambda rec: (rec["election_date"], rec["ballot_id"]))
        return combined, per_file_counts, skipped

    def iter_rows(self, path):
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            try:
                header = next(reader)
            except StopIteration:
                return
            normalized_header = [self.normalize_header(col) for col in header]
            dict_reader = csv.DictReader(fh, fieldnames=normalized_header)
            for idx, row in enumerate(dict_reader, start=2):
                yield idx, row

    def normalize_header(self, raw):
        candidate = (raw or "").strip()
        for canonical, aliases in self.HEADER_ALIASES.items():
            if candidate == canonical or candidate in aliases:
                return canonical
        return candidate

    def normalize_row(self, row, source_file, row_number):
        ballot_id = self.clean_value(row.get("Ballot ID"))
        voter_id = self.clean_value(row.get("Voter ID"))
        county = self.clean_value(row.get("County")) or "Skagit"
        first_name = self.clean_value(row.get("First Name"))
        last_name = self.clean_value(row.get("Last Name"))
        gender = self.clean_value(row.get("Gender")).upper()
        election_name, election_category, election_date = self.parse_election(
            row.get("Election")
        )
        ballot_status = self.clean_value(row.get("Ballot Status"))
        challenge_reason = self.clean_value(row.get("Challenge Reason"))
        sent_date = self.parse_datetime(row.get("Sent Date"))
        received_date = self.parse_datetime(row.get("Received Date"))
        address = self.clean_value(row.get("Address"))
        normalized_address = self.normalize_address(address)
        city = self.normalize_whitespace(row.get("City"))
        city = city.upper() if city else ""
        state = self.clean_value(row.get("State")).upper()
        zip_value = self.clean_value(row.get("Zip"))
        zip5, zip4 = self.split_zip(zip_value)
        country = self.clean_value(row.get("Country")).upper()
        split = self.clean_value(row.get("Split"))
        precinct = self.clean_value(row.get("Precinct"))
        normalized_precinct = self.normalize_whitespace(precinct).upper()
        return_method = self.format_method(row.get("Return Method"))
        return_location = self.normalize_whitespace(row.get("Return Location"))
        party = self.clean_value(row.get("Party")).upper()
        is_po_box = "true" if self.is_po_box(normalized_address) else "false"

        return {
            "ballot_id": ballot_id,
            "voter_id": voter_id,
            "county": county,
            "first_name": first_name,
            "last_name": last_name,
            "gender": gender,
            "election_name": election_name,
            "election_category": election_category,
            "election_date": election_date,
            "ballot_status": ballot_status,
            "challenge_reason": challenge_reason,
            "sent_date": sent_date,
            "received_date": received_date,
            "address": address,
            "normalized_address": normalized_address,
            "is_po_box": is_po_box,
            "city": city,
            "state": state,
            "zip5": zip5,
            "zip4": zip4,
            "country": country,
            "split": split,
            "precinct": precinct,
            "normalized_precinct": normalized_precinct,
            "return_method": return_method,
            "return_location": return_location,
            "party": party,
            "source_file": source_file,
            "source_row": row_number,
        }

    def clean_value(self, value):
        return value.strip() if isinstance(value, str) else ""

    def normalize_whitespace(self, value):
        if not isinstance(value, str):
            return ""
        return " ".join(value.split())

    def normalize_address(self, address):
        normalized = self.normalize_whitespace(address)
        return normalized.upper()

    def is_po_box(self, normalized_address):
        if not normalized_address:
            return False
        return bool(self.PO_BOX_RE.match(normalized_address))

    def parse_datetime(self, raw_value):
        value = self.normalize_whitespace(raw_value)
        if not value:
            return ""
        for fmt in self.DATETIME_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
                return parsed.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
        self.stderr.write(
            self.style.WARNING(f"Unable to parse datetime '{value}'; leaving blank")
        )
        return ""

    def parse_election(self, raw_value):
        normalized = self.normalize_whitespace(raw_value)
        if not normalized:
            return "", "", ""
        tokens = normalized.split()
        if len(tokens) < 4:
            election_name = normalized
            election_category = tokens[0] if tokens else ""
            return election_name, election_category, ""
        date_fragment = " ".join(tokens[-3:])
        election_name = " ".join(tokens[:-3]).strip()
        for fmt in self.ELECTION_DATE_FORMATS:
            try:
                date_obj = datetime.strptime(date_fragment, fmt)
                election_date = date_obj.date().isoformat()
                break
            except ValueError:
                continue
        else:
            self.stderr.write(
                self.style.WARNING(
                    f"Unable to parse election date '{date_fragment}' from '{normalized}'"
                )
            )
            return election_name or normalized, (election_name or normalized).split()[0], ""
        election_category = election_name.split()[0] if election_name else normalized.split()[0]
        return election_name or normalized, election_category, election_date

    def split_zip(self, raw_zip):
        value = raw_zip.strip() if isinstance(raw_zip, str) else ""
        if not value:
            return "", ""
        match = self.ZIP_RE.match(value)
        if match:
            return match.group(1), match.group(2) or ""
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 5:
            return digits[:5], digits[5:9]
        return digits, ""

    def format_method(self, raw_value):
        value = self.normalize_whitespace(raw_value)
        return value.title() if value else ""

