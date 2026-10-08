# S3-4 계획 — 건물 3D·노출 오버레이

2026-10-08 · **계획 승인 완료, P0(#34) main 머지·P1 구현/검증 중**. 브랜치 `s3/building-3d`, base `origin/main ec72095`.

2026-10-08 [#33](https://github.com/hanbeulYou/Gilmok/pull/33) main 머지(`6ff6ba9`)와 사용자 계획 승인을 확인했다. **D1~D6 모두 추천안으로 확정**했다. P0를 먼저 구현하고, P0 머지 후 P1에 착수한다. P1 원격 migration push는 최종 dry-run 보고 후 별도 승인을 받는다.

기준: `AGENTS.md`, [기획서](location-simulator.md), [screens §4.3~4.5·§4.8·§8](screens.md), [S3-3의 S3-4 진입 조건](s3-3-plan.md#15-b-완료와-s3-3-마감), [scoring v0.4.0 §5.5](scoring-spec.md), [데이터 소스](data-sources.md). S3-3 [M](../validation/s3-3-model-20261007.md)·[A](../validation/s3-3-a-20261007.md)·[B](../validation/s3-3-b-20261007.md) 검증과 [v0.4.0 검증](../validation/scoring-v040-20261007.md)을 따른다. B 검증·인계 문서는 #32를 통해 main에 반영됐다.

## 1. 범위와 완료 기준

screens §8의 완료 기준은 **“역삼로 460 3층에서 32/108 가시점이 지도 위 방향과 일치, 데스크톱 60fps 근접”**이다. 사용자가 승인한 범위는 다음과 같다.

- 건물 3D 익스트루전, 선택 후보 층의 목표 높이, 2D/3D 토글 애니메이션.
- 선택 후보의 `ExposureOverlay`: 20/40/60m 링·108개 샘플의 가시/차폐/제외·이동 표시, 차폐 건물 강조, 샘플 선택과 근거 패널 연동.
- 비가중 가시점 수, 거리 가중 visible_ratio, 주목도 Y 적용 점수를 서로 다른 값으로 표시.
- 건물 높이 원천/추정/미상을 구분하고 강남구 적재 범위·부분 결측을 화면에 표시.
- 3D 미진입 시 **추가 3D 모듈·deck.gl·표시용 좌표 RPC 요청0**, 초기/2D 번들 예산 유지.
- CI 슬라이더 측정을 회귀 감지와 production 엄격 판정으로 분리하는 소형 변경.

채점 명세·가중치·원시 판정·RPC scene/model0.2.2·주목도 Y는 그대로다. terrain/가로수/간판/실제 보행 경로 추정, 서울 전체 건물 적재, 업종 프리셋 변경은 포함하지 않는다. **학원 점 레이어는 S3-4 직후 첫 후속 과제**다. 공개 전 Small 전환·2uid+연속5채점 재시험 조건과 D5/익명 정리 운영값도 바꾸지 않는다.

## 2. 확인한 현재 계약과 자료

### 채점·캐시

`lib/compare/load-candidate.ts`의 `CandidateInputs.scene`은 `exposure_inputs_v022` 결과에 후보 floor를 붙인 EPSG:5186 scene이다. `lib/visibility/browser.ts`는 실제 Worker의 전체 result를 반환하지만 `ExposureInput` 타입은 채점용 최소 필드만 드러낸다. `CandidateInputs.exposure`에는 런타임상 샘플·summary가 남아 있어 **새 시각화용 타입/접근 경로를 명시**할 필요가 있다. 저장된 비교를 다시 열 때는 기존 로딩/채점을 통해 캐시를 복구하며, DB 저장 payload에 전체 건물·샘플을 추가하지 않는다.

`SampleResult`에는 안정적인 `id`, `group`, `bearing_deg`, `radius_m`, `point`, `original_point`, `moved_m`, `target`, `building_id`, `status`가 있다. `building_id`는 현재 순수 계산기의 `.find()`가 기록한 차폐 건물이며 **광선상 가장 가까운 건물이라는 보장은 없다**. UI에서 “최초 차폐 건물”이라고 바꾸어 부르지 않는다. 후보 외벽 목표 XY는 관측 샘플마다 달라질 수 있다.

### 로컬 읽기 전용 실측

2026-10-08 기존 로컬 DB에서 `exposure_inputs_v022(lat => ..., lng => ...)`를 조회했다. 쓰기·원격 호출·migration은 하지 않았다. JSON 크기는 Python의 compact UTF-8 직렬화로, HTTP 압축 전송량이나 새 RPC 성능이 아니다.

| 후보 | 건물 수 | 도형 꼭짓점 수 | scene JSON bytes | 높이 source / floors_estimate / unknown | 전체1.23km / 점수 링 적재 범위 |
|---|---:|---:|---:|---|---|
| a 역삼로460 | 4,693 | 47,145 | 2,656,408 | 2,961 / 948 / 784 | 밖으로 걸침 / 안 |
| b 도곡로409 | 4,431 | 45,793 | 2,558,192 | 2,730 / 872 / 829 | 안 / 안 |
| c 역삼로546 | 3,843 | 36,250 | 2,084,902 | 2,469 / 821 / 553 | 밖으로 걸침 / 안 |

a 좌표는 `(lat=37.5025721944737, lng=127.05758573871447)`, b는 `(37.497368428505624,127.05516718391107)`, c는 `(37.50428792732002,127.06287290714192)`다. 4,693개는 **scene 전체 수**이며 줌17의 실제 화면 내 건물 수가 아니다. 위 높이 개수는 scene 전체이며 소형/부속 등을 제외하는 신뢰도 계산의 분모가 아니다. 원천 갱신 시 수를 새로 기록하며 성능 때문에 원천·범위·해상도를 줄이지 않는다.

S3-3 B의 production 5후보 슬라이더 p95/max는34.1/48.6ms, 지도 JS/CSS gzip207.34/9.64KiB, #29 대비 초기 셸+3.15KiB였다. #32 PR의 CI 이력은 같은 제품 코드에서50.1/126.8/66.7ms였고, 126.8ms 실행은 실패했다. 환경 변동 원인은 확정되지 않았으며 이를 제품 성능 개선의 증거로 쓰지 않는다.

#33의 단일 p95 116.8ms 실패는 사용자 확인에 따라 CI 러너 변동으로 기록한다(점수 정상). 이번 P0에서 재조사하거나 과거 실행을 소급 통과 처리하지 않는다.
## 3. 렌더러 선택 — D1

| 선택지 | 장점 | 비용·한계 | 판단 |
|---|---|---|---|
| **MapLibre fill-extrusion + deck.gl 샘플** | 기존 MapLibre 인스턴스/카메라/픽킹 재사용. 건물과 샘플 역할을 분리하고 screens §4.4와 일치 | deck와 같은 depth buffer를 쓰는 interleaved 검증 필요 | **추천** |
| deck.gl `PolygonLayer`/`GeoJsonLayer` extruded + 샘플 | 건물·샘플을 같은 deck 레이어 체계로 다룸 | 기존 지도 위 추가 메시 생성·픽킹·라이프사이클 작업, 번들/메모리 실측 필요. 명세의 건물 fill-extrusion 문구 변경 필요 | 성능/호환성 실측에서 추천안이 실패할 때 재제안 |
| MapLibre만 사용 | deck 의존성 없음 | 현재4.7.1에서 관측점1.5m·외벽 목표 Z를 가진 샘플 레이어를 단순 circle로 동등하게 구현했다고 볼 수 없음. custom WebGL은 이번 규모를 키움 | 비추천 |

MapLibre4.7.1은 유지하고 P2에서 `@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/mapbox` **동일9.x 정확 버전**을 고정한다. 확인 기준 버전은9.1.14이며, 설치 전에 peer/lockfile·라이선스·실제 MapLibre4.7.1 상호 차폐를 확인한다. `deck.gl` 전체 패키지·React 지도 래퍼·별도 투영 라이브러리는 추가하지 않는다. 최신 문서의 `MapLibreOverlay`로 조용히 갈아타지 않고 AGENTS의 **MapboxOverlay** 계약을 따른다.

[deck.gl9.1.14 공식 문서](https://github.com/visgl/deck.gl/blob/v9.1.14/docs/developer-guide/base-maps/using-with-maplibre.md)는 WebGL2/MapLibre>3에서 MapboxOverlay interleaved 구성을 안내한다. [해당 구현](https://github.com/visgl/deck.gl/blob/v9.1.14/modules/mapbox/src/mapbox-overlay.ts)과 [MapLibre fill-extrusion 명세](https://maplibre.org/maplibre-style-spec/layers/#fill-extrusion)를 기준으로 검증한다. 이 문서 확인이 실제 앱의 호환성/FPS 통과를 뜻하지 않는다.

배경 OpenFreeMap 스타일의 기존 fill-extrusion은 계속 제외한다. 원천 높이를 가진 **우리 scene 건물만** 3D로 올려 이중 건물·높이 충돌을 막는다. 기존 OpenFreeMap/OpenMapTiles/OSM 출처와 건물 원천 출처를 보존한다.

## 4. 좌표와 데이터 경로 — D2

### 추천: 캐시 도형을 그대로 투영하는 표시 전용 RPC 1개

원본 Worker 판정은5186미터, 지도 GeoJSON은4326이다. 5186 차이를 경위도 차이로 선형 근사하거나 `METER_OFFSETS`에 그대로 넣지 않는다.

`project_exposure_geometry(items jsonb)`(가칭)를 **새 read-only 함수**로 제안한다. 3D 첫 진입에 캐시 scene의 Polygon/MultiPolygon, 필요한 Point/LineString만 id와 함께 보내고, PostGIS `ST_Transform`으로5186→4326 변환한 같은 id/순서의 geometry를 받는다. 높이·가시/차폐·estimated·score는 클라이언트 원본에서 결합한다. DB의 최신 건물 도형을 다시 찾아 붙이지 않으므로 **채점 시점 scene과 표시 도형이 섞이지 않는다**. 주소·임대료·uid·근거 원문은 전송 payload에 넣지 않는다.

- 새로운 테이블/캐시/트리거·행 쓰기 없음. `SECURITY INVOKER`, 빈 `search_path`, 객체 스키마 명시, authenticated만 EXECUTE. 함수는 입력 도형 변환만 수행한다.
- 입력은5186·출력4326 고정. Point/LineString/Polygon/MultiPolygon과 finite 좌표·폐합·유효 도형·허용 범위를 검증한다. 제안 상한은 요청8MiB·10,000개 item·200,000개 꼭짓점. 초과 시 명시적인 표시 오류이며 일부 건물을 조용히 버리지 않는다. P1 시작 시 현재 scene 전수 최대와 대조해 부족하면 구현/상한 변경 전에 보고한다.
- 후보 좌표는 기존4326 값을 그대로 유지한다. 샘플 XY·목표 XY·링은5186에서 정의한 좌표를 변환하고 Z(관측1.5m/목표 높이)는 미터 메타데이터로 따로 유지한다.
- 원점·네 방위·홀·MultiPolygon·모든 a/b/c 도형의 역변환 오차≤0.01m, 샘플 id/순서/상태 불변을 독립 SQL과 대조한다. WGS84의 나열 순서는 `[lng,lat]`다.
- 표시용 RPC 왕복의 비용은 남는다. a/b/c의 request/response bytes, 새 연결 첫 호출, warm 직접 SQL30회 p95/max, authenticated HTTP와 첫3D-ready 시간을 분리 기록한다. 기존 DB 기준 warm p95<1,000ms를 제안한다. 원격 쓰기 전 dry-run·승인 절차를 따른다.

대안은 **로컬 정식 좌표 변환 라이브러리**를 3D chunk에 넣는 방식이다. 네트워크 왕복은 줄지만 AGENTS의 지도 라이브러리 제한에 대한 별도 예외 승인·번들·정밀도 검증이 필요하다. 수기 역투영 공식을 새로 구현하는 안은 이번에는 권하지 않는다. 원격 HTTP body 상한/413 응답은 아직 검증하지 않았으며 로컬/원격 실증에서 확인한다. 추천 RPC의 실제 전송/지연이 문제가 되면 수치와 함께 이 대안을 다시 제안한다. [PostGIS 변환 의미](https://postgis.net/docs/ST_Transform.html)를 따른다.

### 재사용·수명

- `CandidateInputs`에 시각화용 `VisibilityResult` 접근을 타입으로 보장하되 ScoreResult/채점 입력 계약은 유지한다. `samples`가 없는 fixture/옛 캐시는 “시각화 자료 없음/계산 중”이며 가짜108점을 만들지 않는다.
- 원천 scene+좌표+도형 fingerprint로 변환 캐시를 구분한다. 샘플 결과는 후보ID·floor·generation·scene fingerprint에 묶는다. 같은 건물 층 전환에서 건물 변환은 재사용할 수 있지만 **층은 결과 키에서 빠지면 안 된다**.
- 3D 표시를 위한 추가 레이캐스트/채점 RPC를 만들지 않는다. 기존 채점 흐름이 결과를 완성하면 구독하여 표시한다. 가중치 슬라이더·카메라 이동·샘플 hover는 Worker를 실행하지 않는다.
- 전환 요청 동시1개, 이전 선택의 늦은 응답은 폐기/취소. 좌표 변환 캐시는 최근2개 scene까지만 메모리에 보관하고 후보 제거·uid 변경·라우트 이탈 시 정리한다. 채점용 scene 적재 범위는 줄이지 않는다.

## 5. 3D 화면·높이·적재 한계

3D 버튼은 지도 내부에 둔다. 2D 카메라(center/zoom/bearing)를 보관하고, 3D 진입 시 선택 후보 기준 zoom17·pitch0→55°를 약600ms easeTo로 전환한다. 2D 복귀는 보관한 뷰로 돌린다. reduced-motion은 즉시 전환한다. 빠른 연속 토글·선택 변경은 이전 애니메이션을 취소하고 Map 인스턴스를 추가 생성하지 않는다. 현재 `maxPitch:0`/회전 제한은 모드에 맞게 조정하며 2D 북쪽 기준 동작을 복구한다. [4.7.1 카메라 구현](https://github.com/maplibre/maplibre-gl-js/blob/v4.7.1/src/ui/camera.ts)을 확인한 뒤 실제 전환을 검증한다.

3D 준비 중에는 2D·매트릭스·저장을 계속 사용할 수 있다. 실패/없는 WebGL2/지원하지 않는 GPU에서는 오류·재시도·2D 복귀를 제공하며 점수를 새로 계산하거나0으로 바꾸지 않는다. DOM 후보 마커/묶음 층 목록과 selectedId는 S3-3 것을 유지한다.

| 높이 상태 | 화면과 근거 |
|---|---|
| `height_source=source` | 원천 높이 Xm, 기본 채색 |
| `floors_estimate`, `estimated=true` | 추정 높이 Xm(층수 기반), 별도 채색·범례·툴팁 |
| `unknown`, `estimated=true` | **높이 미상 · 표시/차폐4m 가정**, 추정과도 구분하는 채색·범례 |

WFS를 포함하고 소형/부속/창고를 표시/차폐에서 임의로 빼지 않는다. 표시 높이는 `scene.height_m`을 그대로 쓴다. 새 높이 추정·단순화·terrain/해발 보정은 하지 않는다. 색만으로 정보를 전달하지 않으며 건물 선택 시 높이 출처/estimated를 텍스트로 확인한다.

지도 고정 안내는 **“건물 3D 자료: 강남구 적재분”**이다. `coverage.query_within_loaded_region=false`이면 “주변 반경 일부의 건물 자료가 없습니다”를 병기한다. `score_ring_within_loaded_region=false/미확인`이면 “건물 자료 범위 밖 — 노출 평가 불가”로 기존 exposure 결측과 연결한다. 전체 반경 일부 결측과 점수용90m 적재 범위를 구분해 a/c를 무조건 평가 불가로 만들지 않는다. 강남구 밖의 빈 지도는 “건물 없음”이 아니다. 서울 밖·원천 미적재·관측0건도 구분하고 배경 타일 건물로 결측을 채우지 않는다.

## 6. ExposureOverlay와 근거 연동 — D3

### 판정과 위치

- ring 그룹108개만 점수 오버레이로 사용한다. EPSG:5186 격자축의 북=0°·동=90°·시계방향10° 간격, 원래 반경20/40/60m를 보존한다. 현재 `generateSamples`를 재사용하며 지도의 화면 x/y나4326 진북 방위로 점을 다시 생성하지 않는다.
- 가시는 밝은 초록, 차폐는 어두운 빨강. 이동 점에는 테두리와 원래 위치→최종 위치 표시/툴팁을 둔다. 최종 `point`가 명목 링 밖이어도 원래 weight100/d를 유지한다. 제외는 회색 구분과 제외 이유/비율을 표시하고 차폐로 합산하지 않는다. 제외 원래 위치를 분석 표식으로 표시할 때 광선을 그리지 않는다.
- `ScatterplotLayer` 관측 높이1.5m, 선택 샘플의 **실제 `target`**에 목표 마커를 둔다. 목표 Z는 지상 `(floor−1)×3.3+2.0`, 지하2.0m다. 샘플 미선택 상태에서 하나의 임의 외벽 목표점을 만들어 공통 목표로 쓰지 않는다.
- 차폐 건물은 blocked 샘플의 `building_id` 집합과 조인해 강조하고 선택 샘플의 기록된 건물은 더 강하게 표시한다. 선택 광선은 sample→target을 연결하되 저장되지 않은 충돌 교차점을 추정해서 표시하지 않는다. 후보 자체는 차폐 집합에서 제외된다.
- 후보 도형이 없으면 target은 후보 좌표이고 기존 `candidate_footprint_missing_self_occlusion_unaccounted`/신뢰도−5 근거를 유지한다. 지도도 “후보 도형 없음 · 자기 건물 차폐 미반영”을 표시한다.
- deck는 interleaved depth를 사용한다. 색은 **후보 간판에 대한 가시 판정**이며 현재 카메라에서 보이는지와 다르다. 건물 뒤의 분석점이 현재 시점에서 가려질 수 있으므로 수치/키보드 목록에는 전체108개를 유지한다. 색을 보여주려고 높이를 임의로 올리거나 카메라 가림을 새로운 차폐 판정으로 쓰지 않는다.

### 반드시 분리할 숫자

| 역삼로460 3층 | 표시 | 의미 |
|---|---|---|
| 비가중 | **가시32 / 생성108 · 차폐76 · 제외0** | 점 개수. 20m20/36, 40m8/36, 60m4/36 |
| 거리 가중 | **visible_ratio 0.383838383838 (38.383838%)** | 유효 링의 Σ(가시×100/d) / Σ(100/d), 단순32/108과 다름 |
| 주목도/점수 | **3층 Y0.8 → exposure30.707071점** | 모델 가정. ratio×Y×100. 사용자 조정 exposure 축 가중치와도 다름 |

분모0/자료 결측은 NULL로 표시한다. 제외가 있으면 생성/유효/제외 수 및 count·weight 제외 비율을 함께 표시한다. Y로 점 색·차폐 건물·원래 ratio를 바꾸지 않는다. Y는1층1.0/2층0.9/3층0.8/4층+0.7, 지하0.8이다. 지하는 **“지하: 입구 간판 기준 노출”**을 표시하며 R7−25는 건물 축에 그대로 남는다. X는 명세의 대안 기록으로만 두고 토글을 만들지 않는다.

고정 문구는 성공/결측/대기/오버레이 꺼짐에도 **“가로수·가로시설물·간판 크기 미반영, 현장 확인 필요”**다. 목표 높이와 Y는 모델 가정임을 표시한다. 역/학교 접근 거리·NULL 이유는 기존 근거/툴팁을 연결하되 동선 샘플을 링 점수나108개 분모에 섞지 않는다.

### 상호작용

노출 근거의 “지도에서 보기”가 해당 후보를 선택하고 3D/오버레이를 연다. 지도 샘플 click/키보드 선택은 같은 후보의 exposure 근거를 열고 선택 샘플의 반경·방향·이동·판정·차폐 건물 정보를 연결한다. hover는 일시 강조만 하며 selectedId/가중치/채점 상태를 바꾸지 않는다. 샘플 선택은 로컬 상태이며 후보ID/generation 변경 시 초기화한다. 108개 canvas 점만으로 키보드 조작을 요구하지 않고 근거 안에 링/방향별 접힌 목록을 제공한다. 닫기/2D 복귀 시 원래 컨트롤로 포커스를 돌린다.

screens §4.8대로 **모바일3D는 지원, 샘플 오버레이는 끔**을 추천한다. 모바일에서는 건물·높이/적재 안내와 근거의 세 숫자를 제공하고 “샘플점 지도는 데스크톱에서 확인”을 표시한다. 모바일로 폭을 바꾸면 샘플 렌더링/picking을 멈추고 다시 데스크톱으로 돌아왔을 때 후보/세대가 맞는 결과만 복원한다. 모바일 오버레이까지 확대하려면 화면 명세 변경을 먼저 승인받는다.

## 7. lazy load·번들 예산 — D4

단위는 gzip level9, KiB=1024bytes, sourcemap 제외, 중복 chunk는1번만 합산한다. **아래는 제안 예산이며 아직 구현 실측값이 아니다.**

| 경로/측정 | 제안 기준 |
|---|---|
| 초기 `/compare` / 지도 미진입 | 기존 MapLibre/지도 chunk 요청0 유지 |
| 2D만 사용·근거만 열기 | 추가3D module/deck/좌표 투영 RPC/추가 Worker 요청 **0** |
| 초기 JS 증가 | #32 대비≤5KiB, #29 대비 누적≤10KiB도 유지 |
| 2D 지도 JS/CSS | 기존≤350/15KiB 유지,3D 구현이 섞이지 않음 |
| 첫3D + 데스크톱 오버레이 추가 JS | **≤500KiB**, 별도 CSS≤10KiB |
| 첫3D 건물만(모바일) | 추가 JS≤50KiB, deck 다운로드0 |
| geometry 투영 | request/response 각각 compact JSON≤8MiB 제안. 실제 HTTP bytes·압축 유무·왕복 시간은 별도 기록 |

MapLibre 공통 엔진은2D에서도 이미 로드되며 그 내부의 익스트루전 기능까지0byte라고 주장하지 않는다. 여기서 “3D 번들0”은 **기존2D 대비 추가3D 구현/의존성0**이다. 기존 채점용 exposure RPC/Worker와2D 지도 RPC는 계속 필요하며 그것까지 요청0이라는 뜻이 아니다.

가벼운 토글만2D shell에 두고 `BuildingScene3D`와 `ExposureOverlay`를 동적 import한다.3D를 열기 전 prefetch·preload·호버 import를 하지 않는다. P1의 건물 표현만 쓰는 모바일에는 P2 deck chunk를 로드하지 않는다.2D 복귀 시3D draw/picking/애니메이션을 중지하고 메모리 캐시만 제한적으로 유지한다. 라우트/uid 이탈 시 소스·레이어·overlay·이벤트를 해제한다.

production HTML/chunk 의존 그래프와 새 BrowserContext의 요청 시간표로 검증한다. 지도만 연 상태, 노출 근거만 연 상태,3D 진입,2D 복귀/재진입을 각각 계수한다. 스타일/tile/glyph/sprite와 앱 JS·RPC bytes를 분리하며3D pitch/zoom 때문에 생기는 추가 타일 요청은3D 진입 이후 별도 기록한다. 예산 초과 시 import 중복/불필요 패키지를 먼저 확인하고 승인 없이 범위·데이터를 줄이거나 예산을 올리지 않는다.

## 8. 60fps 측정 조건 — D5

screens의 “4,000~5,000개60fps 가능”은 목표이며 이 앱의 검증 완료값이 아니다. **추천 기준은 각60초 시험에서 평균 렌더 FPS≥55, frame interval p95≤33.4ms,50ms 초과 간격≤1%**다. 모든 수치를 기록하며 평균만으로 긴 끊김을 숨기지 않는다.

- 기준 장치 제안: 현재 확인한 **Apple M5 Pro / GPU16코어 / RAM48GB**, 외부60Hz 화면. 실제 GPU 가속을 쓰는 headed Chrome stable, AC 전원·저전력 모드 해제·foreground, OS/Chrome/renderer/전원 상태를 기록한다. 창1440×1000 CSSpx·DPR2 고정, 실제 map canvas CSS/physical 크기도 기록한다. 다른 기기의60fps 보장으로 일반화하지 않는다.
- CI headless/SwiftShader는 기능·좌표 회귀용이며60fps 판정 기기로 사용하지 않는다. 기본 측정 장치가 없거나 소프트웨어 렌더링이면 FPS는 미검증으로 보고한다.
- production build/start와 승인된 같은 scene을 사용한다. a4,693개/47,145vertices를 기본, b4,431개·c3,843개를 교차 확인한다. 예상과 다르면 실제 snapshot/개수/정점 수를 기록한다.5후보를 비교에 두되 렌더링은 선택 후보 scene1개다.
- 시나리오①zoom17·pitch55°·bearing0,108점/차폐 강조를 켜고 회전/팬/샘플 선택. ②zoom14~15 넓은 뷰에서 같은4,693개 source를 유지하고 pan/zoom/orbit. ③2D↔3D 전환10회와 a↔d↔e 층 전환, 해제/재진입 후 메모리/컨텍스트 누수 확인. 실제 화면 내 unique 건물 수와 source 수를 별도로 적는다.
- 자료와 shader 준비 후 고정 카메라 경로60초×3회, 각 회가 기준을 만족해야 한다. map/render 이벤트·rAF 간격·브라우저 Performance frame trace를 함께 수집해 **정지 화면의 idle rAF를60fps 렌더 실적으로 세지 않는다**. 바닥 타일 네트워크·첫 import/변환/mesh upload/shader compile/first3D-ready 시간은 cold 지표로 별도 공개한다.
- 낮은 성능이면 먼저 데이터 참조 안정성, feature-state, 이벤트 구독·buffer 재생성·draw 호출을 확인한다. 원천 도형 삭제/높이 축소/샘플 수 축소나 자동 새 엔진 전환은 하지 않는다. 통과하지 못하면 장치·뷰·건물 수와 병목을 보고하고 다음 결정을 받는다.

## 9. CI 슬라이더 변동 대응 — D6

2026-10-08 사용자 승인으로 **B(100회×3세트 p95 중앙값≤100ms)**를 확정했다. **제품 production은 각 세트 p95≤100ms를 유지**한다. 아래 선택지 비교는 결정 근거로 보존한다.

| 선택지 | CI | trade-off |
|---|---|---|
| A 완화 회귀선 |100회1세트, p95≤150ms, max 기록 | 빠르지만 단일 실행 잡음과 작은 회귀를 구분하기 어려움 |
| **B 3회 중앙값** |100회×3세트, **세트별 p95의 중앙값≤100ms** | 실행시간 증가, 단발 변동의 영향 감소. 모든 세트/max를 남겨 공통 과부하를 숨기지 않음. **추천** |

문서 전용 PR(`docs/**`, 루트·하위 경로의 `*.md`/`*.mdx`만 변경)은 E2E·그 안의 성능 측정을 건너뛴다. lint/typecheck/test/build·DB 검사는 유지한다. 전체 Git diff로 판정하고 삭제·이름 변경의 양쪽 경로를 포함한다. 코드/설정 혼합·diff 확인 실패·빈 diff는 실행하며 main push는 전체 검증한다.

P0에서 벤치마크 함수를 추출한다. 기준은 기존과 같이 input부터2회 rAF까지,100개 nearest-rank p95/index94, max/index99다. 각 세트는 동일5후보·가중치 순서·지도 idle·준비된 exposure로 실행하고 원래 프리셋/열 순서를 복원한다. RPC·Worker 재계산0과 실제 총점 반영을 함께 확인한다. 숫자50/126/66의 중앙값을 계산해 과거 실패를 소급 통과 처리하지 않는다. 새 규칙 승인 후 같은 조건으로3세트를 새로 수집한다.

CI도 실제 Supabase/Worker/WebGL과 고정 주소/스타일 fixture를 유지한다. 채점·지도 오류·uid 격리·선택·lazy 검사에는 완화 규칙을 적용하지 않는다. CI에서 반복 과부하/3세트 중앙값 초과이면 로그를 남기고 실패로 처리한다. 실패할 때까지/통과할 때까지 자동 반복하거나 느린 세트를 버리지 않는다.

엄격 판정은 위 실제 GPU 장치의 **production**에서2D지도와3D+오버레이 각각100회×3세트, **각 세트 p95≤100ms**, max 전부 기록으로 분리한다. 비교 가능성을 위해 기존2D 배치와 같은 뷰/자료를 기록한다. 실제 OpenFreeMap은 자료가 준비된 뒤 측정하되 cold 지연은 따로 남긴다. 첫 측정 실패도 원본에 남기고 제품을 고쳤다면 새 코드 SHA의 새 실험으로 구분한다. CI 중앙값 통과만으로 strict production 통과를 대신하지 않는다.

## 10. PR 분할과 변경 파일

모두 최신 main에서 분기·Draft PR, 문서와 코드 별도 커밋. 선행 PR의 사용자 머지 후 다음 PR을 최신 main에 맞춘다.

| PR | 파일/범위 | DB/의존성 | 완료 기준 |
|---|---|---|---|
| **P0 성능 판정 분리** `s3/slider-performance-policy` | `tests/e2e/compare.spec.ts`, 벤치마크 helper/config, 필요 시 `.github/workflows/ci.yml`, 운영/검증 문서 | 없음 | 승인된 CI3세트/production 각세트 기준 구현, 기존100회 측정 의미/기능/호출0 불변, 기존/새 코드 측정값과 환경 구분 |
| **P1 건물3D 기반** `s3/building-3d` | `components/map/{CompareMap,BuildingScene3D}.tsx`, 표시 geometry client/adapter, `lib/compare/load-candidate.ts` 타입 경계, 필요 시 store, CSS·DB/좌표·E2E, data-sources/운영/검증 | **새 변환 RPC1개·권한만**, 기존 객체/행 변경 없음. MapLibre 기존 버전 | 토글/카메라복귀·높이3분류·강남구/부분범위 문구, 좌표 검산·RPC 권한/성능,3D 미진입0·mobile deck0·번들/기본 건물 FPS 실측 |
| **P2 ExposureOverlay·인계** `s3/exposure-overlay` | `components/map/ExposureOverlay.tsx`, render adapter·visibility 결과 타입 bridge, `EvidencePanel.tsx`/ComparisonMatrix 연동, package/lock, fixtures·E2E·performance·검증/계획 체크 | deck.gl9.x 필요한 모듈만. 예상 migration 없음 | a32/108 방향/차폐 ID 불일치0, weighted ratio/Y 분리, 지하/추정/결측·모바일 범위, 실제 GPU FPS·strict slider·Preview·전체 회귀, S3-4 마감 |

Worker의 레이캐스트/판정 순서와 scoring v0.4.0 식은 수정하지 않는다. 타입이나 결과 bridge가 필요하면 기존 결과를 그대로 노출하고 수치 전수 대조를 붙인다. 명세/기획과 충돌하거나 데이터 누락 때문에 새 추정이 필요해지면 구현 전에 보고한다.

## 11. 검증과 migration 승인 절차

- 단위: 원본 불변, 타입 guard, 도형/점 id 매핑, 세 숫자/제외 분모, 이동·unknown4m·지하2m/Y0.8, stale generation/층/uid 결과 거부, 선택/구독/캐시 해제. 임의의 “가까운 차폐 건물” 재선정 없음.
- 독립 검산: 합성 벽1개·홀·MultiPolygon·높이 미상·후보 제외·북동남서와 실제 a108점을 SQL/기존 순수 결과와 대조. 지도 bearing0 상면 비교와 pitch55 뷰를 모두 캡처하고 sample ID별 위치/판정·recorded blocker ID 불일치0을 확인한다. 화면 픽셀 거리로 가시율을 재계산하지 않는다.
- 실제 점수: a/b/c/d/e v0.4.0 총점83.10201719669011 /92.60289331263688 /82.67204741731668 /81.84736541572254 /85.08500496915157 불변. 3D·오버레이·슬라이더·저장/재열기에서 원래 score/근거 모델 계약 유지.
- E2E: 실제 로컬 Auth/RPC/Worker/MapLibre/deck WebGL, pending→ready 중3D 선택 유지, 층 전환·두 uid·재접속/역순 회귀, 오류/느린 변환/토글 연타/WebGL 불가, 모바일375/390/1024 경계·키보드·출처 비겹침·초기 요청0. 외부 주소/배경 fixture 여부를 결과에 명시한다.
- Preview: 실제 익명 세션·주소 경로·OpenFreeMap으로 건물3D/추정/범위·오버레이·근거/모바일을 확인. 생성한 검증 uid만 정리한다. 소프트웨어 GPU Preview 캡처를 strict FPS 실측으로 사용하지 않는다.
- 필수 `pnpm lint/typecheck/test/build`, 기존 E2E, P1은DB 회귀/권한 검사. 각 PR의 `docs/validation/s3-4-*.md/json`에 SHA·환경·건물/정점/샘플 수·p95/max/3세트·실패/미실행·실제/fixture를 구분한다.

P1 migration은 `supabase migration new`로 생성하고 과거 파일을 수정하지 않는다. 보고 첫 줄은 **“새 표시용 좌표 변환 함수1개와 권한만 추가, 기존 함수·테이블·열·정책·행 변경 없음”**으로 예상한다. 실제 diff가 이 범위를 벗어나면 따로 설명한다. 로컬 숫자/권한/기존 RPC 계약 불변·rollback(신규 함수 비활성화/제거)·최종 hash·원격 dry-run 결과를 먼저 제출하고 **push 승인 후** 적용한다. Bypass/service_role이 아닌 익명 로그인 authenticated로 확인한다. 원격 데이터 교체·삭제·컴퓨트/운영값 변경은 이 계획에 포함하지 않는다.

## 12. 사용자 처리 단계

1. D1~D6 추천안·계획은 2026-10-08 승인 완료다. P0 머지 후 P1을 최신 main에서 시작한다.
2. P1 최종 dry-run·hash·기존 객체 변경 여부를 보고받은 후 원격 push를 승인한다. 코드 계획 승인만으로 원격 migration을 실행하지 않는다.
3. 추천안에는 새 Vercel 환경변수/타일 계정/API key가 없다. 기존 `NEXT_PUBLIC_MAP_STYLE_URL`과 서버 주소 키를 유지한다. `.env` 전체 업로드는 하지 않는다.
4. 기준 기기를 더 낮은 사양으로 정하려면 기기/OS/GPU/화면 조건을 지정한다. 추천은 현재 사용 가능한 M5 Pro/60Hz이며, 추가 기기 검증을 했다고 임의로 적지 않는다.
5. 각 Draft PR을 검토·머지한다. S3-4 뒤 학원 점 레이어는 후속 계획, 공개 Small 전환/합본 시험은 별도 승인 단계다.

## 13. 결정 필요 항목

| ID | 선택지 | 추천 |
|---|---|---|
| **D1 렌더러** |①MapLibre 건물+deck 샘플 /②deck 건물+샘플 /③MapLibre custom layer까지 단일화 | **①**, 현재 명세/엔진 유지·역할 분리 |
| **D2 5186→4326** |①캐시 도형 표시용 PostGIS RPC1개 /②로컬 투영 라이브러리 예외 승인 | **①**, 원본 scene 고정·공식 변환 재사용. 왕복 bytes/시간은 측정 후 판단 |
| **D3 모바일·연동** |①모바일 건물3D만, 샘플은 desktop·근거 숫자는 공통 /②모바일 샘플까지 확대 | **①**, screens §4.8 유지. desktop은3D 진입 시 오버레이 기본 켜짐, 사용자가 끌 수 있음 |
| **D4 PR/번들** |①P0→P1→P2 3개, §7 incremental JS500KiB/초기+5KiB 등 /②큰 PR1개 | **①**, DB 승인·성능 정책·렌더 검증 분리. “미진입0”은 기존2D 공통 엔진 외 추가 리소스 기준 |
| **D5 60fps 기준** |①M5 Pro 실제GPU/60Hz에서 각회 평균≥55fps+p95≤33.4ms+50ms초과≤1% /②사용자 지정 최소사양으로 동일 판정 | **①**, 지금 측정 가능한 명시적 기준. 지원 최소사양 보장은 별도 |
| **D6 슬라이더 CI** |A 1회p95≤150ms /B 3회p95 중앙값≤100ms. production은 양쪽 모두각회≤100ms | **B**, 모든 세트·max·실패 이력 공개 |

## 14. 계획 PR 작성 당시 실행/미검증 기록 (이력 보존)

실행: 지정 문서와 #32 인계 읽기, main/#32 상태 조회, 현행 TS/RPC/Worker 데이터 경로 확인, **로컬 scene3곳 read-only 건물/높이/꼭짓점/JSON 크기 조회**, 기준 장치 사양 확인, 버전 고정 공식 렌더러 문서와 PostGIS 문서 확인.

미실행: 제품 코드/의존성/명세 변경, 새 migration 생성·원격 쓰기·투영 RPC 구현, deck 실제 호환성·번들/FPS/3D 성능 측정, CI 판정 정책 변경. 숫자 예산·FPS 통과선·렌더러/좌표 경로는 **추천안**이며 API/성능 실증 완료값이 아니다. 승인 후 P0부터 착수한다.

## 15. P0 진행 기록

- D1~D6 추천안 승인, #33 main 머지 확인. P0 검증·실패 이력·실행 방법은 [검증 문서](../validation/s3-4-p0-20261008.md)를 따른다.
- P0: 문서 PR 경로 필터, CI 3세트 중앙값 판정, production 각 세트 엄격 판정. 채점·지도 제품 코드와 DB 변경 없음.
- 공개 전 추가 확인: **내장 GPU 일반 노트북 FPS 확인**. [공개 전 체크리스트](../operations/s3-foundation.md#공개-전-체크리스트-2026-10-02)에서 별도 기록한다.
- P1(건물 3D)은 P0 머지 후, 학원 점 레이어는 S3-4 직후 첫 후속 과제 순서를 유지한다.

## 16. P1 진행 기록

- #34 main 머지 확인 후 P1 착수. MapLibre fill-extrusion·2D/3D·모바일 건물·순수 표시 RPC1개·높이/범위 안내·lazy load 구현. 새 라이브러리·채점 변경 없음.
- 원격 push 전 dry-run 보고/승인 절차와 D5 실측 조건을 유지한다. [P1 검증](../validation/s3-4-p1-20261008.md)에 현재 완료/미완료를 구분한다.
- P2 오버레이와 학원 점 레이어는 이번 PR에 포함하지 않는다.
- 2026-10-08 사용자 지시: FPS 환경은 사용자가 나중에 설정해 알린다. P1 기능·번들·migration dry-run을 먼저 완료하고 FPS만 미완료로 기록하며 Draft를 유지한다. 원격 push는 별도 승인 후 진행한다.
