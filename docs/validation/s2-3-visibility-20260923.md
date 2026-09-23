# S2-3 가시성 Worker 검증 — 2026-09-23

base: main. GitHub #13·#14 머지 후, 채점 명세 v0.1.4 / visibility_inputs v0.1 / score_inputs v1.3 / ScoreResult v0.1. 현장 검증은 사용자가 아래 대조표로 수행할 후속 작업이다.

## 결과

역삼로460 `(37.5025724504279,127.057585738094)`, 3층, 목표 높이 8.6m·눈높이 1.5m. **visible_ratio=0.11649874055415617 (11.649874%)**, visibility 점수 11.649874. 가시 가중치 30.833333333333336 ÷ 유효 가중치 264.6666666666667이다. 단순 가시 점 비율과 구별한다.

- 후보 도형 `shp:1980205023774444864800000000`을 식별하여 자기 차폐에서 제외했다. 이 사례에는 후보 도형 부재 −5가 없다.
- 1km 도형 3,558개(SHP 3,410·WFS 148), unknown 457개를 4m로 포함했다. 작은 부속건물도 차폐 대상에 남긴다.
- 최근접 역은 선릉역 분당선 대표점(`subway:1023`), 거리 816.55370856m다. 학교 대표점 11곳, 1km 조회범위는 적재된 강남구 경계 안이다.
- 역 동선은 **20점 중 가시 1점·차폐 10점·제외 9점**. 가시점은 후보에서 역으로 향하는 1번(동 −38.82m, 북 +12.65m)이다. footprint 내부·경계에 놓인 9점은 분모에서 제외했다.
- 링은 180점 중 가시 10·차폐 103·제외 67, 학교 동선은 110점 중 가시 7·차폐 57·제외 46이다.
- 주 반경 800m ScoreResult에 주입한 total=79.59896895595803, confidence=90. 임대료 미입력 −5, 인구 추정 −5다. 실제 학원 순위 검증은 아니다.

[역 20점·링 36방향 × 5반경 전체 대조표](s2-3-visibility-field-report.md) · [확대 가능한 평면 그림](s2-3-visibility-field-report.svg) · [310개 샘플 및 ScoreResult JSON](s2-3-visibility-results.json) · [시간·소스·해시 JSON](s2-3-visibility-summary.json).

## 검산과 시간

- 합성 벽 하나: h=7m은 차폐 2점·가중치 4, 전체 가중치 162로 79/81. h=9m은 차폐 85점으로 19/36. 기대값을 구현에서 생성하지 않고 상수로 비교했다.
- 실제 샘플 310개의 가시/차폐/제외를 PostGIS ST_Intersection/LineLocatePoint로 독립 계산했다. 불일치 **0**, ST_ClosestPoint로 대조한 후보 도형 경계 목표점 오차 **0m**.
- 브라우저의 실제 module Worker와 Node 순수 함수 결과는 모든 샘플·근거를 포함해 완전히 같다. 잘못된 CRS 요청 거부 후 정상 요청 복구도 확인했다.
- 환경: Apple M5 Pro, Node v22.22.0, Headless Chrome 153.0.0.0. Worker 최초 실행은 따로 기록하고, 각 환경 준비 3회 후 30회 측정, p95는 정렬 29번째다. 실행별 원자료는 summary JSON에 보존한다.

| 구간 | 중앙값 | p95 | 최댓값 |
|---|---:|---:|---:|
| Node 순수 계산 | 15.906ms | 16.957ms | 17.092ms |
| Worker 순수 계산 | 14.550ms | 18.000ms | 21.300ms |
| Worker 메시지 왕복 | 21.150ms | 25.700ms | 28.200ms |

최초 Worker 계산 42.9ms, 최초 메시지 왕복 98.0ms. 메시지 왕복에는 직렬화·기동·수신 비용이 포함되며 순수 계산과 구별한다. visibility_inputs HTTP 왕복 290.252ms, 직접 DB 클라이언트 왕복 255.520ms는 각각 단회 관측이며 DB 내부 실행 p95가 아니다. HTTP와 직접 DB의 입력 응답은 동일하다. 기존 기준 분포 snapshot 20260923T111436Z를 사용했다.

## 코드·호환·검증

신규 RPC 1개만 추가했다. public 데이터 RLS의 anon/authenticated 읽기를 검증했고 쓰기는 거부된다. 구 buildings_in_radius 결과 불변과 모든 도형의 5186 변환 오차 <1μm를 테스트했다. geometry의 수치 오차 허용치는 1μm이며 건물 버퍼가 아니다. source availability가 false이면 visibility는 missing, 정상 0건은 0건으로 처리한다.

`pnpm lint`, `pnpm typecheck`, `pnpm test`(Vitest 63·Python 234), `pnpm test:db`(144) 통과. 후보 도형 제외·구멍·오목 도형·MultiPolygon·높이 경계·WFS/unknown·가중치/분모·순수성·신뢰도 −5 및 슬라이더 불변성·Worker 요청 대응을 확인했다. 실제 입력 재조회 전후 DB 테스트는 트랜잭션을 롤백해 적재 데이터를 보존했다.

## 호출과 재현

새 Worker는 `workers/visibility.worker.ts`이며 bundler에서 `new Worker(new URL('../workers/visibility.worker.ts', import.meta.url), {type:'module'})` 형태로 연결할 수 있다(호출 파일 위치에 맞춰 상대경로 조정). 호출자는 Supabase에서 받은 DTO에 floor를 붙이고 `createVisibilityClient(worker).request(scene)`를 사용한다. requestId를 현재 요청 ID와 비교해 이전 후보/층의 응답을 버린다. 응답 result를 기존 `score(..., result, candidate, preset, reference, context)` visibility 인자에 넣는다. Worker마다 client 한 개를 쓰고 종료 시 client.dispose()와 worker.terminate()를 호출한다. 순수 함수는 Node에서 computeVisibility(scene)를 직접 부른다.

```sh
supabase migration up --local
pnpm visibility:build
uv run --frozen python -m ingest.verify_visibility
uv run --frozen python -m ingest.verify_visibility_geometry
```

실제 브라우저 검증은 별도 터미널에서 로컬 정적 서버를 실행한 뒤 다음 명령을 쓴다. 브라우저 실행파일은 세 번째 인자로 지정할 수 있고 기본값은 macOS Chrome이다. 브라우저 프로필은 검증용 임시 디렉터리이며 종료 시 정리한다.

```sh
python3 -m http.server 8765 --bind 127.0.0.1
# 별도 터미널
node ingest/verify_visibility_browser.mjs \
  http://127.0.0.1:8765/tests/visibility/worker-harness.html \
  .local/validation/s2-3/browser.json
```

원본 입력은 `.local/validation/s2-3/input.json`, 조회 장면은 scene.json이다. 저장된 result와 browser.result 전체 JSON을 비교하면 Node/Worker 동등성을 재검증할 수 있다. 기존 소스가 갱신되면 과거 결과를 덮어쓰는 대신 새로운 snapshot 증거를 남긴다.

## 한계와 다음 작업

현장 대조 전 모델 출력이다. 역 출입구·학교 정문·실제 보행 경로·지형은 없다. 직선 동선이 건물 안을 지나 제외된 점을 도로로 이동시키지 않았다. 범위 밖 역 동선/건물 적재 경계는 근거에 남기며 자동 반경 확대·높이 보정은 하지 않는다. 건물 없는 후보의 좌표 fallback은 자기 차폐 미반영 코드와 신뢰도 −5를 적용한다.

외부 데이터 API는 호출하지 않았고 로컬 Supabase의 기존 적재 데이터만 조회했다. 후보 도형 부재 감점은 사용자 결정이며 실응답에서 유도한 규칙이 아니다. 원격 전환·UI·서울 전체 건물 적재·S2-4 실제 학원 순위 검증과 임대료 보정은 실행하지 않았다. 현장 대조 의견은 S2-4 검증으로 이어간다.
