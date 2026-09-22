# 원격 Supabase 전환 절차 — 아직 실행하지 않음

PR 8은 절차만 제공한다. `supabase link`, 원격 `db push`, 적재, webhook 생성은 수행하지 않았다. 로컬을 계속 기본으로 쓴다. S1은 원격 무료 플랜 유지, S2 서울 전체 건물 시점에 Pro 검토라는 사용자 결정을 따른다. 용량 부족을 이유로 범위·해상도를 줄이거나 자동 유료 전환하지 않는다.

## 1. 사전 확인과 스키마

빈 대상 프로젝트의 ref·리전·현재 플랜 한도·네트워크·TLS를 확인한다. 로컬 DB 전체/테이블/인덱스와 작업 여유 공간, R2 원본 크기를 다시 실측하여 원격 용량에 맞지 않으면 현황을 보고하고 전환을 중지한다. 아래 명령은 **향후 운영자 실행용**이다. 키는 `.env` 또는 실행 환경에 두며 터미널 출력에 URL/비밀번호를 남기지 않는다.

```sh
pnpm exec supabase migration list --local
# Supabase CLI 2.72.7, 검증된 main에서 실행
pnpm exec supabase link --project-ref "$SUPABASE_PROJECT_REF"
pnpm exec supabase migration list --linked
pnpm exec supabase db push --linked --dry-run
pnpm exec supabase db push --linked
```

schema와 RLS가 준비되어도 웹훅은 자동 생성되지 않는다. 해당 SQL은 migration에서 분리되어 있다. 연결은 `db.<project_ref>.supabase.co:5432` direct 또는 `postgres.<project_ref>` 사용자명의 session pooler 5432, `sslmode=require` 이상으로 설정한다. 트랜잭션 pooler 6543은 session lock 때문에 사용하지 않는다. 프로젝트 ref와 URL이 다르면 refresh 실행기가 거부한다.

## 2. 초기 적재 순서

월간 refresh는 기존 행정동·250m 격자·법정동 경계를 전제로 하므로 빈 DB 초기 적재 명령이 아니다. 이미 검증한 로컬 S1을 옮기는 경로를 기본으로 한다. 적재 중 사용자 조회를 열지 않는다.

1. 실행 중 수집기/워커를 중지하고 소스별 snapshot·R2 manifest·Git SHA를 기록한다.
2. **데이터 전용** `pg_dump`로 아래 소스 테이블을 명시적으로 선택하여 dump한다. 소스는 로컬, 대상은 빈 원격으로 확인한다. auth·candidates·address 요청/캐시·일반 geocode_cache·Vault·pg_net은 포함하지 않는다. 이미 인구·건물에 붙은 좌표는 그대로 복사한다. 마이그레이션은 별도로 적용했으므로 schema dump를 덮어쓰지 않는다.
3. 아래 순서로 로드한다. 부모→자식 의존성을 지키며 가능하면 전체 복원을 한 트랜잭션으로 실행한다. 부분 복원 실패 시 조회를 열지 않는다.

| 순서 | 데이터 |
|---|---|
| 1 | admin_dongs, census_blocks, population_cells, legal_dongs |
| 2 | population_age, living_pop |
| 3 | transit_stops → transit_boardings 및 transit_coverage |
| 4 | stores, academies, schools 및 place_snapshots |
| 5 | building_registers → building_floors, buildings 및 building_snapshots |
| 6 | commercial_trade_stats, rent_areas → rent_survey 및 rent_snapshots |
| 7 | refresh_snapshots(존재하는 경우), 원본 manifest 연결 검증 |

예를 들어 운영자가 위 표의 테이블 allowlist를 `--table` 인자로 완성하여 PostgreSQL 17 `pg_dump --data-only --format=custom`으로 생성하고, 빈 대상에서 `pg_restore --data-only --single-transaction --exit-on-error`로 복원한다. 접속 비밀은 권한 0600의 임시 pgpass/service 파일로 전달하고 종료 후 제거한다. 표의 private 메타데이터 테이블은 `ingest_private` 스키마다. 대상에 기존 데이터가 있으면 이 절차를 그대로 적용하지 말고 충돌·롤백 계획을 먼저 정한다.

R2 원본에서 재구축할 때는 기존 population_database, transit_database, commerce_education_database, buildings_database, rent_database의 검증된 load_* 함수에 원격 연결을 명시적으로 주입하여 같은 순서로 실행한다. 기존 verify_* CLI는 로컬 연결이 고정된 부분이 있어 원격 URL만 바꿔 실행하면 안 된다. 원본 경계 버전과 코드 일치, Parquet 재읽기 집계 대조까지 다시 수행한다. 실패 시 로컬을 유지한다.

## 3. 검증 후 전환

커밋 후 소스 테이블별 `VACUUM (ANALYZE)`를 별도 autocommit 연결에서 실행한다. VACUUM FULL은 사용하지 않는다. 행 수/집계/NULL/공간 키/RLS를 로컬과 대조하고 R2 manifest 체크섬을 재확인한다. 대치·학여울·한티 × 500m/1km × 2층 각 30회로 DB p95 <1,000ms와 HTTP 왕복을 기록한다. EXPLAIN ANALYZE에서 조인 증폭·불필요 전체 스캔도 확인한다. 로컬 S1 통과가 원격 성능을 보장하지 않는다.

검증 성공 후 애플리케이션 환경을 전환하고 `ingest-production` Secrets와 활성화 변수를 설정한다. [주소 워커](address-worker.md) 수동 실행을 먼저 검증한 뒤 webhook을 활성화한다. 실패하면 원격 활성화 변수를 끄고 로컬 연결로 돌아간다. 로컬 DB/R2 원본을 전환 직후 삭제하지 않는다.

## 예상 시간과 측정 항목

원격 실행 미측정 계획치: link/dry-run/schema 10~20분, 로컬 데이터 dump·업로드·복원 30~90분, 유지보수·전수 대조·성능 검증 30~90분, Secrets/worker 점검 15~30분. 합계 약 1.5~4시간이며 네트워크·DB 크기·플랜에 따라 초과할 수 있다. R2 재집계 경로는 추가 시간이 필요하다. 대장 전수 API 재수집은 일일 쿼터로 수일이 걸릴 수 있어 이 예상에서 제외한다. 작업별 시작/종료, byte 수, DB/인덱스/임시 공간, API 호출 수를 기록한다.

근거: [Supabase CLI workflow](https://supabase.com/docs/guides/local-development/cli-workflows), [PostgreSQL 17 VACUUM](https://www.postgresql.org/docs/17/sql-vacuum.html).
