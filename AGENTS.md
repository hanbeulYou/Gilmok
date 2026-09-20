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

- 외부 API는 `/ingest` 안에서만 호출한다. 프론트·Edge Function은 Supabase만 본다.
- 좌표는 DB에 EPSG:4326으로 저장. 거리 계산은 `geography` 또는 5186 변환 후.
- 추정값에는 반드시 `estimated` 플래그. 추정 로직은 `data-sources.md`에 적힌 것만 쓴다. 새 추정이 필요하면 문서에 먼저 추가.
- 로컬 인증키·비밀은 `.env`에만. GitHub Actions에서는 Secrets를 실행 환경에 주입한다. 키 값은 코드·문서·로그에 기록하지 않는다. `.env.example`을 항상 최신으로 유지하고, `.gitignore`에 `.env*`와 예외 `!.env.example`을 둔다.
- 사용자가 입력한 임대료 등 개인 데이터는 다른 사용자 집계에 절대 쓰지 않는다. RLS로 강제.

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

- **S1 데이터 기반** (PR 1~3은 통합 GitHub #6으로 main 반영 완료. PR 4 [GitHub #7](https://github.com/hanbeulYou/Gilmok/pull/7) 상가·학원·학교 로컬 실데이터·R2 검증 완료, 리뷰 대기·미머지. S1 전체는 진행 중)
- 적재 범위: 인구·생활인구·교통·상가·학원·학교는 서울 전체, 건축물·실거래·임대동향은 강남구 한정. 서울 전체 건축물 적재는 S2 초반 별도 태스크.
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
- 용량 기준: 사용자 승인으로 로컬 VACUUM FULL 1회 후 171,467,279 byte. 추가 VACUUM·원격 VACUUM은 하지 않는다. 적재 트랜잭션의 임시 공간과 커밋 후 용량을 구분한다.
- RPC: `demand`, `flow`, `transit`, `market`, `compete`, `building`, `rent`의 7개 데이터 묶음과 `meta`. 점수·과목 기준·학원 등록 가능성 판정은 S2, 캐시 미스 사용자 흐름은 S3, 공동주택 세대수는 v2.
- 완료 기준: `docs/planning/location-simulator.md` 스프린트 계획 표 참조
- 이 절은 스프린트가 끝날 때마다 갱신한다.
