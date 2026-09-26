# S3-1 기반 구축 계획

작성: 2026-09-26 · 상태: 2026-09-26 계획 승인·로컬 구현/검증 완료, 원격 DB 쓰기 승인 대기

기준: [화면 정의 v0.1 §8](screens.md#8-s3-스프린트-태스크), [기획서](location-simulator.md), [채점 명세 v0.3](scoring-spec.md), [원격 전환 절차](../operations/remote-supabase.md), [주소 워커 운영](../operations/address-worker.md). S2 #19 머지 기준으로 진행한다. 최신 사용자 지시에 따라 초기 데이터는 R2 원본으로 복원한다. 기존 운영 문서의 로컬 `pg_dump` 복원 경로는 이번 실행에 사용하지 않는다.

## 1. 범위와 승인 순서

범위는 원격 Supabase 전환, 주소 큐 웹훅, 익명 인증·소유자 RLS·큐 제한, Next.js 배포 골격이다. `/compare`에서 익명 로그인 후 `score_inputs` 한 번의 JSON 응답을 표시한다. 지도·후보 입력 폼·채점 매트릭스·공유 화면은 후속 태스크다. 프리셋 v0.3과 기존 채점 계약은 변경하지 않는다.

1. **계획 승인 전:** 문서/코드 조사, 원격 읽기, link·migration 대조·dry-run, 명시적으로 요청한 Secrets 등록.
2. **계획 승인 후:** 로컬 코드·신규 마이그레이션·테스트·운영 절차 작성. 문서와 코드 커밋을 분리한다.
3. **원격 쓰기 전:** 신규 마이그레이션까지 포함한 최종 `migration list --linked`와 `db push --linked --dry-run` 결과, 복원 대상·용량·복구 방법을 보고한다. 사용자의 원격 실행 승인 후에만 push·적재·Auth 설정·Vault·웹훅을 실행한다.
4. **웹훅 실증:** 변경한 워크플로우가 main에 반영된 뒤 실제 pending 1건으로 검증한다. 이 증거가 없으면 S3-1 완료로 표시하지 않는다.

초기 사전 점검은 [별도 기록](../validation/s3-1-preflight-20260926.md)을 따른다. 최종 29개 dry-run·복원 manifest·로컬 검증 결과는 [실행 승인 자료](../validation/s3-1-20260926.md)에 기록했다. 비밀번호 갱신 후 원격 DB 연결·migration 대조·기존 28개 대상 dry-run까지 성공했다. 원격 public 기본 테이블과 적용 이력은 각각 0개다. 실제 push는 실행하지 않았다.

## 2. 원격 DB와 R2 복원

### 연결·마이그레이션

- `.env`의 로컬 `SUPABASE_DB_URL`은 유지한다. Management API에서 확인한 pooler 호스트와 프로젝트 ref, URL 인코딩한 DB 비밀번호로 **Session pooler 5432 / sslmode=require** URI를 조립한다. 비밀은 프로세스 환경/표준입력으로만 전달한다.
- `supabase link` → 로컬/원격 migration 목록 대조 → dry-run 순서다. 기존 마이그레이션 28개는 로컬 DB 이력과 일치하고 원격에서는 전부 적용 대기임을 확인했다. 실행 직전에 이력을 다시 확인한다. 이력 불일치 시 임의 `migration repair`, reset 또는 덮어쓰기는 하지 않는다.
- 로컬에서 `supabase migration new s3_foundation_auth`로 신규 파일을 생성한다. 기존 마이그레이션은 수정하지 않는다. 최종 dry-run에 이 파일을 포함한다.
- 원격의 PostgreSQL/PostGIS 버전·확장 가용성, 테이블/인덱스/DB 용량을 먼저 기록한다. 스택 차이가 있으면 보고한다. Pro는 사용자 승인 상태이며 별도 플랜 변경은 하지 않는다.

### 원본 복원 경로

`ingest/restore_remote.py`를 추가한다. 기존 소스별 정규화·DB loader를 재사용하되 R2 원본을 입력으로 받는다. 기존 월간 refresh를 초기 적재 용도로 실행하지 않는다. 외부 데이터 API 재수집도 하지 않는다.

| 순서 | 복원 대상 |
| --- | --- |
| 1 | 행정동·250m 격자·법정동 경계 |
| 2 | 주민등록·생활인구 |
| 3 | 정류장·승하차량·교통 커버리지 |
| 4 | 상가·학원·학교 및 공개 시설의 검증된 좌표 |
| 5 | 건축물 대장·층별개요·SHP 도형·WFS 보조 도형 |
| 6 | 실거래 집계·임대동향·공간 연결 상태 |
| 7 | 기준 분포와 원본/스냅샷 메타데이터 |

복원 전 R2 객체별 key·hash·행 수·소스 버전을 고정한 manifest를 만든다. 각 단계는 staging/트랜잭션과 검증 후 반영하며 실패 시 다음 단계로 넘어가지 않는다. 재실행은 완료 manifest를 대조하여 중복 적재·부분 결과 노출을 막는다. 원격 접근을 제품에 연결하는 시점은 전수 검증 후다.

**R2 보완 필요:** 현재 학원·학교 원본 Parquet에는 지오코딩 좌표가 없다. 기존 적재는 R2 게시 후 로컬 `geocode_cache`를 붙였다. 따라서 해당 공개 시설 원본의 주소에 해당하는 성공/실패 캐시와 출처 메타데이터만 추출하여 R2 보완 스냅샷으로 게시하고 재읽기 검증한다. 전체 geocode 캐시나 사용자 입력 주소는 복원하지 않는다. 기존 좌표를 재사용하여 Kakao 재호출을 피한다. 이 보완도 계획 승인 후 수행한다.

기준 분포는 snapshot `20260923T111436Z`의 입력·분포·manifest를 명시적으로 선택한다. 기준 분포 reference_version은 0.1.2, 현행 프리셋은 0.3이다. 원본을 재집계한 값·geometry·NULL·원천 메타데이터를 로컬과 대조하고, manifest의 source fingerprint가 실제 복원 결과와 맞는지 확인한다. `ingested_at`을 포함한 원천 이력을 보존하며 복원 실행 시각은 별도 기록한다. 불일치를 숨기기 위해 fingerprint만 바꾸지 않는다. 동일 복원이 불가능하면 재생성 전에 보고한다.

적재 범위는 기존 검증 범위 그대로다. 건물은 강남구 SHP+WFS이며 서울 전체 건물 신규 수집은 이 태스크에 넣지 않는다. 임대 공간 연결 비활성 상태도 유지한다. auth·후보·비교·private 주소 큐/캐시·Vault는 원본 데이터 복원 대상이 아니다.

원격 실행은 기존 remote target 검증을 통과해야 한다. 승인된 수동 프로세스에만 `INGEST_REMOTE_ENABLED=true`를 주입하고 Repository Variable은 false로 유지한다. 적재 후 별도 연결에서 `VACUUM (ANALYZE)`를 실행한다. `VACUUM FULL`은 실행하지 않는다. 실행 전 백업/복구 가능 상태를 확인하고, 실패 시 원격 프론트 연결과 워커를 중지한 채 해당 단계의 staging/트랜잭션을 복구한다.

### 검증·실측

`ingest/verify_remote.py`에서 기존 6조합을 로컬과 원격에 동일 적용한다: 대치 `(37.494612,127.063642)`, 학여울 `(37.496663,127.070594)`, 한티 `(37.496237,127.052873)` × 500/1,000m, 2층. 각 조합 30회 DB 실행 시간 p95 < 1,000ms가 기준이며 HTTP 왕복은 별도 기록한다. 응답의 측정 시각·실행 시간은 값 대조에서 분리한다.

행 수·공간 키·집계·NULL·RLS·원천 버전·기준 분포 정밀도를 검증한다. exposure RPC 0.2.2의 데이터 계약과 건물 미적재 처리도 확인한다. 단계별 시작/종료, R2 다운로드 bytes, 로컬 작업/임시 디스크, 원격 DB·테이블·인덱스 bytes, 적재·검증 시간을 기록한다. 적재 전 원격 DB 전체는 10,816,659 bytes(10.82MB)이며 PostgreSQL 17.6, PostGIS 가용 버전 3.3.7을 확인했다. 적재 후 용량·적재 시간·RPC 성능은 아직 미측정이다. 복원량을 DB 용량으로 대신 보고하지 않는다.

## 3. 주소 큐 웹훅

- `.env`의 `GITHUB_DISPATCH_TOKEN`을 파라미터 바인딩으로 Supabase Vault의 `gilmok_github_dispatch_token`에 저장한다. 값은 SQL 파일·로그·GitHub Secrets에 쓰지 않는다.
- 기존 `docs/operations/sql/enable-address-dispatch.sql`의 pg_net 트리거를 재사용하여 Database Webhook을 하나만 활성화한다. 고정 repository_dispatch endpoint에 이벤트 종류만 전송하며 주소·PNU·uid를 보내지 않는다. Dashboard의 전체 행 전송 웹훅을 중복 생성하지 않는다.
- Actions 3개 파일의 `vars.SUPABASE_PROJECT_REF`를 `secrets.SUPABASE_PROJECT_REF`로 맞춘다. `ingest-production` 환경을 준비하고 필요한 접근 권한을 확인한다.
- `repository_dispatch`는 기본 브랜치의 워크플로우를 실행한다. 수정이 main에 반영된 뒤 검증한다. HTTP 204만으로 성공 판정하지 않는다.
- 검증 직전 기존 큐 상태와 자동 실행 일정을 확인한다. 검증 창에서만 Repository Variable을 true로 변경하고, 캐시에 없는 공개 검증 주소를 익명 세션으로 1건 요청한다. pending → pg_net 접수 → Actions run 성공 → 해당 큐/캐시 처리 → RPC 재조회까지 run URL과 상태를 기록한다. 종료/실패 시 모두 false로 복귀시킨다. 상시 자동 적재 활성화는 별도 운영 결정이다.

## 4. 익명 인증·RLS·일일 제한

Supabase anonymous sign-in을 활성화한다. 익명 로그인 사용자는 `authenticated` 역할과 고유 uid를 받는다. 무세션 `anon` 역할과 구분한다. [공식 인증 문서](https://supabase.com/docs/guides/auth/auth-anonymous)

- `candidates`의 기존 `auth.uid() = user_id` 소유자 정책을 재사용하고 insert/select/update/delete 전 경로를 검증한다.
- `comparisons(id,user_id,candidate_ids[],weights,preset_id,created_at)`를 신설한다. 소유자 RLS와 함께 후보 ID 배열이 같은 사용자의 실제 후보만 참조하고 최대 5개인지 서버에서 확인한다. 공유 공개 읽기는 S3-5 범위다.
- 큐는 private 상태를 유지한다. 사용자 제공 uid를 신뢰하지 않고 JWT의 `auth.uid()`로 요청자를 결정한다. uid·한국 날짜 기준 카운터와 트리거로 익명 사용자당 일 10건을 원자적으로 제한한다. 11번째 동시 요청도 거절되어야 한다.
- 카운트는 실제 새 pending 작업 생성 기준이다. 기존 pending 조회·유효 캐시 조회·같은 주소 중복 요청은 차감하지 않는다. 만료된 done 주소를 새 pending으로 재요청하면 한 건이다. 기존 `INSERT ... ON CONFLICT`의 무조건 BEFORE INSERT 카운트로 중복 차감하지 않는다.
- 무세션 호출이 주소 큐 생성 경로를 우회하지 못하게 한다. 기존 조회 전용 RPC와 신뢰된 배치 경로는 유지한다. service-role 예외는 검증된 역할에만 적용하고 SECURITY DEFINER의 DB 소유자 권한을 사용자 인증으로 오인하지 않는다.
- 이메일 연결은 같은 익명 세션의 `updateUser` 흐름으로 확인한다. 인증 링크 완료 전후 uid, candidates/comparisons ID와 소유권이 유지되어야 한다. 별도 `signUp`으로 사용자를 새로 만들지 않는다. 실제 이메일 수신 확인은 사용자가 수행하며, 승격 UI 자체는 S3-5에 남긴다.

## 5. Next.js·Vercel 골격

기존 pnpm/TypeScript/ESLint/Vitest와 채점 라이브러리를 유지하여 Next.js **15 App Router**, React 호환 버전, Tailwind **4**, Supabase JS 클라이언트를 추가한다. Node 22와 pnpm 10.7.1을 유지한다. 새 라이브러리의 목적과 정확한 버전을 PR에 기록한다. 지도 라이브러리와 Zustand는 실제 소비 화면 태스크에서 추가한다.

예상 파일: `app/layout.tsx`, `app/page.tsx`, `app/globals.css`, `app/compare/page.tsx`, `lib/supabase/client.ts`, `next.config.ts`, `next-env.d.ts`, PostCSS 설정, `package.json`, lockfile, TypeScript/ESLint 설정, `.env.example`.

`/compare`는 기존 세션을 재사용하고 없을 때만 익명 로그인한다. 개발 Strict Mode에서도 중복 로그인·중복 RPC가 생기지 않도록 요청을 공유한다. 고정 검증 좌표·800m·3층·address 미전달로 `score_inputs`를 한 번 호출해 loading/error/JSON을 표시한다. 사용자별 세션은 브라우저에 두고 결과를 공용 정적 캐시에 저장하지 않는다. 이 단계에서 주소 큐를 화면 진입만으로 생성하지 않는다.

### 환경변수 매핑

Vercel Marketplace [공식 자동 주입 목록](https://supabase.com/docs/guides/integrations/vercel-marketplace)을 확인했다. 아직 Vercel 프로젝트가 연결되지 않아 실제 배포 프로젝트의 주입 결과는 미확인이다. 연결 후 `vercel env ls` 또는 Dashboard에서 이름만 확인한다.

| Marketplace 이름 | 앱/운영 사용 |
| --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | `.env.example` 같은 이름, 브라우저 API URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `.env.example` 같은 이름, 익명/사용자 세션 클라이언트 |
| `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | 같은 이름의 서버 전용 예약값. 브라우저로 노출하지 않음 |
| `SUPABASE_PUBLISHABLE_KEY` | 서버 측 공개 키 이름. 브라우저는 위 NEXT_PUBLIC 이름 사용 |
| `POSTGRES_URL`, `POSTGRES_PRISMA_URL`, `POSTGRES_URL_NON_POOLING`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PASSWORD`, `POSTGRES_DATABASE` | Marketplace DB 연결 값. 배치용 Session pooler URI와 구분 |
| `SUPABASE_JWT_SECRET` | 앱 골격에서 직접 사용하지 않음 |

S3-1 브라우저 실행에는 첫 두 값만 필요하다. `.env.example`에 매핑과 원격/로컬 구분을 주석으로 남긴다. `POSTGRES_URL`을 검증 없이 배치 `SUPABASE_DB_URL`로 복사하지 않는다. Session pooler는 [공식 연결 방식](https://supabase.com/docs/guides/database/connecting-to-postgres)에 따라 5432/TLS로 확인한다.

## 6. GitHub Secrets

명시적으로 승인된 `.env`의 13개 이름과 원격용 `SUPABASE_DB_URL`까지 총 14개를 등록했다. 새 Personal Access Token·갱신된 DB 비밀번호를 반영했다. 이름만 출력하여 확인했으며 `INGEST_REMOTE_ENABLED=false`다. `NEIS_API_KEY`는 값이 있어 포함했다. [점검 기록](../validation/s3-1-preflight-20260926.md)

`SUPABASE_DB_URL`은 원격 비밀번호로 Session pooler 연결을 확인한 뒤 등록했다. `.env` 로컬 URL은 사용하지 않았다. `SUPABASE_SECRET_KEY`, `NEXT_PUBLIC_*`, `GITHUB_DISPATCH_TOKEN`은 등록하지 않는다. 비밀 등록에는 `gh secret set`의 표준입력을 사용하고 마지막에 `gh secret list`의 이름만 기록했다.

## 7. 테스트·완료 기준

- `pnpm lint`, `pnpm typecheck`, `pnpm test`, 관련 DB 통합 테스트, `pnpm build`.
- R2 replay의 hash·행 수·공간/NULL 일치, source fingerprint 검증, remote target 오지정 거절 및 단계 실패 시 미반영.
- 익명 사용자 A/B의 후보·비교 교차 접근/소유자 위조/타인 후보 참조 차단, 이메일 승격 전후 uid·소유권 유지.
- 큐 신규 10건/11번째, 병렬 요청, 중복·cache hit, 날짜 경계, 무세션 우회, worker 처리 경로.
- 배포 `/compare`에서 익명 세션 생성/재사용과 score_inputs 1회 응답. Playwright의 전체 등록→채점 흐름은 screens.md에 따라 S3-2에서 추가한다.
- 원격 6조합 DB p95 <1초, HTTP 기록, 실제 주소 웹훅/Actions 처리 완료, 용량·시간 실측.

PR에는 screens.md S3-1 완료 기준을 그대로 옮겨 각 항목을 체크한다. 후속 S3-2 예고와 실제 응답으로 확인한 변경/미확인 항목을 구분한다. 문서·코드는 별도 커밋한다. 운영 결과는 `docs/validation/s3-1-*.md`에 기록하며 미실행 항목을 완료로 표시하지 않는다.

## 8. 사용자가 해야 할 단계

1. **완료:** `.env`의 원격 Database password 갱신. 연결·migration 대조·기존 28개 dry-run과 DB URL Secret 등록을 확인했다.
2. **계획 승인 완료.** [최종 dry-run과 복원 manifest](../validation/s3-1-20260926.md)를 보고 원격 쓰기를 승인한다.
3. 코드 PR을 검토·머지한다. 실제 repository_dispatch 검증은 변경된 워크플로우가 main에 있어야 가능하다. 필요한 경우 `ingest-production` 환경의 조직 정책/승인자를 설정한다.
4. Vercel에서 GitHub 저장소 `hanbeulYou/Gilmok`, root `./`, Framework Next.js, Node 22, install `pnpm install --frozen-lockfile`, build `pnpm build`, 기본 Next.js output으로 연결한다. Supabase Marketplace 연동을 프로젝트에 연결하고 Production/Preview 환경변수 이름을 확인한다.
5. Vercel 도메인 및 사용할 운영 URL을 정한다. Supabase Auth Site URL/Redirect URLs에 운영 URL·localhost·실제 검증할 Preview URL을 등록한다. `gilmok.kr` 확보·연결은 사용자 작업이다.
6. 이메일 승격 검증에 사용할 메일 주소를 정하고 확인 링크를 직접 완료한다. 전후 uid·데이터 보존은 검증 스크립트로 확인한다.

## 9. 예상 리스크와 후속 경계

DB 인증 차단은 해결됐고 원격 PostgreSQL 17.6/PostGIS 가용 버전 3.3.7도 기준과 일치한다. 남은 리스크는 R2 공개 시설 좌표 보완, 원천 메타데이터와 기준 분포의 동일성, 실제 확장 설치/마이그레이션 실행, 기본 브랜치 웹훅 실행 순서다. 구현 시간과 원격 적재 시간은 분리 기록한다. 기존 운영 문서의 1.5~4시간 추정은 pg_dump 중심이므로 R2 replay 실측으로 대체한다.

2026-09-26 사용자 결정으로 다음 세 항목을 확정했다. 이번 PR은 문서만 반영하고 구현은 S3-2다. screens.md는 수정하지 않는다.

1. 백분위: raw 값을 받아 백분위를 반환하는 RPC를 추가한다. 기존 분포 전체 반환 RPC를 브라우저 다운로드 경로로 쓰지 않는다.
2. Realtime: 비공개 주소 캐시를 직접 구독하지 않는다. 요청자 uid로 RLS를 적용한 상태 뷰를 통해 요청 id·status·updated_at만 노출하고 그 상태를 구독한다. 주소·PNU·대장 payload는 구독 결과에 포함하지 않는다. 일반 SQL VIEW는 Postgres Changes의 직접 publication 대상이 아니므로, S3-2에서 이 공개 계약을 유지하는 상태 투영 관계/구독 구현을 검증한다.
3. 주소 API: 사용자 요청으로 시작한 자동완성·지오코딩은 Next.js Route Handler 호출을 허용한다. 키는 서버 환경변수에만 두고 geocode_cache에 결과를 캐시하며 uid당 일일 제한을 둔다. 배치·대장 조회는 계속 /ingest 전용이다. AGENTS.md에 승인 예외를 추가했다.

Vercel 연결·도메인·Auth URL 등록은 프론트 골격의 main 머지 후 사용자가 수행한다. 필요한 설정값을 PR 설명에 포함한다.


### 로컬 검증에서 확정한 복원 보완

공개 좌표·provenance 외에 생활인구 수치와 건물 4326 도형의 기존 표현을 보존하는 R2 baseline을 추가했다. 원본 재계산과 전수 대조를 통과해야만 사용한다. 생활인구의 기존 abs 1e-8/rel 1e-10 허용오차와 도형 정점별 1μm 검증 후, 최종 18개 테이블의 전체 행/도형 digest가 원래 DB와 일치함을 확인했다. DECIMAL은 float 변환 없이 복원한다. 현행 RPC의 transit_counts.source LIMIT 1 선택은 허용된 버스/지하철 메타데이터에 한해 비교 시 정규화한다. 자세한 실측·한계는 실행 승인 자료를 따른다.
