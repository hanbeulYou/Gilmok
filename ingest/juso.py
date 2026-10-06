"""Juso identity + replaceable coordinates; no DB writes or implicit retries.

The registration provider uses the same wire contract in lib/geo/address-provider.ts.
Only batch callers may persist this result in public.geocode_cache.
"""

import json
import math
import re
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

CONTRACT_VERSION = "1"
SEARCH_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
COORD_URL = "https://business.juso.go.kr/addrlink/addrCoordApi.do"
IDENTIFIERS = ("admCd", "rnMgtSn", "udrtYn", "buldMnnm", "buldSlno")
FIELDS = (*IDENTIFIERS, "mtYn", "lnbrMnnm", "lnbrSlno", "bdMgtSn",
          "roadAddrPart1", "jibunAddr", "bdNm", "rn", "sggNm", "emdNm")


def api_json(url, params):
    """Never propagate a keyed URL, response echo or provider error text to logs."""
    from ingest.geocode import GeocodeStopped

    if not params.get("confmKey"):
        raise GeocodeStopped("Juso key missing")
    try:
        with urlopen(url + "?" + urlencode(params), timeout=30) as response:
            return json.load(response)
    except Exception:
        raise GeocodeStopped("Juso transport failed; no automatic retry") from None


def request_search(address, key, *, page=1):
    return api_json(SEARCH_URL, dict(confmKey=key, currentPage=page, countPerPage=100,
                                    keyword=address, resultType="json"))


def results(data):
    from ingest.geocode import GeocodeStopped

    result = data["results"]
    if str(result["common"]["errorCode"]) != "0":
        raise GeocodeStopped("Juso business error; not an address miss")
    return result


def digits(value, width, *, positive=False):
    text = str(value)
    if not re.fullmatch(r"[0-9]{1," + str(width) + r"}", text):
        raise ValueError("Invalid Juso identifier")
    if positive and int(text) == 0:
        raise ValueError("Zero main parcel number")
    return text.zfill(width)


def selection(item):
    """Land numbers define PNU; road building numbers and underground flag do not."""
    result = {name: str(item[name]) if item.get(name) is not None else "" for name in FIELDS}
    adm = result["admCd"]
    if not re.fullmatch(r"[0-9]{10}", adm) or result["mtYn"] not in {"0", "1"}:
        raise ValueError("Invalid Juso land identity")
    if not re.fullmatch(r"[0-9]{25}", result["bdMgtSn"]):
        raise ValueError("Invalid Juso building identity")
    if not re.fullmatch(r"[0-9]{12}", result["rnMgtSn"]):
        raise ValueError("Invalid Juso road identity")
    if result["udrtYn"] not in {"0", "1"} or not result["roadAddrPart1"]:
        raise ValueError("Incomplete Juso road identity")
    digits(result["buldMnnm"], 5, positive=True)
    digits(result["buldSlno"], 5)
    result["pnu"] = (adm + ("2" if result["mtYn"] == "1" else "1")
                     + digits(result["lnbrMnnm"], 4, positive=True)
                     + digits(result["lnbrSlno"], 4))
    result["provider"] = "juso"
    return result


def parse_search(data):
    result = results(data)
    count = int(result["common"]["totalCount"])
    items = result.get("juso") or []
    if count < 0 or len(items) > count or (count == 0 and items):
        raise ValueError("Inconsistent Juso search count")
    return count, [selection(item) for item in items]


def matches_address(item, address):
    from ingest.geocode import same_road_address

    number = str(int(item["buldMnnm"]))
    if int(item["buldSlno"]):
        number += "-" + str(int(item["buldSlno"]))
    if same_road_address(address, item["rn"], number, item["sggNm"]):
        return True
    # Mountain parcels must explicitly retain 산; never treat them as ordinary land.
    parcel = ("산 " if item["mtYn"] == "1" else "") + str(int(item["lnbrMnnm"]))
    if int(item["lnbrSlno"]):
        parcel += "-" + str(int(item["lnbrSlno"]))
    return same_road_address(address, item["emdNm"], parcel, item["sggNm"])


def point(lng, lat):
    lng, lat = float(lng), float(lat)
    if not (math.isfinite(lng) and math.isfinite(lat) and 124 <= lng <= 132
            and 33 <= lat <= 39):
        raise ValueError("Invalid Korean coordinate")
    return lng, lat


class VworldCoordinates:
    """Temporary approved coordinate provider, validated against Juso's road identity."""

    provider = "vworld"

    def __init__(self, key, requester=None):
        from ingest.geocode import request_vworld

        self.key = key
        self.requester = requester or request_vworld

    def locate(self, item):
        from ingest.geocode import GeocodeStopped, parse_vworld

        if not self.key:
            raise GeocodeStopped("VWORLD_API_KEY required")
        try:
            raw = self.requester(item["roadAddrPart1"], self.key)
            status, lng, lat = parse_vworld(raw, item["roadAddrPart1"])
        except Exception:
            raise GeocodeStopped("Vworld coordinate request failed") from None
        if status != "success":
            return {"status": status, "coordinate_provider": self.provider}, raw
        lng, lat = point(lng, lat)
        return dict(status="ready", lng=lng, lat=lat, coordinate_provider=self.provider,
                    source_crs="EPSG:4326", source_x=lng, source_y=lat,
                    reason="juso_coordinate_key_pending"), raw


class JusoCoordinates:
    """Explicit opt-in after key/rollout approval; projection supplied by the caller."""

    provider = "juso"

    def __init__(self, key, project_5179, requester=api_json):
        self.key, self.project, self.requester = key, project_5179, requester

    def locate(self, item):
        raw = self.requester(COORD_URL, dict(confmKey=self.key, resultType="json",
                                           **{key: item[key] for key in IDENTIFIERS}))
        result = results(raw)
        items = result.get("juso") or []
        count = int(result["common"]["totalCount"])
        if count == 0 and not items:
            return dict(status="not_found", coordinate_provider=self.provider), raw
        if count != 1 or len(items) != 1:
            raise ValueError("Juso coordinate result not unique")
        coordinate = items[0]
        if coordinate.get("bdMgtSn") != item["bdMgtSn"]:
            raise ValueError("Juso coordinate building mismatch")
        x, y = float(coordinate["entX"]), float(coordinate["entY"])
        if not (math.isfinite(x) and math.isfinite(y) and x > 0 and y > 0):
            raise ValueError("Invalid Juso source coordinate")
        lng, lat = point(*self.project(x, y))
        return dict(status="ready", lng=lng, lat=lat, coordinate_provider=self.provider,
                    source_crs="EPSG:5179", source_x=x, source_y=y, reason=None), raw


def resolve_address(address, key, coordinates, *, search=request_search):
    """Exact batch selection. UI search returns choices and registers one explicitly."""
    raw = search(address, key)
    count, items = parse_search(raw)
    calls = {"juso_search": 1, "juso_coordinate": 0, "vworld_coordinate": 0}
    envelope = dict(contract_version=CONTRACT_VERSION, search_response=raw, call_counts=calls,
                    fetched_at=datetime.now(UTC).isoformat(), search_provider="juso")
    # Never infer uniqueness from a truncated result page.
    exact = [item for item in items if matches_address(item, address)]
    if not count:
        return dict(envelope, status="not_found")
    if count != len(items) or len(exact) > 1:
        return dict(envelope, status="ambiguous")
    if not exact:
        return dict(envelope, status="invalid")
    item = exact[0]
    calls[coordinates.provider + "_coordinate"] += 1
    location, coordinate_raw = coordinates.locate(item)
    return dict(envelope, status=location["status"], selection=item, location=location,
                coordinate_response=coordinate_raw)


def parse_geocode(envelope, address):
    """Validate trusted batch journals before persistence; never a public write API."""
    if envelope["contract_version"] != CONTRACT_VERSION:
        raise ValueError("Unsupported address provider contract")
    count, items = parse_search(envelope["search_response"])
    exact = [item for item in items if matches_address(item, address)]
    if count == 0:
        return "not_found", None, None
    if count != len(items) or len(exact) > 1:
        return "ambiguous", None, None
    if len(exact) != 1 or envelope.get("selection") != exact[0]:
        return "invalid", None, None
    if envelope["status"] != "ready":
        if envelope["status"] not in {"not_found", "invalid"}:
            raise ValueError("Invalid coordinate outcome")
        return envelope["status"], None, None
    location = envelope["location"]
    lng, lat = point(location["lng"], location["lat"])
    return "success", lng, lat


def request_address(address, key, *, coordinate_key):
    return resolve_address(address, key, VworldCoordinates(coordinate_key))

def batch_request_address(connection, address, key, coordinate_key):
    """Approved batch coordinates: Juso only, without a Vworld fallback."""

    def project(x, y):
        return connection.execute(
            """select extensions.st_x(p),extensions.st_y(p)
          from (select extensions.st_transform(extensions.st_setsrid(
          extensions.st_makepoint(%s,%s),5179),4326) p) s""",
            (x, y),
        ).fetchone()

    return resolve_address(address, key, JusoCoordinates(coordinate_key, project))
