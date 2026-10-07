# S3-3 2D 지도·선택 동기화 구현 계획

2026-10-07 · **D1~D5 추천안 사용자 승인, PR 1(M) 원격 검증 완료**. base `main`의 `80be024`(#29 머지, scoring v0.4.0) 기준. 계획 작성 브랜치는 `s3/compare-map-plan`이다. 승인에 따라 PR 1(M)을 구현한다. 원격 migration은 최종 dry-run 보고 후 별도 push 승인을 받는다.

## 1. 기준과 범위

기준 문서: [AGENTS.md](../../AGENTS.md), [화면 정의 §4·§8](screens.md), [S3-2 확정 계획](s3-2-plan.md), [채점 명세 v0.4.0](scoring-spec.md). S3-2의 과거 v0.3 수치는 역사적 검증이며 이번 회귀 기대값은 #29의 v0.4.0이다.

| 범위 | 이번 완료 동작 |
|---|---|
| CompareMap 2D | MapLibre GL JS 4.x + OpenFreeMap Liberty 계열, 한글 우선 라벨, pitch 0 |
| 후보·반경 | 최대 5후보, 현재 열 순서 번호·선택 강조, 선택 후보 중심 800m/1km 원 |
| 역·학교 | 선택 후보의 1.2km 내 모든 역, 1km 내 초·중·고. 데이터 ID와 출처 유지 |
| 동기화 | 매트릭스 열/모바일 카드·칩 선택 ↔ 후보 마커 선택, 같은 candidate ID 사용 |
| 모바일 | <1024px의 **매트릭스 / 지도 / 근거** 3탭, 지도 하단 후보 칩, 기존 가중치 시트·근거 아코디언 |
| 성능·정확성 | 첫 매트릭스 렌더에 지도 JS 미포함, 모바일 지도 탭 전 지도 요청 없음, 지도 중심=채점 입력 좌표 |
| 모델 버전 안내 | 지도와 독립한 소형 PR M 제안. 실제 저장 모델 기록과 현재 버전을 비교해 재계산 안내 |

3D·익스트루전·deck.gl·노출 샘플/동선 오버레이·2D/3D 토글은 **S3-4**다. 채점 공식·가중치·프리셋·원천 적재는 바꾸지 않는다.

화면 정의와 이번 요청의 차이:

- §4.3에는 줌15+의 `academies` 점도 있으나 이번 명시 범위와 §8 S3-3 행에는 없다. **S3-4 직후 첫 후속 과제로 확정(D2)**. 승인 후 screens에 단계 구분을 문서 커밋으로 남긴다.
- §4.3은 반경800m 하나지만 이번 요청은800m/1km다. 두 원을 같이 표시하고 **주채점 800m / 학교 조회 1km**로 구분한다. 반경 조작으로 프리셋을 바꾸는 기능은 아니다. 역 표시 범위1.2km는 별도 범례다.
- §4.8의 탭명 “비교”는 이번 요청의 “매트릭스”로 맞춘다. 3D 토글은 S3-4까지 넣지 않는다.

## 2. 확인한 현재 상태와 유지할 결정

| 근거 | 확인·인계 |
|---|---|
| [A 등록 검증](../validation/s3-2-a-registration-20260930.md), [리전 재검증](../validation/s3-2-a-region-retry-20261001.md) | Juso 검색→Vworld 좌표→PNU 포함 검증→실제 RPC/Worker. Route Handler icn1. 지도에서 재지오코딩하거나 PNU 중심으로 바꾸지 않음 |
| [B 매트릭스 검증](../validation/s3-2-b-comparison-20261001.md) | 실제 Realtime uid 격리·3분 지연·재접속·역순 처리. 슬라이더는 RPC/Worker 없이 재계산. 공개 전 합본 시험 실패 기록은 보존 |
| [C 저장 검증](../validation/s3-2-c-save-retention-20261002.md) | 후보+비교 단일 트랜잭션, 같은 uid 재열기, 명명 가중치. 익명 정리30/90일·원격 dry-run, 실제 정리 비활성 |
| [D5 종결](../validation/s3-2-d5-closeout-20261006.md) | INGEST_REMOTE_ENABLED=true, 주소 트리거 활성, sweep `23 */6 * * *`, JUSO_COORD_ENABLED=true, AUTH_CLEANUP_ENABLED=false. 새 운영 실행 없이 유지 |
| [v0.4.0 검증](../validation/scoring-v040-20261007.md) | a~e 실제 입력·로컬 Auth/RPC/Worker E2E, 슬라이더100회 p95 34.0ms/max34.1ms. NULL·지하 모델 분기 유지 |
| `lib/compare/store.ts` | `selectedId`, `selectedAxis`, `order`, 세대 번호와 후보 동시 채점 최대2개가 이미 있음. 현재 `select()`는 근거도 열어 지도 선택용 동작 분리가 필요 |
| `components/compare/ComparisonMatrix.tsx` | 매트릭스·모바일 카드·2탭·Realtime·근거를 소유. `app/compare/page.tsx`는 이 컴포넌트만 렌더. MapLibre 의존성은 아직 없음 |
| `lib/compare/load-candidate.ts`, `lib/visibility/types.ts` | 원래 Candidate의4326 좌표와 scene의5186 좌표를 보유. 역·학교 anchor는5186이므로 MapLibre의 `[lng,lat]`에 그대로 넣을 수 없음 |
| `lib/compare/persistence.ts`, C 저장 migration | DB의 `preset_version='0.3'`은 기존 입력/가중치 계약. 실제 저장 당시 모델 버전으로 판별할 수 없음. 재열기는 현재 모델로 재계산하고 구버전 점수 캐시는 거부 |

S3-2 확정 사항 유지: 주소 검색 무캐시·uid 일100회 제한, 등록 좌표1회/후보·비공개 큐 저장, 공용 geocode_cache 쓰기는 배치만, 서버 전용 주소 키, RLS/익명 인증 재시도, pending60·−15, 세대/좌표/층 기준의 늦은 응답 폐기, 슬라이더 p95≤100ms와 max 기록. S3-3 선택·지도 이동·탭 전환은 채점을 다시 실행하지 않는다.

**컴퓨트 Micro 유지.** “2uid + 연속5채점” 합본은 S3-3 완료 기준으로 옮기지 않는다. [운영 문서](../operations/s3-foundation.md)의 **Small 전환 후 재시험 통과가 공개 조건**이라는 결정을 유지한다. 이번 지도 구현은 업그레이드·공개 승인에 해당하지 않는다.

## 3. PR 분할 제안

**사용자 승인: PR 1 M → PR 2 A → PR 3 B, 총3개(D1).** 각 PR은 `main` 기반 `s3/…`, 문서와 코드 별도 커밋. M부터 구현한다. 학원 점 레이어는 S3-4 직후 첫 후속 PR로 구현한다. 후속 PR은 앞 PR 머지 후 최신 main에 동기화한다.

| PR / 브랜치 | 구현 범위·예상 파일 | DB 변경 | 해당 PR 완료 기준 |
|---|---|---|---|
| **PR 1 / M 저장 모델 안내** / `s3/saved-model-notice` | `lib/compare/{persistence,store}.ts`, `SaveControls.tsx`/`Badges.tsx`, 저장 DB 회귀, screens·운영 문서 | 새 nullable 모델 열·버전 저장 RPC, 기존 저장 함수의 구클라이언트 처리 보완(§9) | 구버전/동일 버전/버전 미기록·실패 배지 구분, 0.4.0 재계산 점수 일치, 저장/재열기·uid 격리·원자성 유지 |
| **PR 2 / A 지도·데이터·lazy load** / `s3/compare-map` | `components/map/{CompareMap,MapGate}.tsx`, `lib/map/{context,features}.ts`, 비교 화면 지도 슬롯·CSS, package/lockfile, `.env.example`, 지도 데이터 RPC | 새 읽기 전용 `compare_map_context` 함수1개·권한만. 기존 객체 정의/행 변경 없음(권장안 §4) | 2D·마커·800/1000m·역/학교·출처·한글, 좌표 검산, 지도 오류 격리, 첫 렌더 번들 분리·예산 실측 |
| **PR 3 / B 선택·모바일 마감** / `s3/compare-map-selection` | `ComparisonMatrix.tsx`/필요한 화면 셸, `EvidencePanel.tsx`, `lib/compare/store.ts`, 모바일 탭·칩·스타일, 기존 E2E 확장 | 원칙적으로 없음 | **열 선택 ↔ 마커 선택 동기화, 모바일3탭 동작**, 같은 좌표의 여러 층 후보 선택, 정렬/삭제/층 변경/Realtime 회귀, 슬라이더 p95≤100ms |

MapLibre는 AGENTS의4.x 범위에서 **4.7.1 정확 버전 고정**을 제안한다. 승인 후 Next15·React19·Worker 호환을 실제 build/브라우저로 확인하고 lockfile에 기록한다. 추가 지도 래퍼·Turf·proj4·3D 라이브러리는 넣지 않는다. 새 의존성 이유는 PR에 적는다.

## 4. 데이터·좌표·반경 계약

### 4.1 후보 좌표는 하나만 사용

- 유일한 기준은 `ComparisonCandidate.candidate.{lat,lng}`: 등록 후 `score_inputs`와 `exposure_inputs_v022`에 보낸 값이다. 마커는 `[candidate.lng,candidate.lat]`, 원의 중심과 카메라도 같은 값을 사용한다. 표시용 반올림을 계산 좌표에 되쓰지 않는다.
- 역삼로460 a/d/e는 같은 좌표에서 층만 다르다. 지오코딩 재호출·건물 도형 중심 치환·마커 좌표 이동을 하지 않는다. 현재 사용하지 않는 “주소 문자열 캐시”로 마커를 찾지 않는다.
- 후보 ID를 feature ID/선택 키로 사용하고 순위는 `state.order`에서 파생한다. 정렬로 번호가 바뀌어도 선택 ID는 유지한다. 요청 키는 ID/좌표/입력 세대와 묶어 삭제·이전 좌표의 응답이 새 후보를 덮지 않게 한다.

### 4.2 역·학교·원은 가벼운 읽기 전용 RPC 권장(D3)

제안 계약 `compare_map_context(lat double precision, lng double precision) → jsonb`:

- `schema_version`, 원래 중심4326, GeoJSON FeatureCollection, `meta.sources`/기준일, 조회 범위.
- 후보 중심800m/1000m 원2개: `radius_m`, `purpose=primary/school`. `geography`의 `ST_Project`로 원주128점을 만들고 폐합한다. 채점의 geography 거리와 같은 미터 기준이며 화면 EPSG:3857 위에서 임의 픽셀 원을 만들지 않는다.
- `transit_stops`의 subway 유형 중 geography≤1200m: 원래 ID·역명·노선·4326 Point·distance_m. 현재 scene처럼 노선별 환승역 ID를 임의 합치지 않는다.
- `schools`의 유효 좌표·level(elem/mid/high) 중 geography≤1000m: ID·이름·학교급·Point·distance_m. 원천 NULL 좌표는 추정하지 않는다. 좌표 미상 학교가 반경 안에 있는지는 판정할 수 없으므로 원천 전체의 좌표 결측 수와 반경 내 표시 수를 구분한다.
- 익명 로그인한 **authenticated**만 EXECUTE, `security invoker`, 빈 `search_path`, 모든 객체 스키마 명시. 기존 공공 원천 읽기 권한을 사용한다. 큐·캐시·후보 쓰기나 `score_inputs` 호출을 포함하지 않는다.

기존 exposure RPC는 건물 도형까지 수MB를 반환하고 지상/지하 차폐용 계약이다. 지도 전용으로 재호출하지 않는다. 새 RPC는 건물 없이 작은 Point·원만 반환하고, 서울 밖·원천 결측도 거짓0건과 구분한다. 원격 push 전 실제 반환·권한·성능·기존 함수 무변경을 검증한다.

- 지도 활성화 후 선택 후보1곳만 요청, 동일 좌표는 인메모리 결과/진행 Promise 공유. 좌표·관련 원천 fingerprint 변경 시 무효화한다. 층·가중치만 바뀌면 재조회하지 않는다.
- 지도 조회 동시성1, 후보 채점 동시성2 유지. 초기 채점과 불필요하게 겹치지 않도록 선택 후보의 최초 채점 요청이 끝난 뒤 부가 조회한다. 지도 탭 전에는 새 RPC0회. 후보 마커는 좌표만 있으면 먼저 표시하고 원·역·학교는 로딩 상태를 구분한다.
- 빈 배열은 “해당 반경에 없음”, 소스 unavailable/조회 실패는 “자료를 불러오지 못함”으로 구분. 지도 실패는 점수·근거·저장을 막지 않는다.
- 새 함수는 `supabase migration new`로 생성한다. **기존 객체 변경 없음**을 PR에 명시하고 local DB 검증→최종 dry-run/해시 보고→사용자 승인→remote push 순서다.

대안은 이미 받은 scene의5186 anchor를 클라이언트에서4326으로 역변환하는 무migration 안이다. 현재 역변환 유틸이 없고 새 수학 코드의 PostGIS 검산이 필요하므로 RPC 안을 권장한다. 새 라이브러리 추가나 좌표계 추측으로 대신하지 않는다.

## 5. CompareMap·선택 동기화

- 데스크톱 ≥1024px: §4의 매트릭스55%/지도45%, 근거는 하단. 첫 지도 준비 시 모든 후보를 fitBounds하고, 선택 변경 시 해당 후보로 이동한다. 순위/가중치만 바뀔 때 사용자가 조절한 카메라를 초기화하지 않는다. reduced-motion은 즉시 이동한다.
- 800m 원은 옅은 면+실선, 1km는 점선으로 구분하고 텍스트 범례를 둔다. 선택 후보의 원만 표시한다. 역1.2km·학교1km는 범례에 별도로 적어 주채점 범위와 혼동하지 않게 한다.
- 후보는 번호+별칭/층, 선택 강조. 역은 이름+노선, 학교는 초/중/고 기호와 이름. 건물/역의 외부 지도 POI를 채점 원천 점처럼 표시하지 않는다. Liberty 기본 POI는 최소화하고 실제 표시 원천과 구분한다.
- **동일 좌표 후보(D5):** 위치는 그대로 두고 하나의 묶음 마커(예: “3곳”)에서 a3층/d4층/e1층 목록을 제공한다. 내부 feature/candidate ID는 각각 유지한다. 칩에서도 직접 고를 수 있다. 같은 좌표를 보기 좋게 흩뿌리는 방식은 사용하지 않는다.
- store에서 후보 선택과 근거 열기를 분리한다. `selectCandidate(id)`는 선택만, `openEvidence(id,axis?)`는 선택+근거. 기존 셀 클릭의 근거 열기를 보존하고 마커 클릭 때문에 지도 탭이 근거로 강제 전환되지 않게 한다.
- 열 머리의 선택 버튼/총점·카드·마커·칩은 동일 선택 경로를 사용한다. 선택된 열을 가로 스크롤 영역 안으로 가져오되 사용자 수동 열 순서는 유지한다. 슬라이더 드래그 중 재정렬하지 않는 B 동작도 유지한다.
- 선택 후보 삭제 시 남은 현재 열 순서의 첫 후보, 0개면 선택 해제/빈 상태. 층 변경·pending→ready는 ID/선택을 유지한다. 지도 pan/zoom·역/학교 정보 열기는 점수 재계산이나 후보 좌표 편집을 유발하지 않는다.

## 6. 모바일 3탭

- 기본 “매트릭스”; 후보 카드·가중치 시트를 재사용한다. “지도”는 탭 영역을 채우는 2D와 하단 후보 칩. “근거”는 선택 후보의 기존 아코디언이며 채점 v0.4.0 근거 문구를 그대로 쓴다.
- 지도 칩/마커 선택은 지도 탭 유지, 카드의 축 클릭은 해당 축 근거로 이동. 근거 닫기는 직전 비근거 탭으로 돌아간다. 별도 탭에 선택 후보를 복제해 보관하지 않는다.
- 탭은 tablist/tab/tabpanel·aria-selected·aria-controls·키보드 화살표/Home/End·포커스 이동을 제공한다. 숨긴 패널은 키보드/접근성 탐색에서 빠진다. 모바일375/390px, 태블릿 및1024px 경계 전환을 검증한다.
- 첫 지도 진입 전 지도 컴포넌트는 mount하지 않는다. 한 번 연 지도는 페이지 안에서 인스턴스1개만 유지하고 탭 복귀/사이즈 변경 때 `resize()`한다. 탭 전환·breakpoint 변경으로 Worker/리스너를 중복 생성하지 않는다. 페이지 이탈/후보0개 시 정리한다.
- 지도 탭 로딩 중에도 탭 전환·근거·저장이 가능하다. WebGL 불가/타일 실패 시 지도 영역의 오류·재시도와 후보 목록을 제공한다. 오류를 건물/역 결측으로 바꾸지 않는다.

## 7. lazy load·번들 예산

[Next.js15 공식 lazy-loading 문서](https://nextjs.org/docs/15/app/guides/lazy-loading)를 따른다. `ssr:false`만 붙이고 첫 렌더부터 mount하는 방식은 충분하지 않다.

- 가벼운 Client `MapGate`만 초기 비교 셸에 둔다. MapLibre·CSS·지도 구현을 route/layout/store에서 정적으로 import하지 않는다(type-only 제외).
- 데스크톱은 매트릭스/스켈레톤의 첫 paint 이후 idle 시점에 지도 슬롯을 mount한다. 모바일은 지도 탭을 눌렀을 때만 import한다. 동적 컴포넌트는 Client 경계 안에서 구성하고 자동 preload/prefetch로 첫 렌더에 지도 chunk가 요청되지 않는지 확인한다.
- 최초 점수/RPC 완료를 지도 준비에 종속시키지 않는다. 2~4초 cold 스켈레톤과 기존 잠정 규칙은 유지한다. 지도 스켈레톤은 실제 지도 크기를 미리 확보해 레이아웃 이동을 막는다.

**아래는 승인 요청 예산이며 구현 후 실측으로 통과 여부를 판정한다.** KiB=1024bytes, gzip level9, source map 제외. DB JSON·지도 타일/폰트 전송과 앱 JS를 구분한다.

| 측정 | 예산/판정 |
|---|---|
| `/compare` 초기 JS에 MapLibre/지도 구현 포함 | **0 bytes**, 첫 matrix-shell paint 이전 해당 chunk/Worker 요청0회 |
| 초기 셸 추가 JS | #29 동일 production build 기준 **gzip +10KiB 이하**. 지도와 M 배지 기여도 분리 |
| 지도 최초 진입에 추가되는 앱 JS 합 | MapLibre+Worker(별도 파일이면 합산)+지도 어댑터 **gzip ≤350KiB** |
| 지도 CSS | **gzip ≤15KiB**, global layout에 전체 지도 CSS를 추가하지 않음 |
| 지도 전 모바일 외부 요청 | MapLibre chunk·타일·glyph·sprite·지도 RPC **0회** |
| 최초 고정 지도 뷰 | 타일/폰트 bytes·요청 수·첫 map idle 시간을 앱 번들과 별도 기록. 네트워크를 제외한 값으로 바꿔 보고하지 않음 |
| 슬라이더 회귀 | 지도 열린 상태에서5후보×100회, **p95≤100ms**, max 기록. RPC/Worker 재채점0회 |

계획 단계 npm 배포 파일 실측: `maplibre-gl@4.7.1` JS803,086bytes / gzip210,896bytes(약206.0KiB), CSS65,534bytes / gzip9,239bytes(약9.0KiB). [배포 메타데이터](https://registry.npmjs.org/maplibre-gl/4.7.1)의 tarball에서 읽은 값이며 **Next 최종 chunk 크기나 앱 성능 통과 값이 아니다**.

검증은 `pnpm build` 산출물·초기/비동기 chunk 의존 관계와 production Playwright의 요청 시간표를 함께 본다. 최초 HTML의 script/preload에 지도 chunk가 없음을 검사하고 지도 요청을 지연/차단해도 매트릭스가 먼저 렌더되는지 확인한다. 예산 초과 시 중복 의존성·잘못된 eager import를 먼저 확인하고 수치 변경은 보고 후 결정한다.

## 8. 타일 공급자·라이선스·환경변수

2026-10-07 공식 자료 확인:

| 항목 | 확인과 적용 |
|---|---|
| 사용 조건 | [OpenFreeMap 공식 FAQ](https://openfreemap.org/)는 상업 이용 가능, 공개 인스턴스 무료·API key/계정 불필요·요청/지도 수 제한 없음으로 안내한다. SLA 보장은 없음 |
| 약관 | [ToS](https://openfreemap.org/tos/)는 as-is 제공·사전 고지 없는 종료 가능성·무허가 자동 수집 금지 등을 명시. 공식 임베드 지도 사용만 하며 대량 다운로드/오프라인 타일 수집은 이번 범위에 없음 |
| 출처 | 지도 안에 **OpenFreeMap · © OpenMapTiles · © OpenStreetMap contributors**와 각각의 링크 유지. OSM은 [copyright/ODbL 링크](https://www.openstreetmap.org/copyright)를 제공. OpenFreeMap 명칭은 공식상 선택이지만 이번에는 표시. 모바일 칩/탭으로 출처를 가리지 않음 |
| 코드·스타일 | [MapLibre4.7.1 라이선스](https://github.com/maplibre/maplibre-gl-js/blob/v4.7.1/LICENSE.txt)는 BSD-3-Clause 계열. [OpenFreeMap license 목록](https://github.com/hyperknot/openfreemap/blob/main/LICENSE.md)은 프로젝트 MIT와 Liberty 원 코드 BSD-3-Clause·디자인 CC BY4.0 등을 구분. “전체 지도 데이터가 MIT”로 표기하지 않음 |
| 스타일 조정 | [공식 Quick Start](https://openfreemap.org/quick_start/)의 Liberty URL 사용. 로딩 후 색조·POI·라벨 표현만 조정하고 변경 사실/원 출처를 `docs/data-attribution.md`에 기록. 타일 데이터를 재배포하지 않음 |
| 개인정보 | [Privacy Policy](https://openfreemap.org/privacy/)는 제한된 로그·오류 시 IP/URL·Cloudflare 처리를 안내. 브라우저가 외부 타일에 접속하므로 “제3자 요청 없음”으로 설명하지 않음. 후보명·임대료·uid·PNU를 타일 요청에 싣지 않음 |

지도 공개 URL 설정은 **`NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty`** 1개를 추가 제안한다. style이 참조하는 glyph/sprite/tile URL은 환경변수로 선택한 스타일에서 읽고 제품 코드에 별도 외부 URL을 하드코딩하지 않는다. 공개 URL이며 비밀 키가 아니다. `.env.example`과 운영 문서의 Vercel 허용 변수 목록을 함께 갱신한다. 주소 API의 서버 키·icn1은 그대로 유지한다.

계획 단계 실제 응답: Liberty JSON HTTP200(curl), 43,079bytes, style spec8, CORS `*`. OpenFreeMap의 planet 벡터 소스·sprite·Noto Sans glyph 경로를 확인했다. 기본 라벨은 latin/nonlatin 조합이므로 **한글 우선 라벨과 Hangul glyph의 브라우저 표시 성공은 아직 미검증**이다. Python urllib에서는403, curl에서는200이었으며 원인은 단정하지 않는다. PR A에서 실제 Chromium/모바일·Preview의 스타일/타일/glyph를 확인하고 계속403이면 그 응답을 보고한다. 검증 없이 공급자를 바꾸지 않는다.

폰트/라벨은 로컬 비라틴 이름을 우선하고 없으면 원래 이름으로 fallback한다. 번역/이름 추정은 하지 않는다. 실제 서울 타일 속성과 한글 렌더를 확인한 뒤 표현식을 확정한다. 키 발급·유료 플랜·타일 서버 구축은 필요하지 않다.

## 9. 저장 모델 버전 배지 — 별도 소형 PR M 권장

현재 `comparisons.preset_version=0.3`을 단순히 `academyV0.version=0.4.0`과 비교하면 #29 이후 저장까지 매번 “구버전”으로 오인한다. localStorage의 마지막 화면 버전만으로 다른 저장 기록의 버전을 추정하지 않는다.

제안:

1. `comparisons.scoring_model_version text NULL` 추가. 기존 행은 NULL 그대로 두고 **미기록**으로 취급한다. 기존0.3 필드는 입력/가중치 계약으로 유지하고 명명 가중치 프리셋을 채점 모델로 재해석하지 않는다.
2. 새 `save_comparison_v2`는 현재 저장 RPC를 호출한 뒤 실제 사용 모델 버전을 같은 트랜잭션에 기록한다. 구RPC 시그니처/반환·RLS·후보/비교 원자성은 유지한다. **구클라이언트의 구RPC 저장은 모델 열을 NULL로 초기화**하도록 기존 save 함수도 보완해 이전 태그가 거짓으로 남지 않게 한다. 권한과 security/search_path는 기존 계약을 대조한다. `load_comparison`의 기존 `to_jsonb(c)`는 새 필드가 포함되는지 검증한다.
3. 태그는 현재 결과들이 같은 모델로 계산됐을 때만 남긴다. 부분 실패/버전 미상 상태를 현재 모델로 인증하지 않는다. 재계산 결과를 자동 DB 저장하지 않고 사용자의 저장 시점에 갱신한다.
4. 배지: 알려진 구버전은 “v0.3 → v0.4.0으로 다시 계산 중/계산됨”; NULL은 “저장 당시 모델 미기록 — v0.4.0으로 다시 계산”; 동일 버전은 전환 배지 없음. 실패는 “재계산 실패·다시 시도”이며 옛 점수를 현재 모델 점수로 표시하지 않는다. 재계산 후 저장하면 새 버전 기록으로 안내를 정리한다.

**기존 객체 변경 있음:** 비교 테이블에 nullable 열 추가, 기존 save 함수 교체, 새 저장 RPC·권한 추가. 기존 행 백필/삭제·기존 열/테이블 DROP 없음. 새 overload로 기존 RPC 해석을 모호하게 만들지 않는다. 별도 migration·dry-run·push 승인을 받는다. 롤백은 이전 앱/구RPC로 돌아가며 확장 열과 저장 데이터는 보존한다.

검증: 진짜0.3 태그/NULL/0.4.0, 원래 가중치·후보·순서 보존, 재계산 성공/실패/재시도, 재저장 뒤 재열기, 구클라이언트 저장 뒤NULL, 다른 uid 접근 차단, 태그 쓰기 실패 시 후보/비교 쓰기까지 원자 롤백. 이것은 저장 내용의 정합성이므로 부수 기록 fail-safe로 삼키지 않는다. 기존 활동/투영 부수 트리거의 예외 격리는 유지한다.

## 10. 검증·완료 기준

§8 완료 기준 원문: **“열 선택 ↔ 마커 선택 동기화, 모바일 3탭 동작”**.

| 검증 | 통과 기준 |
|---|---|
| 좌표 단위 검산 | 후보 마커/중심이 실제 채점 RPC 인자와 숫자 그대로 일치. GeoJSON 순서[lng,lat], 임의 중심 치환 없음. 원주128점의 geography 거리 목표800/1000m 오차≤1m |
| 역·학교 대조 | 고정 후보별 ID 집합·거리·학교급·반경을 기존 exposure scene/원천 SQL과 대조. 같은 원천 snapshot에서 불일치0. 1km 밖~1.2km 안 역도 포함 |
| 선택 | 열→마커/마커→열, 키보드/칩, 정렬/수동순서/삭제/층 변경/동일 좌표 다층 선택. 선택 변경으로 채점 RPC/Worker0회 |
| 모바일 | 매트릭스↔지도↔근거, 카드 축→근거, 닫기 복귀, 탭 포커스·390px/1024px 경계, 값·근거 동일, 가로 넘침0 |
| lazy·지도 장애 | 초기 JS/요청0 기준, 모바일 탭 전 지도 요청0, 지연·실패·WebGL 불가에도 매트릭스/저장 가능, 인스턴스·리스너 정리 |
| S3-2 회귀 | 실제 로컬 Auth/RPC/Worker/Realtime. pending→ready 선택 유지·새로고침 없이 점수 갱신, 구독 중복 없음·uid 격리 유지. mock ready 이벤트로 대체하지 않음 |
| 점수 | a83.10201719669011 / b92.60289331263688 / c82.67204741731668 / d81.84736541572254 / e85.08500496915157. 지도 유무·모바일·저장 전후 동일 |
| 성능 | §7 bundle·초기 요청 예산, 지도 열린5후보 슬라이더100회 p95≤100ms/max 기록. 지도 RPC는30회 직접SQL warm p95<1,000ms, cold·HTTP 별도 기록 |
| 권한·DB | 새 map RPC anon 거부/authenticated 성공, 입력 범위 검사·쓰기 없음, 실제 기존 6조합 채점 계약 불변. M은 두 uid 저장 격리·원자성 |

Vitest(선택/기능 데이터·지연 gate·버전 배지), PostGIS 통합(거리/경계/권한), 기존 Playwright 핵심 E2E 확장(등록→지도/열 선택→3탭→슬라이더→저장/재열기)을 사용한다. CI는 실제 로컬 Supabase·공개 snapshot·실제 MapLibre/WebGL을 사용하고 외부 주소/지도 네트워크만 고정 응답으로 분리할 수 있다. 외부 타일 라이브 검증은 Preview에서 따로 실행해 fixture 시험과 구분한다.

`pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`, migration 있는 PR의 `pnpm test:db`, E2E를 실행한다. 결과는 `docs/validation/s3-3-{a,b,model}-*.md`에 코드SHA·환경·실제/fixture·원천 snapshot·cold/warm·bytes·p95/max·미실행 항목을 남긴다. 원격 새 함수 성능/계약 실패 시 원인을 보고하고 다음 실행으로 넘어가지 않는다.

## 11. 사용자가 처리할 단계

1. 아래 D1~D5와 본 계획을 승인한다. 승인 뒤 screens의 단계 차이·지도 URL 허용 목록을 별도 문서 커밋으로 반영한다.
2. PR A 배포 전 Vercel의 사용할 Production/Preview에 공개 `NEXT_PUBLIC_MAP_STYLE_URL`을 등록한다. `.env` 로컬값도 맞춘다. OpenFreeMap 계정/API 키나 추가 서버 비밀은 필요 없다. NEXT_PUBLIC_*는 빌드 때 들어가므로 **설정 후 새 배포**에서 확인한다.
3. A/M의 migration은 각각 최종 dry-run·해시·기존 객체 변경 여부·권한/행 영향·로컬 검증 보고를 검토하고 원격 push를 별도로 승인한다. 계획 승인은 원격 push 승인이 아니다.
4. PR별 리뷰·머지는 사용자가 한다. 실제 Preview에서 모바일3탭·한글·동일 건물 여러 층 선택을 대조할 수 있도록 URL과 검증 방법을 제공한다.
5. Small 전환/공개 전 합본 재시험, 익명 삭제 활성화, 13,542건 좌표 교체는 기존 별도 승인 범위다. S3-3 배포와 함께 실행하지 않는다.

## 12. 확정 결정 (2026-10-07 사용자 승인)

| ID | 선택지 | 추천과 이유 |
|---|---|---|
| **D1 PR 분할** | ①지도 A/B + 독립 모델M 총3개 / ②지도와 배지를 묶은2개 | **①**. 지도 번들/데이터, 선택 UI, 저장 계약을 각각 검토 가능 |
| **D2 학원 점** | ①S3-4 직후 첫 후속 과제로 명시 / ②줌15+ 입시·보습 학원 점도 A에 포함 | **①**. 이번 요청·S3-3 행의 후보/역/학교 범위 유지. ②선택 시 데이터 계약·검증 범위를 승인 전에 보완 |
| **D3 지도 좌표 데이터** | ①가벼운4326 map RPC 추가 / ②기존5186 scene의 클라이언트 역변환 | **①**. 거리/원/Point를 PostGIS에서 검산하고 대용량 도형 재조회·새 투영 라이브러리를 피함. migration 승인 필요 |
| **D4 모델 배지 방식** | ①실제 모델 nullable 열+버전 저장 RPC / ②DB 변경 없이 “현재 모델로 재계산” 공통 안내만 | **①**. 알려진 불일치·동일·미기록을 정확히 구분. ②는 저장 당시 버전 판별 요구를 완전히 충족하지 못하는 임시안 |
| **D5 같은 좌표 후보** | ①동일 위치 묶음 마커+층별 선택 목록/칩 / ②마커는 선택 후보만, 모든 후보는 칩에서 선택 | **①**. 지도에서 후보 여러 개임을 알리면서 a/d/e의 원래 좌표를 보존 |

## 13. 이번 계획 작성에서 확인한 것과 남은 실증

확인 완료: #29 MERGED/main80be024, 지정 문서·S3-2 A/B/C/D5·v0.4.0 검증 읽기, 현재 store/저장/RPC 계약, 공식 타일 약관·라이선스, Liberty HTTP200/좌표 소스 선언, MapLibre4.7.1 배포 파일 크기. 제품 코드·migration·원격 데이터 변경은0이다.

구현 후 확인할 것: Next 최종 번들·초기 네트워크 분리, 실제 한글 타일/glyph·WebGL·Preview 접근, 새 지도 SQL 비용/권한, M의 원자 저장과 구클라이언트 호환, 3탭과 실제 Realtime 회귀. 계획 수치와 사용자 추천안을 실측 통과 또는 이미 승인된 결정으로 표현하지 않는다.

## PR 1 착수 기록

D1~D5는 모두 추천안으로 승인됐다. M은 nullable 모델 열·구RPC의 NULL 초기화·별도 v2 RPC로 혼합 버전을 지원한다. 기존 객체 변경 여부·권한·롤백·로컬 검증·최종 dry-run을 보고한 뒤 원격 push 승인을 요청한다. 지도 A/B 코드는 이 PR에 포함하지 않는다.


2026-10-07 PR 1(M) 승인 migration1개 원격 적용·혼합 클라이언트 저장·uid 격리·재열기·기존 미기록 배지 확인 완료. [실측·검증 경계](../validation/s3-3-model-20261007.md#사용자-승인-후-원격-적용검증)를 기록했으며 머지는 사용자가 수행한다.
