# AGENTS.md — 길목(GILMOK)

이 파일은 이 리포지토리에서 작업하는 모든 AI 에이전트가 세션 시작 시 가장 먼저 읽는다.

## 1. 기준 문서 (Single Source of Truth)

1. `docs/planning/location-simulator.md` — 기획서. 무엇을 왜 만드는지. **코드와 이 문서가 충돌하면 문서가 맞다.** 문서를 바꿔야 한다고 판단되면 코드를 고치지 말고 사용자에게 먼저 말한다.
2. `docs/planning/data-sources.md` — 데이터 소스 명세. 엔드포인트·컬럼·좌표계·적재 방식.
3. `docs/planning/scoring-spec.md` — 채점 명세 (S2 전에 작성됨). 없으면 채점 로직을 구현하지 않는다.
4. `docs/planning/screens.md` — 화면 정의 (S3 전에 작성됨). 없으면 UI를 임의로 설계하지 않는다.

## 2. 프로젝트 한 줄 정의

서비스업 창업자가 후보 점포 여러 곳을 3D 지도 위에서 같은 채점표로 비교하고, 가중치를 바꿔가며 "목"을 검증하는 입지 시뮬레이터. 첫 버전: 서울, 학원업, 후보지 최대 5곳.

## 3. 스택 (버전 고정)

- Next.js 15 (App Router), TypeScript strict, pnpm
- Supabase: Postgres 17 + PostGIS 3.3.7, Auth, Edge Functions (Deno). 로컬 기준은 Supabase CLI 2.72.7의 PostgreSQL 17.6 이미지다. PR 1에서 CLI가 16을 거부하고 이미지가 PostGIS 3.3.7을 제공함을 확인해 사용자 승인으로 조정했다.
- 지도: MapLibre GL JS 4.x, deck.gl 9.x (MapboxOverlay 모드)
- 상태: Zustand
- 스타일: Tailwind CSS 4
- 테스트: Vitest (단위), Playwright (E2E, S3부터)
- 배치 적재: Python 3.12 + PublicDataReader + DuckDB + psycopg. 공공데이터 수집·Parquet 집계를 재사용하기 위해 Python으로 통일한다. PublicDataReader의 소스별 호환성은 실제 응답으로 확인한다.
- 데이터 저장: Cloudflare R2에 원본 Parquet, Supabase에 조회용 집계와 공간 조회에 필요한 최소 개체 정보. R2 환경변수가 없으면 로컬 파일시스템(`INGEST_LOCAL_ROOT`, 기본 `.local/ingest`)을 사용한다. DuckDB 집계는 `/ingest`에서 실행한다.
- 배포: Vercel (프론트), Supabase (DB/Functions), GitHub Actions (배치 스케줄)
- 개발 환경: 원격 Supabase 프로젝트와 R2 버킷은 사용자가 준비한다. 준비 전에는 `supabase start`로 로컬 Supabase에서 진행한다.

버전을 올리려면 이 파일을 먼저 수정하고 이유를 커밋 메시지에 적는다.

## 4. 폴더 구조

```
/app                 Next.js 라우트
/components          UI 컴포넌트 (map/, compare/, candidate/, report/)
/lib                 클라이언트 유틸 (scoring/, visibility/, geo/)
/workers             Web Worker (가시성 레이캐스트)
/supabase
  /migrations        SQL 마이그레이션 (수기 편집 금지, supabase CLI로 생성)
  /functions         Edge Functions
/ingest              배치 적재 스크립트 (소스별 1파일)
/docs/planning       기획 문서
/tests
```

## 5. 지켜야 할 규칙

### 데이터

- 외부 데이터 API는 `/ingest` 안에서만 호출한다. 프론트·Edge Function은 Supabase만 본다. PR 8 사용자 승인 예외: DB의 pg_net webhook이 고정 GitHub repository_dispatch 엔드포인트를 호출하여 Python 주소 워커를 깨울 수 있다. 주소·PNU 전송 및 DB/Edge의 데이터 API 호출은 허용하지 않는다. 원격 전환 후 수동 활성화한다.
- S3 사용자 승인 예외: 사용자 요청으로 시작되는 주소 자동완성·지오코딩은 Next.js Route Handler에서 호출할 수 있다. 키는 서버 환경변수에만 두고 결과를 `geocode_cache`에 캐시하며 uid당 일일 제한을 둔다. 배치·건축물 대장 조회는 여전히 `/ingest`에서만 호출한다. 구현은 S3-2다.
- 좌표는 DB에 EPSG:4326으로 저장. 거리 계산은 `geography` 또는 5186 변환 후.
- 추정값에는 반드시 `estimated` 플래그. 추정 로직은 `data-sources.md`에 적힌 것만 쓴다. 새 추정이 필요하면 문서에 먼저 추가.
- 로컬 인증키·비밀은 `.env`에만. GitHub Actions에서는 Secrets를 실행 환경에 주입한다. 키 값은 코드·문서·로그에 기록하지 않는다. `.env.example`을 항상 최신으로 유지하고, `.gitignore`에 `.env*`와 예외 `!.env.example`을 둔다.
- 사용자가 입력한 임대료 등 개인 데이터는 다른 사용자 집계에 절대 쓰지 않는다. RLS로 강제.
- 용량 정책: **로컬 DB에는 500MB 제한을 적용하지 않는다.** 원격 Supabase는 S1까지 무료 플랜을 유지하고, S2 서울 전체 건물 적재 시점에 Pro 전환을 검토한다. 이후 PR에서 용량을 이유로 데이터 구조·필드·해상도·적재 범위를 바꾸지 않는다. DB·테이블·인덱스·원본·임시 공간의 실측만 기록하며, 원격 플랜 한도에 접근하면 현황을 보고한다. 자동 축소·유료 전환은 하지 않는다.

### 코드

- 마이그레이션은 `supabase migration new`로 만든다. 기존 마이그레이션 파일은 수정하지 않는다.
- 채점 로직은 순수 함수로 `/lib/scoring`에 두고, 서버(Edge Function)와 클라이언트(가중치 재계산)가 같은 코드를 쓴다.
- 3D 지도 코드에서 외부 타일·스타일 URL은 환경변수로. 스타일은 MapLibre 호환 오픈 스타일만 쓴다.
- 새 라이브러리 추가는 이유를 PR 설명에 적는다. 3D/지도 관련 라이브러리는 MapLibre·deck.gl 외에 추가하지 않는다 (CesiumJS·Three.js 직접 사용 금지, 필요하면 사용자에게 먼저 제안).

### 작업 방식

- 스프린트 작업을 받으면 **코드보다 계획을 먼저** 낸다: 건드릴 파일, 마이그레이션, 테스트, 예상 리스크. 사용자 승인 후 구현.
- 한 PR은 하나의 스프린트 태스크. 기획서의 "완료 기준"을 PR 설명에 복사하고 각 항목 충족 여부를 체크한다.
- 완료 조건: `pnpm lint`, `pnpm typecheck`, `pnpm test` 통과. S1은 승인된 범위의 실제 데이터를 적재한 뒤 대치동 좌표 3건에서 각각 반경 500m·1km로 `score_inputs`를 검증한다. 각 좌표·반경 조합의 DB 실행 시간 p95 < 1,000ms가 성능 기준이며 HTTP 왕복 시간은 기록만 한다.
- 각 PR 설명 끝에 (a) 완료 기준 체크리스트, (b) 실제 응답으로 확인해 문서를 고친 항목, (c) 다음 PR 예고를 붙인다. 실제 응답을 확인하지 않았다면 명시하며 사용자 결정을 API 검증 결과로 표현하지 않는다.
- 기획서에 없는 기능을 "있으면 좋겠다"고 추가하지 않는다. 제안은 PR 설명의 "제안" 절에 적고 구현하지 않는다.
- 모르는 것(API 응답 스키마, 좌표계, 쿼터)은 추측하지 않는다. `data-sources.md`의 "확인 필요" 항목은 실제 응답을 받아 확인한 뒤 문서를 갱신하는 것까지가 작업이다.
- 확인 결과가 사용자의 승인된 결정과 충돌하면 해당 구현을 진행하지 말고 먼저 보고한다.

## 6. 커밋·브랜치

- 브랜치: `s1/데이터-스키마`처럼 `s{스프린트}/짧은-설명`
- 커밋 메시지: 한국어 또는 영어, 첫 줄 50자 이내, 본문에 "왜"
- 기획 문서 수정은 코드와 별도 커밋

## 7. 현재 스프린트

- **S2 완료 — v0.3, 대치동3곳 검증 통과(b>a>c)**. PR #18 머지 및 2026-09-26 사용자 마감 승인. 다음 작업은 S3이며 [S3 인계](docs/planning/location-simulator.md#s3-인계--s2-마감)의 계약·결측 처리·신뢰도 사유와 보류 목록을 따른다. 서울 전체 건물 적재·Pro 전환 검토, 임대료 lo/hi 보정·임대동향 공간 연결은 이월했다. 원격 전환·webhook 활성화는 아직 미실행이다.
- 적재 범위: 인구·생활인구·교통·상가·학원·학교는 서울 전체, 건축물·실거래·임대동향은 강남구 한정. 서울 전체 건축물 적재는 S2에서 이월했으며 Pro 전환 검토 후 별도 태스크로 진행한다.
- 생활인구는 사용자 승인에 따라 250m 격자로 전환한다. 공간 키는 `(resolution_m, cell_id)`, 경계는 `population_cells`다. 원천 EPSG:5179 → DB EPSG:4326. 실제 경계·생성 규칙과 컬럼·용량 증거는 `docs/validation/pr2-population-20260919.md`를 따른다. 기존 집계구 테이블은 보존한다.
- 생활인구 DB는 고정 연령 컬럼을 사용하고 JSONB는 채택하지 않는다. 연령대별 유효 날짜만 평균내며 표본 수 `sample_days`는 total 기준이다. 학원 생활인구 입력은 원천 15~19세 그대로, 0~4·5~9세는 원천에서 분리 불가하여 NULL. `docs/planning/data-sources.md`의 결측·편향 정책을 따른다.
- 날짜별 임시 파일에는 컬럼별 합계·유효 일수만 저장하고 최종 합계÷일수로 집계한다. 평균의 평균 금지. 실측 living_pop+PK 98,787,328 byte(98.79MB), 주민등록·경계 추가 직후 로컬 DB 전체 122,285,203 byte(122.29MB). 재적재 중 이전 행 공간도 포함한 측정과 검증 조건은 data-sources.md를 따른다.
- 행정동은 SGIS 기반 공개 가공물 vuski/admdongkor 2026-07-01판, 서울 427개를 2026-08 주민등록 코드와 전수 매칭했다. SGIS `adm_cd` 대신 행안부 `adm_cd2`의 말미 00을 제거해 조인한다. 출처·라이선스 표시는 `docs/data-attribution.md`를 유지한다.
- PR 2 R2 원본 6개 객체 게시 및 DuckDB 재읽기 검증 완료. 생활인구 411,512행 재집계 불일치 0. 원격 Supabase는 미전환이며 로컬 기본을 유지한다.
- PR 3 교통은 2026-06~08 월 합계의 합÷92일인 일평균이다. 6월 지하철 전체·버스 100/5511번으로 월 합계와 중복 규칙을 일별 응답과 대조했다. 7월 지하철의 정확한 복제 621행만 집계에서 제거하며 원본은 보존한다. 노선별 환승역·버스 정차 순번·개명 구간을 임의 중복 제거하지 않는다. 신분당선 누락·대체 추정 없음.
- 교통 R2 원본 8개 객체·재읽기 재집계 대조 완료. 서울 위치 11,620개, 시간대 집계 264,696행(버스 6개 정류장 144행은 3개월 미충족으로 NULL). 승하차량 기준 조인율은 지하철 99.71~99.74%, 버스 95.24~95.42%. 90% 미만 또는 분모 미확인 시 다음 적재 전에 보고한다. 위치는 9월 조회본이므로 6~8월 당시 위치·개폐 이력은 미검증이다.
- S2 인계: **교통 축은 요일 구분 없는 일평균, 생활인구는 평일/주말 분리**다. 버스 누락 4.6543%는 균일하지 않으며 서울 외 연결 노선·2xx ID 대역에 편중된다. 유형 내 누락률은 서울광역 49.96%, 마을 0.63%. 상세·위치 판정 한계는 docs/validation/pr3-bus-coverage-20260919.md를 따른다. 일괄 보정은 하지 않는다.
- PR 4: 서울 상가 554,092행, 학원·교습소 25,508행, 초·중·고 1,319행. stores는 사용자 승인에 따라 업소번호·대/중/소 코드·층·geom 6컬럼만 둔다. 상호명·주소·표준산업분류는 R2 원본에만, 출처는 스냅샷 메타데이터에 둔다. 분야·계열·과정 원문을 보존하고 국어·논술 분류는 S2로 남긴다.
- 기준 브랜치는 **main**, PR 4 브랜치는 `s1/상가-학원-학교`다. `s1/supabase-인증키`는 원격·로컬 삭제 완료. 다음 PR도 main에서 분기한다. PR 설명 첫 줄은 `base: main`이다.
- PR 4 지오코딩: 고유 주소 13,542개 중 13,491개 확보, 51개 실패(학원 86행·학교 7행). 성공/실패 캐시와 호출 전 영속 claim으로 같은 주소 재호출을 막는다. provider가 도로명·건물번호를 바꾼 응답은 거부한다. 자세한 한계·학교 캠퍼스 대표점·주소 대조는 docs/validation/pr4-places-20260920.md를 따른다.
- 용량 기준: 사용자 승인으로 로컬 VACUUM FULL 1회 후 171,467,279 byte. PR 8 승인으로 갱신 커밋 후 별도 연결의 VACUUM (ANALYZE)를 허용한다. 추가 VACUUM FULL과 이번 PR의 원격 실행은 하지 않는다. 적재 트랜잭션의 임시 공간과 커밋 후 용량을 구분한다.
- 2026-09-20 사용자 결정으로 이전 500MB 목표를 폐기했다. PR 4 커밋 후 로컬 DB 312,110,227 byte는 관측값이며 다음 적재의 통과 조건이 아니다. S1 원격 무료 유지, S2 서울 전체 건물 적재 시 Pro 검토를 따른다.
- PR 5는 `docs/planning/pr5-buildings-plan.md` 승인 범위로 구현한다. 주 소스는 SHP(PNU 100%, 대장 연결률 우위, CC BY, 주 원본의 API 약관·쿼터 비의존), WFS는 SHP에 없는 도형만 source를 구분해 보조 추가한다. WFS는 대장 미연결·대장 기반 집계 제외이며 3D 표시와 차폐 계산에는 포함한다. 높이는 원천 양수→층수×3.3m(1층 단층 상업건물 4m)→NULL/unknown 순서다. unknown의 표시·차폐 입력은 4m이고 신뢰도에 unknown 비율을 반환한다. SHP 중복 1쌍은 하나만, 자기 교차 4건은 ST_MakeValid로 정리하고 원본은 R2에 그대로 보존한다. 운영은 **수동 다운로드 후 R2 raw/에 게시, 갱신 주기 분기**다. 서울 전체 원본 중 S1 DB 적재는 강남구만이다.
- PR 5 실측: SHP 28,227개 + WFS 보조 1,885개, 표제부 24,324행, 층별개요 198,637행. SHP 대장 연결 19,016개(67.37%), 미연결·층별개요 부모 없음 66행도 보존. unknown 6,152개는 4m 차폐 입력과 신뢰도 분모에 포함한다. WFS 겹침 3,231개·붕괴 1개는 제외 기록을 남겼다. R2 원본 5개 재읽기 일치, 건물 RPC 6개 조합 DB p95 16.084~157.651ms. `docs/validation/pr5-buildings-20260920.md`를 따른다.
- PR 6 강남구 실거래·임대동향은 `s1/실거래-임대동향`에서 실제 적재·검증 완료했다. 매매 원본 2,092행·유효1,744행·집계180행, 법정동14개, 임대동향원본1,810행·집계34행이다. R2 27개 객체 재읽기·매매집계 DB전수 대조 불일치0, rent RPC DB p95 0.122~0.485ms. 상권/권역12개 공간 연결은 정의·분기 적용 미확인으로 비활성화하여 실제 rent_level은 NULL이다. `docs/validation/pr6-rent-20260920.md`를 따른다. 실거래 일반/집합 중 표본이 많은 유형을 기본값으로 반환하고 5건 미만은 NULL. 임대동향은 포함 상권→공식 정의에 포함된 권역→NULL과 rent_level(district/region/NULL)을 반환하며 근접 상권 대체는 금지한다. 공식 강남 권역 경계/포함 자치구를 확인하기 전에는 region을 NULL로 둔다. PR 7에서 전체 7개 묶음 `score_inputs` 통합·S1 완료 검증을 통과했다. PR 7(GitHub #10)은 main 머지 완료다. 현재 건물 RPC 데이터 계약을 실제 렌더러·레이캐스트에서 소비하는 작업은 후속 스프린트이며 가시성 점수/학원 적합성은 구현하지 않았다.
- PR 7 재검토: `score_inputs(lat,lng,radius_m,floor,address DEFAULT NULL)` 입력 계약 v1.2, main 머지 완료다. flow는 유효 격자 부분 합계·시간별 커버리지와 80% 미만 low_coverage를 반환한다. 주민등록 15~18세는 단일 연령 정확 합계이며 생활인구 15~19세와 구분한다. 도형/대장 미연결 시 주소 캐시(30일)→private 큐→`ingest/building_on_demand.py` 경로를 쓴다. 최초 미스는 pending이며 PR 8 이벤트/시간별 워크플로우는 원격 활성화 전, 실행 방법·전체 JSON 계약은 `docs/planning/data-sources.md` 3절을 따른다. unknown 비율은 30㎡ 미만 또는 주용도 부속·창고를 분자/분모에서 제외하고 원래/제외 수를 병기한다. 대치 500m는 27/194=13.92%. 6조합 각 30회 DB p95 14.803~61.198ms, HTTP 기록·내부 EXPLAIN·독립 원천 대조·묶음별 결측 테스트 통과. `pnpm lint/typecheck/test/test:db` 통과(Python 205·Vitest 1, DB 121). `building.all_floors`는 요청 층과 무관한 전 층 용도·면적 배열이며 기존 floor_use를 보존한다. `docs/validation/pr7-building-all-floors-20260922.md`가 최신 증거다. 임대 공간 연결은 비활성, 기존 RPC·buildings_in_radius 병존. 채점/UI는 미구현이다.
- RPC: `demand`, `flow`, `transit`, `market`, `compete`, `building`, `rent`의 7개 데이터 묶음과 `meta`. 점수·과목 기준·학원 등록 가능성 판정은 S2, 캐시 미스 사용자 흐름은 S3, 공동주택 세대수는 v2.
- 완료 기준: `docs/planning/location-simulator.md` 스프린트 계획 표 참조
- 이 절은 스프린트가 끝날 때마다 갱신한다.

- PR 8: 월간 6개 소스 자동, 상가·건물 SHP·임대동향 수동. 소스별 atomic promotion 후 별도 VACUUM ANALYZE. 주소 pending은 DB webhook→repository_dispatch, 매시간 sweep 보완이며 10분 폴링은 사용하지 않는다. `INGEST_REMOTE_ENABLED` 기본 false. [운영](docs/operations/data-refresh.md), [S2 인계](docs/planning/location-simulator.md#s2-인계--s1-마감)를 따른다.

- 2026-09-23 승인: scoring-spec.md v0.1.1 기준 S2-1(medium) 먼저 PR, 머지 후 main에서 S2-2(high). R6 유해 용도 관측 시 표제부 gross_area<1650㎡이면 false, ≥1650/결측이면 NULL; 실간 거리 계산 제외. gross_area는 현재 표제부 DB에만 있어 S2-2에서 RPC에 추가한다. S2-3·S2-4는 별도 세션.

- S2-1 2026-09-23: 10,127셀×800/1000m×8지표=162,032행, RPC 20,254회. 수집 463.912초·게시/검증/적재 19.903초(합계 483.816초), R2 재계산·DB 바이너리 전수 대조 불일치 0. cluster.saturation은 근거 전용이며 NULL/0 분모는 NULL, 점수 제외. [검증](docs/validation/s2-1-score-reference-20260923.md) 및 [운영](docs/operations/score-reference.md)을 따른다. S2-2는 이 PR 머지 후 main에서 시작하며 reference 조회 정밀도도 보존한다.

- S2-1 GitHub #12 머지 완료. S2-2는 명세 v0.1.2 / score_inputs v1.3 / ScoreResult v0.1이며 gross_area가 도형·주소 경로에 포함된다. 기준 분포 snapshot 20260923T111436Z는 162,032행, HTTP 정밀도 보존 RPC score_reference_distribution의 비NULL 155,815개 값과 DB binary가 일치한다. 실제 역삼로460 3층=100·4층=90, 고정 3좌표×2반경 ScoreResult 생성 및 lint/typecheck/test(39·234)/test:db(137) 통과. 학여울은 건물 부재로 3축 결측·total=NULL이며 순위 해석은 하지 않는다. [검증](docs/validation/s2-2-scoring-20260923.md)을 따른다. S2-3·S2-4는 별도 세션이다.

- 2026-09-23 PR #13 후속 사용자 결정: 명세 v0.1.3 §6은 백분위 5축 중 2축 이상 결측일 때 total=NULL이다. 규칙 축 결측은 재배분 근거를 남기고 계산한다. §5.7 지하층은 R4 없이 R7 −25만 적용한다. 기존 학여울 total=NULL 기록은 v0.1.2 당시 결과다. 기준 분포·프리셋 0.1.2와 입력 v1.3은 유지한다.

- S2-3 2026-09-23: GitHub #13·#14 머지 후 구현. 명세 v0.1.4는 후보 도형 부재 fallback에 candidate_footprint_missing_self_occlusion_unaccounted 근거와 신뢰도 −5를 추가한다. visibility_inputs v0.1은 1km 건물·학교와 2km 이내 최근접 역을 5186으로 반환하고 Worker/Node는 같은 순수 함수를 실행한다. 역삼로460 3층 visible_ratio=0.11649874055415617, 역 20점 가시1/차폐10/제외9. 310샘플 독립 PostGIS 판정 불일치0, Node/브라우저 Worker 결과 일치. lint/typecheck/test(63·234)/test:db(144) 통과. [현장 대조표](docs/validation/s2-3-visibility-field-report.md), [검증·시간](docs/validation/s2-3-visibility-20260923.md)을 따른다. 현장 검증은 사용자 대조 전이며 S2-4는 별도다.

- 2026-09-24 PR #15 후속: 명세/ScoreResult/preset v0.2, 축 exposure 5·demand 30. 1km 내 모든 역 각각20점, 링30/60/100m×36, 내부 샘플 최대30m 이동을 적용했다. exposure_inputs는 EPSG:5186이며 기존 visibility_inputs v0.1과 raw 분포0.1.2는 보존한다. 역삼로460 3층 visible_ratio=0.12460209185993637, 역 동선4/100점 가시, 링23/108점 가시, 전체120점 이동·1/318점 제외. Worker/Node 결과 및 독립 PostGIS 검산 일치. lint/typecheck/test(68·234)/test:db(146) 통과. [현장 대조표](docs/validation/exposure-v02-field-report.md), [검증](docs/validation/exposure-v02-20260924.md)을 따른다. S2-4 실제 학원 검증·임대료 보정은 별도 태스크다.

- 2026-09-25 PR #16 후속: 명세/ScoreResult/preset/model_version0.2.1. exposure는 “건물 앞 도로·맞은편에서의 간판 노출”, 점수는20/40/60m×36방향 링만 사용한다. exposure_inputs_v021은 역1.2km·학교1km·건물1.23km(이동30m 포함), EPSG:5186이다. 역/학교 각각 첫 가시 샘플까지 거리(근거 전용·직선 샘플 추정·점수0)를 반환한다. 역삼로460 3층 가중 가시율38.383838%, 링32/108점 가시(20m20·40m8·60m4), 사용자 현장 진술의 절반 이상 기준은 미충족이다. 대치역3호선1,033.143m가 포함되며 가시 샘플이 없어 첫 노출 거리NULL이다. lint/typecheck/test(73·234)/test:db(148), Worker/Node 일치, 독립 PostGIS338판정·17동선 거리 검산 통과. [현장 대조표](docs/validation/exposure-v021-field-report.md), [검증](docs/validation/exposure-v021-20260925.md). S2-4는 별도 태스크다.

- S2-4 2026-09-26: PR #17 머지 후 고정 주소3곳+시드20260926 서울5셀 검증. [조정 전](docs/validation/s2-4-20260926.md)과 [v0.3 조정1회차](docs/validation/s2-4-v03-20260926.md)를 구분한다. 승인된 두 버그(적재 범위 밖 exposure=100, 요청 층10003 학원 미인식)를 수정하고 cluster만 p50=3.332204510175204 / p99.97=7.070653980704802 고정 선형 스케일로 변경했다. 원시 reference v0.1.2·가중치는 유지한다. preset/ScoreResult0.3, exposure scene/model0.2.2 및 v022 RPC. 실제 순위 b>a>c, 추가 조정은 사용자 판단 대기. 서울 전체 건축물 적재·원격 전환은 미실행이며 현재 적재는 강남구다.

- S2 마감 2026-09-26: PR #18 머지 확인. [명세 §8](docs/planning/scoring-spec.md#8-검증-절차--대치동-실제-학원-3곳)에 결과·cluster 스케일1회 조정·과적합 유의 사항을 기록했다. ScoreResult 최초v0.1→현행v0.3, exposure scene/model0.2.2 및 v022 RPC, 주소 pending·임대료/지역 결측·신뢰도 문자열/코드는 S3 인계를 따른다. transit 라이딩 학원 이슈는 S3 이후 프리셋v0.4 검토이며 현재 식·가중치는 유지한다.

- S3-1 2026-09-26 진행: 원격 gp3 8GB 확장·migration 30개·7단계 R2 복원 완료. 18테이블 digest 일치, 유지보수 후 DB 889,810,067 byte. 초기 복원 종료 원인은 WAL 공간 부족이며 keepalive는 보조 조치다. HTTP 검증은 anon role 3초 timeout(57014)으로 중단했다. Auth·Vault·webhook 미실행, `INGEST_REMOTE_ENABLED=false`, PR #20 Draft. [최신 원격 기록](docs/validation/s3-1-remote-20260926.md)을 따른다.
