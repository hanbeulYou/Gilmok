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

## 공통 적재 경로

- `ingest/common.py`: `.env`/환경변수 설정, 같은 키 규칙을 쓰는 로컬·R2 원본 저장. 로컬 파일은 임시 파일을 완성한 뒤 교체한다.
- `ingest/aggregate.py`: `/ingest/sql`의 신뢰된 배치 SQL에서 `raw_data` 뷰를 조회한다. 같은 원본에 새 SQL을 적용해 재수집 없이 재집계할 수 있다.
- `ingest/database.py`: 원천 어댑터가 검증·변환한 `code`, `name`, `wkt` 행을 받아 행정동·집계구 경계를 적재한다. EPSG:4326만 허용한다. 빈 스냅샷은 거부한다.
- DB 적재는 소스별 교체와 성공 이력을 같은 트랜잭션으로 처리한다. 중복 키·잘못된 geometry 등으로 실패하면 이전 자료와 이력을 보존한다.
- `geocode_cache`는 캐시 스키마만 준비했으며 외부 지오코더 호출이나 S3 주소 검색 흐름은 구현하지 않았다.
- `candidates`는 사용자 소유권 RLS를 적용하고, 공통 경계 적재 함수의 대상으로 허용하지 않는다.

## 종료

```sh
supabase stop
colima stop --profile gilmok
```

`supabase db reset --local`은 로컬 DB 데이터를 지우므로 새 마이그레이션의 초기 적용을 검증할 때만 사용한다. 마이그레이션은 CLI로 생성하고 적용된 파일은 변경하지 않는다.
