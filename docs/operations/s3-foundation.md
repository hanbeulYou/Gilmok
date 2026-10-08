# S3-1 실행 절차

2026-09-29 · **S3-1 기능 검증 완료**. 원격6조합·uid RLS·실제 웹훅 Actions→cache ready→익명 RPC ready와 Production `/compare` JSON·uid 재사용을 통과했다. 종료 후 variable=false·DB 트리거 disabled. [마감 검증](../validation/s3-1-closeout-20260929.md)을 따른다. 사용자 승인 후 Vercel 앱 변수23개를 Production·Preview에서 삭제해 공개2개만 남겼고, 재배포 없이 `/compare` 재검증을 통과했다.

## 준비·승인 대상

- CLI 2.72.7, PostgreSQL 17.6, PostGIS 3.3.7. 기존 28개 + `20260926093918_s3_foundation_auth.sql`의 원격 적용은 완료했다. 재개 상태 테이블 `20260926112125_restore_stage_manifest.sql`과 역할 제한 `20260926123953_authenticated_rpc_timeout.sql`까지 31개 적용했다. 기존 마이그레이션 파일은 수정하지 않는다.
- 새 마이그레이션: comparisons와 소유자 RLS, 같은 소유자의 후보 최대 5개 참조 검증, private 익명 uid별 한국 날짜 기준 10건 카운터·트리거, 큐 요청자 uid. 무세션 큐 생성은 거절하고 조회 전용 RPC는 유지한다.
- S3-2의 raw→백분위 RPC, uid별 상태 뷰/구독, 주소 Route Handler는 이번에 구현하지 않는다. [확정 결정](../planning/s3-1-plan.md#9-예상-리스크와-후속-경계)을 따른다.
- [복원 manifest](../validation/s3-1-restore-manifest.json)의 SHA256은 최초 승인 값을 유지한다. 최종 원격 이력 31개를 대조하고 후속 변경은 dry-run으로 확인한다. 승인 이후 코드/원본/manifest가 바뀌면 변경 내용을 보고하고 해당 대상을 다시 대조한다.

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
uv run --frozen python -m ingest.measure_product_rpc --target remote \
  --output .local/validation/product-sql.json
uv run --frozen python -m ingest.configure_remote --step auth \
  --manifest docs/validation/s3-1-restore-manifest.json \
  --approved-manifest-sha256 <SHA256>
```

순서는 경계→인구→교통→상가·학원·학교→건물→실거래·임대→기준 분포다. 각 단계는 새 연결의 독립 트랜잭션이며 데이터와 `ingest_private.restore_stages`(단계·manifest SHA256·테이블별 행수/digest·소요 시간)를 함께 커밋한다. 같은 manifest 재실행은 완료 단계의 digest를 확인하고 건너뛴다. 다른 해시·변조된 완료 기록·미기록 기존 데이터는 거절한다. COPY는 5만 행마다 나누되 단계 내 커밋은 하지 않는다. 연결은 TCP keepalive idle 30초·interval 10초·count 5를 사용한다. 실패하면 후속 단계로 진행하지 않는다. 복원은 원본 API를 호출하지 않는다. 커밋 후 별도 연결의 VACUUM ANALYZE를 수행한다. VACUUM FULL은 하지 않는다. 단계별 시간과 전후 DB·테이블·인덱스 bytes를 `.local/restore/s3-1/remote-restore-report.json`에 기록한다. R2 원본 bytes와 임시 디스크 사용량을 DB 용량과 구분해 운영 검증 문서에 옮긴다.

`measure_product_rpc.sql_measure`는 3좌표×500/1,000m·2층을 새 세션 첫 실행 1회와 웜 30회로 분리한다. 직접 EXPLAIN ANALYZE 웜 p95 <1,000ms가 합격 기준이고 HTTP는 실제 익명 로그인 세션으로 별도 기록한다. 최종 검산은 아래 제품 RPC 절차를 따른다. Auth Site URL/Redirect URLs는 main 머지 후 사용자 Vercel 설정 단계다.

## Vault·Database Webhook·실제 pending 1건

워크플로우의 `SUPABASE_PROJECT_REF`는 Repository Secret을 읽는다. 실제 repository_dispatch 실행에는 변경한 워크플로우가 main에 있어야 한다. `ingest-production` 환경과 토큰의 해당 저장소 Contents:write 권한을 확인한다.

```sh
uv run --frozen python -m ingest.configure_remote --step webhook \
  --manifest docs/validation/s3-1-restore-manifest.json \
  --approved-manifest-sha256 <SHA256>
```

동일한 승인된 원격 프로세스 환경이 필요하다. `.env`의 `GITHUB_DISPATCH_TOKEN`을 Vault에 파라미터 바인딩으로 저장/갱신하고 pg_net과 [검토한 트리거 SQL](sql/enable-address-dispatch.sql)을 활성화한다. 주소/PNU/uid 없이 고정 이벤트만 보내며 Dashboard 전체 행 웹훅을 추가하지 않는다. Vault에 저장한 토큰은 GitHub Actions Secret으로 등록하지 않는다.

1. 최초 실증은 큐가 비어 있는지와 자동 실행 일정을 확인한다. 실패 후 재개는 사용자가 승인한 보존 pending의 주소·건수·미처리 상태만 확인하고 추가 요청을 만들지 않는다. 다른 미처리 요청이 있으면 검토 전 워커를 켜지 않는다.
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

두 공개 변수 이름은 `.env.example`과 같다. 프로젝트·배포 메타데이터에서 실제 이름을 확인하고 Marketplace 자동 생성 출처는 별도 확인한다. `.env` 전체를 Vercel로 가져오지 않는다. 아래 환경변수 등록 규칙을 따른다.

## 원격 연결 종료 후 재시도

2026-09-26 10:59:34 UTC의 실제 Postgres 로그는 `pg_wal` 쓰기 중 공간 부족이다. 승인된 VACUUM ANALYZE 1회는 38.308초에 성공했고 DB는 566.9→184.6MB로 줄었다. WAL은 별도로 956.3MB다. `/data` 전체 2.08GB·가용 745.7MB를 실측해 사용자에게 디스크 확장 여부를 확인했다. 임의 유료 전환·원본 축소는 하지 않는다. 상세는 [재시도 전 보고](../validation/s3-1-staged-restore-20260926.md)를 따른다.

로컬 실제 재개 검증: `uv run --frozen python -m ingest.verify_restore_local --database gilmok_s3_replay_<새이름> --manifest docs/validation/s3-1-restore-manifest.json --resume-proof`. 이 검증은 4단계 적재 후 의도적 예외를 발생시키고, 앞의 3단계 보존·실패 단계 롤백·재개 및 18테이블 digest를 확인한다. 기본 로컬 DB나 원격에서는 실행하지 않는다.

## 8GB 확장 후 원격 복원 결과

8GB 확장과 18개 원천 테이블 전수 digest 대조를 완료했다. 상태 테이블 migration 포함 총 30개, 복원 완료 기록 7개다. 복원·검증 589.764초, VACUUM ANALYZE 18.320초, 유지보수 후 DB 889,810,067 byte. 원인은 기존 로그의 WAL 디스크 부족이며 keepalive는 보조 조치다. `df` 직접 실행 대신 Metrics API로 `/data` 전체 8,416,882,688 byte·가용 7,085,551,616 byte를 확인했다. Pro gp3 8GB 포함 기준은 공식 요금표로 확인했으며 조직 청구서 API는 권한 제한으로 열람하지 못했다.

HTTP 검증은 200 150건 후 500 1건으로 중단됐다. PostgREST 57014 statement timeout과 anon role 3초 설정을 확인했다. 개별 DB/HTTP p95 파일은 성공 시에만 저장돼 이번에는 생성되지 않았다. Auth·Vault·webhook은 아직 적용하지 않았으며 `INGEST_REMOTE_ENABLED=false`를 유지한다. [상세 결과와 실패 로그](../validation/s3-1-remote-20260926.md)를 따른다.

## 제품 RPC의 첫 실행·웜 검산과 갱신 후 예열

`ingest.measure_product_rpc.sql_measure`는 조합마다 새 연결의 EXPLAIN ANALYZE와 같은 호출의 bundle_ms를 기록한다. 공유 캐시는 비우지 않는다. 웜 p95가 1초를 넘으면 후속 설정을 중단하고 Small 검토를 보고한다. 최신 실측은 모두 통과하여 authenticated의 statement_timeout=15s를 적용했다. rollback은 새 migration에서 8초로 되돌리고 PostgREST config를 reload한다.

HTTP는 `ingest.measure_product_rpc.http_measure`에 익명 signup으로 발급한 사용자 access token과 고정 manifest provenance를 전달한다. Authorization에 프로젝트 anon 키를 넣는 기존 `verify_remote` HTTP 경로는 제품 합격 검증에 사용하지 않는다. 프로젝트 apikey 헤더와 사용자 JWT는 구분한다. 조합별 첫 실행+웜 30회, 응답 대조와 실패 전 표본 저장을 수행하며 검증 사용자는 삭제한다. 원격 Auth 활성화는 이 HTTP 검증 전에 필요하다.

월간 workflow는 소스 갱신→기준 분포 갱신이 모두 성공하면 마지막에 `uv run --frozen python -m ingest.warm_score_inputs`로 6조합을 예열한다. 원격 환경은 위와 같이 프로세스에만 주입한다. 명령의 실제 원격 실행은 2.788초로 통과했다. 모든 PostgREST 세션 캐시를 보장하는 것은 아니다.

2026-09-29 PAT 권한 수정 후 보존 pending 1건을 재전송해 실제 Actions 성공·ready·RPC 재조회를 확인했다. 최종 큐는 done 1건이며 트리거 **disabled**, Repository variable=false다. [성공 run](https://github.com/hanbeulYou/Gilmok/actions/runs/36546048704). 상시 자동 적재는 별도 운영 결정 전까지 켜지 않는다.

## Vercel 환경변수 실제 조회 — 2026-09-27

사용자 확인 URL은 `https://gilmok-weld.vercel.app/compare`, 실제 프로젝트는 `hanbeulyous-projects/gilmok`이다. Production 배포 READY·PR #20 main SHA, HTTP 200, Auth Site URL의 동일 배포 alias 등록을 확인했다. `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`는 프로젝트와 배포 메타데이터 양쪽에서 실제 이름을 확인했고 `.env.example`과 일치한다. 값은 기록하지 않았다. integration configurationId가 없어 Marketplace 자동 생성 출처는 미확인이다.

새 브라우저에서는 JSON 대신 “Supabase 연결 설정이 필요합니다.”가 표시되고 signup/RPC는 0회였다. 배포 bundle의 클라이언트 생성 경로도 해당 오류를 직접 throw한다. Production의 두 공개 변수 값·빌드 반영을 확인하고 재배포 후 JSON을 검증한다. 앞서 다른 프로젝트 vineyard/gilmok을 조회한 404 결과는 실제 서비스 상태에서 제외한다. [최신 증거](../validation/s3-1-webhook-20260927.md).

## Vercel 환경변수 등록 규칙 — A0 승인 반영

현재 공개 `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` 2개를 유지한다. **A0에서는 Vercel 환경변수를 추가/변경하지 않는다.** 이전의 S3-2 KAKAO_REST_API_KEY 예외는 폐기했다.

S3-2 검색은 Juso로 전환한다. 사용자 검색은 무캐시 실시간, 등록 좌표는 후보 행에만 저장한다. 공용 cache는 배치 DB URL만 쓰므로 cache 서명키·관리자키가 필요하지 않다. Route Handler 실제 배포에 필요한 Juso 공급자 서버 키는 #22 배포 시 명시하며 `NEXT_PUBLIC_` 이름을 붙이지 않는다.

Production·Preview 모두 .env 전체 업로드 금지. SUPABASE_SECRET_KEY, service-role/JWT 관리자키, DB URL·비밀번호, GITHUB_DISPATCH_TOKEN, R2 및 배치 API 키는 Vercel에 등록하지 않는다. 실제 .env·Actions Kakao 키 삭제는 재산출·8축 차이 보고·manifest 승인 뒤 수행한다.

## 2026-09-29 최종 배포 확인

`https://gilmok-weld.vercel.app/compare`에서 익명 로그인1회·최초 RPC1회·JSON schema1.3·새로고침 uid 재사용을 확인했다. 앞선 연결 설정 오류는 해결됐다. 테스트 사용자는 삭제했다. 이후 삭제 목록 사전 제시·사용자 승인을 거쳐 23개를 Production·Preview 양쪽에서 삭제했다. 공개2개만 남았고 Production 배포 ID는 삭제 전후 동일하다. 재배포 없이 `/compare`에서 익명 signup1·최초 RPC1·JSON1.3·새로고침 uid 재사용을 다시 확인하고 테스트 사용자를 삭제했다. 삭제·검증 증거는 [마감 검증](../validation/s3-1-closeout-20260929.md)을 따른다.


## PR A 주소 Route Handler 배포 설정 (2026-09-30)

S3-2의 공개 변수는 `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`다. S3-3 A 승인 범위에서 공개 `NEXT_PUBLIC_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/liberty` 1개를 추가한다. 지도 URL은 비밀이 아니며 [배포 절차](compare-map.md)에 따라 사용자가 Production·Preview에 등록 후 재배포한다. #22 배포에는 서버 전용 `JUSO_API_KEY`와 Juso 좌표 승인 전의 `VWORLD_API_KEY`가 추가로 필요하다. 사용자가 Vercel에 등록한 뒤 재배포한다. Kakao 키·Supabase 관리자키·DB 비밀번호·DB URL·R2·dispatch 토큰은 등록하지 않는다. `.env` 전체 업로드는 금지한다. 이 PR에서 Vercel 변수는 직접 변경하지 않았다.

주소 Route Handler는 Next.js15 `runtime=nodejs`, `preferredRegion=icn1`, 외부 fetch `cache=no-store`로 실행한다. 국내 사용자·주소 API와의 왕복을 줄이기 위한 선택이며 Supabase 프로젝트는 계속 Tokyo다. [Next.js15 지역 설정](https://nextjs.org/docs/15/app/api-reference/file-conventions/route-segment-config#preferredregion). 브라우저 bearer 토큰을 서버의 [auth.getUser](https://supabase.com/docs/reference/javascript/auth-getuser)로 검증하고 사용자 권한 RPC로 쿼터를 예약한다. public key 이외의 Supabase 서버 비밀은 사용하지 않는다.

A는 `/new` 등록→`/compare` 미저장 점수 목록까지다. 최초 데이터 조회 동안 후보명·층을 유지하고 스켈레톤을 표시한다. 주소 확인55초·채점 RPC 단계55초, 개별 외부 데이터 API10초, Worker15초를 상한으로 재시도 가능 오류/결측으로 전환한다. 일반적인 콜드2~4초는 보장 상한이 아니다. 저장·새로고침 복원은 C, Realtime 구독은 B에서 완성한다. [검증·원격 승인 목록](../validation/s3-2-a-registration-20260930.md)을 따른다.


## 주소 상태 투영 복구 (2026-10-01)

원천 큐·캐시 AFTER 트리거는 상태 투영 오류를 private projection_errors에 남기고 원천 쓰기를 계속한다. 오류 기록도 실패하면 식별자/메시지 없이 SQLSTATE warning만 남긴다. 주소 sweep의 drain 뒤 보정은 현재 캐시/큐와 모든 관찰자를 대조하므로 오류 기록 누락도 복구한다. 보고 항목은 repaired/errors_resolved/unresolved_errors이며 보정 실패/미해결 오류가 남으면 실패 종료한다.

- 조회만: `uv run --frozen python -m ingest.address_dispatch --target local --dry-run`
- 보정 대상 확인: `uv run --frozen python -m ingest.reconcile_projection --target local --dry-run`
- 보정 실행: `uv run --frozen python -m ingest.reconcile_projection --target local`

원격은 기존 DB URL/INGEST_REMOTE_ENABLED 가드와 작업 승인을 따른다. Actions는 main을 체크아웃하므로 PR 머지 후에 새 보정 단계가 실행된다. 현재 상시 운영과6시간 주기 전환은 B 실증 이후이며 이번 PR에서 variable이나 cron을 바꾸지 않는다. 롤백은 프론트/보정 실행을 중단한 뒤 신규 두 트리거 제거와 원본 score_inputs 복귀를 시행하고 로그 데이터는 보존한다. [검증·롤백 SQL](../validation/s3-2-a-projection-recovery-20261001.md).

## Vineyard 팀 연결·원격 A 검증 (2026-10-01)

Vercel 프로젝트는 동일 ID로 `vineyard`(Vineyard) 팀에 이전됐다. CLI는 `vercel switch vineyard` 후 작업 폴더에서 `vercel link --yes --project gilmok --scope vineyard`로 기존 프로젝트에 연결한다. 다른 팀의 동명 프로젝트를 새로 만들지 않는다. 환경변수 자동 다운로드가 있는 CLI에서는 서버 비밀이 파일/로그에 남지 않도록 확인한다.

팀/Function Region 설정 변경 전의 Preview는 기존 리전으로 실행될 수 있다. 승인된 Preview를 새 팀에서 재배포하고 `/api/address-search` 응답의 `X-Gilmok-Function-Region`을 확인한다. `x-vercel-id`의 엣지 위치와 혼동하지 않는다. 이번 프로젝트 전체 regions는 `[iad1,icn1]`, 검증한 주소 Route Handler의 실제 요청6건은 모두 icn1이었다.

주소 API 실패 로그 `address_provider_failure`에는 공급자, 단계, HTTP 상태, 제한된 기계 오류 코드만 남긴다. 키·주소·요청 URL·원문 응답을 추가하지 않는다. HTTP 응답 전 실패하면 상태/공급자 응답 코드가 NULL일 수 있다. 이번 재시험에서는 Juso 검색과 Vworld 좌표가 모두200이었다. [3곳·uid·한도·HTTP 최종 검증](../validation/s3-2-a-region-retry-20261001.md).


## 공개 전 체크리스트 (2026-10-02)

**현재 컴퓨트는 Micro 유지.** 사용자가 대시보드에서 확정했으며 이번 문서 갱신에서
컴퓨트 변경이나 관리 API 확인은 하지 않았다. 이 결정과 향후 공개 조건을 구분한다.

S3-2 B의 계획 완료 기준은 통과했다. 원격 합본 **2uid Realtime + 연속5채점**은
B 완료/PR #24 Ready의 차단 조건에서 제외하고 **공개 전 체크리스트**로 관리한다.
**Small 전환 후 재시험 통과가 공개 조건**이다. 두 조건을 충족하기 전에는 공개하지 않는다.
기존 Micro 시험에서 `score_inputs`/`exposure_inputs_v022`의 HTTP500·SQLSTATE57014
(15초 statement timeout)이 발생한 [실패·진단 기록](../validation/s3-2-b-comparison-20261001.md#공개-전-합본-시험--기존-실패-기록)은 보존한다.

- [ ] 내장 GPU 일반 노트북 FPS 확인 — S3-4 3D·오버레이 장면에서 기기·GPU·뷰·건물 수와 FPS를 기록한다.
- [ ] 공개 전 컴퓨트를 Small로 전환하고, 재시작/복구 완료 후 실제 컴퓨트와 DB 정상 상태를 기록한다.
- [ ] 같은 브라우저별 후보 동시 채점 최대2개, v0.3 프리셋·원천 snapshot·3곳 좌표를 유지한 채
  원격 합본(서로 다른 익명 authenticated uid2개, Realtime 유지, 연속5채점)을 다시 실행한다.
  `tests/compare/verify_browser.py`의 전체 경로를 사용하며 `PROOF_REALTIME_ONLY`와
  `PROOF_SKIP_DELAY`를 설정하지 않는다. 익명 세션의 실제 RPC/Worker/Realtime과 실제3분 대기를 사용한다.
- [ ] 전체 검증 통과(exit0, `scope=all`, `status=passed`)와 HTTP/SQL timeout 없는 5후보 채점,
  v0.3 점수 일치 및 Realtime 검증을 확인한다. 분리 시험 통과로 합본 통과를 대신하지 않는다.
- [ ] 실제 컴퓨트·커밋·snapshot·시험 시각·RPC 오류/소요 시간·슬라이더 p95/max·시험 데이터 정리를
  새 `docs/validation/` 기록으로 남기고, 위 Small 전환과 합본 통과가 모두 확인된 뒤 공개한다.

`lib/compare/store.ts`는 브라우저의 비교 store마다 후보 작업2개까지 실행하고 나머지는 대기시킨다.
성공뿐 아니라 실패 후에도 슬롯을 반환한다. 5개 동시 요청 회귀 테스트는 최대 실행 수2를 확인한다.
후보 내3개 RPC 병렬 및 여러 사용자의 요청은 별개이므로 서버 전체 동시 쿼리 상한2로 해석하지 않는다.

현재 Micro 설정, `INGEST_REMOTE_ENABLED=false`, webhook disabled, 기존 sweep cron은 유지한다.
Small 전환/합본 재시험과 D5 webhook 상시 운영·6시간 sweep 전환은 이번 Ready 처리에서 실행하지 않는다.
D5는 [기존 승인 후 실행 절차](../validation/s3-2-b-comparison-20261001.md#d5-전환-계획--실행-전-사용자-승인-필요)를 따른다.


## D5 승인 후 실증 상태 (2026-10-02)

#24 머지 후 상시 웹훅·6시간 sweep 실행을 승인받았다. **상시 운영 시작일은 미정**이다. 실제 공개 주소의 webhook→Actions는 도달했으나 지오코딩 실패로 ready/화면 갱신까지 완료하지 못해 variable=false·트리거 disabled로 복귀했다. [운영 시작·재개·롤백 절차](data-refresh.md#d5-상시-운영-전환-2026-10-02), [실측](../validation/s3-2-d5-20261002.md)을 따른다. 이 상태는 B 완료와 공개 전 Small 합본 시험 조건을 바꾸지 않는다.


### D5 최종 상태 갱신 (2026-10-06)

위 2026-10-02 실패 상태는 해소했다. 원격 migration 1개 적용·등록 PNU/좌표 재사용·실제 Actions/ready/Realtime 화면 갱신을 통과했고 **2026-10-06 19:22:36 KST** 웹훅 상시 운영을 시작했다. `INGEST_REMOTE_ENABLED=true`, 주소 dispatch 활성, `JUSO_COORD_ENABLED=true`, `AUTH_CLEANUP_ENABLED=false`. #25 사용자 머지 전 sweep은 기존 hourly이며, 머지 시 6시간 cron과 좌표 키/flag 전달이 적용된다. [실증](../validation/s3-2-d5-20261002.md), [시작일·설정·롤백](data-refresh.md#2026-10-06-상시-웹훅-시작과-최종-롤백)을 따른다. Micro/공개 전 Small 재시험 조건은 그대로다.


### D5 main 반영 확인 (2026-10-06)

#25 main 머지 후 6시간 cron·월간 좌표 key/flag 전달과 Production 등록 UI 배포를 확인했다. 실제 Production 등록의 search/locate는 icn1·HTTP200, RPC registered_pnu 전달·ready, 점수는 Preview와 동일하다. **D5 종결은 첫 6시간 scheduled sweep 성공 확인 대기**이며 [최종 검증](../validation/s3-2-d5-closeout-20261006.md)에 기록한다.


### D5 종결 (2026-10-07)

main 6시간 cron의 실제 [schedule run 37511542422](https://github.com/hanbeulYou/Gilmok/actions/runs/37511542422)이 03:28 KST 성공해 **D5를 종결**했다. 월간 좌표 env 전달·Production 등록 검증도 통과했다. pending/needs_coord/투영 오류0, 좌표 key 전달·flag=true를 확인했다. 이전 슬롯 미관측과 실제 실행 시각은 [검증](../validation/s3-2-d5-closeout-20261006.md)에 보존한다. 스케줄 설정의 6시간 간격과 실제 실행 시각은 구분하며 [운영·롤백](data-refresh.md#2026-10-07-d5-종결--main-6시간-cron-실제-실행-확인)을 따른다. 13,542건 교체·실제 삭제·공개 전 Small 재시험 조건은 그대로다.
