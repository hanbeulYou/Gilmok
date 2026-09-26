# S3-1 실행 절차

2026-09-26 · 원격 gp3 8GB 확장·30개 migration·7단계 복원을 완료했다. HTTP RPC 검증은 anon 3초 statement timeout으로 중단했고 Auth·Vault·webhook은 미실행이다. [최신 실행 기록](../validation/s3-1-remote-20260926.md)을 따른다. Vercel 연결·Auth URL 등록은 main 머지 후 사용자가 수행한다.

## 준비·승인 대상

- CLI 2.72.7, PostgreSQL 17.6, PostGIS 3.3.7. 기존 28개 + `20260926093918_s3_foundation_auth.sql`의 원격 적용은 완료했다. 재개 상태 테이블 `20260926112125_restore_stage_manifest.sql` 1개를 추가 적용한다. 기존 마이그레이션 파일은 수정하지 않는다.
- 새 마이그레이션: comparisons와 소유자 RLS, 같은 소유자의 후보 최대 5개 참조 검증, private 익명 uid별 한국 날짜 기준 10건 카운터·트리거, 큐 요청자 uid. 무세션 큐 생성은 거절하고 조회 전용 RPC는 유지한다.
- S3-2의 raw→백분위 RPC, uid별 상태 뷰/구독, 주소 Route Handler는 이번에 구현하지 않는다. [확정 결정](../planning/s3-1-plan.md#9-예상-리스크와-후속-경계)을 따른다.
- [복원 manifest](../validation/s3-1-restore-manifest.json)의 SHA256은 최초 승인 값을 유지한다. 기존 29개 원격 이력과 신규 상태 테이블 1개 dry-run을 대조한다. 승인 이후 코드/원본/manifest가 바뀌면 변경 내용을 보고하고 해당 대상을 다시 대조한다.

## R2 복원 준비

```sh
uv run --frozen python -m ingest.restore_manifest --publish-supplements
```

이 명령은 원격 DB에 쓰지 않는다. R2 원본을 SHA256으로 고정·재읽기 검증하고 공개 데이터 보완 스냅샷을 게시한다. S3-1의 고정 원천 기간(생활인구/교통 2026-06~08, 실거래 2024-09~2026-08, reference `20260923T111436Z`) 전용이다. 정기 갱신에는 기존 refresh를 사용한다.

보완 스냅샷은 네 종류다. 공개 학원·학교 원본 주소만의 지오코딩 결과, 원천 버전·적재 시각·검증 기준을 담은 provenance, 원래 적재된 생활인구 수치 표현을 보존하는 baseline, 건물 EPSG:4326 도형의 기존 이진 표현을 보존하는 baseline이다. 일반 주소 캐시나 사용자 후보·임대료·auth·private 주소 큐는 복원하지 않는다.

생활인구 baseline은 R2 세 달 원본을 재집계한 411,512행과 키·날짜·sample_days·NULL을 전수 대조하고 기존 검증 허용오차(abs 1e-8, rel 1e-10) 안임을 확인한 후 게시한다. 복원 때도 같은 전수 검사를 다시 수행한 뒤 baseline 값을 적재한다. 이는 집계식/프리셋 변경이 아니라 S1 수치 표현의 보존이다. 금액 DECIMAL은 DuckDB `.df()`로 float 변환하지 않고 보존한다. 건물 도형은 R2 원본에서 재생성한 결과와 ID·도형 유형·정점 수·정점 경로를 전수 대조하고, 모든 정점의 위치 차이가 1μm 이내일 때만 기존 이진 표현을 보존한다. 실질적인 위치/도형 변경은 거절한다.

manifest의 원본 키·SHA256·행 수·bytes를 검토한다. 메타데이터/좌표 보완도 해시를 가진 R2 객체이며, 적재 결과는 원래 DB의 18개 소스 테이블 전체 행·도형·메타데이터 digest와 같아야 커밋한다. 기준 분포의 source fingerprint와 값도 확인한다. 복원 실패는 전체 트랜잭션을 롤백하고, 같은 manifest의 재실행은 기존 결과가 일치할 때만 건너뛴다. 다른 데이터가 있으면 덮어쓰지 않는다.

## 원격 실행 — 별도 승인 후에만

1. 현재 백업/복구 가능 상태와 적용 이력을 확인하고 최종 dry-run을 보고한다. 승인 후 `supabase db push --linked`를 실행한다.
2. `.env`의 로컬 DB URL을 바꾸지 않는다. Management API가 반환한 pooler host, 프로젝트 ref, URL 인코딩한 DB 비밀번호로 `postgresql://postgres.<ref>:<password>@<pooler-host>:5432/postgres?sslmode=require`를 메모리에서 조립한다. 비밀번호/전체 URI를 명령행·문서·로그에 출력하지 않는다. 수동 Python 프로세스의 `subprocess.run(..., env=...)`으로 `SUPABASE_DB_URL`과 `INGEST_REMOTE_ENABLED=true`를 주입한다. Repository Variable은 false를 유지한다.
3. 위 프로세스 환경으로 아래 명령을 순서대로 실행한다. `<SHA256>`은 승인받은 manifest 파일의 값이다.

```sh
uv run --frozen python -m ingest.restore_remote --target remote \
  --manifest docs/validation/s3-1-restore-manifest.json \
  --approved-manifest-sha256 <SHA256>
uv run --frozen python -m ingest.verify_remote --target remote \
  --manifest docs/validation/s3-1-restore-manifest.json
uv run --frozen python -m ingest.configure_remote --step auth \
  --manifest docs/validation/s3-1-restore-manifest.json \
  --approved-manifest-sha256 <SHA256>
```

순서는 경계→인구→교통→상가·학원·학교→건물→실거래·임대→기준 분포다. 각 단계는 새 연결의 독립 트랜잭션이며 데이터와 `ingest_private.restore_stages`(단계·manifest SHA256·테이블별 행수/digest·소요 시간)를 함께 커밋한다. 같은 manifest 재실행은 완료 단계의 digest를 확인하고 건너뛴다. 다른 해시·변조된 완료 기록·미기록 기존 데이터는 거절한다. COPY는 5만 행마다 나누되 단계 내 커밋은 하지 않는다. 연결은 TCP keepalive idle 30초·interval 10초·count 5를 사용한다. 실패하면 후속 단계로 진행하지 않는다. 복원은 원본 API를 호출하지 않는다. 커밋 후 별도 연결의 VACUUM ANALYZE를 수행한다. VACUUM FULL은 하지 않는다. 단계별 시간과 전후 DB·테이블·인덱스 bytes를 `.local/restore/s3-1/remote-restore-report.json`에 기록한다. R2 원본 bytes와 임시 디스크 사용량을 DB 용량과 구분해 운영 검증 문서에 옮긴다.

`verify_remote`는 읽기 전용 트랜잭션에서 원본 테이블과 3좌표×500/1,000m·2층을 대조한다. 각 조합 3회 예열·30회 DB 측정, p95 <1,000ms가 통과 기준이다. HTTP 30회는 별도 기록한다. 원격 Auth는 익명 로그인·수동 identity linking·이메일 확인을 활성화하고 Site URL/Redirect URLs는 사용자의 Vercel 연결 후 설정을 따른다.

## Vault·Database Webhook·실제 pending 1건

워크플로우의 `SUPABASE_PROJECT_REF`는 Repository Secret을 읽는다. 실제 repository_dispatch 실행에는 변경한 워크플로우가 main에 있어야 한다. `ingest-production` 환경과 토큰의 해당 저장소 Contents:write 권한을 확인한다.

```sh
uv run --frozen python -m ingest.configure_remote --step webhook \
  --manifest docs/validation/s3-1-restore-manifest.json \
  --approved-manifest-sha256 <SHA256>
```

동일한 승인된 원격 프로세스 환경이 필요하다. `.env`의 `GITHUB_DISPATCH_TOKEN`을 Vault에 파라미터 바인딩으로 저장/갱신하고 pg_net과 [검토한 트리거 SQL](sql/enable-address-dispatch.sql)을 활성화한다. 주소/PNU/uid 없이 고정 이벤트만 보내며 Dashboard 전체 행 웹훅을 추가하지 않는다. Vault에 저장한 토큰은 GitHub Actions Secret으로 등록하지 않는다.

1. 기존 큐가 비어 있는지와 자동 실행 일정을 확인한다. 빈 큐 확인 없이 워커를 켜지 않는다.
2. 검증 창에서 Repository Variable을 일시적으로 true로 설정한다.
3. 캐시에 없는 공개 검증 주소 하나를 익명 JWT로 score_inputs에 요청한다. uid별 쿼터를 통과한 실제 pending 행을 확인한다.
4. pg_net HTTP 접수, 해당 repository_dispatch Actions run URL/성공, 요청 상태와 cache 준비, RPC 재조회 결과까지 기록한다. HTTP 204만으로 완료 처리하지 않는다.
5. 성공/실패 모두 finally에서 `INGEST_REMOTE_ENABLED=false`로 복귀한다. 실패한 processing/failed 행을 무조건 pending으로 초기화하지 않는다.

원격 쓰기 승인 전에는 이 검증을 실행하지 않는다. 웹훅/상시 배치 운영을 계속 켤지는 검증 후 별도 결정한다.

## 로컬 검증과 복구

```sh
pnpm lint
pnpm typecheck
pnpm test
pnpm test:db
pnpm build
uv run --frozen python -m ingest.verify_anonymous_auth
```

Auth HTTP 검증은 로컬 Supabase와 Mailpit만 사용하여 두 익명 uid의 소유권 차단과 실제 이메일 확인 링크 완료 후 uid·후보·비교 유지까지 확인한다. 검증 사용자는 삭제한다. 설정 변경 후 로컬 Supabase를 재시작하되 실행 중인 DB 검증이 끝난 뒤에만 한다. `pnpm dev`의 로컬 URL에 `node ingest/verify_compare_browser.mjs <URL>/compare <output.json>`을 실행하면 Chrome에서 최초 RPC 1회와 새로고침의 uid 재사용을 확인한다. 원격 이메일 승격은 사용자가 확인 링크를 완료한 뒤 추가로 검증한다.

R2 복원 테스트는 기존 `postgres` 데이터베이스에 실행할 수 없다. `uv run --frozen python -m ingest.verify_restore_local --database gilmok_s3_replay_<name> --manifest docs/validation/s3-1-restore-manifest.json`으로 새 DB에 같은 마이그레이션과 Auth 함수 계약을 준비하여 복원한다. 기존 이름의 DB를 덮어쓰지 않는다. template0에서 생성하므로 기존 template1의 locale 관련 인덱스나 collation 설정을 변경하지 않는다. HTTP 서버가 없는 별도 DB는 `verify_remote --target local --no-http`로 검증한다. 원격 검증에서는 HTTP를 생략할 수 없다.

문제 발생 시 프론트의 원격 연결과 워커 활성화를 보류하고 로그의 단계·manifest SHA를 확인한다. 데이터 복원 중 오류는 트랜잭션 전체 롤백이다. 커밋 후에는 자동 삭제/역복원을 하지 않는다. 앱/워커를 멈춘 뒤 별도 복구 마이그레이션으로 새 트리거를 해제할 수 있으며 comparisons/사용량 데이터는 삭제하지 않는다. 기존 로컬 DB와 R2 원본은 유지한다.

## main 머지 후 사용자가 설정할 값

| 항목 | 값 |
| --- | --- |
| Vercel Git / root | `hanbeulYou/Gilmok`, `./` |
| Framework / Node / package manager | Next.js / 22.x / pnpm 10.7.1 |
| Install / Build / Output | `pnpm install --frozen-lockfile` / `pnpm build` / Next.js 기본값 |
| 브라우저 필수 환경변수 | `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` |
| 환경 범위 | Supabase Marketplace를 프로젝트의 Production/Preview에 연결하고 자동 주입 이름 확인 |
| Auth Site URL | 실제 운영 HTTPS origin |
| Auth Redirect URLs | 실제 운영/검증 Preview URL 및 개발 `http://127.0.0.1:3000` |
| Domain | 사용자 선택·연결. `gilmok.kr` 확보 여부 확인 |

Marketplace가 주입하는 공개 변수 이름과 `.env.example` 이름은 같다. 서버 전용 `SUPABASE_SECRET_KEY`, JWT secret, POSTGRES 비밀번호는 브라우저 코드에 사용하지 않는다. POSTGRES 자동 변수는 배치의 Session pooler URL로 임의 대체하지 않는다. [Supabase Vercel Marketplace 문서](https://supabase.com/docs/guides/integrations/vercel-marketplace)

## 원격 연결 종료 후 재시도

2026-09-26 10:59:34 UTC의 실제 Postgres 로그는 `pg_wal` 쓰기 중 공간 부족이다. 승인된 VACUUM ANALYZE 1회는 38.308초에 성공했고 DB는 566.9→184.6MB로 줄었다. WAL은 별도로 956.3MB다. `/data` 전체 2.08GB·가용 745.7MB를 실측해 사용자에게 디스크 확장 여부를 확인했다. 임의 유료 전환·원본 축소는 하지 않는다. 상세는 [재시도 전 보고](../validation/s3-1-staged-restore-20260926.md)를 따른다.

로컬 실제 재개 검증: `uv run --frozen python -m ingest.verify_restore_local --database gilmok_s3_replay_<새이름> --manifest docs/validation/s3-1-restore-manifest.json --resume-proof`. 이 검증은 4단계 적재 후 의도적 예외를 발생시키고, 앞의 3단계 보존·실패 단계 롤백·재개 및 18테이블 digest를 확인한다. 기본 로컬 DB나 원격에서는 실행하지 않는다.

## 8GB 확장 후 원격 복원 결과

8GB 확장과 18개 원천 테이블 전수 digest 대조를 완료했다. 상태 테이블 migration 포함 총 30개, 복원 완료 기록 7개다. 복원·검증 589.764초, VACUUM ANALYZE 18.320초, 유지보수 후 DB 889,810,067 byte. 원인은 기존 로그의 WAL 디스크 부족이며 keepalive는 보조 조치다. `df` 직접 실행 대신 Metrics API로 `/data` 전체 8,416,882,688 byte·가용 7,085,551,616 byte를 확인했다. Pro gp3 8GB 포함 기준은 공식 요금표로 확인했으며 조직 청구서 API는 권한 제한으로 열람하지 못했다.

HTTP 검증은 200 150건 후 500 1건으로 중단됐다. PostgREST 57014 statement timeout과 anon role 3초 설정을 확인했다. 개별 DB/HTTP p95 파일은 성공 시에만 저장돼 이번에는 생성되지 않았다. Auth·Vault·webhook은 아직 적용하지 않았으며 `INGEST_REMOTE_ENABLED=false`를 유지한다. [상세 결과와 실패 로그](../validation/s3-1-remote-20260926.md)를 따른다.
