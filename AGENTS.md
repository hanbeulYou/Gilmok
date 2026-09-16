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

- **S1 데이터 기반** (PR 1 로컬 저장·적재 기반)
- 적재 범위: 인구·생활인구·교통·상가·학원·학교는 서울 전체, 건축물·실거래·임대동향은 강남구 한정. 서울 전체 건축물 적재는 S2 초반 별도 태스크.
- RPC: `demand`, `flow`, `transit`, `market`, `compete`, `building`, `rent`의 7개 데이터 묶음과 `meta`. 점수·과목 기준·학원 등록 가능성 판정은 S2, 캐시 미스 사용자 흐름은 S3, 공동주택 세대수는 v2.
- 완료 기준: `docs/planning/location-simulator.md` 스프린트 계획 표 참조
- 이 절은 스프린트가 끝날 때마다 갱신한다.
