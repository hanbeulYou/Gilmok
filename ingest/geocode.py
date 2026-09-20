"""Batch-only geocoding: durable claims and positive/negative address caches."""

import argparse
import hashlib
import json
import math
import os
import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.database import connect_database


class GeocodeStopped(RuntimeError):
    """Operational error, not proof that an address cannot be located."""


def normalize_address(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value or "").split())


def same_road_address(address, road, number, district):
    """Only whitespace may differ; reject corrections to road or building number."""
    if not all([road, number, district]) or district not in address:
        return False
    road_pattern = r"\s*".join(re.escape(c) for c in road)
    pattern = r"(?<![가-힣A-Za-z0-9])" + road_pattern + r"\s*" + re.escape(number)
    return re.search(pattern + r"(?:번지)?(?![0-9가-힣A-Za-z-])", address) is not None


def parse_kakao(data, address=None):
    count = data["meta"]["total_count"]
    documents = data["documents"]
    if count == 0 and not documents:
        return "not_found", None, None
    if count != 1 or len(documents) != 1:
        return "ambiguous", None, None
    item = documents[0]
    # REGION/ROAD centroids are not a building location.
    if item.get("address_type") not in {"ROAD_ADDR", "REGION_ADDR"}:
        return "invalid", None, None
    if address is not None:
        road = item.get("road_address") or {}
        number = road.get("main_building_no", "")
        sub = road.get("sub_building_no", "")
        if sub and sub != "0":
            number += "-" + sub
        road_match = same_road_address(
            address, road.get("road_name"), number, road.get("region_2depth_name")
        )
        parcel = item.get("address") or {}
        parcel_number = parcel.get("main_address_no", "")
        if parcel.get("sub_address_no") not in {None, "", "0"}:
            parcel_number += "-" + parcel["sub_address_no"]
        parcel_match = parcel.get("mountain_yn") != "Y" and same_road_address(
            address,
            parcel.get("region_3depth_name"),
            parcel_number,
            parcel.get("region_2depth_name"),
        )
        if not (road_match or parcel_match):
            return "invalid", None, None
    x, y = float(item["x"]), float(item["y"])
    if not (math.isfinite(x) and math.isfinite(y) and 124 <= x <= 132 and 33 <= y <= 39):
        return "invalid", None, None
    return "success", x, y


def request_kakao(address, key):
    query = urlencode({"query": address, "size": 30, "analyze_type": "exact"})
    request = Request(
        "https://dapi.kakao.com/v2/local/search/address.json?" + query,
        headers={"Authorization": "KakaoAK " + key},
    )
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise GeocodeStopped("Unexpected geocoder HTTP status")
        return json.load(response)


def parse_vworld(data, address=None):
    response = data["response"]
    if response["status"] == "NOT_FOUND":
        return "not_found", None, None
    if response["status"] != "OK":
        raise GeocodeStopped("Vworld operational error; not an address failure")
    result = response["result"]
    structure = response["refined"]["structure"]
    if result["crs"].upper() != "EPSG:4326" or not structure.get("level5"):
        return "invalid", None, None
    address = address or response["input"]["address"]
    if not same_road_address(
        address, structure.get("level4L"), structure.get("level5"), structure.get("level2")
    ):
        return "invalid", None, None
    point = result["point"]
    return parse_kakao(
        {
            "meta": {"total_count": 1},
            "documents": [{"address_type": "ROAD_ADDR", "x": point["x"], "y": point["y"]}],
        }
    )


def request_vworld(address, key):
    query = urlencode(
        {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "address": address,
            "refine": "true",
            "simple": "false",
            "format": "json",
            "type": "road",
            "key": key,
        }
    )
    with urlopen("https://api.vworld.kr/req/address?" + query, timeout=30) as response:
        return json.load(response)


def save_result(connection, address, provider, data):
    """Also permits explicit recovery from a saved response without calling either API."""
    status, x, y = (parse_kakao if provider == "kakao" else parse_vworld)(data, address)
    with connection.transaction():
        connection.execute(
            "insert into public.geocode_cache(address,provider,geom,geocode_failed,"
            "failure_reason,source,source_version) values (%s,%s,"
            "case when %s::float8 is null then null else "
            "extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326) end,%s,%s,%s,%s)",
            (
                address,
                provider,
                x,
                x,
                y,
                status != "success",
                None if status == "success" else status,
                provider + "_address",
                datetime.now(UTC).date().isoformat(),
            ),
        )
        connection.execute(
            "update ingest_private.geocode_requests set status=%s where address=%s and provider=%s",
            (status, address, provider),
        )
    return status


def cached(connection, address, provider="kakao"):
    return connection.execute(
        "select geocode_failed, extensions.st_x(geom), extensions.st_y(geom), "
        "failure_reason from public.geocode_cache where address=%s and provider=%s",
        (address, provider),
    ).fetchone()


def resolve_one(connection, address, *, key, budget, journal, requester=None, provider="kakao"):
    """Connection must be autocommit: claim commits BEFORE the HTTP request."""
    if not connection.autocommit:
        raise ValueError("Geocoding requires durable autocommit claims")
    if provider not in {"kakao", "vworld"}:
        raise ValueError("Unsupported geocoder")
    requester = requester or (request_kakao if provider == "kakao" else request_vworld)
    address = normalize_address(address)
    if not address:
        raise ValueError("Empty address")
    with connection.transaction():
        connection.execute("select pg_advisory_xact_lock(7412401)")
        if cached(connection, address, provider) is not None:
            return "cached"
        if connection.execute(
            "select 1 from ingest_private.geocode_requests where address=%s and provider=%s",
            (address, provider),
        ).fetchone():
            raise GeocodeStopped("Existing unresolved claim; inspect journal, never auto-retry")
        used = connection.execute(
            "select count(*) from ingest_private.geocode_requests where provider=%s "
            "and attempted_at >= (date_trunc('day',now() at time zone 'Asia/Seoul') "
            "at time zone 'Asia/Seoul')",
            (provider,),
        ).fetchone()[0]
        if used >= budget:
            raise GeocodeStopped("Daily request budget reached")
        connection.execute(
            "insert into ingest_private.geocode_requests(address,provider,status) "
            "values (%s,%s,'pending')",
            (address, provider),
        )
    try:
        data = requester(address, key)
        # Save successful HTTP responses before parsing/DB completion for manual crash recovery.
        (journal / provider).mkdir(parents=True, exist_ok=True)
        path = journal / provider / (hashlib.sha256(address.encode()).hexdigest() + ".json")
        path.write_text(json.dumps({"address": address, "response": data}, ensure_ascii=False))
        (parse_kakao if provider == "kakao" else parse_vworld)(data, address)
    except Exception as error:
        blocked = isinstance(error, HTTPError) and error.code in {401, 403, 429}
        connection.execute(
            "update ingest_private.geocode_requests set status=%s,error_code=%s "
            "where address=%s and provider=%s",
            (
                "blocked" if blocked else "unknown",
                str(error.code) if isinstance(error, HTTPError) else type(error).__name__,
                address,
                provider,
            ),
        )
        raise GeocodeStopped(
            "Geocoder stopped; inspect request status (no address failure)"
        ) from None
    return save_result(connection, address, provider, data)


def run(addresses, *, budget, journal, workers=4):
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    key = env.get("KAKAO_REST_API_KEY")
    if not key:
        raise ValueError("KAKAO_REST_API_KEY required")
    addresses = sorted({normalize_address(a) for a in addresses} - {""})
    stop = threading.Event()
    lock = threading.Lock()
    counts = {}

    def worker(part):
        with connect_database(local_only=True) as connection:
            connection.autocommit = True
            for address in part:
                if stop.is_set():
                    return
                try:
                    status = resolve_one(
                        connection, address, key=key, budget=budget, journal=journal
                    )
                except Exception:
                    stop.set()
                    raise
                with lock:
                    counts[status] = counts.get(status, 0) + 1
                    if sum(counts.values()) % 250 == 0:
                        print(json.dumps(counts), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(worker, [addresses[i::workers] for i in range(workers)]))
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("addresses", type=Path, help="JSON array of source base addresses")
    parser.add_argument(
        "--budget", type=int, required=True, help="Local daily cap; not account quota"
    )
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument(
        "--vworld-budget", type=int, help="Explicit local daily cap for NOT_FOUND-only fallback"
    )
    args = parser.parse_args()
    if not 1 <= args.budget <= 100000:
        parser.error("budget must be between 1 and 100000")
    if args.vworld_budget is not None and not 1 <= args.vworld_budget <= 1000:
        parser.error("vworld-budget must be between 1 and 1000")
    input_addresses = json.loads(args.addresses.read_text())
    print(
        json.dumps(run(input_addresses, budget=args.budget, journal=args.journal)),
        flush=True,
    )
    if args.vworld_budget is not None:
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        if not env.get("VWORLD_API_KEY"):
            raise ValueError("VWORLD_API_KEY required for fallback")
        with connect_database(local_only=True) as connection:
            connection.autocommit = True
            addresses = connection.execute(
                "select address from public.geocode_cache where provider='kakao' "
                "and failure_reason='not_found' and address=any(%s) order by address",
                (sorted({normalize_address(a) for a in input_addresses} - {""}),),
            ).fetchall()
            counts = {}
            for (address,) in addresses:
                status = resolve_one(
                    connection,
                    address,
                    key=env["VWORLD_API_KEY"],
                    budget=args.vworld_budget,
                    journal=args.journal,
                    provider="vworld",
                )
                counts[status] = counts.get(status, 0) + 1
            print("vworld", json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
