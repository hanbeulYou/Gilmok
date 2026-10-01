import json
import os
import time
import uuid
from pathlib import Path

import psycopg
from playwright.sync_api import sync_playwright
from psycopg.types.json import Jsonb

OUT = Path(".local/compare-browser")
# Approved A0 / v0.3 addresses and coordinates; live RPCs supply all score inputs.
inputs = [
    {
        "key": "a",
        "candidate": {
            "lat": 37.5025721944737,
            "lng": 127.05758573871447,
            "floor": 3,
            "address": "서울특별시 강남구 역삼로 460",
        },
        "address_resolution": {"pnu": "1168010600109120013"},
    },
    {
        "key": "b",
        "candidate": {
            "lat": 37.497368428505624,
            "lng": 127.05516718391107,
            "floor": 2,
            "address": "서울특별시 강남구 도곡로 409",
        },
        "address_resolution": {"pnu": "1168010600109380022"},
    },
    {
        "key": "c",
        "candidate": {
            "lat": 37.50428792732002,
            "lng": 127.06287290714192,
            "floor": 3,
            "address": "서울특별시 강남구 역삼로 546",
        },
        "address_resolution": {"pnu": "1168010600109670000"},
    },
]
report = {
    "status": "running",
    "delay_enabled": not bool(os.environ.get("PROOF_SKIP_DELAY")),
    "scope": "realtime" if os.environ.get("PROOF_REALTIME_ONLY") else "all",
    "environment": os.environ.get("PROOF_TARGET", "local")
    + " real Postgres/Auth/Realtime/RPC + production React bundle + actual Worker",
    "checks": {},
}
users = []
addresses = []
if os.environ.get("PROOF_DB_URL") and os.environ.get("PROOF_ALLOW_REMOTE_FIXTURES") != "yes":
    raise RuntimeError(
        "Remote test fixtures require PROOF_ALLOW_REMOTE_FIXTURES=yes after operator approval"
    )
db = psycopg.connect(
    os.environ.get("PROOF_DB_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"),
    autocommit=True,
)


def check(name, value):
    assert value, name
    report["checks"][name] = True
    print("PASS", name, flush=True)


def make(c, alias, pnu=""):
    return {
        "alias": alias,
        "candidate": c,
        "selection": {"pnu": pnu},
        "location": {
            "status": "ready",
            "lat": c["lat"],
            "lng": c["lng"],
            "source_crs": "EPSG:4326",
            "coordinate_provider": "vworld",
            "reason": "juso_coordinate_key_pending",
            "source_x": c["lng"],
            "source_y": c["lat"],
        },
    }


def newaddr():
    a = f"서울특별시 강남구 역삼로 {100000 + uuid.uuid4().int % 800000}"
    exists = db.execute(
        "select exists(select 1 from ingest_private.building_address_cache where address=%s)",
        (a,),
    ).fetchone()[0]
    if exists:
        return newaddr()
    db.execute("insert into ingest_private.building_address_requests(address) values(%s)", (a,))
    addresses.append(a)
    return a


def ready(address):
    # Controlled cache fixture: only random test addresses, never an existing cache row.
    building = {
        "id": None,
        "register_pk": "verification",
        "location_basis": "address_cache",
        "main_use": {"code": "04", "name": "제2종근린생활시설", "other_use": None},
        "gross_area": 1000,
        "floors_above": 5,
        "floors_below": 1,
        "elevators": {"passenger": 1, "emergency": 0},
    }
    floors = [
        {
            "floor_no": 3,
            "floor_kind": "20",
            "use_name": "학원",
            "use_code": "10003",
            "other_use": "학원",
            "area_m2": 100,
        }
    ]
    db.execute(
        """insert into ingest_private.building_address_cache
 (address,pnu,geom,status,payload,fetched_at,expires_at)
 values(%s,'1168010600109120013',extensions.st_setsrid(extensions.st_makepoint(127.08,37.493),4326),
 'ready',%s,now(),now()+interval '30 days')
 on conflict(address) do update set status=excluded.status,payload=excluded.payload,
 fetched_at=excluded.fetched_at,expires_at=excluded.expires_at""",
        (address, Jsonb({"building": building, "floors": floors})),
    )


def row(page, id):
    return page.evaluate("(id)=>comparisonProof.state().candidates.find(r=>r.id===id)", id)


def waitready(page, id):
    page.wait_for_function(
        """(id)=>{const row=comparisonProof.state().candidates.find(r=>r.id===id);
 return row?.lookupStatus==="ready" && !row?.refreshing;}""",
        arg=id,
        timeout=25000,
    )


try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        pages = []
        frames_by_page = []
        errors = []
        requests = []
        rpc_failures = []

        def inspect_response(response):
            if "/rpc/" in response.url and response.status >= 400:
                data = response.json()
                failure = {
                    "rpc": response.url.split("/")[-1],
                    "status": response.status,
                    "code": data.get("code"),
                    "message": data.get("message"),
                }
                rpc_failures.append(failure)
                print("RPC failure", json.dumps(failure), flush=True)

        report["rpc_failures"] = rpc_failures
        for _ in range(2):
            context = browser.new_context(
                viewport={"width": 1440, "height": 1050}, reduced_motion="reduce"
            )
            context.add_init_script(
                """window.workerCalls=0;const W=window.Worker;window.Worker=class extends W{
 postMessage(...a){window.workerCalls++;return super.postMessage(...a)}}"""
            )
            page = context.new_page()
            frames = []
            frames_by_page.append(frames)

            def receive_frame(payload, captured=frames):
                try:
                    data = json.loads(payload)
                    envelope = data[4] if isinstance(data, list) else data.get("payload", {})
                    change = envelope.get("data", {})
                    if change.get("table") == "candidate_lookup_status":
                        captured.append(change.get("record", {}))
                except (ValueError, TypeError, IndexError):
                    pass

            page.on("websocket", lambda ws, handler=receive_frame: ws.on("framereceived", handler))
            page.on("response", inspect_response)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: requests.append(
                    {"url": r.url.split("?")[0], "body": r.post_data if "/rpc/" in r.url else None}
                ),
            )
            page.goto("http://127.0.0.1:4173")
            page.wait_for_function("window.comparisonProof")
            users.append(page.evaluate("comparisonProof.start()"))
            pages.append(page)
        a, b = pages
        shared, other = newaddr(), newaddr()
        pending = {"lat": 37.493, "lng": 127.08, "floor": 3, "address": shared}
        ida = a.evaluate("(v)=>comparisonProof.add(v)", make(pending, "pending-a"))
        idb = b.evaluate("(v)=>comparisonProof.add(v)", make(pending, "pending-b"))
        ra, rb = row(a, ida), row(b, idb)
        print("initial stages", [(r["stage"], r.get("error")) for r in [ra, rb]], flush=True)
        check(
            "initial_pending_score",
            ra["lookupStatus"] == "pending" and ra["result"]["total"] is not None,
        )
        aid, bid = ra["lookupRequestId"], rb["lookupRequestId"]
        check("opaque_request_id_per_uid", aid != bid)
        oid = b.evaluate("(s)=>comparisonProof.watch(s)", other)
        for page in pages:
            page.evaluate("(ids)=>{comparisonProof.observe(ids);}", [aid, bid, oid])
        for page in pages:
            page.wait_for_function('comparisonProof.states.includes("connected")', timeout=20000)
        visiblea = a.evaluate("comparisonProof.visible()")
        visibleb = b.evaluate("comparisonProof.visible()")
        check(
            "state_view_owner_rls",
            [x["request_id"] for x in visiblea] == [aid]
            and set(x["request_id"] for x in visibleb) == {bid, oid},
        )
        db.execute(
            "update ingest_private.building_address_requests "
            "set status='processing' where address=any(%s)",
            ([shared, other],),
        )
        for page in pages:
            page.wait_for_function(
                'comparisonProof.events.some(e=>e.status==="processing")', timeout=20000
            )
        b.wait_for_function(
            """(id)=>comparisonProof.events.some(e=>
 e.request_id===id&&e.status==="processing")""",
            arg=oid,
            timeout=20000,
        )
        check(
            "real_ws_two_uid_isolation",
            all(e["request_id"] == aid for e in a.evaluate("comparisonProof.events"))
            and all(e["request_id"] in [bid, oid] for e in b.evaluate("comparisonProof.events")),
        )
        check(
            "projection_only_three_fields",
            all(
                set(e) == {"request_id", "status", "updated_at"}
                for page in pages
                for e in page.evaluate("comparisonProof.events")
            ),
        )
        check(
            "raw_ws_payload_and_rls",
            all(frames_by_page)
            and all(
                set(row) == {"request_id", "status", "updated_at"}
                for frames in frames_by_page
                for row in frames
            )
            and all(row["request_id"] == aid for row in frames_by_page[0])
            and all(row["request_id"] in [bid, oid] for row in frames_by_page[1]),
        )
        before = len(requests)
        workers = a.evaluate("workerCalls") + b.evaluate("workerCalls")
        ready(shared)
        waitready(a, ida)
        waitready(b, idb)
        updated = row(a, ida)
        beforebuilding = next(x for x in ra["result"]["axes"] if x["key"] == "building")
        afterbuilding = next(x for x in updated["result"]["axes"] if x["key"] == "building")
        check(
            "pending_to_ready_no_reload",
            afterbuilding["normalized"] != beforebuilding["normalized"],
        )
        refresh = [r for r in requests[before:] if "/rpc/" in r["url"]]
        print(
            "refresh RPCs",
            [(r["url"].rsplit("/", 1)[-1], json.loads(r["body"]).get("radius_m")) for r in refresh],
            flush=True,
        )
        print(
            "changed sources",
            [
                k
                for k, v in updated["inputs"]["primary"]["meta"]["sources"].items()
                if ra["inputs"]["primary"]["meta"]["sources"].get(k) != v
            ],
            flush=True,
        )
        check(
            "ready_refresh_primary_only",
            len(refresh) == 2
            and all(
                r["url"].endswith("/score_inputs") and json.loads(r["body"])["radius_m"] == 800
                for r in refresh
            ),
        )
        check(
            "ready_reuses_worker", workers == a.evaluate("workerCalls") + b.evaluate("workerCalls")
        )
        report["pending_before_after"] = {
            "total": [ra["result"]["total"], updated["result"]["total"]],
            "confidence": [
                ra["result"]["confidence"]["value"],
                updated["result"]["confidence"]["value"],
            ],
        }
        count = len(a.evaluate("comparisonProof.events"))
        db.execute(
            "update public.candidate_lookup_status "
            "set status='pending',updated_at=updated_at-interval '1 hour' where request_id=%s",
            (aid,),
        )
        a.wait_for_timeout(1000)
        check(
            "out_of_order_real_event_ignored",
            len(a.evaluate("comparisonProof.events")) == count
            and row(a, ida)["lookupStatus"] == "ready",
        )
        lost = newaddr()
        lostid = a.evaluate(
            "(v)=>comparisonProof.add(v)", make({**pending, "address": lost}, "reconnect")
        )
        a.wait_for_timeout(1000)
        a.evaluate("comparisonProof.disconnect()")
        ready(lost)
        a.wait_for_timeout(700)
        check("disconnected_remains_pending", row(a, lostid)["lookupStatus"] == "pending")
        a.evaluate("comparisonProof.reconnect()")
        waitready(a, lostid)
        check("reconnect_recovers_ready", True)
        early = newaddr()
        earlyid = a.evaluate("(s)=>comparisonProof.watch(s)", early)
        ready(early)
        a.evaluate("(id)=>{comparisonProof.observe([id]);}", earlyid)
        a.wait_for_function(
            """(id)=>comparisonProof.events.some(e=>
 e.request_id===id&&e.status==="ready")""",
            arg=earlyid,
            timeout=20000,
        )
        check("ready_before_subscribe_reconciled", True)
        delay = newaddr()
        delayid = a.evaluate(
            "(v)=>comparisonProof.add(v)", make({**pending, "address": delay}, "three-minute")
        )
        start = time.monotonic()
        print("WAIT real 180s; optional matrix checks alongside", flush=True)
        if not os.environ.get("PROOF_REALTIME_ONLY"):
            for r in b.evaluate("comparisonProof.state().candidates"):
                b.evaluate("(id)=>comparisonProof.remove(id)", r["id"])
            for index, item in enumerate(inputs + inputs[:2]):
                b.evaluate(
                    "(v)=>comparisonProof.add(v)",
                    make(
                        item["candidate"],
                        f"{item['key']}-{index}",
                        item["address_resolution"]["pnu"],
                    ),
                )
            loading = b.evaluate(
                "comparisonProof.state().candidates.map(c=>({alias:c.alias,stage:c.stage,error:c.error,total:c.result?.total}))"
            )
            report["loading"] = loading
            print("loading", json.dumps(loading, ensure_ascii=False), flush=True)
            results = b.evaluate("comparisonProof.state().candidates.map(c=>c.result)")
            check("all_five_candidates_scored", all(result is not None for result in results))
            expected = [85.08500496915157, 93.3997327394482, 83.86448162784299]
            check(
                "v03_fixture_totals",
                all(abs(results[i]["total"] - expected[i]) < 1e-10 for i in range(3)),
            )
            report["scores"] = [
                {
                    "alias": inputs[i]["key"],
                    "total": results[i]["total"],
                    "confidence": results[i]["confidence"]["value"],
                    "axes": {x["key"]: x["normalized"] for x in results[i]["axes"]},
                }
                for i in range(3)
            ]
            b.locator(".desktop-matrix .candidate-name").first.click()
            desktop = b.locator(".evidence-panel").inner_text()
            totals = b.locator(".desktop-matrix [data-total]").evaluate_all(
                "(els)=>els.map(e=>e.dataset.total)"
            )
            axes = b.locator(".desktop-matrix [data-score]").evaluate_all(
                "(els)=>els.map(e=>e.dataset.score)"
            )
            b.screenshot(path=str(OUT / "desktop.png"))
            b.set_viewport_size({"width": 390, "height": 844})
            check("mobile_same_evidence", b.locator(".evidence-panel").inner_text() == desktop)
            b.get_by_role("tab", name="비교", exact=True).click()
            check(
                "mobile_same_totals",
                b.locator(".mobile-cards [data-total]").evaluate_all(
                    "(els)=>els.map(e=>e.dataset.total)"
                )
                == totals,
            )
            mobileaxes = b.locator(".mobile-cards [data-score]").evaluate_all(
                "(els)=>els.map(e=>e.dataset.score)"
            )
            check(
                "mobile_same_axes",
                mobileaxes == [axes[j * 5 + i] for i in range(5) for j in range(8)],
            )
            b.screenshot(path=str(OUT / "mobile.png"))
            b.set_viewport_size({"width": 1440, "height": 1050})
            before = len(requests)
            workers = b.evaluate("workerCalls")
            perf = b.evaluate("""async()=>{
     const slider=document.querySelector('#desktop-demand'),times=[];
     const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
     slider.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
     const order=comparisonProof.state().order.join();
     for(let i=0;i<100;i++){
      const t=performance.now();set.call(slider,String(i%41));
      slider.dispatchEvent(new Event('input',{bubbles:true}));
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      times.push(performance.now()-t);
      if(comparisonProof.state().order.join()!==order)throw Error('sort during drag');
     }
     slider.dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
     times.sort((a,b)=>a-b);
     return {samples:100,p50:times[49],p95:times[94],max:times[99],
      heap:performance.memory?.usedJSHeapSize,userAgent:navigator.userAgent,
      weight:comparisonProof.state().weights.demand};
    }""")
            report["slider"] = perf
            check("slider_p95_100ms", perf["p95"] <= 100 and perf["weight"] == 17)
            check(
                "slider_no_rpc_or_worker",
                len(requests) == before and workers == b.evaluate("workerCalls"),
            )
        delay_seconds = 181 if not os.environ.get("PROOF_SKIP_DELAY") else 0
        while time.monotonic() - start < delay_seconds:
            a.wait_for_timeout(min(20000, (delay_seconds - (time.monotonic() - start)) * 1000))
            print("delay elapsed", round(time.monotonic() - start), flush=True)
        if delay_seconds:
            check(
                "real_180s_delay_badge",
                a.locator(".desktop-matrix")
                .get_by_text("건물 정보 확인 지연 — 나중에 다시 열면 반영됩니다", exact=True)
                .is_visible(),
            )
        ready(delay)
        waitready(a, delayid)
        check("ready_after_delay_still_subscribed", True)
        check("no_browser_errors", not errors)
        report["browser_errors"] = errors
        report["status"] = "passed"
        browser.close()
finally:
    if report["status"] == "running":
        report["status"] = "failed"
    for address in addresses:
        db.execute("delete from app_private.candidate_lookup_watchers where address=%s", (address,))
        db.execute("delete from ingest_private.building_address_cache where address=%s", (address,))
        db.execute(
            "delete from ingest_private.building_address_requests where address=%s", (address,)
        )
    for uid in users:
        db.execute("delete from auth.users where id=%s", (uid,))
    db.close()
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("report written", flush=True)
