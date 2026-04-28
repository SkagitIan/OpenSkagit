import copy
import csv
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
import geopandas as gpd
import numpy as np
from django.conf import settings
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Transform
from django.core.files.base import ContentFile
from django.core.files.base import File
from django.db import connection, transaction
from django.utils import timezone
from django.utils.text import get_valid_filename
from shapely import affinity as shapely_affinity
from shapely import wkb as shapely_wkb
from shapely.geometry import LineString as shapely_linestring
from shapely.geometry import box as shapely_box
from shapely.prepared import prep as shapely_prep

try:
    from libpysal.weights import Rook
    from libpysal.weights import W
    from spopt.region import MaxPHeuristic
except Exception:  # pragma: no cover - optional clustering backend
    Rook = None
    W = None
    MaxPHeuristic = None

from openskagit.models import (
    CoAppraiserParcelSet,
    CoAppraiserParcelSetItem,
    CoAppraiserRoutePlan,
    MasterParcel,
    ParcelGeometry,
)

logger = logging.getLogger(__name__)

US_SURVEY_FOOT_TO_METER = 1200.0 / 3937.0
METER_TO_US_SURVEY_FOOT = 3937.0 / 1200.0


MODE_PRESETS: Dict[str, Dict[str, Any]] = {
    CoAppraiserRoutePlan.MODE_NEIGHBORHOOD: {
        "label": "Neighborhood (walkable / dense)",
        "target_stops": 75,
        "min_stops": 70,
        "max_stops": 90,
        "grid_cell_size_m": 900,
        "routing_profile": "driving",
    },
    CoAppraiserRoutePlan.MODE_DRIVING: {
        "label": "Driving (house-to-house)",
        "target_stops": 35,
        "min_stops": 30,
        "max_stops": 45,
        "grid_cell_size_m": 1200,
        "routing_profile": "driving",
    },
}

PARCEL_COLUMN_CANDIDATES = [
    "parcel_number",
    "parcel number",
    "parcel",
    "parcel_id",
    "parcel id",
    "parcelid",
    "geoskagit_parcel",
    "pin",
    "tax_parcel_id",
]

MAX_MISSING_PREVIEW = 100
COAPPRAISER_CLUSTER_BACKEND_AUTO = "auto"
COAPPRAISER_CLUSTER_BACKEND_HEURISTIC = "heuristic"
COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP = "spopt_maxp"

STREET_SUFFIX_NORMALIZATION = {
    "STREET": "ST",
    "ROAD": "RD",
    "DRIVE": "DR",
    "LANE": "LN",
    "COURT": "CT",
    "AVENUE": "AVE",
    "PLACE": "PL",
    "TERRACE": "TER",
    "CIRCLE": "CIR",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "ROUTE": "RTE",
}


@dataclass(frozen=True)
class StopRecord:
    item_id: int
    parcel_number: str
    land_use_code: str
    address: str
    lon: float
    lat: float
    x: float
    y: float


class CoAppraiserError(Exception):
    pass


class RoutingError(CoAppraiserError):
    pass


def get_mode_preset(mode: str) -> Dict[str, Any]:
    preset = MODE_PRESETS.get(mode)
    if not preset:
        raise CoAppraiserError(f"Unsupported mode '{mode}'.")
    return dict(preset)


def normalize_parcel_number(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if not text:
        return ""
    text = " ".join(text.split())
    return text


def infer_parcel_column(fieldnames: Sequence[str]) -> Optional[str]:
    if not fieldnames:
        return None
    normalized_map = {str(name).strip().lower(): name for name in fieldnames if name is not None}
    for candidate in PARCEL_COLUMN_CANDIDATES:
        if candidate in normalized_map:
            return normalized_map[candidate]
    for key, original in normalized_map.items():
        if "parcel" in key:
            return original
    return fieldnames[0]


def _decode_csv_bytes(payload: bytes) -> str:
    if payload.startswith(b"PK\x03\x04"):
        raise CoAppraiserError(
            "This looks like an Excel workbook (.xlsx), not a CSV. Please export/save it as CSV and upload again."
        )
    if payload.startswith(b"\xD0\xCF\x11\xE0"):
        raise CoAppraiserError(
            "This looks like an Excel .xls file, not a CSV. Please export/save it as CSV and upload again."
        )

    # Handle UTF-16 CSV exports (common from Windows/legacy systems) before Latin-1 fallback.
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16").replace("\ufeff", "")

    if b"\x00" in payload:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                decoded = payload.decode(encoding)
            except UnicodeDecodeError:
                continue
            if "\x00" not in decoded:
                return decoded.replace("\ufeff", "")

    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            decoded = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in decoded:
            continue
        return decoded.replace("\ufeff", "")

    # Last-ditch cleanup for malformed text exports with embedded NULs.
    cleaned = payload.decode("latin-1", errors="ignore").replace("\x00", "")
    if cleaned.strip():
        return cleaned
    raise CoAppraiserError("Unable to decode CSV file. Try saving as UTF-8 CSV.")


def _read_csv_rows(payload: bytes) -> Tuple[List[Dict[str, str]], str]:
    text = _decode_csv_bytes(payload)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    stream = io.StringIO(text)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel

    try:
        reader = csv.DictReader(stream, dialect=dialect)
        if not reader.fieldnames:
            raise CoAppraiserError("CSV appears to be missing a header row.")

        parcel_column = infer_parcel_column(reader.fieldnames)
        if not parcel_column:
            raise CoAppraiserError("Could not detect a parcel ID column in the CSV.")

        rows: List[Dict[str, str]] = []
        for idx, row in enumerate(reader, start=2):
            rows.append(
                {
                    "row_number": str(idx),
                    "parcel_raw": (row.get(parcel_column) or "").strip(),
                }
            )
        return rows, parcel_column
    except csv.Error as exc:
        raise CoAppraiserError(
            f"Could not parse CSV file ({exc}). If this came from Excel or GeoSkagit, export as CSV UTF-8 and retry."
        ) from exc


def create_parcel_set_from_upload(
    uploaded_file: File,
    *,
    client_ip: Optional[str] = None,
    display_name: str = "",
) -> CoAppraiserParcelSet:
    payload = uploaded_file.read()
    if not payload:
        raise CoAppraiserError("Uploaded file is empty.")

    rows, parcel_column = _read_csv_rows(payload)
    total_rows = len(rows)
    unique_entries: Dict[str, Dict[str, Any]] = {}
    duplicate_count = 0
    blank_rows = 0

    for row in rows:
        raw = row["parcel_raw"]
        row_number = int(row["row_number"])
        normalized = normalize_parcel_number(raw)
        if not normalized:
            blank_rows += 1
            continue
        existing = unique_entries.get(normalized)
        if existing:
            existing["duplicate_instances"] += 1
            duplicate_count += 1
            continue
        unique_entries[normalized] = {
            "source_row": row_number,
            "parcel_number_raw": raw,
            "parcel_number_normalized": normalized,
            "duplicate_instances": 1,
        }

    if not unique_entries:
        raise CoAppraiserError("No parcel IDs were found in the CSV.")

    timestamp_prefix = timezone.now().strftime("%Y%m%d_%H%M%S")
    source_filename = Path(getattr(uploaded_file, "name", "") or "coappraiser_upload.csv").name
    safe_filename = get_valid_filename(source_filename) or "coappraiser_upload.csv"
    storage_filename = f"{timestamp_prefix}_{safe_filename}"

    with transaction.atomic():
        parcel_set = CoAppraiserParcelSet(
            name=(display_name or "").strip(),
            source_filename=source_filename,
            parcel_id_column=parcel_column,
            created_by_ip=client_ip,
            status=CoAppraiserParcelSet.STATUS_PENDING,
            total_rows=total_rows,
            parsed_rows=total_rows - blank_rows,
            duplicate_count=duplicate_count,
            upload_notes={"blank_rows": blank_rows},
        )
        parcel_set.upload_file.save(storage_filename, ContentFile(payload), save=False)
        parcel_set.save()

        normalized_ids = list(unique_entries.keys())
        parcel_map = {
            parcel.parcel_number: parcel
            for parcel in MasterParcel.objects.filter(parcel_number__in=normalized_ids).only(
                "parcel_number",
                "situs_address",
            )
        }
        geometry_map = {
            geom.parcel_id: geom
            for geom in (
                ParcelGeometry.objects.filter(parcel_id__in=normalized_ids)
                .annotate(
                    centroid_geog_fallback=Transform("centroid_2926", 4326),
                    centroid_2926_fallback=Transform("centroid_geog", 2926),
                )
                .select_related("parcel")
            )
        }

        items: List[CoAppraiserParcelSetItem] = []
        found_count = 0
        missing_count = 0
        missing_geometry_count = 0
        missing_examples: List[str] = []
        missing_geometry_examples: List[str] = []

        for normalized in sorted(unique_entries, key=lambda key: (unique_entries[key]["source_row"], key)):
            entry = unique_entries[normalized]
            parcel = parcel_map.get(normalized)
            geom = geometry_map.get(normalized)
            point_geog = None
            point_2926 = None
            if geom:
                point_geog = getattr(geom, "centroid_geog", None) or getattr(geom, "centroid_geog_fallback", None)
                point_2926 = getattr(geom, "centroid_2926", None) or getattr(geom, "centroid_2926_fallback", None)

            status = CoAppraiserParcelSetItem.STATUS_READY
            latitude = longitude = x_2926 = y_2926 = None
            if parcel is None:
                status = CoAppraiserParcelSetItem.STATUS_MISSING
                missing_count += 1
                if len(missing_examples) < MAX_MISSING_PREVIEW:
                    missing_examples.append(normalized)
            elif point_geog is None or point_2926 is None:
                status = CoAppraiserParcelSetItem.STATUS_MISSING_GEOMETRY
                missing_geometry_count += 1
                if len(missing_geometry_examples) < MAX_MISSING_PREVIEW:
                    missing_geometry_examples.append(normalized)
            else:
                longitude = float(point_geog.x)
                latitude = float(point_geog.y)
                x_2926 = float(point_2926.x)
                y_2926 = float(point_2926.y)
                found_count += 1

            items.append(
                CoAppraiserParcelSetItem(
                    parcel_set=parcel_set,
                    source_row=entry["source_row"],
                    parcel_number_raw=entry["parcel_number_raw"],
                    parcel_number_normalized=normalized,
                    duplicate_instances=entry["duplicate_instances"],
                    status=status,
                    parcel=parcel,
                    situs_address=getattr(parcel, "situs_address", None),
                    point_geog=point_geog,
                    point_2926=point_2926,
                    latitude=latitude,
                    longitude=longitude,
                    x_2926=x_2926,
                    y_2926=y_2926,
                    metadata={},
                )
            )

        CoAppraiserParcelSetItem.objects.bulk_create(items, batch_size=1000)

        parcel_set.unique_parcel_count = len(unique_entries)
        parcel_set.found_count = found_count
        parcel_set.missing_count = missing_count
        parcel_set.missing_geometry_count = missing_geometry_count
        parcel_set.status = (
            CoAppraiserParcelSet.STATUS_READY
            if found_count and missing_count == 0 and missing_geometry_count == 0
            else CoAppraiserParcelSet.STATUS_PARTIAL if found_count else CoAppraiserParcelSet.STATUS_FAILED
        )
        parcel_set.upload_notes = {
            "blank_rows": blank_rows,
            "missing_examples": missing_examples,
            "missing_geometry_examples": missing_geometry_examples,
        }
        parcel_set.save(
            update_fields=[
                "unique_parcel_count",
                "found_count",
                "missing_count",
                "missing_geometry_count",
                "status",
                "upload_notes",
                "updated_at",
            ]
        )

    logger.info(
        "CoAppraiser parcel_set created id=%s rows=%s unique=%s found=%s missing=%s missing_geometry=%s",
        parcel_set.id,
        total_rows,
        len(unique_entries),
        found_count,
        missing_count,
        missing_geometry_count,
    )
    return parcel_set


def get_ready_stops(parcel_set: CoAppraiserParcelSet) -> List[StopRecord]:
    qs = (
        CoAppraiserParcelSetItem.objects.filter(
            parcel_set=parcel_set,
            status=CoAppraiserParcelSetItem.STATUS_READY,
        )
        .select_related("parcel")
        .only(
            "id",
            "parcel_number_normalized",
            "situs_address",
            "longitude",
            "latitude",
            "x_2926",
            "y_2926",
            "parcel__land_use_code",
        )
        .order_by("source_row", "parcel_number_normalized")
    )
    stops: List[StopRecord] = []
    for item in qs:
        if None in (item.longitude, item.latitude, item.x_2926, item.y_2926):
            continue
        stops.append(
            StopRecord(
                item_id=item.id,
                parcel_number=item.parcel_number_normalized,
                land_use_code=(getattr(getattr(item, "parcel", None), "land_use_code", None) or ""),
                address=item.situs_address or "",
                lon=float(item.longitude),
                lat=float(item.latitude),
                # EPSG:2926 coordinates are US survey feet; convert to meters so clustering
                # parameters remain intuitive and match the UI labels.
                x=float(item.x_2926) * US_SURVEY_FOOT_TO_METER,
                y=float(item.y_2926) * US_SURVEY_FOOT_TO_METER,
            )
        )
    return stops


def _sql_initial_bins(parcel_set_id: str, cell_size_m: int) -> List[Dict[str, Any]]:
    cell_size_2926_units = max(float(cell_size_m) * METER_TO_US_SURVEY_FOOT, 1.0)
    sql = """
        SELECT
            FLOOR(ST_X(point_2926) / %s)::bigint AS gx,
            FLOOR(ST_Y(point_2926) / %s)::bigint AS gy,
            ARRAY_AGG(id ORDER BY source_row, parcel_number_normalized) AS item_ids
        FROM coappraiser_parcel_set_item
        WHERE parcel_set_id = %s
          AND status = %s
          AND point_2926 IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 2 DESC, 1 ASC
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [
                cell_size_2926_units,
                cell_size_2926_units,
                str(parcel_set_id),
                CoAppraiserParcelSetItem.STATUS_READY,
            ],
        )
        rows = cursor.fetchall()
    return [{"gx": int(gx), "gy": int(gy), "item_ids": list(item_ids or [])} for gx, gy, item_ids in rows]


def _cluster_backend_setting() -> str:
    raw = str(getattr(settings, "COAPPRAISER_CLUSTER_BACKEND", COAPPRAISER_CLUSTER_BACKEND_AUTO) or "").strip().lower()
    if raw in {
        COAPPRAISER_CLUSTER_BACKEND_AUTO,
        COAPPRAISER_CLUSTER_BACKEND_HEURISTIC,
        COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP,
    }:
        return raw
    return COAPPRAISER_CLUSTER_BACKEND_AUTO


def _spopt_available() -> bool:
    return Rook is not None and MaxPHeuristic is not None


def _spopt_max_ready_stops() -> int:
    raw = getattr(settings, "COAPPRAISER_SPOPT_MAX_READY_STOPS", 500)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 500


def _street_component_min_stops() -> int:
    raw = getattr(settings, "COAPPRAISER_STREET_COMPONENT_MIN_STOPS", 5)
    try:
        return max(int(raw), 2)
    except (TypeError, ValueError):
        return 5


def _street_component_link_distance_m() -> float:
    raw = getattr(settings, "COAPPRAISER_STREET_COMPONENT_LINK_DISTANCE_M", 450.0)
    try:
        return max(float(raw), 50.0)
    except (TypeError, ValueError):
        return 450.0


def _street_component_max_span_m() -> float:
    raw = getattr(settings, "COAPPRAISER_STREET_COMPONENT_MAX_SPAN_M", 2200.0)
    try:
        return max(float(raw), 250.0)
    except (TypeError, ValueError):
        return 2200.0


def _street_component_overflow_stops(max_stops: int) -> int:
    raw = getattr(settings, "COAPPRAISER_STREET_COMPONENT_OVERFLOW_STOPS", max(4, int(round(max_stops * 0.12))))
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return max(4, int(round(max_stops * 0.12)))


def _async_min_ready_stops() -> int:
    raw = getattr(settings, "COAPPRAISER_ASYNC_MIN_READY_STOPS", 450)
    try:
        return max(int(raw), 0)
    except (TypeError, ValueError):
        return 450


def should_generate_plan_async(parcel_set: CoAppraiserParcelSet) -> bool:
    threshold = _async_min_ready_stops()
    if threshold <= 0:
        return False
    return int(parcel_set.found_count or 0) >= threshold


def _barrier_contiguity_enabled() -> bool:
    raw = getattr(settings, "COAPPRAISER_BARRIER_CONTIGUITY_ENABLED", True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _barrier_bbox_buffer_m() -> float:
    raw = getattr(settings, "COAPPRAISER_BARRIER_BBOX_BUFFER_M", 1200.0)
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return 1200.0


def _barrier_road_buffer_m() -> float:
    raw = getattr(settings, "COAPPRAISER_BARRIER_ROAD_BUFFER_M", 14.0)
    try:
        return max(float(raw), 0.0)
    except (TypeError, ValueError):
        return 14.0


def _major_barrier_geometry_for_cells(cells: Sequence[Dict[str, Any]]) -> Optional[Any]:
    if not _barrier_contiguity_enabled():
        return None
    if not cells:
        return None

    min_x_m = min(float(cell["gx"]) * float(cell["cell_size_m"]) for cell in cells)
    min_y_m = min(float(cell["gy"]) * float(cell["cell_size_m"]) for cell in cells)
    max_x_m = max((float(cell["gx"]) + 1.0) * float(cell["cell_size_m"]) for cell in cells)
    max_y_m = max((float(cell["gy"]) + 1.0) * float(cell["cell_size_m"]) for cell in cells)

    pad_m = _barrier_bbox_buffer_m()
    min_x_2926 = (min_x_m - pad_m) * METER_TO_US_SURVEY_FOOT
    min_y_2926 = (min_y_m - pad_m) * METER_TO_US_SURVEY_FOOT
    max_x_2926 = (max_x_m + pad_m) * METER_TO_US_SURVEY_FOOT
    max_y_2926 = (max_y_m + pad_m) * METER_TO_US_SURVEY_FOOT

    sql = """
        SELECT ST_AsBinary(ST_UnaryUnion(ST_Collect(geometry)))
        FROM reference_roads
        WHERE geometry && ST_MakeEnvelope(%s, %s, %s, %s, 2926)
          AND (
                "TYPE" = 'S'
                OR UPPER(COALESCE("ROAD_DES", '')) IN ('HIGHWAY', 'FREEWAY')
                OR UPPER(COALESCE("ROAD_NM", '')) LIKE 'STATE ROUTE %%'
                OR UPPER(COALESCE("ROAD_NM", '')) LIKE 'INTERSTATE %%'
                OR UPPER(COALESCE("ROAD_NM", '')) LIKE '%% HIGHWAY%%'
                OR UPPER(COALESCE("ROAD_NM", '')) LIKE '%% FREEWAY%%'
              )
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql,
                [min_x_2926, min_y_2926, max_x_2926, max_y_2926],
            )
            row = cursor.fetchone()
    except Exception as exc:
        logger.warning("CoAppraiser barrier query failed; skipping barrier cut: %s", exc)
        return None

    blob = row[0] if row else None
    if not blob:
        return None
    try:
        barrier_geom_2926 = shapely_wkb.loads(bytes(blob))
    except Exception as exc:
        logger.warning("CoAppraiser barrier decode failed; skipping barrier cut: %s", exc)
        return None
    if barrier_geom_2926.is_empty:
        return None

    barrier_geom_m = shapely_affinity.scale(
        barrier_geom_2926,
        xfact=US_SURVEY_FOOT_TO_METER,
        yfact=US_SURVEY_FOOT_TO_METER,
        origin=(0.0, 0.0),
    )
    road_buffer_m = _barrier_road_buffer_m()
    if road_buffer_m > 0.0:
        barrier_geom_m = barrier_geom_m.buffer(road_buffer_m)
    return barrier_geom_m if not barrier_geom_m.is_empty else None


def _normalize_street_key(address: str) -> str:
    if not address:
        return ""
    text = str(address).upper().split(",", 1)[0]
    text = re.sub(r"\b(?:APT|UNIT|STE|SUITE)\b.*$", "", text).strip()
    text = re.sub(r"#.*$", "", text).strip()
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    text = re.sub(r"^\d+[A-Z]?(?:-\d+)?\s+", "", text).strip()
    if not text:
        return ""
    tokens = text.split()
    if not tokens:
        return ""
    if len(tokens) >= 2 and tokens[-1] in STREET_SUFFIX_NORMALIZATION:
        tokens[-1] = STREET_SUFFIX_NORMALIZATION[tokens[-1]]
    return " ".join(tokens)


def _build_street_components(stops: Sequence[StopRecord]) -> List[Tuple[str, List[StopRecord]]]:
    min_stops = _street_component_min_stops()
    max_dist = _street_component_link_distance_m()
    max_dist_sq = max_dist * max_dist
    max_span_m = _street_component_max_span_m()

    grouped: Dict[str, List[StopRecord]] = {}
    for stop in stops:
        street_key = _normalize_street_key(stop.address)
        if not street_key:
            continue
        grouped.setdefault(street_key, []).append(stop)

    components: List[Tuple[str, List[StopRecord]]] = []
    for street_key in sorted(grouped.keys()):
        group = sorted(grouped[street_key], key=lambda s: (s.y, s.x, s.parcel_number))
        if len(group) < min_stops:
            continue

        parent = list(range(len(group)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a: int, b: int) -> None:
            ra = find(a)
            rb = find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(group) - 1):
            si = group[i]
            for j in range(i + 1, len(group)):
                sj = group[j]
                dx = si.x - sj.x
                dy = si.y - sj.y
                if (dx * dx) + (dy * dy) <= max_dist_sq:
                    union(i, j)

        by_component: Dict[int, List[StopRecord]] = {}
        for idx, stop in enumerate(group):
            root = find(idx)
            by_component.setdefault(root, []).append(stop)

        for stops_in_component in by_component.values():
            if len(stops_in_component) < min_stops:
                continue
            xs = [stop.x for stop in stops_in_component]
            ys = [stop.y for stop in stops_in_component]
            span_m = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            if span_m > max_span_m:
                continue
            components.append(
                (
                    street_key,
                    sorted(stops_in_component, key=lambda s: (s.y, s.x, s.parcel_number)),
                )
            )

    return sorted(
        components,
        key=lambda row: (
            -len(row[1]),
            row[0],
            row[1][0].item_id if row[1] else 0,
        ),
    )


def _apply_street_component_lock(
    clusters: List[Dict[str, Any]],
    *,
    parcel_set_id: Any,
    target_stops: int,
    max_stops: int,
    grid_cell_size_m: int,
) -> List[Dict[str, Any]]:
    if len(clusters) <= 1:
        return clusters

    cluster_stops: List[List[StopRecord]] = [list(cluster.get("stops") or []) for cluster in clusters]
    all_stops = [stop for stops in cluster_stops for stop in stops]
    if not all_stops:
        return clusters

    components = _build_street_components(all_stops)
    if not components:
        return clusters

    cluster_sizes = [len(stops) for stops in cluster_stops]
    item_to_cluster: Dict[int, int] = {}
    stop_by_id: Dict[int, StopRecord] = {}
    for cluster_idx, stops in enumerate(cluster_stops):
        for stop in stops:
            item_to_cluster[stop.item_id] = cluster_idx
            stop_by_id[stop.item_id] = stop

    overflow_limit = _street_component_overflow_stops(max_stops)
    hard_cap = int(max_stops) + int(overflow_limit)
    moved_stops = 0
    locked_components = 0

    for street_key, street_stops in components:
        item_ids = [stop.item_id for stop in street_stops if stop.item_id in item_to_cluster]
        if len(item_ids) < _street_component_min_stops():
            continue

        per_cluster: Dict[int, int] = {}
        for item_id in item_ids:
            idx = item_to_cluster[item_id]
            per_cluster[idx] = per_cluster.get(idx, 0) + 1
        if len(per_cluster) <= 1:
            continue

        component_size = len(item_ids)
        candidates = []
        for idx, owned in per_cluster.items():
            projected_size = cluster_sizes[idx] - owned + component_size
            if projected_size > hard_cap:
                continue
            candidates.append(
                (
                    -owned,
                    abs(projected_size - target_stops),
                    projected_size,
                    idx,
                )
            )
        if not candidates:
            continue

        target_idx = min(candidates)[3]
        moved_here = 0
        for item_id in item_ids:
            source_idx = item_to_cluster[item_id]
            if source_idx == target_idx:
                continue
            stop = stop_by_id[item_id]
            cluster_stops[source_idx].remove(stop)
            cluster_stops[target_idx].append(stop)
            cluster_sizes[source_idx] -= 1
            cluster_sizes[target_idx] += 1
            item_to_cluster[item_id] = target_idx
            moved_here += 1

        if moved_here:
            moved_stops += moved_here
            locked_components += 1
            logger.debug(
                "CoAppraiser street-lock moved %s stops on %s into cluster index %s",
                moved_here,
                street_key,
                target_idx,
            )

    if not moved_stops:
        return clusters

    rebuilt: List[Dict[str, Any]] = []
    for idx, stops in enumerate(cluster_stops):
        if not stops:
            continue
        rebuilt_cluster = _make_cluster(
            stops,
            seed_cells=_seed_cells_from_stops(stops, grid_cell_size_m),
        )
        if clusters[idx].get("cluster_backend"):
            rebuilt_cluster["cluster_backend"] = clusters[idx]["cluster_backend"]
        rebuilt.append(rebuilt_cluster)

    logger.info(
        "CoAppraiser street-lock adjusted parcel_set=%s components=%s moved_stops=%s",
        parcel_set_id,
        locked_components,
        moved_stops,
    )
    return rebuilt


def _spopt_cell_size_m_for_plan(grid_cell_size_m: int) -> int:
    # Use a finer base grid than the display/tuning cell so MaxP has room to form contiguous shapes.
    return max(int(grid_cell_size_m // 6), 150)


def _spopt_iteration_limits(cell_count: int) -> Tuple[int, int]:
    """
    Cap MaxP iterations so large inputs do not hit Gunicorn worker timeouts.
    """
    if cell_count >= 90:
        return (20, 4)
    if cell_count >= 60:
        return (30, 6)
    return (60, 8)


def _build_atomic_grid_cells_for_spopt(
    parcel_set: CoAppraiserParcelSet,
    *,
    cell_size_m: int,
) -> List[Dict[str, Any]]:
    stop_map = {stop.item_id: stop for stop in get_ready_stops(parcel_set)}
    if not stop_map:
        return []
    initial_bins = _sql_initial_bins(str(parcel_set.id), cell_size_m)
    cells: List[Dict[str, Any]] = []
    for bucket in initial_bins:
        stops = [stop_map[item_id] for item_id in bucket["item_ids"] if item_id in stop_map]
        if not stops:
            continue
        gx = int(bucket["gx"])
        gy = int(bucket["gy"])
        x0 = gx * float(cell_size_m)
        y0 = gy * float(cell_size_m)
        x1 = x0 + float(cell_size_m)
        y1 = y0 + float(cell_size_m)
        cells.append(
            {
                "gx": gx,
                "gy": gy,
                "cell_size_m": int(cell_size_m),
                "item_ids": [stop.item_id for stop in stops],
                "stops": stops,
                "parcel_count": len(stops),
                "center_x": (x0 + x1) / 2.0,
                "center_y": (y0 + y1) / 2.0,
                # Geometry is only for adjacency (Rook), so planar meter grid coordinates are fine.
                "geometry": shapely_box(x0, y0, x1, y1),
            }
        )
    return cells


def _build_clusters_from_spopt_labels(
    cells: Sequence[Dict[str, Any]],
    labels: Sequence[Any],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for cell, raw_label in zip(cells, labels):
        label_key = str(int(raw_label)) if isinstance(raw_label, (int, float)) else str(raw_label)
        if label_key not in grouped:
            grouped[label_key] = {"stops": [], "seed_cells": []}
            order.append(label_key)
        grouped[label_key]["stops"].extend(cell["stops"])
        grouped[label_key]["seed_cells"].append(
            {
                "gx": cell["gx"],
                "gy": cell["gy"],
                "cell_size_m": cell["cell_size_m"],
            }
        )

    clusters: List[Dict[str, Any]] = []
    for key in order:
        payload = grouped[key]
        cluster = _make_cluster(payload["stops"], seed_cells=payload["seed_cells"])
        clusters.append(cluster)
    return clusters


def _spopt_seed(parcel_set_id: Any, *, grid_cell_size_m: int, target_stops: int, attempt_index: int) -> int:
    raw = f"{parcel_set_id}|{grid_cell_size_m}|{target_stops}|{attempt_index}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(raw, digest_size=8).digest(), "big") & 0xFFFFFFFF


def _spopt_attempts_for_cell_count(cell_count: int) -> int:
    if cell_count <= 120:
        return 4
    if cell_count <= 300:
        return 3
    return 2


def _score_cluster_shape(cluster: Dict[str, Any]) -> float:
    count = max(int(cluster.get("stop_count") or 0), 1)
    x1, y1, x2, y2 = cluster.get("bbox") or (0.0, 0.0, 0.0, 0.0)
    width = max(0.0, float(x2) - float(x1))
    height = max(0.0, float(y2) - float(y1))
    bbox_area = width * height
    bbox_diag = math.hypot(width, height)
    # Penalize long/sparse shapes, but lightly versus size-balance penalties.
    return (bbox_diag / math.sqrt(count)) + (bbox_area / count / 10000.0)


def _evaluate_spopt_cluster_solution(
    clusters: Sequence[Dict[str, Any]],
    *,
    target_stops: int,
    min_stops: int,
    max_stops: int,
) -> Tuple[float, Dict[str, Any]]:
    if not clusters:
        return float("inf"), {"acceptable": False, "reason": "no_clusters"}

    counts = [int(c.get("stop_count") or 0) for c in clusters]
    total_stops = sum(counts)
    cluster_count = len(counts)
    expected_cluster_count = max(1, int(math.ceil(total_stops / max(target_stops, 1))))

    tiny_threshold = max(5, int(round(min_stops * 0.6)))
    tiny_count = sum(1 for c in counts if c < tiny_threshold)
    undersized_count = sum(1 for c in counts if c < min_stops)
    oversize_count = sum(1 for c in counts if c > max_stops)
    within_range_count = sum(1 for c in counts if min_stops <= c <= max_stops)

    # Quality gate: accept some small islands, reject obviously fragmented outputs.
    max_reasonable_clusters = max(expected_cluster_count + 3, int(math.ceil(expected_cluster_count * 1.8)))
    too_fragmented = cluster_count > max_reasonable_clusters
    too_many_tiny = tiny_count > max(2, int(math.ceil(cluster_count * 0.25)))
    poor_range_fit = within_range_count < max(1, int(math.floor(cluster_count * 0.5)))

    acceptable = not (too_fragmented or (too_many_tiny and poor_range_fit))

    shape_penalty = sum(_score_cluster_shape(cluster) for cluster in clusters)
    size_penalty = 0.0
    for count in counts:
        if count < min_stops:
            gap = min_stops - count
            size_penalty += 15.0 + (gap * gap * 0.8)
        elif count > max_stops:
            gap = count - max_stops
            size_penalty += 12.0 + (gap * gap * 0.5)
        else:
            size_penalty += abs(count - target_stops) * 0.1

    score = (
        (abs(cluster_count - expected_cluster_count) * 30.0)
        + (tiny_count * 40.0)
        + (undersized_count * 10.0)
        + (oversize_count * 20.0)
        + size_penalty
        + shape_penalty
    )
    if not acceptable:
        score += 10000.0

    stats = {
        "acceptable": acceptable,
        "cluster_count": cluster_count,
        "expected_cluster_count": expected_cluster_count,
        "tiny_threshold": tiny_threshold,
        "tiny_count": tiny_count,
        "undersized_count": undersized_count,
        "oversize_count": oversize_count,
        "within_range_count": within_range_count,
        "counts": sorted(counts),
        "score": round(score, 3),
        "too_fragmented": too_fragmented,
        "too_many_tiny": too_many_tiny,
        "poor_range_fit": poor_range_fit,
    }
    return score, stats


def _build_spopt_maxp_clusters(
    parcel_set: CoAppraiserParcelSet,
    *,
    target_stops: int,
    min_stops: int,
    max_stops: int,
    grid_cell_size_m: int,
) -> List[Dict[str, Any]]:
    if not _spopt_available():
        raise CoAppraiserError("spopt/libpysal is not available.")

    spopt_cell_size_m = _spopt_cell_size_m_for_plan(grid_cell_size_m)
    cells = _build_atomic_grid_cells_for_spopt(parcel_set, cell_size_m=spopt_cell_size_m)
    if not cells:
        return []
    if len(cells) == 1:
        return [_make_cluster(cells[0]["stops"], seed_cells=[{"gx": cells[0]["gx"], "gy": cells[0]["gy"], "cell_size_m": spopt_cell_size_m}])]

    gdf = gpd.GeoDataFrame(
        {
            "cell_id": list(range(len(cells))),
            "parcel_count": [int(cell["parcel_count"]) for cell in cells],
            "threshold_count": [int(cell["parcel_count"]) for cell in cells],
            "center_x": [float(cell["center_x"]) for cell in cells],
            "center_y": [float(cell["center_y"]) for cell in cells],
        },
        geometry=[cell["geometry"] for cell in cells],
    )

    # Rook contiguity avoids diagonal-only touching cells from acting as connected regions.
    w = Rook.from_dataframe(gdf, silence_warnings=True, use_index=False)

    barrier_geom = _major_barrier_geometry_for_cells(cells)
    if barrier_geom is not None and W is not None:
        prepared = shapely_prep(barrier_geom)
        kept_neighbors: Dict[int, List[int]] = {idx: [] for idx in range(len(cells))}
        seen_edges = set()
        blocked_edges = 0
        kept_edges = 0
        for a, neighbors in w.neighbors.items():
            for b in neighbors:
                i = int(a)
                j = int(b)
                edge = (i, j) if i < j else (j, i)
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)

                center_line = shapely_linestring(
                    [
                        (float(cells[edge[0]]["center_x"]), float(cells[edge[0]]["center_y"])),
                        (float(cells[edge[1]]["center_x"]), float(cells[edge[1]]["center_y"])),
                    ]
                )
                if prepared.intersects(center_line):
                    blocked_edges += 1
                    continue

                kept_neighbors[edge[0]].append(edge[1])
                kept_neighbors[edge[1]].append(edge[0])
                kept_edges += 1

        if blocked_edges > 0:
            kept_weights = {idx: [1.0] * len(nbrs) for idx, nbrs in kept_neighbors.items()}
            w = W(kept_neighbors, weights=kept_weights, silence_warnings=True)
            logger.info(
                "CoAppraiser barrier-cut contiguity edges blocked=%s kept=%s",
                blocked_edges,
                kept_edges,
            )

    if w.n_components > 1:
        logger.info("CoAppraiser spopt graph has %s disconnected components; solving globally with contiguity graph.", w.n_components)

    threshold = max(int(min_stops), 1)
    best_clusters: Optional[List[Dict[str, Any]]] = None
    best_score = float("inf")
    best_stats: Optional[Dict[str, Any]] = None
    max_iterations_construction, max_iterations_sa = _spopt_iteration_limits(len(cells))

    attempts = _spopt_attempts_for_cell_count(len(cells))
    started_at = time.monotonic()
    for attempt_index in range(attempts):
        seed = _spopt_seed(
            parcel_set.id,
            grid_cell_size_m=spopt_cell_size_m,
            target_stops=target_stops,
            attempt_index=attempt_index,
        )
        py_state = random.getstate()
        np_state = np.random.get_state()
        try:
            random.seed(seed)
            np.random.seed(seed)
            model = MaxPHeuristic(
                gdf,
                w,
                attrs_name=["center_x", "center_y"],
                threshold_name="threshold_count",
                threshold=threshold,
                top_n=3,
                max_iterations_construction=max_iterations_construction,
                max_iterations_sa=max_iterations_sa,
                verbose=False,
                policy="single",
            )
            model.solve()
        finally:
            random.setstate(py_state)
            np.random.set_state(np_state)

        labels = getattr(model, "labels_", None)
        if labels is None:
            raise CoAppraiserError("spopt MaxP returned no labels.")
        if len(labels) != len(cells):
            raise CoAppraiserError("spopt MaxP label count did not match cell count.")

        labels_list = list(labels)
        if any(label is None for label in labels_list):
            raise CoAppraiserError("spopt MaxP returned unassigned cells.")

        attempt_clusters = _build_clusters_from_spopt_labels(cells, labels_list)

        # Soft minimum: keep clean small islands if they exist. Hard maximum: split oversized clusters.
        split_threshold = max(int(max_stops) + max(5, int(round(max_stops * 0.15))), int(max_stops) + 1)
        finalized: List[Dict[str, Any]] = []
        for cluster in attempt_clusters:
            if cluster["stop_count"] > split_threshold:
                finalized.extend(
                    _subdivide_oversized_cluster(
                        cluster,
                        target_stops=target_stops,
                        max_stops=max_stops,
                        cell_size_m=max(spopt_cell_size_m // 2, 50),
                    )
                )
            else:
                finalized.append(cluster)

        score, stats = _evaluate_spopt_cluster_solution(
            finalized,
            target_stops=target_stops,
            min_stops=min_stops,
            max_stops=max_stops,
        )
        logger.info(
            "CoAppraiser spopt MaxP attempt parcel_set=%s seed=%s score=%.2f clusters=%s counts=%s acceptable=%s",
            parcel_set.id,
            seed,
            score,
            stats.get("cluster_count"),
            stats.get("counts"),
            stats.get("acceptable"),
        )
        if score < best_score:
            best_score = score
            best_clusters = finalized
            best_stats = stats
        if stats.get("acceptable"):
            logger.info(
                "CoAppraiser spopt MaxP accepted first valid attempt parcel_set=%s seed=%s elapsed_s=%.2f",
                parcel_set.id,
                seed,
                time.monotonic() - started_at,
            )
            break

    if not best_clusters or not best_stats:
        raise CoAppraiserError("spopt MaxP did not produce a usable clustering result.")
    if not best_stats.get("acceptable"):
        raise CoAppraiserError(
            "spopt MaxP produced a fragmented clustering ("
            f"clusters={best_stats.get('cluster_count')}, "
            f"expected~{best_stats.get('expected_cluster_count')}, "
            f"tiny={best_stats.get('tiny_count')})."
        )

    return sorted(
        best_clusters,
        key=lambda c: (
            round(c["centroid_y"], 3),
            round(c["centroid_x"], 3),
            c["stop_count"],
        ),
    )


def _cluster_metrics(cluster: Dict[str, Any]) -> None:
    stops: List[StopRecord] = cluster["stops"]
    count = len(stops)
    cluster["stop_count"] = count
    if not stops:
        cluster["centroid_x"] = 0.0
        cluster["centroid_y"] = 0.0
        cluster["bbox"] = (0.0, 0.0, 0.0, 0.0)
        return
    xs = [s.x for s in stops]
    ys = [s.y for s in stops]
    cluster["centroid_x"] = sum(xs) / count
    cluster["centroid_y"] = sum(ys) / count
    cluster["bbox"] = (min(xs), min(ys), max(xs), max(ys))


def _dedupe_seed_cells(seed_cells: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for cell in seed_cells:
        try:
            gx = int(cell["gx"])
            gy = int(cell["gy"])
            cell_size_m = int(cell["cell_size_m"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (gx, gy, cell_size_m)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"gx": gx, "gy": gy, "cell_size_m": cell_size_m})
    return deduped


def _seed_cells_from_stops(stops: Sequence[StopRecord], cell_size_m: int) -> List[Dict[str, Any]]:
    if not stops or cell_size_m <= 0:
        return []
    raw = []
    for stop in stops:
        raw.append(
            {
                "gx": math.floor(stop.x / cell_size_m),
                "gy": math.floor(stop.y / cell_size_m),
                "cell_size_m": int(cell_size_m),
            }
        )
    return _dedupe_seed_cells(raw)


def _make_cluster(stops: List[StopRecord], seed_cells: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cluster = {
        "stops": sorted(stops, key=lambda s: (s.y, s.x, s.parcel_number)),
        "seed_cells": _dedupe_seed_cells(seed_cells or []),
    }
    _cluster_metrics(cluster)
    return cluster


def _subdivide_oversized_cluster(
    cluster: Dict[str, Any],
    *,
    target_stops: int,
    max_stops: int,
    cell_size_m: int,
) -> List[Dict[str, Any]]:
    stops: List[StopRecord] = cluster["stops"]
    if len(stops) <= max_stops:
        return [cluster]

    if cell_size_m <= 50:
        chunk_size = max(target_stops, 1)
        return [
            _make_cluster(
                stops[idx : idx + chunk_size],
                seed_cells=_seed_cells_from_stops(stops[idx : idx + chunk_size], cell_size_m),
            )
            for idx in range(0, len(stops), chunk_size)
        ]

    subcell = max(int(cell_size_m / 2), 50)
    buckets: Dict[Tuple[int, int], List[StopRecord]] = {}
    for stop in stops:
        key = (math.floor(stop.x / subcell), math.floor(stop.y / subcell))
        buckets.setdefault(key, []).append(stop)

    if len(buckets) <= 1:
        chunk_size = max(target_stops, 1)
        return [
            _make_cluster(
                stops[idx : idx + chunk_size],
                seed_cells=_seed_cells_from_stops(stops[idx : idx + chunk_size], subcell),
            )
            for idx in range(0, len(stops), chunk_size)
        ]

    parts: List[Dict[str, Any]] = []
    for (gx, gy) in sorted(buckets.keys(), key=lambda t: (t[1], t[0])):
        child = _make_cluster(
            buckets[(gx, gy)],
            seed_cells=[{"gx": gx, "gy": gy, "cell_size_m": int(subcell)}],
        )
        parts.extend(
            _subdivide_oversized_cluster(
                child,
                target_stops=target_stops,
                max_stops=max_stops,
                cell_size_m=subcell,
            )
        )
    return parts


def _cluster_distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return math.hypot(a["centroid_x"] - b["centroid_x"], a["centroid_y"] - b["centroid_y"])


def _adjacency_score(a: Dict[str, Any], b: Dict[str, Any], base_cell_size_m: int) -> int:
    ax1, ay1, ax2, ay2 = a["bbox"]
    bx1, by1, bx2, by2 = b["bbox"]
    gap_x = max(0.0, max(bx1 - ax2, ax1 - bx2))
    gap_y = max(0.0, max(by1 - ay2, ay1 - by2))
    threshold = float(base_cell_size_m) * 1.25
    return 0 if gap_x <= threshold and gap_y <= threshold else 1


def _merge_small_clusters(
    clusters: List[Dict[str, Any]],
    *,
    min_stops: int,
    target_stops: int,
    max_stops: int,
    base_cell_size_m: int,
) -> List[Dict[str, Any]]:
    working = list(clusters)
    if not working:
        return working

    while True:
        undersized_indexes = [idx for idx, c in enumerate(working) if c["stop_count"] < min_stops]
        if not undersized_indexes or len(working) == 1:
            break

        idx = min(
            undersized_indexes,
            key=lambda i: (
                working[i]["stop_count"],
                round(working[i]["centroid_y"], 3),
                round(working[i]["centroid_x"], 3),
            ),
        )
        cluster = working[idx]

        candidates: List[Tuple[Any, int]] = []
        for j, other in enumerate(working):
            if j == idx:
                continue
            combined = cluster["stop_count"] + other["stop_count"]
            overflow_penalty = max(0, combined - max_stops)
            under_target_penalty = abs(target_stops - combined)
            candidates.append(
                (
                    (
                        overflow_penalty,
                        _adjacency_score(cluster, other, base_cell_size_m),
                        under_target_penalty,
                        round(_cluster_distance(cluster, other), 3),
                        round(other["centroid_y"], 3),
                        round(other["centroid_x"], 3),
                    ),
                    j,
                )
            )

        if not candidates:
            break

        _, chosen_index = min(candidates, key=lambda row: row[0])
        other = working[chosen_index]
        merged_stops = cluster["stops"] + other["stops"]
        merged_cluster = _make_cluster(
            merged_stops,
            seed_cells=list(cluster.get("seed_cells") or []) + list(other.get("seed_cells") or []),
        )

        for remove_index in sorted([idx, chosen_index], reverse=True):
            working.pop(remove_index)
        working.append(merged_cluster)

    return sorted(
        working,
        key=lambda c: (
            round(c["centroid_y"], 3),
            round(c["centroid_x"], 3),
            c["stop_count"],
        ),
    )


def build_route_clusters(
    parcel_set: CoAppraiserParcelSet,
    *,
    target_stops: int,
    min_stops: int,
    max_stops: int,
    grid_cell_size_m: int,
    allow_large_spopt: bool = False,
) -> List[Dict[str, Any]]:
    backend_setting = _cluster_backend_setting()
    prefer_spopt = backend_setting in {
        COAPPRAISER_CLUSTER_BACKEND_AUTO,
        COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP,
    }
    spopt_stop_limit = _spopt_max_ready_stops()
    ready_count_estimate = int(parcel_set.found_count or 0)
    if (
        backend_setting == COAPPRAISER_CLUSTER_BACKEND_AUTO
        and not allow_large_spopt
        and spopt_stop_limit > 0
        and ready_count_estimate > spopt_stop_limit
    ):
        prefer_spopt = False
        logger.info(
            "CoAppraiser skipping spopt backend for parcel_set=%s ready_count=%s limit=%s",
            parcel_set.id,
            ready_count_estimate,
            spopt_stop_limit,
        )
    if prefer_spopt and _spopt_available():
        try:
            clusters = _build_spopt_maxp_clusters(
                parcel_set,
                target_stops=target_stops,
                min_stops=min_stops,
                max_stops=max_stops,
                grid_cell_size_m=grid_cell_size_m,
            )
            clusters = _apply_street_component_lock(
                clusters,
                parcel_set_id=parcel_set.id,
                target_stops=target_stops,
                max_stops=max_stops,
                grid_cell_size_m=grid_cell_size_m,
            )
            for cluster in clusters:
                cluster["cluster_backend"] = COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP
            numbered = []
            for index, cluster in enumerate(clusters, start=1):
                cluster["cluster_id"] = f"day-{index}"
                numbered.append(cluster)
            logger.info(
                "CoAppraiser clustering backend=%s parcel_set=%s clusters=%s",
                COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP,
                parcel_set.id,
                len(numbered),
            )
            return numbered
        except Exception as exc:
            logger.exception(
                "CoAppraiser spopt clustering failed for parcel_set=%s; falling back to heuristic: %s",
                parcel_set.id,
                exc,
            )
            if backend_setting == COAPPRAISER_CLUSTER_BACKEND_SPOPT_MAXP:
                raise

    stop_map = {stop.item_id: stop for stop in get_ready_stops(parcel_set)}
    if not stop_map:
        return []

    initial_bins = _sql_initial_bins(str(parcel_set.id), grid_cell_size_m)
    atomic_clusters: List[Dict[str, Any]] = []
    seen_item_ids = set()
    for bucket in initial_bins:
        stops = [stop_map[item_id] for item_id in bucket["item_ids"] if item_id in stop_map]
        if not stops:
            continue
        for stop in stops:
            seen_item_ids.add(stop.item_id)
        cluster = _make_cluster(stops, seed_cells=_seed_cells_from_stops(stops, grid_cell_size_m))
        atomic_clusters.extend(
            _subdivide_oversized_cluster(
                cluster,
                target_stops=target_stops,
                max_stops=max_stops,
                cell_size_m=grid_cell_size_m,
            )
        )

    orphan_ids = [item_id for item_id in stop_map.keys() if item_id not in seen_item_ids]
    if orphan_ids:
        atomic_clusters.extend(
            [
                _make_cluster(
                    [stop_map[item_id]],
                    seed_cells=_seed_cells_from_stops([stop_map[item_id]], grid_cell_size_m),
                )
                for item_id in sorted(orphan_ids)
            ]
        )

    merged = _merge_small_clusters(
        atomic_clusters,
        min_stops=min_stops,
        target_stops=target_stops,
        max_stops=max_stops,
        base_cell_size_m=grid_cell_size_m,
    )

    finalized: List[Dict[str, Any]] = []
    for cluster in merged:
        if cluster["stop_count"] > max_stops:
            finalized.extend(
                _subdivide_oversized_cluster(
                    cluster,
                    target_stops=target_stops,
                    max_stops=max_stops,
                    cell_size_m=max(int(grid_cell_size_m / 2), 50),
                )
            )
        else:
            finalized.append(cluster)

    finalized = _apply_street_component_lock(
        finalized,
        parcel_set_id=parcel_set.id,
        target_stops=target_stops,
        max_stops=max_stops,
        grid_cell_size_m=grid_cell_size_m,
    )

    numbered = []
    for index, cluster in enumerate(
        sorted(
            finalized,
            key=lambda c: (
                round(c["centroid_y"], 3),
                round(c["centroid_x"], 3),
                c["stop_count"],
            ),
        ),
        start=1,
    ):
        cluster["cluster_id"] = f"day-{index}"
        cluster["cluster_backend"] = COAPPRAISER_CLUSTER_BACKEND_HEURISTIC
        numbered.append(cluster)
    logger.info(
        "CoAppraiser clustering backend=%s parcel_set=%s clusters=%s",
        COAPPRAISER_CLUSTER_BACKEND_HEURISTIC,
        parcel_set.id,
        len(numbered),
    )
    return numbered


def _geojson_from_sql(sql: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def build_cluster_geometries(item_ids: Sequence[int]) -> Dict[str, Any]:
    ids = [int(item_id) for item_id in item_ids]
    if not ids:
        return {"hull": None, "bounds": None, "centroid": None}

    params = [ids]
    hull = _geojson_from_sql(
        """
        SELECT ST_AsGeoJSON(
            ST_ConvexHull(ST_Collect(point_geog))
        )
        FROM coappraiser_parcel_set_item
        WHERE id = ANY(%s) AND point_geog IS NOT NULL
        """,
        params,
    )
    bounds = _geojson_from_sql(
        """
        SELECT ST_AsGeoJSON(
            ST_Envelope(ST_Collect(point_geog))
        )
        FROM coappraiser_parcel_set_item
        WHERE id = ANY(%s) AND point_geog IS NOT NULL
        """,
        params,
    )
    centroid = _geojson_from_sql(
        """
        SELECT ST_AsGeoJSON(
            ST_Centroid(ST_Collect(point_geog))
        )
        FROM coappraiser_parcel_set_item
        WHERE id = ANY(%s) AND point_geog IS NOT NULL
        """,
        params,
    )
    return {"hull": hull, "bounds": bounds, "centroid": centroid}


def build_cluster_grid_cell_bounds(seed_cells: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cells = _dedupe_seed_cells(seed_cells)
    if not cells:
        return []

    gx_values = [int(cell["gx"]) for cell in cells]
    gy_values = [int(cell["gy"]) for cell in cells]
    size_m_values = [float(cell["cell_size_m"]) for cell in cells]

    sql = """
        WITH raw_cells AS (
            SELECT
                gx,
                gy,
                size_m,
                (size_m * %s::double precision) AS size_2926
            FROM unnest(%s::bigint[], %s::bigint[], %s::double precision[]) AS c(gx, gy, size_m)
        ),
        cell_geoms AS (
            SELECT
                gx,
                gy,
                size_m,
                ST_Transform(
                    ST_MakeEnvelope(
                        gx * size_2926,
                        gy * size_2926,
                        (gx + 1) * size_2926,
                        (gy + 1) * size_2926,
                        2926
                    ),
                    4326
                ) AS geom
            FROM raw_cells
        )
        SELECT json_agg(
            json_build_object(
                'gx', gx,
                'gy', gy,
                'cell_size_m', size_m,
                'west', ST_XMin(geom),
                'south', ST_YMin(geom),
                'east', ST_XMax(geom),
                'north', ST_YMax(geom)
            )
            ORDER BY size_m DESC, gy DESC, gx ASC
        )
        FROM cell_geoms
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [
                METER_TO_US_SURVEY_FOOT,
                gx_values,
                gy_values,
                size_m_values,
            ],
        )
        row = cursor.fetchone()

    payload = row[0] if row else []
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return payload if isinstance(payload, list) else []


class OSRMClient:
    def __init__(self, *, base_url: str, profile: str, timeout_seconds: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self.profile = profile
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _coord_string(coords: Sequence[Tuple[float, float]]) -> str:
        return ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in coords)

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(url, params=params, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise RoutingError(f"Router request failed: {exc}") from exc
        if payload.get("code") not in (None, "Ok"):
            raise RoutingError(f"Router returned error: {payload.get('code')}")
        return payload

    def table(self, coords: Sequence[Tuple[float, float]]) -> Tuple[List[List[float]], List[List[float]]]:
        payload = self._get(
            f"/table/v1/{self.profile}/{self._coord_string(coords)}",
            {"annotations": "duration,distance"},
        )
        durations = payload.get("durations")
        distances = payload.get("distances")
        if not isinstance(durations, list):
            raise RoutingError("Router table response missing durations matrix.")
        if not isinstance(distances, list):
            distances = [[0.0 for _ in row] for row in durations]
        return durations, distances

    def route(self, coords: Sequence[Tuple[float, float]]) -> Dict[str, Any]:
        payload = self._get(
            f"/route/v1/{self.profile}/{self._coord_string(coords)}",
            {"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        routes = payload.get("routes") or []
        if not routes:
            raise RoutingError("Router route response contained no route.")
        route = routes[0]
        return {
            "distance_m": float(route.get("distance") or 0.0),
            "duration_s": float(route.get("duration") or 0.0),
            "geometry": route.get("geometry"),
        }


def _matrix_path_cost(order: Sequence[int], durations: Sequence[Sequence[float]], end_index: int) -> float:
    current = 0
    total = 0.0
    for idx in order:
        leg = durations[current][idx]
        total += float(leg or 0.0)
        current = idx
    total += float(durations[current][end_index] or 0.0)
    return total


def _solve_fixed_depot_order(durations: Sequence[Sequence[float]], stop_count: int) -> List[int]:
    if stop_count <= 0:
        return []
    stop_indexes = list(range(1, stop_count + 1))
    unvisited = set(stop_indexes)
    current = 0
    order: List[int] = []

    while unvisited:
        next_idx = min(unvisited, key=lambda idx: (float(durations[current][idx] or 0.0), idx))
        order.append(next_idx)
        unvisited.remove(next_idx)
        current = next_idx

    end_index = stop_count + 1
    best = list(order)
    best_cost = _matrix_path_cost(best, durations, end_index)

    improved = True
    while improved:
        improved = False
        for i in range(0, len(best) - 1):
            for j in range(i + 1, len(best)):
                candidate = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                candidate_cost = _matrix_path_cost(candidate, durations, end_index)
                if candidate_cost + 1e-6 < best_cost:
                    best = candidate
                    best_cost = candidate_cost
                    improved = True
                    break
            if improved:
                break

    return best


def _depot_config() -> Dict[str, Any]:
    return {
        "name": getattr(settings, "COAPPRAISER_DEPOT_NAME", "Skagit County Assessor (Mount Vernon)"),
        "lat": float(getattr(settings, "COAPPRAISER_DEPOT_LAT", 48.4180)),
        "lon": float(getattr(settings, "COAPPRAISER_DEPOT_LON", -122.3378)),
    }


def _router_config() -> Dict[str, Any]:
    return {
        "base_url": getattr(settings, "COAPPRAISER_ROUTER_BASE_URL", "https://router.project-osrm.org"),
        "timeout_seconds": float(getattr(settings, "COAPPRAISER_ROUTER_TIMEOUT_SECONDS", 20.0)),
        "max_coords": int(getattr(settings, "COAPPRAISER_ROUTER_MAX_COORDS", 100)),
    }


def _format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return ""
    seconds = int(round(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, _ = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _format_distance_m(distance_m: Optional[float]) -> str:
    if distance_m is None:
        return ""
    miles = float(distance_m) / 1609.344
    return f"{miles:.1f} mi"


def _cluster_stops_for_display(cluster: Dict[str, Any]) -> List[Dict[str, Any]]:
    ordered = sorted(
        list(cluster["stops"]),
        key=lambda stop: (
            round(stop.y, 3),
            round(stop.x, 3),
            stop.parcel_number,
        ),
    )
    rows: List[Dict[str, Any]] = []
    for seq, stop in enumerate(ordered, start=1):
        rows.append(
            {
                "stop_order": seq,
                "item_id": stop.item_id,
                "parcel_number": stop.parcel_number,
                "land_use_code": stop.land_use_code,
                "address": stop.address,
                "lat": stop.lat,
                "lon": stop.lon,
                "eta_seconds": None,
            }
        )
    return rows


def _route_cluster(
    cluster: Dict[str, Any],
    *,
    router: OSRMClient,
    depot_lon: float,
    depot_lat: float,
) -> Dict[str, Any]:
    stops: List[StopRecord] = list(cluster["stops"])
    depot = (depot_lon, depot_lat)
    coords_for_matrix = [depot] + [(s.lon, s.lat) for s in stops] + [depot]
    durations, distances = router.table(coords_for_matrix)

    stop_order_indices = _solve_fixed_depot_order(durations, len(stops))
    ordered_stops = [stops[idx - 1] for idx in stop_order_indices]
    end_index = len(stops) + 1

    eta_seconds = 0.0
    current_index = 0
    ordered_stop_rows: List[Dict[str, Any]] = []
    for seq, matrix_idx in enumerate(stop_order_indices, start=1):
        eta_seconds += float(durations[current_index][matrix_idx] or 0.0)
        ordered_stop = stops[matrix_idx - 1]
        ordered_stop_rows.append(
            {
                "stop_order": seq,
                    "item_id": ordered_stop.item_id,
                    "parcel_number": ordered_stop.parcel_number,
                    "land_use_code": ordered_stop.land_use_code,
                    "address": ordered_stop.address,
                    "lat": ordered_stop.lat,
                "lon": ordered_stop.lon,
                "eta_seconds": int(round(eta_seconds)),
            }
        )
        current_index = matrix_idx

    estimated_duration_s = _matrix_path_cost(stop_order_indices, durations, end_index)
    estimated_distance_m = 0.0
    current_index = 0
    for matrix_idx in stop_order_indices:
        estimated_distance_m += float(distances[current_index][matrix_idx] or 0.0)
        current_index = matrix_idx
    estimated_distance_m += float(distances[current_index][end_index] or 0.0)

    route_coords = [depot] + [(stop.lon, stop.lat) for stop in ordered_stops] + [depot]
    route_detail = router.route(route_coords)

    return {
        "ordered_stops": ordered_stop_rows,
        "matrix_estimated_duration_s": round(estimated_duration_s, 1),
        "matrix_estimated_distance_m": round(estimated_distance_m, 1),
        "route_duration_s": round(float(route_detail["duration_s"]), 1),
        "route_distance_m": round(float(route_detail["distance_m"]), 1),
        "route_geometry": route_detail["geometry"],
    }


def create_route_plan(parcel_set: CoAppraiserParcelSet, *, mode: str) -> CoAppraiserRoutePlan:
    preset = get_mode_preset(mode)
    ready_count = CoAppraiserParcelSetItem.objects.filter(
        parcel_set=parcel_set, status=CoAppraiserParcelSetItem.STATUS_READY
    ).count()
    if ready_count == 0:
        raise CoAppraiserError("This parcel set has no valid parcels with geometry to cluster.")

    depot = _depot_config()
    routing_profile = str(preset.get("routing_profile") or "driving")

    depot_point = Point(float(depot["lon"]), float(depot["lat"]), srid=4326)
    plan = CoAppraiserRoutePlan.objects.create(
        parcel_set=parcel_set,
        mode=mode,
        routing_profile=routing_profile,
        status=CoAppraiserRoutePlan.STATUS_PENDING,
        target_stops=int(preset["target_stops"]),
        min_stops=int(preset["min_stops"]),
        max_stops=int(preset["max_stops"]),
        grid_cell_size_m=int(preset["grid_cell_size_m"]),
        depot_name=str(depot["name"]),
        depot_lat=float(depot["lat"]),
        depot_lon=float(depot["lon"]),
        depot_point_geog=depot_point,
        summary={},
        result={},
    )
    return plan


def run_route_plan(plan: CoAppraiserRoutePlan) -> CoAppraiserRoutePlan:
    plan = CoAppraiserRoutePlan.objects.select_related("parcel_set").get(id=plan.id)
    if plan.status == CoAppraiserRoutePlan.STATUS_COMPLETED:
        return plan

    parcel_set = plan.parcel_set
    ready_count = CoAppraiserParcelSetItem.objects.filter(
        parcel_set=parcel_set, status=CoAppraiserParcelSetItem.STATUS_READY
    ).count()
    if ready_count == 0:
        raise CoAppraiserError("This parcel set has no valid parcels with geometry to cluster.")
    allow_large_spopt = should_generate_plan_async(parcel_set)

    try:
        clusters = build_route_clusters(
            parcel_set,
            target_stops=plan.target_stops,
            min_stops=plan.min_stops,
            max_stops=plan.max_stops,
            grid_cell_size_m=plan.grid_cell_size_m,
            allow_large_spopt=allow_large_spopt,
        )

        routes: List[Dict[str, Any]] = []
        routed_stop_count = 0
        for day_number, cluster in enumerate(clusters, start=1):
            cluster_item_ids = [stop.item_id for stop in cluster["stops"]]
            geometry_artifacts = build_cluster_geometries(cluster_item_ids)
            cluster_grid_cells = build_cluster_grid_cell_bounds(cluster.get("seed_cells") or [])
            clustered_stops = _cluster_stops_for_display(cluster)
            routed_stop_count += len(clustered_stops)

            routes.append(
                {
                    "day_number": day_number,
                    "cluster_id": cluster["cluster_id"],
                    "cluster_backend": cluster.get("cluster_backend") or COAPPRAISER_CLUSTER_BACKEND_HEURISTIC,
                    "stop_count": len(clustered_stops),
                    "estimated_duration_s": None,
                    "estimated_distance_m": None,
                    "estimated_duration_label": "",
                    "estimated_distance_label": "",
                    "cluster_hull_geojson": geometry_artifacts.get("hull"),
                    "cluster_bounds_geojson": geometry_artifacts.get("bounds"),
                    "cluster_centroid_geojson": geometry_artifacts.get("centroid"),
                    "cluster_grid_cells": cluster_grid_cells,
                    "route_geojson": None,
                    "stops": clustered_stops,
                }
            )

        excluded_stop_count = max(0, parcel_set.found_count - routed_stop_count)
        result = {
            "mode": plan.mode,
            "plan_kind": "cluster_only",
            "routing_enabled": False,
            "routing_profile": plan.routing_profile,
            "cluster_backend": (routes[0].get("cluster_backend") if routes else COAPPRAISER_CLUSTER_BACKEND_HEURISTIC),
            "depot": {
                "name": plan.depot_name,
                "lat": plan.depot_lat,
                "lon": plan.depot_lon,
            },
            "params": {
                "target_stops": plan.target_stops,
                "min_stops": plan.min_stops,
                "max_stops": plan.max_stops,
                "grid_cell_size_m": plan.grid_cell_size_m,
            },
            "routes": routes,
            "summary": {
                "cluster_count": len(routes),
                "routed_stop_count": routed_stop_count,
                "excluded_stop_count": excluded_stop_count,
                "total_duration_s": None,
                "total_distance_m": None,
            },
        }

        plan.cluster_count = len(routes)
        plan.routed_stop_count = routed_stop_count
        plan.excluded_stop_count = excluded_stop_count
        plan.status = CoAppraiserRoutePlan.STATUS_COMPLETED
        plan.summary = result["summary"]
        plan.result = result
        plan.error_message = ""
        plan.save(
            update_fields=[
                "cluster_count",
                "routed_stop_count",
                "excluded_stop_count",
                "status",
                "summary",
                "result",
                "error_message",
                "updated_at",
            ]
        )
        parcel_set.mode_last_used = plan.mode
        parcel_set.save(update_fields=["mode_last_used", "updated_at"])
        return plan
    except Exception as exc:
        logger.exception("CoAppraiser route plan failed for parcel_set=%s plan=%s", parcel_set.id, plan.id)
        plan.status = CoAppraiserRoutePlan.STATUS_FAILED
        plan.error_message = str(exc)
        plan.save(update_fields=["status", "error_message", "updated_at"])
        raise


def generate_route_plan(parcel_set: CoAppraiserParcelSet, *, mode: str) -> CoAppraiserRoutePlan:
    plan = create_route_plan(parcel_set, mode=mode)
    return run_route_plan(plan)


def enqueue_route_plan_generation(plan: CoAppraiserRoutePlan) -> None:
    base_dir = Path(settings.BASE_DIR)
    manage_py = base_dir / "manage.py"
    if not manage_py.exists():
        raise CoAppraiserError(f"Unable to find manage.py at {manage_py}")

    logs_dir = base_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"coappraiser_route_worker_{plan.id}.log"
    cmd = [sys.executable, str(manage_py), "coappraiser_run_plan", "--plan-id", str(plan.id)]
    log_handle = None
    try:
        try:
            log_handle = open(log_path, "ab")
        except PermissionError:
            # Fallback so queueing still works even if file ownership is bad.
            log_handle = open(os.devnull, "ab")
        subprocess.Popen(
            cmd,
            cwd=str(base_dir),
            stdout=log_handle,
            stderr=log_handle,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:
        raise CoAppraiserError(f"Failed to queue route generation: {exc}") from exc
    finally:
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass

    logger.info(
        "CoAppraiser queued background route generation plan=%s parcel_set=%s cmd=%s",
        plan.id,
        plan.parcel_set_id,
        " ".join(cmd),
    )


def route_plan_export_rows(plan: CoAppraiserRoutePlan) -> List[List[Any]]:
    result = plan.result if isinstance(plan.result, dict) else {}
    routes = result.get("routes") if isinstance(result.get("routes"), list) else []
    rows: List[List[Any]] = []
    for route in routes:
        day_number = route.get("day_number")
        cluster_id = route.get("cluster_id")
        for stop in route.get("stops") or []:
            rows.append(
                [
                    day_number,
                    cluster_id,
                    stop.get("stop_order"),
                    stop.get("parcel_number"),
                    stop.get("address"),
                    stop.get("lat"),
                    stop.get("lon"),
                    stop.get("eta_seconds"),
                ]
            )
    return rows


def _find_route_in_result(result: Dict[str, Any], cluster_id: str) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
    routes = result.get("routes")
    if not isinstance(routes, list) or not routes:
        raise CoAppraiserError("Plan has no routes.")
    wanted = str(cluster_id or "").strip()
    if not wanted:
        raise CoAppraiserError("Route id is required.")
    for idx, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        if str(route.get("cluster_id") or "") == wanted:
            return routes, idx, route
    raise CoAppraiserError(f"Route '{wanted}' was not found in this plan.")


WEB_MERCATOR_MAX_LAT = 85.05112878
COAPPRAISER_PICTOMETRY_IMAGE_SERVICE_ID = "36AB6FD9-8DC8-3133-7871-1347FB79B3E8"
COAPPRAISER_PICTOMETRY_HISTORICAL_LAYER_ID = "PICT-WASKAG19-MJtGoV8oof"
COAPPRAISER_PICTOMETRY_CURRENT_LAYER_ID = "PICT-WASKAG25-qSfR3O1lit"


def _coappraiser_imagery_service_id() -> str:
    return str(
        getattr(settings, "COAPPRAISER_IMAGERY_SERVICE_ID", COAPPRAISER_PICTOMETRY_IMAGE_SERVICE_ID)
        or COAPPRAISER_PICTOMETRY_IMAGE_SERVICE_ID
    ).strip()


def _coappraiser_imagery_historical_layer_id() -> str:
    return str(
        getattr(settings, "COAPPRAISER_IMAGERY_HISTORICAL_LAYER_ID", COAPPRAISER_PICTOMETRY_HISTORICAL_LAYER_ID)
        or COAPPRAISER_PICTOMETRY_HISTORICAL_LAYER_ID
    ).strip()


def _coappraiser_imagery_current_layer_id() -> str:
    return str(
        getattr(settings, "COAPPRAISER_IMAGERY_CURRENT_LAYER_ID", COAPPRAISER_PICTOMETRY_CURRENT_LAYER_ID)
        or COAPPRAISER_PICTOMETRY_CURRENT_LAYER_ID
    ).strip()


def _coappraiser_imagery_historical_label() -> str:
    return str(getattr(settings, "COAPPRAISER_IMAGERY_HISTORICAL_LABEL", "2019") or "2019").strip()


def _coappraiser_imagery_current_label() -> str:
    return str(getattr(settings, "COAPPRAISER_IMAGERY_CURRENT_LABEL", "2025") or "2025").strip()


def _coappraiser_pictometry_base_url() -> str:
    return f"https://svc.pictometry.com/Image/{_coappraiser_imagery_service_id()}/wmts"


def _latlon_to_xyz_tile(lat: float, lon: float, z: int) -> Tuple[int, int]:
    clamped_lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, float(lat)))
    n = 2**z
    x_float = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(clamped_lat)
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    x = int(min(max(x_float, 0), n - 1))
    y = int(min(max(y_float, 0), n - 1))
    return x, y


def _coappraiser_pictometry_tile_url(layer_id: str, z: int, x: int, y: int) -> str:
    return f"{_coappraiser_pictometry_base_url()}/{layer_id}/default/GoogleMapsCompatible/{z}/{x}/{y}.png"


def _coappraiser_imagery_tile_margin_px() -> float:
    raw = getattr(settings, "COAPPRAISER_IMAGERY_TILE_MARGIN_PX", 16)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 16.0
    return max(0.0, min(value, 96.0))


def _project_lonlat_to_tile_pixels(lon: float, lat: float, *, z: int, x: int, y: int) -> Tuple[float, float]:
    clamped_lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, float(lat)))
    n = 2**int(z)
    x_float = (float(lon) + 180.0) / 360.0 * n
    lat_rad = math.radians(clamped_lat)
    y_float = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    pixel_x = (x_float - float(x)) * 256.0
    pixel_y = (y_float - float(y)) * 256.0
    return pixel_x, pixel_y


def _polygon_fits_tile(
    polygon_points: Sequence[Tuple[float, float]],
    *,
    z: int,
    x: int,
    y: int,
    margin_px: float,
) -> bool:
    if not polygon_points:
        return True
    pixel_points = [_project_lonlat_to_tile_pixels(lon, lat, z=z, x=x, y=y) for lon, lat in polygon_points]
    xs = [p[0] for p in pixel_points]
    ys = [p[1] for p in pixel_points]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    return (
        min_x >= margin_px
        and max_x <= (256.0 - margin_px)
        and min_y >= margin_px
        and max_y <= (256.0 - margin_px)
    )


def _polygon_points_from_geom_2926(geom_2926: Any) -> List[Tuple[float, float]]:
    if geom_2926 is None or getattr(geom_2926, "empty", True):
        return []
    try:
        geom_geog = geom_2926.transform(4326, clone=True)
    except Exception:
        return []
    if geom_geog is None or geom_geog.empty:
        return []

    polygon = None
    geom_type = str(getattr(geom_geog, "geom_type", "") or "")
    if geom_type == "Polygon":
        polygon = geom_geog
    elif geom_type == "MultiPolygon" and len(geom_geog):
        polygon = max((geom_geog[idx] for idx in range(len(geom_geog))), key=lambda g: float(getattr(g, "area", 0.0)))

    if polygon is None:
        return []
    try:
        ring = polygon.coords[0]
    except Exception:
        return []

    points: List[Tuple[float, float]] = []
    for coord in ring:
        if not isinstance(coord, (tuple, list)) or len(coord) < 2:
            continue
        lon = float(coord[0])
        lat = float(coord[1])
        if not math.isfinite(lon) or not math.isfinite(lat):
            continue
        if lat < -WEB_MERCATOR_MAX_LAT or lat > WEB_MERCATOR_MAX_LAT:
            continue
        points.append((lon, lat))
    return points


def _find_route_stop_index(route: Dict[str, Any], item_id: int) -> Optional[int]:
    stops = route.get("stops") or []
    for idx, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue
        try:
            stop_item_id = int(stop.get("item_id"))
        except (TypeError, ValueError):
            continue
        if stop_item_id == int(item_id):
            return idx
    return None


def _next_manual_imagery_stop(route: Dict[str, Any]) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    stops = route.get("stops") or []
    for idx, stop in enumerate(stops):
        if not isinstance(stop, dict):
            continue
        info = stop.get("imagery_change")
        if not isinstance(info, dict):
            return idx, stop
        status = str(info.get("status") or "")
        if status not in {"done", "error"}:
            return idx, stop
    return None, None


def _parcel_imagery_context(stop: Dict[str, Any]) -> Dict[str, Any]:
    item_id = stop.get("item_id")
    try:
        item_id_int = int(item_id)
    except (TypeError, ValueError):
        return {}

    parcel_id = (
        CoAppraiserParcelSetItem.objects.filter(id=item_id_int)
        .values_list("parcel_id", flat=True)
        .first()
    )
    if not parcel_id:
        return {}

    geom = (
        ParcelGeometry.objects.filter(parcel_id=parcel_id)
        .only("centroid_geog", "geom_2926")
        .first()
    )
    if geom is None:
        return {}

    center_lat = center_lon = None
    center_source = ""
    parcel_span_m = None
    polygon_points: List[Tuple[float, float]] = []
    geom_2926 = getattr(geom, "geom_2926", None)
    if geom_2926 is not None and not geom_2926.empty:
        polygon_points = _polygon_points_from_geom_2926(geom_2926)
        try:
            min_x, min_y, max_x, max_y = geom_2926.extent
            width_units = max(0.0, float(max_x) - float(min_x))
            height_units = max(0.0, float(max_y) - float(min_y))
            if width_units > 0.0 or height_units > 0.0:
                width_m = width_units * US_SURVEY_FOOT_TO_METER
                height_m = height_units * US_SURVEY_FOOT_TO_METER
                # Diagonal span better matches parcel fit for rotated/irregular polygons.
                parcel_span_m = math.hypot(width_m, height_m)

            center_x_2926 = (float(min_x) + float(max_x)) / 2.0
            center_y_2926 = (float(min_y) + float(max_y)) / 2.0
            center_point = Point(center_x_2926, center_y_2926, srid=2926)
            center_point.transform(4326)
            center_lon = float(center_point.x)
            center_lat = float(center_point.y)
            center_source = "bbox_center_2926"
        except (TypeError, ValueError):
            parcel_span_m = None
        except Exception:
            pass

    if not _is_numeric_coordinate(center_lat) or not _is_numeric_coordinate(center_lon):
        centroid = getattr(geom, "centroid_geog", None)
        if centroid is not None:
            try:
                center_lon = float(centroid.x)
                center_lat = float(centroid.y)
                center_source = "centroid_geog"
            except (TypeError, ValueError):
                center_lon = center_lat = None

    return {
        "center_lat": center_lat,
        "center_lon": center_lon,
        "parcel_span_m": parcel_span_m,
        "center_source": center_source,
        "polygon_points": polygon_points,
    }


def _imagery_zoom_for_parcel(
    lat: float,
    lon: Optional[float],
    polygon_points: Optional[Sequence[Tuple[float, float]]],
    parcel_span_m: Optional[float],
    *,
    default_z: int,
) -> int:
    min_zoom_raw = getattr(settings, "COAPPRAISER_IMAGERY_MIN_Z", 16)
    try:
        min_zoom = int(min_zoom_raw)
    except (TypeError, ValueError):
        min_zoom = 16
    min_zoom = max(0, min_zoom)
    max_zoom = int(default_z)
    if min_zoom > max_zoom:
        min_zoom = max_zoom

    if _is_numeric_coordinate(lon) and polygon_points:
        margin_px = _coappraiser_imagery_tile_margin_px()
        for candidate_z in range(max_zoom, min_zoom - 1, -1):
            tile_x, tile_y = _latlon_to_xyz_tile(float(lat), float(lon), int(candidate_z))
            if _polygon_fits_tile(
                polygon_points,
                z=int(candidate_z),
                x=int(tile_x),
                y=int(tile_y),
                margin_px=float(margin_px),
            ):
                return int(candidate_z)

    if parcel_span_m is None:
        return int(default_z)

    try:
        span_m = float(parcel_span_m)
    except (TypeError, ValueError):
        return int(default_z)
    if span_m <= 0:
        return int(default_z)

    fit_margin_raw = getattr(settings, "COAPPRAISER_IMAGERY_FIT_MARGIN", 2.4)
    try:
        fit_margin = float(fit_margin_raw)
    except (TypeError, ValueError):
        fit_margin = 2.4
    fit_margin = max(fit_margin, 1.1)

    min_span_raw = getattr(settings, "COAPPRAISER_IMAGERY_MIN_SPAN_M", 30.0)
    try:
        min_span_m = float(min_span_raw)
    except (TypeError, ValueError):
        min_span_m = 30.0
    min_span_m = max(min_span_m, 10.0)

    # Fit parcel span inside a single tile with margin for roofs, shadows, and slight center offsets.
    span_with_margin_m = max(span_m * fit_margin, min_span_m)
    clamped_lat = max(-WEB_MERCATOR_MAX_LAT, min(WEB_MERCATOR_MAX_LAT, float(lat)))
    meters_per_tile_at_equator = 40075016.68557849
    lat_factor = max(math.cos(math.radians(clamped_lat)), 1e-6)
    tile_width_at_z0_m = meters_per_tile_at_equator * lat_factor
    if tile_width_at_z0_m <= 0:
        return max(min_zoom, min(max_zoom, int(default_z)))

    raw_zoom = math.log2(tile_width_at_z0_m / span_with_margin_m)
    suggested_zoom = int(math.floor(raw_zoom))
    return max(min_zoom, min(max_zoom, suggested_zoom))


def _imagery_urls_for_stop(stop: Dict[str, Any]) -> Dict[str, Any]:
    lat = stop.get("lat")
    lon = stop.get("lon")
    if not _is_numeric_coordinate(lat) or not _is_numeric_coordinate(lon):
        return {
            "available": False,
            "message": "Parcel coordinates are unavailable for imagery preview.",
            "z": None,
            "x": None,
            "y": None,
            "historical": {
                "label": _coappraiser_imagery_historical_label(),
                "url": "",
            },
            "current": {
                "label": _coappraiser_imagery_current_label(),
                "url": "",
            },
        }

    lat_value = float(lat)
    lon_value = float(lon)
    context = _parcel_imagery_context(stop)
    if _is_numeric_coordinate(context.get("center_lat")) and _is_numeric_coordinate(context.get("center_lon")):
        lat_value = float(context["center_lat"])
        lon_value = float(context["center_lon"])

    base_z = _coappraiser_imagery_zoom()
    z = _imagery_zoom_for_parcel(
        lat_value,
        lon_value,
        context.get("polygon_points"),
        context.get("parcel_span_m"),
        default_z=int(base_z),
    )
    x, y = _latlon_to_xyz_tile(lat_value, lon_value, int(z))
    tight_z = min(int(z) + 1, 22)
    tight_x, tight_y = _latlon_to_xyz_tile(lat_value, lon_value, int(tight_z))
    wider_z = max(int(z) - 1, 0)
    wider_x, wider_y = _latlon_to_xyz_tile(lat_value, lon_value, int(wider_z))
    return {
        "available": True,
        "message": "",
        "lat": lat_value,
        "lon": lon_value,
        "z": int(z),
        "x": int(x),
        "y": int(y),
        "tight_z": int(tight_z),
        "tight_x": int(tight_x),
        "tight_y": int(tight_y),
        "wider_z": int(wider_z),
        "wider_x": int(wider_x),
        "wider_y": int(wider_y),
        "parcel_span_m": round(float(context["parcel_span_m"]), 1)
        if _is_numeric_coordinate(context.get("parcel_span_m"))
        else None,
        "historical": {
            "label": _coappraiser_imagery_historical_label(),
            "url": _coappraiser_pictometry_tile_url(_coappraiser_imagery_historical_layer_id(), int(z), int(x), int(y)),
            "tight_url": _coappraiser_pictometry_tile_url(
                _coappraiser_imagery_historical_layer_id(),
                int(tight_z),
                int(tight_x),
                int(tight_y),
            ),
            "wider_url": _coappraiser_pictometry_tile_url(
                _coappraiser_imagery_historical_layer_id(),
                int(wider_z),
                int(wider_x),
                int(wider_y),
            ),
        },
        "current": {
            "label": _coappraiser_imagery_current_label(),
            "url": _coappraiser_pictometry_tile_url(_coappraiser_imagery_current_layer_id(), int(z), int(x), int(y)),
            "tight_url": _coappraiser_pictometry_tile_url(
                _coappraiser_imagery_current_layer_id(),
                int(tight_z),
                int(tight_x),
                int(tight_y),
            ),
            "wider_url": _coappraiser_pictometry_tile_url(
                _coappraiser_imagery_current_layer_id(),
                int(wider_z),
                int(wider_x),
                int(wider_y),
            ),
        },
    }


def _manual_scan_status(route: Dict[str, Any], *, now_iso: str) -> Dict[str, Any]:
    scan = _refresh_route_scan_counts(route)
    total_count = int(scan.get("total_count") or 0)
    processed_count = int(scan.get("processed_count") or 0)
    if total_count <= 0:
        scan["status"] = "idle"
        scan["current_item_id"] = None
        scan["completed_at"] = None
    elif processed_count >= total_count:
        scan["status"] = "completed"
        scan["current_item_id"] = None
        scan["completed_at"] = now_iso
        if not scan.get("started_at"):
            scan["started_at"] = now_iso
    elif processed_count > 0 or scan.get("started_at"):
        scan["status"] = "in_progress"
        scan["current_item_id"] = None
        scan["completed_at"] = None
        if not scan.get("started_at"):
            scan["started_at"] = now_iso
    else:
        scan["status"] = "idle"
        scan["current_item_id"] = None
        scan["completed_at"] = None
    scan["updated_at"] = now_iso
    return scan


def _manual_imagery_modal_payload(route: Dict[str, Any], *, cluster_id: str, now_iso: str) -> Dict[str, Any]:
    scan = _manual_scan_status(route, now_iso=now_iso)
    _, stop = _next_manual_imagery_stop(route)
    if stop is None:
        return {
            "cluster_id": cluster_id,
            "is_complete": True,
            "current_stop": None,
            "scan": scan,
        }

    info = stop.get("imagery_change") if isinstance(stop.get("imagery_change"), dict) else {}
    manual_comment = str(info.get("manual_comment") or "").strip()
    flagged = bool(info.get("flagged"))
    status = str(info.get("status") or "")
    return {
        "cluster_id": cluster_id,
        "is_complete": False,
        "current_stop": {
            "item_id": stop.get("item_id"),
            "stop_order": stop.get("stop_order"),
            "parcel_number": stop.get("parcel_number"),
            "address": stop.get("address") or "",
            "lat": stop.get("lat"),
            "lon": stop.get("lon"),
            "imagery": _imagery_urls_for_stop(stop),
            "flagged": flagged,
            "manual_comment": manual_comment,
            "status": status,
            "saved_at": info.get("saved_at"),
            "checked_at": info.get("checked_at"),
        },
        "scan": scan,
    }


@transaction.atomic
def run_route_imagery_manual_modal_context(
    plan: CoAppraiserRoutePlan,
    *,
    cluster_id: str,
) -> Tuple[CoAppraiserRoutePlan, Dict[str, Any]]:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be reviewed.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = plan.result
    routes, route_index, route = _find_route_in_result(result, cluster_id)
    stops = route.get("stops")
    if not isinstance(stops, list):
        raise CoAppraiserError("Route stops payload is missing.")

    now_iso = timezone.now().isoformat(timespec="seconds")
    payload = _manual_imagery_modal_payload(route, cluster_id=cluster_id, now_iso=now_iso)
    routes[route_index] = route
    result["routes"] = routes
    plan.result = result
    plan.save(update_fields=["result", "updated_at"])
    return plan, payload


@transaction.atomic
def run_route_imagery_manual_draft(
    plan: CoAppraiserRoutePlan,
    *,
    cluster_id: str,
    item_id: int,
    flagged: bool,
    manual_comment: str,
) -> Tuple[CoAppraiserRoutePlan, Dict[str, Any]]:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be reviewed.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = plan.result
    routes, route_index, route = _find_route_in_result(result, cluster_id)
    stops = route.get("stops")
    if not isinstance(stops, list):
        raise CoAppraiserError("Route stops payload is missing.")

    stop_index = _find_route_stop_index(route, int(item_id))
    if stop_index is None:
        raise CoAppraiserError("Selected parcel was not found in this route.")

    now = timezone.now()
    now_iso = now.isoformat(timespec="seconds")
    stop = stops[stop_index]
    info = stop.get("imagery_change") if isinstance(stop.get("imagery_change"), dict) else {}
    note = str(manual_comment or "").strip()
    draft_payload = {
        **info,
        "status": "draft",
        "flagged": bool(flagged),
        "manual_comment": note,
        "brief_notes": _trim_notes(note) if note else ("Flagged for manual review." if flagged else ""),
        "review_mode": "manual",
        "saved_at": now_iso,
    }
    if "checked_at" in info:
        draft_payload["checked_at"] = info.get("checked_at")
    stop["imagery_change"] = draft_payload
    stops[stop_index] = stop
    route["stops"] = stops

    scan = _route_scan_state(route)
    if not scan.get("started_at"):
        scan["started_at"] = now_iso
    scan["status"] = "in_progress"
    scan["current_item_id"] = None
    scan["completed_at"] = None
    scan["updated_at"] = now_iso
    _refresh_route_scan_counts(route)

    routes[route_index] = route
    result["routes"] = routes
    plan.result = result
    plan.save(update_fields=["result", "updated_at"])
    return plan, {
        "item_id": int(item_id),
        "flagged": bool(flagged),
        "manual_comment": note,
        "saved_at": now_iso,
        "saved_at_label": timezone.localtime(now).strftime("%Y-%m-%d %H:%M:%S"),
    }


@transaction.atomic
def run_route_imagery_manual_continue(
    plan: CoAppraiserRoutePlan,
    *,
    cluster_id: str,
    item_id: Optional[int] = None,
    flagged: Optional[bool] = None,
    manual_comment: Optional[str] = None,
) -> Tuple[CoAppraiserRoutePlan, Dict[str, Any]]:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be reviewed.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = plan.result
    routes, route_index, route = _find_route_in_result(result, cluster_id)
    stops = route.get("stops")
    if not isinstance(stops, list):
        raise CoAppraiserError("Route stops payload is missing.")

    target_index = None
    if item_id is not None:
        target_index = _find_route_stop_index(route, int(item_id))
        if target_index is None:
            raise CoAppraiserError("Selected parcel was not found in this route.")
    if target_index is None:
        target_index, _ = _next_manual_imagery_stop(route)

    now_iso = timezone.now().isoformat(timespec="seconds")
    if target_index is not None:
        stop = stops[target_index]
        info = stop.get("imagery_change") if isinstance(stop.get("imagery_change"), dict) else {}
        if flagged is not None:
            info["flagged"] = bool(flagged)
        if manual_comment is not None:
            info["manual_comment"] = str(manual_comment or "").strip()
        flagged_value = bool(info.get("flagged"))
        note = str(info.get("manual_comment") or "").strip()
        info.update(
            {
                "status": "done",
                "flagged": flagged_value,
                "manual_comment": note,
                "brief_notes": _trim_notes(note)
                if note
                else ("Flagged for manual review." if flagged_value else "Reviewed manually."),
                "review_mode": "manual",
                "saved_at": now_iso,
                "checked_at": now_iso,
            }
        )
        stop["imagery_change"] = info
        stops[target_index] = stop
        route["stops"] = stops

    payload = _manual_imagery_modal_payload(route, cluster_id=cluster_id, now_iso=now_iso)
    routes[route_index] = route
    result["routes"] = routes
    plan.result = result
    plan.save(update_fields=["result", "updated_at"])
    return plan, payload


def _coappraiser_imagery_zoom() -> int:
    raw = getattr(settings, "COAPPRAISER_IMAGERY_CHANGE_Z", 19)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 19
    return min(max(value, 0), 22)


def _coappraiser_listing_model() -> str:
    return str(getattr(settings, "COAPPRAISER_LISTING_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash")


def _coappraiser_listing_site_hint() -> str:
    raw = str(getattr(settings, "COAPPRAISER_LISTING_SITE_HINT", "redfin") or "redfin").strip().lower()
    if raw in {"redfin", "zillow", "realtor", "any"}:
        return raw
    return "redfin"


def _route_scan_state(route: Dict[str, Any]) -> Dict[str, Any]:
    scan = route.get("imagery_scan")
    if isinstance(scan, dict):
        return scan
    total_count = len(route.get("stops") or [])
    scan = {
        "status": "idle",
        "processed_count": 0,
        "changed_count": 0,
        "total_count": total_count,
        "current_item_id": None,
        "error_count": 0,
        "started_at": None,
        "completed_at": None,
        "updated_at": None,
    }
    route["imagery_scan"] = scan
    return scan


def _route_listing_scan_state(route: Dict[str, Any]) -> Dict[str, Any]:
    scan = route.get("listing_scan")
    if isinstance(scan, dict):
        return scan
    total_count = len(route.get("stops") or [])
    scan = {
        "status": "idle",
        "processed_count": 0,
        "flagged_count": 0,
        "total_count": total_count,
        "current_item_id": None,
        "error_count": 0,
        "started_at": None,
        "completed_at": None,
        "updated_at": None,
    }
    route["listing_scan"] = scan
    return scan


def _refresh_route_scan_counts(route: Dict[str, Any]) -> Dict[str, Any]:
    scan = _route_scan_state(route)
    stops = route.get("stops") or []
    processed = 0
    changed = 0
    errors = 0
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        info = stop.get("imagery_change")
        if not isinstance(info, dict):
            continue
        status = str(info.get("status") or "")
        is_processed = status in {"done", "error"}
        if is_processed:
            processed += 1
        if is_processed and bool(info.get("flagged")):
            changed += 1
        if status == "error":
            errors += 1
    scan["total_count"] = len(stops)
    scan["processed_count"] = processed
    scan["changed_count"] = changed
    scan["error_count"] = errors
    return scan


def _refresh_route_listing_scan_counts(route: Dict[str, Any]) -> Dict[str, Any]:
    scan = _route_listing_scan_state(route)
    stops = route.get("stops") or []
    processed = 0
    flagged = 0
    errors = 0
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        info = stop.get("listing_check")
        if not isinstance(info, dict):
            continue
        status = str(info.get("status") or "")
        if status in {"done", "error", "skipped"}:
            processed += 1
        if bool(info.get("flagged")):
            flagged += 1
        if status == "error":
            errors += 1
    scan["total_count"] = len(stops)
    scan["processed_count"] = processed
    scan["flagged_count"] = flagged
    scan["error_count"] = errors
    return scan


def _trim_notes(text: Any, *, limit: int = 180) -> str:
    note = str(text or "").strip()
    if not note:
        return ""
    if len(note) <= limit:
        return note
    return note[: limit - 1].rstrip() + "…"


def _extract_listing_summary(payload: Dict[str, Any], *, status_code: int) -> Dict[str, Any]:
    payload_error = str(payload.get("error") or "").strip()
    if payload_error:
        if payload_error == "parcel_address_unavailable":
            return {
                "status": "skipped",
                "flagged": False,
                "listing_found": False,
                "listing_status": "unknown",
                "source_site": "unknown",
                "source_url": "",
                "summary": "Address unavailable for listing check.",
                "upgrade_signals": [],
                "analysis_status": payload_error,
            }
        return {
            "status": "error",
            "flagged": False,
            "listing_found": False,
            "listing_status": "unknown",
            "source_site": "unknown",
            "source_url": "",
            "summary": _trim_notes(payload_error),
            "upgrade_signals": [],
            "analysis_status": payload_error,
        }

    research = payload.get("listing_research")
    if not isinstance(research, dict):
        return {
            "status": "error",
            "flagged": False,
            "listing_found": False,
            "listing_status": "unknown",
            "source_site": "unknown",
            "source_url": "",
            "summary": "No listing payload returned.",
            "upgrade_signals": [],
            "analysis_status": "",
        }

    analysis_status = str(research.get("status") or "")
    parsed = research.get("parsed")
    if not isinstance(parsed, dict):
        parse_error = str(research.get("parse_error") or "").strip()
        if analysis_status == "ok" and parse_error:
            return {
                "status": "skipped",
                "flagged": False,
                "listing_found": False,
                "listing_status": "unknown",
                "source_site": "unknown",
                "source_url": "",
                "summary": "Listing response was unstructured; skipped.",
                "upgrade_signals": [],
                "analysis_status": "parse_unstructured",
            }

        notes = (
            research.get("error")
            or parse_error
            or analysis_status
            or f"HTTP {status_code}"
        )
        return {
            "status": "error",
            "flagged": False,
            "listing_found": False,
            "listing_status": "unknown",
            "source_site": "unknown",
            "source_url": "",
            "summary": _trim_notes(notes),
            "upgrade_signals": [],
            "analysis_status": analysis_status,
        }

    listing_found = bool(parsed.get("listing_found"))
    listing_status = str(parsed.get("listing_status") or "unknown").strip().lower() or "unknown"
    source_site = str(parsed.get("source_site") or "unknown").strip().lower() or "unknown"
    source_url = str(parsed.get("source_url") or "").strip()
    public_remarks = str(parsed.get("public_remarks") or "").strip()
    recent_upgrades = parsed.get("recent_upgrades_or_new_structures")
    other_signals = parsed.get("other_listing_signals")
    notes = parsed.get("notes")

    recent_items = [str(item).strip() for item in recent_upgrades or [] if str(item).strip()]
    other_items = [str(item).strip() for item in other_signals or [] if str(item).strip()]
    note_items = [str(item).strip() for item in notes or [] if str(item).strip()]

    keyword_text = " ".join([public_remarks, *recent_items, *other_items, *note_items]).lower()
    keyword_hit = any(
        token in keyword_text
        for token in ("addition", "new ", "newly", "remodel", "renovat", "adu", "outbuilding", "shop", "garage")
    )
    flagged = bool(recent_items or keyword_hit)

    summary = ""
    if recent_items:
        summary = "; ".join(recent_items[:2])
    elif other_items:
        summary = "; ".join(other_items[:2])
    elif note_items:
        summary = "; ".join(note_items[:2])
    elif public_remarks:
        summary = public_remarks
    elif listing_found:
        summary = f"Listing found ({listing_status})."
    else:
        summary = "No listing found."

    return {
        "status": "done",
        "flagged": flagged,
        "listing_found": listing_found,
        "listing_status": listing_status,
        "source_site": source_site,
        "source_url": source_url,
        "summary": _trim_notes(summary),
        "upgrade_signals": [_trim_notes(item, limit=120) for item in recent_items[:3]],
        "analysis_status": analysis_status,
        "match_confidence": parsed.get("match_confidence"),
    }


def _run_parcel_listing_check(parcel_number: str) -> Dict[str, Any]:
    # Local function call keeps this server-side and avoids extra HTTP hop overhead.
    from mcp_agent.views import _build_parcel_listing_payload

    payload, status = _build_parcel_listing_payload(
        parcel_number,
        gemini_model=_coappraiser_listing_model(),
        site_hint=_coappraiser_listing_site_hint(),
        include_raw=False,
    )
    if not isinstance(payload, dict):
        return {
            "status": "error",
            "flagged": False,
            "listing_found": False,
            "listing_status": "unknown",
            "source_site": "unknown",
            "source_url": "",
            "summary": f"Unexpected listing payload (HTTP {status}).",
            "upgrade_signals": [],
            "analysis_status": "",
        }
    return _extract_listing_summary(payload, status_code=int(status))


def _is_numeric_coordinate(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


@transaction.atomic
def run_route_driving_line(plan: CoAppraiserRoutePlan, *, cluster_id: str) -> CoAppraiserRoutePlan:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be routed.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = plan.result
    routes, route_index, route = _find_route_in_result(result, cluster_id)
    stops = route.get("stops")
    if not isinstance(stops, list):
        raise CoAppraiserError("Route stops payload is missing.")

    router_cfg = _router_config()
    profile = str(plan.routing_profile or "driving")
    router = OSRMClient(
        base_url=str(router_cfg["base_url"]),
        profile=profile,
        timeout_seconds=float(router_cfg["timeout_seconds"]),
    )
    max_coords = int(router_cfg.get("max_coords") or 0)
    now_iso = timezone.now().isoformat(timespec="seconds")

    valid_stops: List[Dict[str, Any]] = []
    invalid_stops: List[Dict[str, Any]] = []
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        if _is_numeric_coordinate(stop.get("lat")) and _is_numeric_coordinate(stop.get("lon")):
            valid_stops.append(dict(stop))
        else:
            invalid_stops.append(dict(stop))

    if not valid_stops:
        raise CoAppraiserError("No route stops have usable lat/lon coordinates.")
    if len(valid_stops) == 1:
        only = dict(valid_stops[0])
        only["stop_order"] = 1
        only["eta_seconds"] = 0
        route["stops"] = [only, *invalid_stops]
        route["stop_count"] = len(route["stops"])
        route["route_geojson"] = None
        route["estimated_duration_s"] = 0.0
        route["estimated_distance_m"] = 0.0
        route["estimated_duration_label"] = _format_duration(0.0)
        route["estimated_distance_label"] = _format_distance_m(0.0)
        route["routing_state"] = {
            "status": "done",
            "updated_at": now_iso,
            "message": "Single stop route; no driving line needed.",
        }
        routes[route_index] = route
        result["routes"] = routes
        result["routing_enabled"] = True
        plan.result = result
        plan.save(update_fields=["result", "updated_at"])
        return plan

    matrix_coords = [(float(plan.depot_lon), float(plan.depot_lat))]
    matrix_coords.extend((float(stop["lon"]), float(stop["lat"])) for stop in valid_stops)
    matrix_coords.append((float(plan.depot_lon), float(plan.depot_lat)))
    if max_coords > 0 and len(matrix_coords) > max_coords:
        raise CoAppraiserError(
            f"Route has {len(valid_stops)} stops; router limit is {max_coords - 2} stops per route."
        )

    durations, distances = router.table(matrix_coords)
    order_indices = _solve_fixed_depot_order(durations, len(valid_stops))
    end_index = len(valid_stops) + 1

    eta_seconds = 0.0
    current_index = 0
    ordered_stops: List[Dict[str, Any]] = []
    used_item_ids = set()
    for seq, matrix_idx in enumerate(order_indices, start=1):
        src = dict(valid_stops[matrix_idx - 1])
        eta_seconds += float(durations[current_index][matrix_idx] or 0.0)
        src["stop_order"] = seq
        src["eta_seconds"] = int(round(eta_seconds))
        ordered_stops.append(src)
        used_item_ids.add(src.get("item_id"))
        current_index = matrix_idx

    # Keep non-routable stops at the end so user can still see/edit them.
    next_order = len(ordered_stops) + 1
    for stop in invalid_stops:
        stop["stop_order"] = next_order
        stop["eta_seconds"] = None
        ordered_stops.append(stop)
        next_order += 1

    estimated_duration_s = _matrix_path_cost(order_indices, durations, end_index)
    estimated_distance_m = 0.0
    current_index = 0
    for matrix_idx in order_indices:
        estimated_distance_m += float(distances[current_index][matrix_idx] or 0.0)
        current_index = matrix_idx
    estimated_distance_m += float(distances[current_index][end_index] or 0.0)

    # Display route line excludes depot legs; map should show route over parcels only.
    map_route_coords = [(float(stop["lon"]), float(stop["lat"])) for stop in ordered_stops if _is_numeric_coordinate(stop.get("lon")) and _is_numeric_coordinate(stop.get("lat"))]
    route_geojson = None
    if len(map_route_coords) >= 2:
        if max_coords > 0 and len(map_route_coords) > max_coords:
            map_route_coords = map_route_coords[:max_coords]
        route_detail = router.route(map_route_coords)
        route_geojson = route_detail.get("geometry")

    route["stops"] = ordered_stops
    route["stop_count"] = len(ordered_stops)
    route["route_geojson"] = route_geojson
    route["estimated_duration_s"] = round(float(estimated_duration_s), 1)
    route["estimated_distance_m"] = round(float(estimated_distance_m), 1)
    route["estimated_duration_label"] = _format_duration(estimated_duration_s)
    route["estimated_distance_label"] = _format_distance_m(estimated_distance_m)
    route["routing_state"] = {
        "status": "done",
        "updated_at": now_iso,
        "message": "Driving line updated.",
    }

    routes[route_index] = route
    result["routes"] = routes
    result["routing_enabled"] = True
    summary = result.get("summary")
    if isinstance(summary, dict):
        durations_all = [float(r.get("estimated_duration_s")) for r in routes if r.get("estimated_duration_s") is not None]
        distances_all = [float(r.get("estimated_distance_m")) for r in routes if r.get("estimated_distance_m") is not None]
        summary["total_duration_s"] = round(sum(durations_all), 1) if durations_all else None
        summary["total_distance_m"] = round(sum(distances_all), 1) if distances_all else None
        result["summary"] = summary

    plan.result = result
    plan.save(update_fields=["result", "updated_at"])
    return plan


@transaction.atomic
def run_route_listing_scan_step(
    plan: CoAppraiserRoutePlan,
    *,
    cluster_id: str,
    reset: bool = False,
) -> CoAppraiserRoutePlan:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be scanned.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = plan.result
    routes, route_index, route = _find_route_in_result(result, cluster_id)
    stops = route.get("stops")
    if not isinstance(stops, list):
        raise CoAppraiserError("Route stops payload is missing.")

    now_iso = timezone.now().isoformat(timespec="seconds")
    scan = _route_listing_scan_state(route)
    if reset:
        for stop in stops:
            if isinstance(stop, dict) and "listing_check" in stop:
                stop.pop("listing_check", None)
        scan["status"] = "running"
        scan["started_at"] = now_iso
        scan["completed_at"] = None
        scan["current_item_id"] = None
    elif str(scan.get("status") or "") in {"completed", "failed"}:
        plan.result = result
        plan.save(update_fields=["result", "updated_at"])
        return plan
    else:
        scan["status"] = "running"
        if not scan.get("started_at"):
            scan["started_at"] = now_iso

    next_stop = None
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        info = stop.get("listing_check")
        if not isinstance(info, dict):
            next_stop = stop
            break
        if str(info.get("status") or "") not in {"done", "error", "skipped"}:
            next_stop = stop
            break

    if next_stop is None:
        _refresh_route_listing_scan_counts(route)
        scan["status"] = "completed"
        scan["current_item_id"] = None
        scan["completed_at"] = now_iso
        scan["updated_at"] = now_iso
        routes[route_index] = route
        result["routes"] = routes
        plan.result = result
        plan.save(update_fields=["result", "updated_at"])
        return plan

    parcel_number = str(next_stop.get("parcel_number") or "").strip().upper()
    stop_address = str(next_stop.get("address") or "").strip()
    item_id = next_stop.get("item_id")
    scan["current_item_id"] = item_id
    if not stop_address:
        summary = {
            "status": "skipped",
            "flagged": False,
            "listing_found": False,
            "listing_status": "unknown",
            "source_site": "unknown",
            "source_url": "",
            "summary": "Skipped listing check (no address).",
            "upgrade_signals": [],
            "analysis_status": "skipped_no_address",
        }
    else:
        try:
            summary = _run_parcel_listing_check(parcel_number)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "CoAppraiser listing-check failed plan=%s route=%s parcel=%s",
                plan.id,
                cluster_id,
                parcel_number,
            )
            summary = {
                "status": "error",
                "flagged": False,
                "listing_found": False,
                "listing_status": "unknown",
                "source_site": "unknown",
                "source_url": "",
                "summary": _trim_notes(f"Listing check failed: {exc}"),
                "upgrade_signals": [],
                "analysis_status": "request_failed",
            }

    summary["checked_at"] = now_iso
    next_stop["listing_check"] = summary

    _refresh_route_listing_scan_counts(route)
    if int(scan.get("processed_count") or 0) >= int(scan.get("total_count") or 0):
        scan["status"] = "completed"
        scan["completed_at"] = now_iso
    else:
        scan["status"] = "running"
    scan["current_item_id"] = None
    scan["updated_at"] = now_iso

    routes[route_index] = route
    result["routes"] = routes
    plan.result = result
    plan.save(update_fields=["result", "updated_at"])
    return plan


def _normalize_plan_route(route: Dict[str, Any], *, day_number: int) -> Dict[str, Any]:
    route["day_number"] = int(day_number)
    route["cluster_id"] = f"day-{int(day_number)}"
    normalized_stops: List[Dict[str, Any]] = []
    for idx, stop in enumerate(route.get("stops") or [], start=1):
        if not isinstance(stop, dict):
            continue
        stop_row = dict(stop)
        stop_row["stop_order"] = idx
        if "eta_seconds" not in stop_row:
            stop_row["eta_seconds"] = None
        normalized_stops.append(stop_row)
    route["stops"] = normalized_stops
    route["stop_count"] = len(normalized_stops)
    return route


def _refresh_plan_route_geometries(route: Dict[str, Any]) -> Dict[str, Any]:
    item_ids: List[int] = []
    for stop in route.get("stops") or []:
        try:
            item_ids.append(int(stop.get("item_id")))
        except (TypeError, ValueError):
            continue
    if item_ids:
        geometry_artifacts = build_cluster_geometries(item_ids)
        route["cluster_hull_geojson"] = geometry_artifacts.get("hull")
        route["cluster_bounds_geojson"] = geometry_artifacts.get("bounds")
        route["cluster_centroid_geojson"] = geometry_artifacts.get("centroid")
    else:
        route["cluster_hull_geojson"] = None
        route["cluster_bounds_geojson"] = None
        route["cluster_centroid_geojson"] = None
    # Grid cells are derived from seed cells and become stale after manual edits.
    route["cluster_grid_cells"] = []
    return route


@transaction.atomic
def move_plan_stop_to_route(
    plan: CoAppraiserRoutePlan,
    *,
    item_id: int,
    target_cluster_id: str,
) -> CoAppraiserRoutePlan:
    plan = CoAppraiserRoutePlan.objects.select_for_update().select_related("parcel_set").get(id=plan.id)
    if plan.status != CoAppraiserRoutePlan.STATUS_COMPLETED:
        raise CoAppraiserError("Only completed route plans can be edited.")
    if not isinstance(plan.result, dict):
        raise CoAppraiserError("Plan result is missing.")

    result = copy.deepcopy(plan.result)
    routes = result.get("routes")
    if not isinstance(routes, list) or not routes:
        raise CoAppraiserError("Plan has no routes to edit.")

    target_cluster_id = str(target_cluster_id or "").strip()
    if not target_cluster_id:
        raise CoAppraiserError("Choose a destination route.")

    source_route_idx = None
    source_stop_idx = None
    target_route_idx = None

    for route_idx, route in enumerate(routes):
        if not isinstance(route, dict):
            continue
        if str(route.get("cluster_id") or "") == target_cluster_id:
            target_route_idx = route_idx
        for stop_idx, stop in enumerate(route.get("stops") or []):
            try:
                stop_item_id = int(stop.get("item_id"))
            except (TypeError, ValueError):
                continue
            if stop_item_id == int(item_id):
                source_route_idx = route_idx
                source_stop_idx = stop_idx
                break
        if source_route_idx is not None and target_route_idx is not None:
            break

    if source_route_idx is None or source_stop_idx is None:
        raise CoAppraiserError("Parcel was not found in this route plan.")
    if target_route_idx is None:
        raise CoAppraiserError("Destination route was not found.")
    if source_route_idx == target_route_idx:
        raise CoAppraiserError("Parcel is already in that route.")

    source_route = routes[source_route_idx]
    target_route = routes[target_route_idx]
    source_stops = list(source_route.get("stops") or [])
    target_stops = list(target_route.get("stops") or [])

    moved_stop = source_stops.pop(source_stop_idx)
    target_stops.append(moved_stop)
    source_route["stops"] = source_stops
    target_route["stops"] = target_stops

    removed_source_route = False
    if not source_stops:
        routes.pop(source_route_idx)
        removed_source_route = True

    for idx, route in enumerate(routes, start=1):
        if not isinstance(route, dict):
            continue
        _normalize_plan_route(route, day_number=idx)

    if removed_source_route:
        for route in routes:
            if isinstance(route, dict):
                _refresh_plan_route_geometries(route)
    else:
        refresh_indexes = {source_route_idx, target_route_idx}
        for idx in refresh_indexes:
            if 0 <= idx < len(routes) and isinstance(routes[idx], dict):
                _refresh_plan_route_geometries(routes[idx])

    routed_stop_count = sum(int((route or {}).get("stop_count") or 0) for route in routes if isinstance(route, dict))
    excluded_stop_count = max(0, int(plan.parcel_set.found_count or 0) - routed_stop_count)

    result["routes"] = routes
    result["summary"] = {
        **(result.get("summary") if isinstance(result.get("summary"), dict) else {}),
        "cluster_count": len(routes),
        "routed_stop_count": routed_stop_count,
        "excluded_stop_count": excluded_stop_count,
    }
    result["summary"]["route_count"] = len(routes)

    plan.cluster_count = len(routes)
    plan.routed_stop_count = routed_stop_count
    plan.excluded_stop_count = excluded_stop_count
    plan.summary = result["summary"]
    plan.result = result
    plan.save(update_fields=["cluster_count", "routed_stop_count", "excluded_stop_count", "summary", "result", "updated_at"])
    return plan
