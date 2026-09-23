"""Drain address requests from score_inputs; only /ingest calls geocoder/register APIs."""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values
from psycopg.types.json import Jsonb

from ingest.building_register import RegisterClient, pnu_parts, record_pnu, text_id
from ingest.common import ROOT, RawStore, Settings
from ingest.database import connect_database
from ingest.geocode import parse_kakao, request_kakao, same_road_address
from ingest.seoul_transit import write_frame


def address_parcel(response, address):
    status, lng, lat = parse_kakao(response, address)
    if status != "success":
        if status in {"not_found", "ambiguous"}:
            return dict(status=status)
        raise ValueError("Geocoder did not verify the exact road address")
    item = response["documents"][0]
    parcel = item["address"]
    code = parcel["b_code"]
    main, sub = str(parcel["main_address_no"]), str(parcel["sub_address_no"] or "0")
    land = {"N": "1", "Y": "2"}.get(parcel["mountain_yn"])
    if not (
        len(code) == 10
        and code.isdigit()
        and code.startswith("11680")
        and main.isdigit()
        and sub.isdigit()
        and len(main) <= 4
        and len(sub) <= 4
        and land
    ):
        raise ValueError("Unverified Gangnam parcel components")
    pnu = code + land + main.zfill(4) + sub.zfill(4)
    return dict(
        status="ready",
        pnu=pnu,
        lng=lng,
        lat=lat,
        road=item["road_address"]["road_name"],
        number=item["road_address"]["main_building_no"]
        + (
            "-" + item["road_address"]["sub_building_no"]
            if item["road_address"]["sub_building_no"]
            else ""
        ),
    )


def number(value, *, positive=False):
    if value is None or not str(value).strip():
        return None
    n = float(value)
    if n < 0 or n != n or n == float("inf"):
        raise ValueError("Invalid register number")
    return n if not positive or n > 0 else None


def integer(value):
    n = number(value)
    if n is not None and not n.is_integer():
        raise ValueError("Expected register integer")
    return int(n) if n is not None else None


def normalize_register(parcel, titles, floors):
    if any(record_pnu(row) != parcel["pnu"] for row in titles + floors):
        raise ValueError("Register parcel differs from exact geocoder PNU")
    matching = [
        r
        for r in titles
        if str(r.get("mainAtchGbCd")) == "0"
        and same_road_address(r.get("newPlatPlc", ""), parcel["road"], parcel["number"], "강남구")
    ]
    if len(matching) != 1:
        return dict(status="not_found" if not titles else "ambiguous", payload={})
    title = matching[0]
    pk = text_id(title["mgmBldrgstPk"])
    height = number(title.get("heit"), positive=True)
    building = dict(
        id=None,
        pnu=parcel["pnu"],
        source="building_hub_address",
        location_basis="address",
        register_pk=pk,
        main_use=dict(
            code=title.get("mainPurpsCd"),
            name=title.get("mainPurpsCdNm"),
            other_use=title.get("etcPurps"),
        ),
        gross_area=number(title.get("totArea")),
        floors_above=integer(title.get("grndFlrCnt")),
        floors_below=integer(title.get("ugrndFlrCnt")),
        height_m=height,
        height_estimated=False,
        height_source="source" if height is not None else "unknown",
        elevators=dict(
            passenger=integer(title.get("rideUseElvtCnt")),
            emergency=integer(title.get("emgenUseElvtCnt")),
        ),
        estimated=False,
    )
    uses = [
        dict(
            floor_kind=r.get("flrGbCd"),
            floor_no=integer(r.get("flrNo")),
            use_code=r.get("mainPurpsCd"),
            use_name=r.get("mainPurpsCdNm"),
            other_use=r.get("etcPurps"),
            area_m2=number(r.get("area")),
            main_attached_code=r.get("mainAtchGbCd"),
        )
        for r in floors
        if text_id(r["mgmBldrgstPk"]) == pk
    ]
    return dict(status="ready", payload=dict(building=building, floors=uses))


def claim(db):
    # Commit before HTTP: concurrent workers cannot issue the same request.
    with db.transaction():
        row = db.execute("""update ingest_private.building_address_requests r
            set status='processing',started_at=clock_timestamp(),error_code=null
            where r.address=(select address from ingest_private.building_address_requests
              where status='pending' order by requested_at for update skip locked limit 1)
            returning address""").fetchone()
    return row[0] if row else None


def publish_raw(store, directory, address, response, titles, floors, snapshot, pnu):
    rows = [
        dict(
            operation="geocode",
            address=address,
            response_json=json.dumps(response, ensure_ascii=False),
        )
    ]
    for operation, records in [("getBrTitleInfo", titles), ("getBrFlrOulnInfo", floors)]:
        rows.extend(
            dict(
                operation=operation,
                address=address,
                response_json=json.dumps(r, ensure_ascii=False),
            )
            for r in records
        )
    path = directory / "address-register.parquet"
    write_frame(pd.DataFrame(rows), path)
    manifest = store.publish_revision(
        "address_building_" + (pnu or hashlib.sha256(address.encode()).hexdigest()),
        snapshot[:4] + "-" + snapshot[4:6],
        snapshot,
        path,
    )
    # Publication must be readable before the serving cache can become ready.
    location = (
        "s3://" + store.settings.r2_bucket + "/" + manifest["key"]
        if store.settings.uses_r2
        else str(store.settings.local_root / manifest["key"])
    )
    with store.connection() as c:
        c.read_parquet(str(path)).create_view("original")
        c.read_parquet(location).create_view("published")
        mismatch = c.execute("""select count(*) from (
          (select * from original except all select * from published) union all
          (select * from published except all select * from original))""").fetchone()[0]
        if mismatch:
            raise ValueError("Published address register differs")
    return manifest["key"]


def process_one(db, directory, *, geocoder=None, client_factory=None, store=None):
    if not db.autocommit:
        raise ValueError("Worker requires autocommit for durable claims")
    address = claim(db)
    if address is None:
        return None
    now = datetime.now(UTC)
    snapshot = now.strftime("%Y%m%dT%H%M%SZ")
    directory = Path(directory) / snapshot
    directory.mkdir(parents=True, exist_ok=True)
    try:
        if geocoder is None:
            env = {**dotenv_values(ROOT / ".env"), **os.environ}
            key = env.get("KAKAO_REST_API_KEY")
            if not key:
                raise ValueError("KAKAO_REST_API_KEY required")
            response = request_kakao(address, key)
        else:
            response = geocoder(address)
        (directory / "geocode.json").write_text(json.dumps(response, ensure_ascii=False))
        parcel = address_parcel(response, address)
        result, calls = dict(status=parcel["status"], payload={}), 0
        titles, floors = [], []
        if parcel["status"] == "ready":
            client = (
                client_factory(directory)
                if client_factory
                else RegisterClient(directory, now.date().isoformat(), request_limit=30)
            )
            titles = client.group("getBrTitleInfo", pnu_parts(parcel["pnu"]))
            floors = client.group("getBrFlrOulnInfo", pnu_parts(parcel["pnu"]))
            calls = client.request_count
            result = normalize_register(parcel, titles, floors)
        raw_key = publish_raw(
            store or RawStore(Settings.from_env()),
            directory,
            address,
            response,
            titles,
            floors,
            snapshot,
            parcel.get("pnu"),
        )
        with db.transaction():
            db.execute(
                """insert into ingest_private.building_address_cache
                (address,pnu,geom,status,payload,fetched_at,expires_at,raw_key)
                values(%s,%s,case when %s::float8 is not null then
                  extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326) end,
                  %s,%s,%s,%s+interval '30 days',%s)
                on conflict(address) do update set pnu=excluded.pnu,geom=excluded.geom,
                  status=excluded.status,payload=excluded.payload,fetched_at=excluded.fetched_at,
                  expires_at=excluded.expires_at,raw_key=excluded.raw_key""",
                (
                    address,
                    parcel.get("pnu"),
                    parcel.get("lng"),
                    parcel.get("lng"),
                    parcel.get("lat"),
                    result["status"],
                    Jsonb(result["payload"]),
                    now,
                    now,
                    raw_key,
                ),
            )
            db.execute(
                """update ingest_private.building_address_requests
                set status='done',finished_at=clock_timestamp() where address=%s""",
                (address,),
            )
        return dict(
            address=address,
            status=result["status"],
            pnu=parcel.get("pnu"),
            register_calls=calls,
            raw_key=raw_key,
        )
    except Exception as error:
        # Operational failure is not a negative address cache; explicit retry required.
        db.execute(
            """update ingest_private.building_address_requests set status='failed',
            finished_at=clock_timestamp(),error_code=%s where address=%s""",
            (type(error).__name__, address),
        )
        raise RuntimeError("Address worker failed; inspect private request status") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/ingest/building-address")
    parser.add_argument(
        "--watch", action="store_true", help="Poll on-demand queue every 30 seconds"
    )
    parser.add_argument(
        "--max-requests",
        type=int,
        default=10,
        help="Per-process address budget; restart deliberately after exhaustion",
    )
    args = parser.parse_args()
    if args.max_requests < 1 or args.max_requests > 100:
        parser.error("max-requests must be 1..100")
    with connect_database(local_only=True) as db:
        db.autocommit = True
        for _ in range(args.max_requests):
            while True:
                result = process_one(db, args.directory)
                if result is not None or not args.watch:
                    break
                time.sleep(30)
            if result is None:
                break
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
