# 학원 점 레이어 A — 합성 RPC 검증

2026-10-16 · base main `9023d75` · branch `s3/academy-layer-data` · Draft

## 범위와 결론

전체반경 학원 RPC와 TypeScript 계약을 합성 데이터로 검증했다. **원격 DB/R2 읽기·쓰기 0, 외부 좌표 API 호출 0.** 실제 학원 주소/좌표/이름이나 101행의 실제 ID를 fixture로 복사하지 않았다. 공개 기관명·전 분야·명시층·보류 배지 속성만 반환하며 채점 N과 화면 M을 구분한다. 프리셋/채점/기준분포/기존 원천은 변경하지 않았다.

로컬 기능 기준은 통과했다. G 원격 승격과 실제 자료의 품질·최대밀도 대조는 미완료이며 A는 Ready로 전환하지 않는다. B의 지도·팝업·배지 렌더/번들 검증은 후속이다.

## Migration·안전 경계

- `20261016084609_academy_layer_rpc.sql`, SHA256 `add798767fb4375416b349adea70a157ce8dacce07175a4b14cf93309b274e45`.
- **기존 객체 변경 여부: 신규 private 테이블 2개·RPC 1개·신규 객체 권한만 추가. 기존 테이블/함수/트리거/행 변경·DROP 없음.** 새 트리거가 없으므로 부수 기록/정합성 트리거 패턴 변경도 없다.
- G의 표시 테이블 없이 A migration을 적용하고 RPC가 미승격으로 닫히는 것을 시험했다. 표시 스키마는 테스트에서만 합성 fixture로 만든다. metadata 두 테이블은 migration 직후 비어 있으며 자동 활성화/원천 복사 없음.
- Supabase CLI 2.72.7의 별도 프로젝트 `gilmok-academy-layer-synthetic`, API 55421 / DB 55422, PostgreSQL 17.6 로컬 Docker. `.env`를 연결하지 않고 loopback DB URL을 명시했다. 기존 로컬 원천 DB를 재적재하지 않았다.
- 전체 migration을 격리 DB `db reset --local --no-seed`로 적용 성공. **적용 후** `db push --local --dry-run` exit 0, 적용 대기 0. CLI의 마지막 `Remote database is up to date.` 문구는 공통 메시지이며 같은 출력에 `Connecting to local database...`가 있다.
- **원격 dry-run 미실행**: 원격 migration 이력 조회가 필요하여 이번 원격 읽기 금지와 양립하지 않는다. 원격 조회 허용 후 별도 보고/승인 절차를 따른다. 이번 결과를 원격 dry-run 통과로 기재하지 않는다.
- [G 게시 연결·롤백](../operations/academy-layer.md): G 원천/층/기준분포 atomic promotion에 review/release metadata를 함께 게시하고, rollback manifest에도 포함해야 한다. 이 후속 G 수정·원격 실행은 수행하지 않았다.

## 합성 응답·권한·정합성

300/1,500/5,000기관을 중심 `(37.5,127)` 주변에 생성했다. 모든 기관이 800m 안에 있고 첫 10기관은 같은 점이다. `입시.검정 및 보습`·`예능(대)`·빈 분야를 섞고 공개 합성 이름, 지하/복수층/모호/누락층을 포함했다. 학교 보류 두 ID는 별도 inventory에만 존재한다. source/provider 값은 Juso 호출 결과가 아닌 **계약 시험용 합성 metadata**다.

| 검증 | 결과 |
|---|---|
| 실제 SQL `score_internal.compete` vs 학원 RPC | 300기관에서 전 분야 count 일치, 같은 분야 N=100. 모든 성능 시나리오의 ready 응답도 대조 |
| 중복 좌표 | 첫 10점 동일 좌표여도 고유 기관 ID 10개 보존. M 계산은 렌더 ID 중복만 제거 |
| 반경/폐원/NULL | 799.999/800.001/999.999/1000.001m 안팎, 개원/폐원, 좌표 NULL 제외 검증. 정상 0건과 미승격/서울 밖 구분 |
| 보류 101행 | 합성 학원 99 + 학교 2. 300기관에서 반경 보류 99, 같은 분야 보류 33. 학교가 점 응답에 섞이지 않음 |
| 원천 일관성 | 채점 descriptor, 표시 revision/SHA, 보류 버전/행수 불일치 시 `source_mismatch`; G 스키마/gate 없음은 `coordinate_replacement_pending` |
| 공개 필드 | 이름/분야/명시층/보류 3필드만. 비공개 합성 상세주소·uid 없음. 모호층 label=null, 301호를 층으로 추정하지 않음 |
| 권한 | auth.uid 필수·anon EXECUTE 불가·authenticated 허용·private 테이블 SELECT 불가 |
| 두 uid | 실제 로컬 익명 로그인 두 세션의 동일 요청 응답 완전 일치(공개 자료), 개인 자료 없음 |
| SQL→HTTP→TS | 6시나리오 SQL/HTTP JSON 일치, 실제 HTTP 응답을 TS parser로 재검증 6/6 통과. 전체 화면 ID를 넘기면 M=N |
| loader | 최근 5개 메모리 캐시, source/field/radius/center 키, 미승격 캐시 안 함, 동시 1개, abort·늦은 응답 무시 검증 |
| 과밀 | 5,001기관 경계 테스트 및 아래 5,000기관 byte 초과에서 `too_dense`, 부분 feature/counts 없음 |

`quality_inventory`는 전체 검토 목록의 기관 종류별 개수다. `counts.radius_pending`은 반경·개원 조건에 들어온 학원 보류 부분집합이다. 실제 101건 모두가 어떤 반경에나 들어온다고 주장하지 않는다. 숫자 N은 채점 모집단 그대로이며 좌표 보류 학원을 임의 제외하지 않는다.

## 응답 크기·지연

**800m 제안 목표**: SQL 웜 p95 ≤300ms, raw ≤1.5MiB(1,572,864B), gzip ≤256KiB(262,144B); 1000m도 같은 목표. 5,000기관은 검토 경계이며 초과 시 닫는다. SQL >1,000ms나 실제 최대밀도에서 예산 초과가 있으면 원인/대안 보고 후 진행한다.

측정 환경: macOS 26.5.2 arm64의 로컬 Docker Supabase. 이것은 원격 Micro 성능이나 OS 콜드 측정이 아니다. 첫 값은 seed 직후 첫 EXPLAIN ANALYZE, 이후 웜 30회 p95(오름차순 ceil(n×0.95))와 max를 분리했다. OS/Postgres 버퍼를 비우지 않았다. 다른 검사 종료 후 벤치마크만 실행한 최종 값을 채택했다. 처음 다른 검사와 겹친 실행(800m·1,500기관 SQL p95 53.858ms)은 공식 표에서 제외했다.

HTTP는 실제 로컬 익명 로그인 authenticated 세션으로 30회, 별도 두 번째 uid로 동일 응답을 대조했다. `Accept-Encoding: identity`, 실제 Content-Encoding 없음(identity). gzip은 반환 body에 `gzip.compress(mtime=0)`을 적용한 **오프라인 크기**이며 실제 wire 압축으로 주장하지 않는다. [집계 JSON](academy-layer-a-20261016.json)에 max/조건을 함께 보관한다.

| 기관 수 | 반경 m | 상태 | SQL 첫 ms | SQL 웜 p95 / max ms | HTTP p95 / max ms | 실제 응답 raw / 오프라인 gzip B |
|---|---|---|---|---|---|---|
| 300 | 800 | ready | 6.563 | 3.620 / 3.723 | 5.879 / 11.521 | 115,618 / 7,882 |
| 300 | 1000 | ready | 3.537 | 3.389 / 3.481 | 6.590 / 7.687 | 115,619 / 7,881 |
| 1,500 | 800 | ready | 16.282 | 17.203 / 18.452 | 28.845 / 29.788 | 563,058 / 36,285 |
| 1,500 | 1000 | ready | 16.714 | 18.156 / 19.551 | 22.817 / 24.500 | 563,059 / 36,286 |
| 5,000 | 800 | too_dense | 61.562 | 61.239 / 64.252 | 62.424 / 63.171 | 284 / 233 |
| 5,000 | 1000 | too_dense | 57.300 | 58.743 / 65.918 | 63.434 / 63.666 | 285 / 232 |

5,000기관·800m의 정상 형태 JSONB 크기는 **1,870,056B**(1000m 1,870,057B)로 raw 예산을 넘었다. 표의 284/285B는 오류 안내 응답 크기이며 **5,000개 점을 예산 내 전달했다는 뜻이 아니다**. LIMIT로 목록 일부를 반환하지 않는다. 실제 밀집 지역이 이 크기에 도달하면 G 이후 속성 경량화/전송 압축/MVT 중 대안을 검토해야 한다. gzip 목표는 로컬 계측 항목이며 서버 gzip 강제 기능은 이번 범위에 없다.

## 검사

- `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build` 통과. Vitest 226개, Python ingest 269개.
- 신규 TS 계약/loader 18개, 신규 DB 계약 17개 포함. 전체 `pnpm test:db` 282개 통과.
- 전체 DB 검사 첫 실행에서 기존 `test_retention_auth_api`가 기본 프로젝트의 GoTrue를 조회하고 DB는 별도 55422를 사용하여 실패했다. 해당 테스트는 `supabase status` 경로를 내부 호출하므로 실행용 PATH shim으로 동일 격리 프로젝트의 `--workdir`를 지정한 후 282/282 통과했다. 기존 테스트/제품 코드는 변경하지 않았다. 로컬 합성 인증 세션만 사용했다.
- 새 의존성/환경변수/프론트 import 없음. 지도 UI는 아직 신규 모듈을 import하지 않으며 B에서 lazy load/번들/요청 수를 검증한다.

## 실제 응답으로 보완한 사항·다음 PR

실제 **로컬 합성 SQL/HTTP** 응답을 확인했다. 외부 API·원격 실제 기관 데이터 응답을 확인한 것은 아니다. count 이름을 `counts.radius_same_field`로 확정했고, 101행을 학원 99/학교 2로 나눠 inventory와 반경 보류 수를 분리했다. 5,000기관 synthetic에서는 byte 예산이 먼저 걸리므로 과밀 안내와 원본 JSONB byte 진단을 명시했다.

다음 B는 MapLibre 줌 15 이상 전 분야 점/동일 분야 강조, N/M 숫자, 공개 기관명·명시층 팝업, 좌표 보류 배지와 cluster 근거 연동을 합성 자료로 구현한다. G 승격 이후 실제 수 일치·성능·품질을 확인하기 전 A/B Ready는 보류한다.
