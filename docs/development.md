# S1 로컬 개발

PR 1은 원격 API 키 없이 원본 Parquet 저장 → DuckDB 집계 → 로컬 PostGIS 적재를 검증한다. 소스별 실제 API 수집·RPC·실데이터 성능 검증은 후속 PR 범위다.

## 실행 환경

- Node.js 22.12 이상(22.x), pnpm 10.7.1
- Python 3.12, uv 0.12.15 (`uv.lock`으로 실제 의존성 고정)
- Supabase CLI 2.72.7, Docker 호환 실행기
- 확인된 로컬 DB: PostgreSQL 17.6, PostGIS 3.3.7

CLI 2.72.7은 `db.major_version = 16`을 거부한다. 사용자 승인 후 실제 로컬 이미지의 버전을 확인해 `AGENTS.md`와 설정을 조정했다. 원격 프로젝트 생성 시에도 이 기준과의 호환성을 먼저 확인한다.

macOS에서 실행기가 없다면 Docker Desktop 또는 Colima를 준비한다. 이 작업 환경에서는 별도 `gilmok` 프로필의 Colima를 사용했다.

```sh
colima start --profile gilmok --cpu 2 --memory 4 --disk 30 --vm-type vz
docker context use colima-gilmok
```

## 키 없이 설치·검증

프로젝트 루트에서 실행한다. `.env`를 복사하지 않아도 아래 검증은 동작한다.

```sh
pnpm install --frozen-lockfile
uv sync --frozen
pnpm lint
pnpm typecheck
pnpm test
pnpm ingest:smoke
```

`pnpm test`는 Vitest의 CLI 통합 검사와 Python 저장/집계 검사를 실행한다. `ingest:smoke`는 실제 데이터가 아닌 작은 합성 자료를 사용하며, 사용자 `.env`에 R2 키가 있어도 항상 로컬에 저장한다. 출력의 `002` 행은 관측값이 없어 합계가 `null`이다.

```sh
supabase start
pnpm test:db
```

`supabase start`는 마이그레이션을 적용한다. 이미 실행 중이면 새 마이그레이션은 `supabase migration up --local`로 적용한다. 첫 실행의 이미지·의존성 다운로드에는 인터넷이 필요하지만 원격 Supabase·R2·공공 API 키는 필요하지 않다.

`pnpm test:db`는 로컬 DB가 없으면 실패하며 조용히 건너뛰지 않는다. 원격 URL은 거부하고 모든 테스트 데이터를 트랜잭션 롤백으로 지운다. 공간 경계 적재·재실행·실패 보존·RLS·버전을 검증하며 S1의 실제 데이터 p95 검증을 대체하지 않는다.

## 저장소 선택과 환경변수

실제 자료를 다룰 때 `.env.example`을 `.env`로 복사하고 필요한 값만 채운다. 로컬 DB의 기본 URL은 `postgresql://postgres:postgres@127.0.0.1:54322/postgres`다. 외부 서비스 키 이름은 `.env.example`과 `docs/planning/data-sources.md` 1.1절을 따른다.

- R2 변수 4개가 모두 없거나 빈 값이면 로컬 저장을 선택한다.
- `INGEST_LOCAL_ROOT` 기본값은 프로젝트 기준 `.local/ingest`이며, 절대 경로도 사용할 수 있다.
- 로컬과 R2 모두 `raw/{source}/{YYYY-MM}.parquet`를 사용한다. 상대 경로 탈출은 허용하지 않는다.
- R2 변수가 일부만 설정되면 누락된 변수 이름을 알려주고 중단한다.
- R2 접근 오류에는 자동 로컬 전환을 하지 않는다. 오류 메시지에 자격증명을 포함하지 않는다.

R2 업로드에는 boto3, 직접 Parquet 조회에는 DuckDB `httpfs`를 사용한다. R2 연결을 선택했을 때만 확장 설치와 원격 요청이 발생하며 자격증명은 메모리에서만 사용한다. 로컬 테스트는 실제 R2 연결 성공을 증명하지 않는다.

## Supabase 인증키와 CLI

Supabase 데이터 API와 CLI의 프로젝트 관리 API는 서로 다른 인증을 사용한다.

| 환경변수 | 용도·발급 위치 |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | 브라우저·사용자 세션 조회용. 프로젝트 Connect 또는 Settings → API Keys에서 URL과 `sb_publishable_...` 키를 확인한다. RLS 적용 |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | 서버 관리자 API용. 같은 프로젝트의 API Keys에서 `sb_secret_...` 키를 발급한다. RLS를 우회하므로 Secret key에는 `NEXT_PUBLIC_` 접두사를 붙이지 않는다 |
| `SUPABASE_ACCESS_TOKEN` | CLI 프로젝트 관리·배포용 계정 Personal Access Token. 계정 [Access Tokens](https://supabase.com/dashboard/account/tokens)에서 발급. 프로젝트 Secret key와 다르다 |
| `SUPABASE_PROJECT_REF` | 원격 프로젝트 식별자. 대시보드 URL의 `/project/` 다음 값. `link --project-ref`에 명시적으로 전달한다 |
| `SUPABASE_DB_PASSWORD` | 원격 DB 연결·마이그레이션에 필요한 프로젝트 DB 비밀번호. 프로젝트 생성 시 정한 값이며 API 키가 아니다 |
| `SUPABASE_DB_URL` | Python 배치의 psycopg 직접 연결 문자열. 원격에서는 프로젝트 Connect의 Postgres 연결 문자열에 DB 비밀번호를 URL 인코딩해 넣는다 |

현재 `ingest/database.py`는 `.env`와 프로세스 환경에서 `SUPABASE_DB_URL`만 읽는다(프로세스 환경 우선). API 클라이언트는 아직 없으므로 Publishable/Secret key는 후속 구현을 위한 선택 항목이며 배치·로컬 테스트에 필요하지 않다. Secret key를 DB URL이나 DB 비밀번호 대신 넣지 않는다.

기존 `.env`를 쓰고 있다면 `SUPABASE_ANON_KEY`를 제거하고 새 Publishable key를 `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`에 넣는다. 기존 프로젝트 URL은 `NEXT_PUBLIC_SUPABASE_URL`에도 설정한다. 레거시 JWT 값을 이름만 바꿔 재사용하지 않는다. 로컬 키가 필요하면 `supabase start` 또는 `supabase status`의 로컬 값을 사용한다.

원격 CLI 실행 시 `.env`를 명시적으로 읽도록 기존 uv의 `--env-file`을 사용한다. 아래 `YOUR_PROJECT_REF`를 `.env`의 `SUPABASE_PROJECT_REF` 값으로 바꾼다. 셸의 변수 확장은 uv가 `.env`를 읽기 전에 일어나므로, export하지 않은 `$SUPABASE_PROJECT_REF`를 그대로 쓰지 않는다.

```sh
uv run --frozen --env-file .env supabase link --project-ref YOUR_PROJECT_REF
uv run --frozen --env-file .env supabase db push --dry-run
```

`SUPABASE_ACCESS_TOKEN`과 `SUPABASE_DB_PASSWORD`는 명령 환경으로 전달하므로 인자에 비밀 값을 붙일 필요가 없다. `--dry-run`은 적용 예정 마이그레이션을 확인한다. 실제 반영은 내용을 검토한 뒤 수행한다. 이 설정 변경에서는 원격 연결·배포를 실행하지 않았다.

근거: [Supabase API 키](https://supabase.com/docs/guides/getting-started/api-keys), [CLI 환경변수](https://supabase.com/docs/guides/deployment/managing-environments).

## 공통 적재 경로

- `ingest/common.py`: `.env`/환경변수 설정, 같은 키 규칙을 쓰는 로컬·R2 원본 저장. 로컬 파일은 임시 파일을 완성한 뒤 교체한다.
- `ingest/aggregate.py`: `/ingest/sql`의 신뢰된 배치 SQL에서 `raw_data` 뷰를 조회한다. 같은 원본에 새 SQL을 적용해 재수집 없이 재집계할 수 있다.
- `ingest/database.py`: 원천 어댑터가 검증·변환한 `code`, `name`, `wkt` 행을 받아 행정동·집계구 경계를 적재한다. EPSG:4326만 허용한다. 빈 스냅샷은 거부한다.
- DB 적재는 소스별 교체와 성공 이력을 같은 트랜잭션으로 처리한다. 중복 키·잘못된 geometry 등으로 실패하면 이전 자료와 이력을 보존한다.
- `geocode_cache`는 캐시 스키마만 준비했으며 외부 지오코더 호출이나 S3 주소 검색 흐름은 구현하지 않았다.
- `candidates`는 사용자 소유권 RLS를 적용하고, 공통 경계 적재 함수의 대상으로 허용하지 않는다.

## PR 2 실데이터 재현

계약·실측·다음 작업은 `docs/planning/data-sources.md` §2.1·§2.6·§6이 기준이다. Supabase는 로컬을 유지한다. `.local` 자료는 Git에 없으며, 현재 워크스페이스에 있는 검증 파일 위치를 아래에 기록한다. 새 체크아웃은 명세의 제공자 파일/고정 커밋 또는 실제 R2 원본에서 복구한다.

DuckDB 공간 확장은 최초 한 번 설치한다(공개 확장 다운로드이며 API 키 불필요).

```sh
uv run --frozen python -c 'import duckdb; duckdb.connect().execute("INSTALL spatial")'
supabase migration up --local
```

주민등록·경계: 아래 명령은 원본 3종을 선택된 저장소에 게시하고 DuckDB로 다시 읽어 전체 행을 대조한 뒤, 행정동·주민등록을 로컬 DB에 원자 적재한다. R2 변수가 있으면 **실제 버킷에 게시하는 명령**이다. 기존 객체는 크기·SHA-256이 같으면 재사용하고 다르면 중단한다. 새 자료로 갱신할 때는 기준월·경계 버전·현재 행정동 코드 집합을 다시 검증한다.

```sh
uv run --frozen python -m ingest.publish_population \
  --residents .local/validation/residents-202608.csv \
  --boundary .local/validation/boundary-final/20260701.geojson \
  --grid .local/validation/grid250/match/match.shp \
  --month 2026-08 --directory .local/validation/pr2-final
```

행정동 파일은 `ingest/admin_boundaries.py`의 `BOUNDARY_URL`에 고정된 커밋을 사용하며 출처 표시를 유지한다. 격자 SHP는 공식 안내의 `match.shp`와 같은 디렉터리의 DBF/SHX/PRJ가 모두 필요하다. `grid_rows`로 CRS·규칙을 확인한 후 `load_population_cells`에 넣는다. 관측 셀 ID는 3개월 원본 `250M격자` 공백 제거 값의 집합이며 제공 경계 밖 두 셀만 검증된 규칙으로 생성한다.

생활인구: 이미 R2에 게시된 월별 원본을 다시 읽고 같은 집계 코드로 로컬 기준본과 대조한다. `--expected`는 앞서 로컬 폴백에서 만든 기준본이다. 원격에서 만든 결과를 자기 자신과 비교하지 않는다.

```sh
uv run --frozen python -m ingest.verify_population_storage \
  --months 2026-06 2026-07 2026-08 --start 2026-06-01 --end 2026-08-31 \
  --expected .local/ingest/aggregates/living_population-fixed-sums-202606-202608.parquet \
  --directory .local/validation/r2-readback
```

로컬 기준본을 새로 만들 때는 `prepare_month`로 제공자 ZIP을 월별 raw Parquet로 변환하고, `aggregate_window`에 세 로컬 경로와 위 시작·종료일을 넣는다. 날짜별 합계·일수 임시 파일은 자동 정리한다. 메모리 한도 1GB·threads=2이며 readback 및 디스크 spill을 위한 여유 공간이 필요하다. 최종 profile 행을 `load_living_population`으로 적재한다. DB 실제 검증에 사용한 source는 `seoul_living_population_250m`, source_version은 `2026-06/2026-08`이다. 같은 source의 격자 source_version은 `2026-09-19;raw:2026-06/2026-08`이며 적재 시 기존 값을 먼저 확인한다.

월별 원본 게시는 `RawStore(Settings.from_env()).publish_file("living_population", month, path)`로 실행한다. 직접 파일을 읽어 multipart 업로드하므로 전체 원본을 DataFrame으로 만들지 않는다. 키 없는 폴백 검증에는 `.env` 자동 읽기를 피하도록 `Settings.from_env({"INGEST_LOCAL_ROOT": "원본이 있는 로컬 경로"})`를 명시적으로 전달한다. 단위 테스트는 이미 이 방식으로 사용자 키와 독립적이다.

## PR 3 교통 실데이터 재현

PR 2의 427개 행정동이 적재된 로컬 Supabase를 사용한다. `supabase migration up --local`로 새 교통 마이그레이션을 적용한다. 환경은 기존 Python 3.12·DuckDB·psycopg를 그대로 쓰며 새 라이브러리는 없다. 소스 HTTP 기본 URL은 `.env.example`의 `SEOUL_TRANSIT_API_URL`, 인증은 `SEOUL_OPEN_DATA_API_KEY`다. 인증 URL·비밀 값은 출력하지 않는다.

```sh
uv run --frozen python -m ingest.verify_transit
uv run --frozen python -m ingest.verify_transit --load
```

첫 명령은 6월 전체 자료와 일별 교차 검증을 먼저 끝내고 7·8월에 같은 정규화 규칙을 적용한다. 두 번째는 검증된 원본을 선택된 저장소에 게시하고 실제 저장소에서 재읽기·재집계한 뒤 **로컬 Supabase만** 원자 교체한다. R2 4개 변수가 설정돼 있으면 실제 R2에 게시한다. 기존 객체의 크기·SHA-256이 같으면 재사용하며 다르면 덮어쓰지 않는다. R2 실패 시 로컬로 전환하지 않는다. 원격 Supabase는 연결하지 않는다.

현재 명령은 PR 3 검증 기간인 2026-06~08 및 9월 위치 스냅샷의 재현용이며 월별 자동 실행 스케줄이 아니다. 첫 수집의 위치 API는 조회 시점 자료를 반환하므로 미래에 빈 디렉터리에서 실행하면 9월 스냅샷과 달라질 수 있다. 이 경우 기존 R2 객체와 다르다는 오류를 무시하거나 원본을 덮어쓰지 말고 기준월·위치 버전을 먼저 재검증한다. 기존 로컬 원본 또는 고정 R2 스냅샷으로 재집계할 수 있으며, 원격 Parquet는 `RawStore.connection()`으로 읽고 소스별 `stops`/`normalize`와 `aggregate_months`를 그대로 사용한다.

기본 산출물은 `.local/validation/pr3/`다. 실제 원본·상세 목록은 Git에 넣지 않는다.

- `CardSubwayTime-202606.parquet` 등: API 원본. 7월 지하철의 정확한 복제 행도 보존한다.
- `subwayStationMaster-current.parquet`, `busStopLocationXyInfo-current.parquet`: 검증에 사용한 9월 위치 응답.
- `CardSubwayStatsNew-202606DD.parquet`, `CardBusStatisticsServiceNew-202606DD_{100,5511}.parquet`: 6월 단위·정차/개명 검증용 일별 자료.
- `coverage.json`, `unmatched.csv`: 소스·월별 조인 분모/분자, 이름을 포함한 모든 미매칭 ID. 승하차량 조인율 90% 미만 또는 미확인 시 여기에 결과를 남기고 중단한다.
- `aggregated.parquet`: 실제 저장소에서 읽은 자료로 재집계한 서울 조회용 수치.
- `report.json`: 원본 해시·R2 재읽기·3개월 집계 대조·DB 환경/용량·대치동 3곳×2반경의 교통 SQL 측정. HTTP와 전체 RPC는 미구현이므로 통과로 표시하지 않는다.

공간·시간·원자성·RLS 검증은 기존 `pnpm test`·`pnpm test:db`에 포함된다. DB 테스트는 트랜잭션 롤백으로 실제 스냅샷을 보존한다. 검증 근거와 실제 수치는 [PR 3 기록](validation/pr3-transit-20260919.md)을 따른다.

## 종료

```sh
supabase stop
colima stop --profile gilmok
```

`supabase db reset --local`은 로컬 DB 데이터를 지우므로 새 마이그레이션의 초기 적용을 검증할 때만 사용한다. 마이그레이션은 CLI로 생성하고 적용된 파일은 변경하지 않는다.


## PR 4 상가·학원·학교 실데이터 재현

Python 3.12, Node 22.x, pnpm 10.7.1, 로컬 Supabase와 기존 인구·교통 데이터가 전제다. 외부 수집은 `/ingest` 모듈만 수행한다. 새 의존성은 없다. `.env.example`의 기존 `SEOUL_OPEN_DATA_API_KEY`, `NEIS_API_KEY`, `KAKAO_REST_API_KEY`, `VWORLD_API_KEY`, R2 설정을 사용한다. 지오코딩 실행 전에 Kakao 제품 활성화와 주소 1건의 HTTP 200/유일한 좌표를 확인한다. 이번 검증에서는 그 1건도 캐시하여 일괄 단계에서 재호출하지 않았다.

```sh
supabase migration up --local
uv sync --frozen
```

사용자가 승인한 로컬 VACUUM FULL은 이미 1회 완료됐고 기준은 171,467,279 byte다. 재현 명령에 VACUUM이나 DB reset은 포함하지 않는다. 원격 DB에서는 실행하지 않는다.

2026-09-19 수집 스냅샷의 재현(해당 원본이 확보된 환경):

```sh
uv run --frozen python -m ingest.verify_commerce_education \
  --stores-zip .local/validation/pr4-preflight/stores-20260630.zip \
  --stores-month 2026-06 --education-version 2026-09-19 \
  --academy-json .local/validation/pr4-preflight/neisAcademyInfo-all.json \
  --school-json .local/validation/pr4-preflight/schoolInfo-all.json \
  --directory .local/validation/pr4/places

uv run --frozen python -m ingest.geocode \
  .local/validation/pr4/places/addresses.json \
  --budget 14000 --vworld-budget 1000 \
  --journal .local/validation/pr4/geocode-responses

uv run --frozen python -m ingest.verify_commerce_education \
  --stores-zip .local/validation/pr4-preflight/stores-20260630.zip \
  --stores-month 2026-06 --education-version 2026-09-19 \
  --academy-json .local/validation/pr4-preflight/neisAcademyInfo-all.json \
  --school-json .local/validation/pr4-preflight/schoolInfo-all.json \
  --directory .local/validation/pr4/places --load
```

첫 명령은 원본 보존·실제 R2 재읽기 대조·주소 목록·원문 분포를 생성한다. 마지막 명령은 캐시가 완성됐는지 확인한 후 표본 용량 측정, 로컬 DB 원자 reconcile, DB 필드/기하 대조, 3곳×2반경 SQL p95를 검증한다. 같은 원본의 재적재에서는 변경 없는 개체 행을 다시 쓰지 않는다. 실패/빈 스냅샷이면 이전 DB를 보존한다. 저장공간은 적재 트랜잭션 중 임시 파일을 포함한 값과 커밋 후 값을 나누어 기록한다.

새 학원·학교 API 스냅샷을 수집할 때는 두 JSON 옵션을 빼고 실제 조회일을 `--education-version`에 지정한다. 수집일별 새 작업 디렉터리를 사용한다. 상가 ZIP은 공공데이터포털 15083033의 최신 분기 파일을 확보한다. 이전 수집일을 새 응답의 기준일로 재사용하지 않는다. 원본 파일과 `.local`은 Git에 넣지 않는다. R2는 같은 월 키의 다른 바이트를 덮어쓰지 않으므로 이미 게시한 월의 새 스냅샷이 다르면 중단한다.

캐시는 성공과 확정 실패 모두 재사용한다. Vworld는 이번 입력 주소 중 Kakao NOT_FOUND인 주소에만 호출한다. 명시한 요청 예산은 앱의 실제 잔여 쿼터를 의미하지 않는다. 401/403/429·타임아웃·pending/unknown claim에서는 원인을 검토하며 **자동 재호출하지 않는다**. journal에 응답이 있으면 검토 후 `ingest.geocode.save_result`로 API 호출 없이 복구할 수 있다. 의도적으로 재시도하려면 별도 운영 결정을 먼저 한다.

검증 기록: [PR 4 실데이터·용량·주소 대조](validation/pr4-places-20260920.md). `score_inputs` 전체 RPC와 HTTP 왕복은 아직 미구현이며 이 SQL 결과를 S1 전체 완료로 표시하지 않는다.

## PR 5 강남구 건물

원본 입력은 사용자가 내려받은 서울 전체 GIS건물통합정보 ZIP이다. **수동 다운로드 후 R2 raw/에 게시, 갱신 주기 분기**이며 ZIP을 압축 해제하지 않는다. `.prj` EPSG:5186·CP949·강남구 코드와 필수 컬럼을 확인하고 서울 전체 원문/geometry를 보존한다. 소스·높이·대장 연결 계약과 실측은 [PR 5 검증](validation/pr5-buildings-20260920.md)에 있다.

`.env`에 기존 DATA_GO_KR_SERVICE_KEY, VWORLD_API_KEY와 `VWORLD_SERVICE_URL=http://localhost`를 둔다. WFS 요청의 domain은 등록 서비스 URL과 같아야 한다. R2 환경변수가 있으면 실제 R2에 게시하고, 없으면 기존 `INGEST_LOCAL_ROOT` 정책으로 저장한다. 배치 로그에는 키가 포함된 URL을 쓰지 않는다.

```sh
supabase db push --local
uv run --frozen python -m ingest.verify_buildings \
  --shp-zip .local/downloads/AL_D010_11_20260909.zip \
  --snapshot 2026-09-20 \
  --directory .local/validation/pr5/implementation \
  --load
```

`--load`를 생략하면 파일/응답 수집과 임시 테이블 기반 geometry 검증까지만 실행한다. `--load`는 원본 4개 Parquet와 ZIP을 먼저 게시·재읽기 검증한 뒤 로컬 DB 스냅샷을 원자적으로 교체한다. `--load` 경로의 DB·HTTP 검증은 로컬만 허용한다. 기존 S1의 강남구 행정동 경계와 대치·한티·학여울 위치가 필요하다. 결과는 지정 디렉터리의 `validation.json`에 기록한다. 같은 원본/월의 R2 객체는 덮어쓰지 않으며 다른 내용이면 실패한다.

건축HUB 성공 페이지는 스냅샷/요청 조건별로 저장해 재사용한다. 정상 0건과 HTTP 오류·200 빈 본문을 구분한다. transient 오류는 최대 8회 시도하고, 인증/쿼터/응용 오류는 중단한다. 프로세스당 건축HUB 호출 상한은 5,000회이며 계정 일일 잔량을 대신하지 않는다. 실패 후 같은 디렉터리·snapshot으로 재실행하면 성공 페이지를 재호출하지 않는다. WFS도 성공 타일을 재사용하며 count/feature ID 합집합과 중복 응답 내용 일치를 확인한다.

전체 저장 페이지를 다시 검증하려면 아래 명령을 사용한다. `register-groups.json`은 표제부 manifest의 `groups`(sigunguCd/bjdongCd/platGbCd 목록)를 JSON 배열로 저장한 파일이며 키 값은 포함하지 않는다. 검증 기록의 재실행에서는 추가 API 호출 0건이었다.

```sh
uv run --frozen python -m ingest.building_register \
  --groups-json .local/validation/pr5/register-groups.json \
  --directory .local/validation/pr5/implementation \
  --snapshot 2026-09-20
```

`buildings`는 SHP 주 소스와 WFS 보조의 EPSG:4326 MultiPolygon·출처·높이·연결 상태를 담는다. WFS는 대장 FK가 없으며, `building_registers`와 `building_floors`는 원문 사실을 보존한다. `buildings_in_radius(lng,lat,radius_m)`의 GeoJSON 도형은 모두 차폐 입력이고 unknown은 원래 높이 NULL·표시/차폐 4m·신뢰도 unknown 비율을 반환한다. `registry`는 연결된 SHP 고유 대장만 집계한다. S2 등록 가능성/채점이나 3D 렌더러를 제공하는 RPC가 아니다.

마이그레이션 `20260920095423_buildings.sql`은 기존 테이블을 바꾸지 않는 추가형이다. 세 테이블·스냅샷 감사 기록은 하나의 트랜잭션에서 교체하며 파싱/geometry/제약 오류는 기존 스냅샷을 보존한다. 통합 테스트는 실패 롤백과 반복 적재를 검증한다. 기능을 되돌려야 한다면 소비 코드를 먼저 제거하고 원본·감사 기록을 보관한 뒤 `supabase migration new rollback_buildings`로 새 마이그레이션을 만들어 아래 순서로 제거한다. 기존 migration 파일을 수정하거나 DB 전체 reset을 하지 않는다. 이 롤백은 이번 적재에서는 실행하지 않았다.

```sql
drop function public.buildings_in_radius(double precision,double precision,integer);
drop table public.buildings;
drop table public.building_floors;
drop table public.building_registers;
drop table ingest_private.building_snapshots;
```

공개 원천은 anon/authenticated SELECT·RPC만 허용하며 쓰기·private 감사 조회는 차단한다. 기존 다른 S1 데이터는 보존한다. 전체 score_inputs와 S1 완료 검증은 후속 PR에서 수행한다.


## PR 6 실거래·임대동향 재현

새 마이그레이션 3개를 로컬에 적용한다. 기존 데이터 초기화나 VACUUM은 필요하지 않다.

```sh
supabase migration up --local
pnpm lint
pnpm typecheck
pnpm test
pnpm test:db
```

실제 키는 `.env`에만 둔다. 기존 값을 덮지 않고 `.env.example`의 빠진 항목을 병합한다. REB 부동산통계정보 키의 이름은 `RONE_API_KEY`다. URL 항목은 키가 아니며 예시의 공식 주소를 그대로 사용할 수 있다. `VWORLD_SERVICE_URL`은 로컬 등록 도메인 `http://localhost`다. R2가 설정돼 있는데 실패하면 로컬로 몰래 전환하지 않는다.

이번 스냅샷의 수집 캐시는 `.local/validation/pr6/`에 있다. 새 법정동 파일은 다음처럼 `/ingest`의 검증된 수집기를 통해 준비할 수 있다.

```sh
uv run --frozen python - <<'PYCODE'
from pathlib import Path
from ingest.legal_boundaries import fetch_legal_boundaries
fetch_legal_boundaries(Path('.local/validation/pr6/legal-dongs.geojson'))
PYCODE

uv run --frozen python -m ingest.verify_rent trades \
  --snapshot 20260920T120200Z --start-month 202409 --end-month 202608
uv run --frozen python -m ingest.publish_rent_survey \
  --quarter 2026-Q2 --directory .local/validation/pr6 --snapshot 20260920T120200Z
uv run --frozen python -m ingest.verify_rent verify --snapshot 20260920T120200Z
```

동일 원본/스냅샷의 재실행은 게시된 바이트를 재사용한다. 지연신고·해제 정정을 새로 수집하려면 **새 cache directory**, 새 UTC 스냅샷 ID, `trades --revision`을 사용한다. 캐시 파일을 남긴 채로 “새로 조회했다”고 기록하지 않는다. 새 디렉터리에는 법정동 원본도 준비한다. 임대동향은 항상 revision 원본 경로를 사용하며 `.local/validation/pr6/rone-authenticated/`의 8개 표 전체 캐시를 검증한다. 무키 샘플은 전체 수집으로 인정하지 않는다.

임대동향 게시기는 공간 증거 `boundary-intersections.json`, `rone-cls-names.json`, `rone-cls-office-names.json`, `rone-cls-small-names.json`, `rone-cls-collective-names.json`과 원천 `rone-seoul-boundaries.json`을 보존한다. 이들은 검증 당시의 공식 응답이다. 새 환경에서는 R2 `raw/rent_survey_scope/revisions/20260920T120200Z/2026-06.parquet`의 `evidence_json`에서 `intersections`, `classification_metadata`, `raw_geometry_response`를 복원할 수 있다. 임의로 다른 분기에 유효하다고 표시하지 않는다. 새 분류 코드와 맞지 않으면 다시 공식 자료를 확인한다.

조회 예시(현재 실제 데이터의 임대동향 공간 연결은 비활성):

```sql
select public.rent_inputs(127.063642,37.494612,500,null,null);
select public.rent_inputs(127.052873,37.496237,1000,2,null);
```

앞의 두 좌표는 각각 법정동 대치동·도곡동이다. 요청 층에서 일반/집합 중 표본이 많은 유형을 고르고 5건 미만이면 매매 단가가 NULL이다. 임대료는 상권→공식 정의가 확인된 권역→NULL이며 근접 상권·이전 분기로 대체하지 않는다. 현재 공간 정의 미확인 사유는 [검증 문서](validation/pr6-rent-20260920.md)에 있다. `score_inputs` 전체 통합은 다음 태스크다.

적재 실패는 트랜잭션을 롤백한다. 정정본은 원본 revision으로 보존하며 같은 출처의 이전 DB 집계를 새 완전 스냅샷으로 교체한다. 복구 시 이전 R2 원본과 그 기간/분류 증거를 다시 읽어 집계·적재한다. 현재 원격 Supabase 전환은 하지 않았다. 구조를 철회해야 한다면 새 CLI 마이그레이션으로 PR 6 함수/테이블만 제거하며 기존 S1 테이블을 건드리지 않는다.


## PR 7 score_inputs 통합·S1 검증

PR 7의 두 신규 마이그레이션을 적용한다. 기존 적재 데이터를 초기화하지 않는다.

```sh
supabase migration list --local
supabase migration up --local
pnpm lint
pnpm typecheck
pnpm test
pnpm test:db
uv run --frozen python -m ingest.verify_score_inputs \
  --directory .local/validation/pr7/20260921-final
```

```sql
select public.score_inputs(
  lat => 37.494612, lng => 127.063642, radius_m => 500, floor => 2
);
```

위경도 위치 인자 순서는 score_inputs가 lat,lng이고 이전 rent_inputs/buildings_in_radius는 lng,lat이다. 이름 있는 인자를 사용한다. HTTP는 `/rest/v1/rpc/score_inputs`에 같은 네 필드를 POST한다. 공개 원천 조회만 하며 개인 임대료 입력은 이 RPC에 포함하지 않는다.

검증 스크립트는 로컬 DB/HTTP만 허용한다. 6조합 각각 준비 호출 3회·EXPLAIN 30회, 바로 뒤 별도 진단값 RPC 30회, HTTP 30회를 수행한다. EXPLAIN p95와 meta.bundle_ms/total_ms는 서로 다른 계측값이다. 내부 SQL 본문을 추출해 계획·결과를 대조하며, 독립 소스 집계와 전체 JSON을 비교한다. `.local/`의 보고서는 새 directory로 남겨 이전 실측을 보존한다. R2 재게시나 외부 API 재수집은 하지 않는다.

전체 JSON 타입·NULL·단위·추정 계약은 [data-sources.md 3절](planning/data-sources.md#3-score_inputs--s2-채점-입력-계약-v10)이다. 기준일은 소스별로 다르며 공간 적용 미확인 임대동향, 불완전 셀 인구, 미연결 대장 등은 사유와 NULL을 반환한다. 모든 값이 비NULL이어야 S1이 완료되는 것은 아니다.

기존 rent_inputs는 score_internal.rent_inputs와 공통 구현을 사용한다. buildings_in_radius는 지도·차폐용 별도 RPC로 유지한다. score_internal은 PostgREST 공개 스키마에 추가하지 않는다. 기존 공개 테이블 RLS와 비공개 ingest_private 권한을 그대로 둔다.

복구가 필요하면 `supabase migration new rollback_score_inputs`로 새 마이그레이션을 만든다. 의존성 역순으로 public.score_inputs와 새 public.rent_inputs wrapper를 제거하고, score_internal.rent_inputs를 public으로 옮겨 PR 6 경로를 복원한 뒤 남은 내부 helper/schema를 제거한다. 기존 buildings_in_radius·적재 테이블·R2 원본은 보존한다. 이미 적용한 두 마이그레이션을 편집하거나 DB reset으로 복구하지 않는다.
