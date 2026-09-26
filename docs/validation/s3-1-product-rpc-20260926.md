# S3-1 제품 경로 원격 검산 — 2026-09-26

6조합 모두 직접 SQL 웜 p95 < 1,000ms를 통과했다. 익명 로그인 세션의 HTTP 186회도 성공하고 고정 원본 기준 응답과 일치했다. 승인 조건에 따라 authenticated 제한을 15초로 조정하고 월간 갱신 뒤 예열을 추가했다. Auth·Vault·비활성 웹훅 준비 및 원격 RLS 검증을 완료했다. 웹훅 실제 dispatch와 Vercel 연결은 main 머지 후 진행한다.

## 측정 조건

- 대치 `(37.494612,127.063642)`, 학여울 `(37.496663,127.070594)`, 한티 `(37.496237,127.052873)` × 500/1,000m, 2층, 주소 미입력. 기존 6조합과 동일하다.
- SQL: Session pooler 5432/TLS, `SET LOCAL ROLE authenticated`, `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`의 Execution Time. 조합마다 새 연결에서 첫 실행 1회와 직후 웜 30회를 분리했다. p95는 정렬 후 29번째 값이다. 계측 세션만 timeout 60초로 두어 기존 역할 제한에 잘리지 않게 했다.
- 같은 RPC 호출의 결과를 트랜잭션 로컬 GUC에 저장해 `meta.bundle_ms`와 대조했다. EXPLAIN에는 이 작은 직렬화·GUC 저장 비용이 포함되며 HTTP 왕복은 포함되지 않는다. 매 표본 저장으로 중도 실패 시에도 앞선 측정값을 보존한다.
- **콜드의 의미는 새 세션 첫 실행이다.** DB/OS 공유 캐시는 강제로 비우지 않았다. 이번 EXPLAIN의 Shared Read Blocks는 첫 실행과 웜 모두 0이었다. 따라서 물리 디스크 콜드 캐시 시험이나 재시작 직후 성능 보장은 아니다.
- HTTP: 익명 signup JWT의 `role=authenticated`, `is_anonymous=true`를 확인했다. `Authorization`은 사용자 access token이며 프로젝트 apikey는 헤더에 별도로 사용했다. anon 역할 호출이 아니다. 같은 세션에서 조합별 첫 1회+웜 30회, 총 186회. JWT·uid·키 값은 기록하지 않고 테스트 사용자는 삭제했다.
- 응답은 고정 manifest의 provenance 기준과 대조했다. 시각·성능 메타데이터를 제외하고 기존 `transit_counts.source`의 순서 비결정성(bus/subway 두 허용값)만 정규화했다. 모든 업무 필드가 일치한다.

## 첫 실행·웜 결과

단위 ms. HTTP는 왕복 실측이며 DB 합격 기준과 구분한다.

| 조합 | SQL 첫 실행 | SQL 웜 p95 | SQL 웜 최대 | HTTP 첫 실행 | HTTP 웜 p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 대치 500m | 4132.416 | 54.732 | 79.775 | 3641.145 | 232.190 |
| 대치 1000m | 3813.975 | 148.650 | 163.726 | 2379.846 | 291.048 |
| 학여울 500m | 64.541 | 52.203 | 70.404 | 127.789 | 351.928 |
| 학여울 1000m | 588.459 | 117.729 | 134.916 | 695.952 | 326.780 |
| 한티 500m | 357.937 | 79.503 | 82.160 | 337.276 | 210.615 |
| 한티 1000m | 2046.750 | 220.983 | 231.909 | 1750.794 | 352.982 |

SQL 계측 전체 49.935초, HTTP 계측 전체 48.498초. [SQL 전체 186표본](s3-1-product-sql.json), [HTTP 전체 186표본](s3-1-product-http.json).

## 3초 초과 조합·묶음

SQL 첫 실행은 **대치 500m 4,132.416ms**, **대치 1,000m 3,813.975ms**가 3초를 초과했다. 개별 `meta.bundle_ms`가 3초를 넘은 표본은 없다. 두 조합의 가장 큰 묶음은 market으로 각각 1,490.876ms와 2,471.756ms다. 한티 1,000m 첫 실행도 market 1,545.352ms가 가장 컸지만 전체 2,046.750ms로 3초 미만이었다.

| SQL 첫 실행 | demand | flow | transit | market | compete | building | rent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 대치 500m | 35.757 | 207.636 | 54.032 | 1490.876 | 316.567 | 498.185 | 18.226 |
| 대치 1000m | 14.292 | 239.606 | 5.947 | 2471.756 | 268.555 | 796.030 | 2.220 |
| 학여울 500m | 1.872 | 22.076 | 5.505 | 2.726 | 0.945 | 13.809 | 2.358 |
| 학여울 1000m | 8.907 | 160.368 | 3.004 | 287.193 | 14.278 | 95.649 | 2.872 |
| 한티 500m | 5.594 | 27.800 | 7.752 | 191.642 | 13.421 | 77.049 | 3.146 |
| 한티 1000m | 3.214 | 46.942 | 4.415 | 1545.352 | 31.814 | 393.953 | 2.949 |

묶음 합계와 전체 시간은 같지 않다. sources 메타데이터 등 묶음 밖 작업과 계측 비용이 전체에 포함된다. 실패했던 이전 anon HTTP 요청에는 성공 payload가 없어 해당 요청의 bundle_ms를 소급 확정하지 않는다. 위 표는 이번 직접 SQL 재측정값이다.

| SQL 웜 묶음별 p95 | demand | flow | transit | market | compete | building | rent |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 대치 500m | 0.962 | 8.967 | 0.655 | 7.477 | 2.957 | 15.890 | 1.413 |
| 대치 1000m | 2.236 | 27.135 | 0.923 | 20.765 | 4.965 | 85.437 | 0.649 |
| 학여울 500m | 1.650 | 11.151 | 0.882 | 3.642 | 0.900 | 17.902 | 0.689 |
| 학여울 1000m | 2.972 | 28.523 | 0.963 | 15.103 | 3.517 | 56.600 | 0.617 |
| 한티 500m | 2.324 | 10.418 | 0.848 | 8.705 | 2.788 | 38.438 | 0.662 |
| 한티 1000m | 2.653 | 29.265 | 1.844 | 46.783 | 5.909 | 126.786 | 0.644 |

## 적용·후속 설정

- 웜 p95가 모두 1초 이내여서 Small 업그레이드는 실행하지 않았다.
- CLI로 생성한 `20260926123953_authenticated_rpc_timeout.sql`: `ALTER ROLE authenticated SET statement_timeout=15s`, PostgREST config reload. 원격 readback 15초, 전체 31개 migration. rollback은 새 migration에서 8초로 되돌리고 reload한다. anon 제한은 3초 그대로다. [Supabase 역할별 timeout 공식 절차](https://supabase.com/docs/guides/database/postgres/timeouts)를 따랐다.
- 로컬 CLI 기본 postgres는 이미지의 예약 역할 보호로 ALTER ROLE을 거절했다. 로컬 supabase_admin 연결로 동일 migration을 적용했다. 원격 postgres는 실제 supabase_privileged_role 멤버임을 확인한 뒤 표준 CLI push가 성공했다.
- `.github/workflows/refresh-monthly.yml`: 모든 소스 갱신과 기준 분포 갱신 성공 뒤 `ingest.warm_score_inputs` 6회 호출. 읽기 전용 SQL/authenticated/15초, 오류는 workflow 실패로 전파한다. 한 세션의 예열은 모든 PostgREST backend의 세션 캐시 예열을 보장하지 않으므로 15초 제한도 함께 둔다. 명령의 원격 실증은 완료했으며 월간 workflow 자체의 실행은 머지 후다.
- 실제 HTTP 세션 발급을 위해 SQL 합격·timeout 적용 후 Auth anonymous를 먼저 활성화했다. manual linking=true, 이메일 확인은 계속 필요하다. HTTP 합격 후 Vault·웹훅을 순서대로 준비했다.

| 단계 | 결과 | 소요 시간(초) |
| --- | --- | ---: |
| dry_run | success | 0.990 |
| push | success | 1.471 |
| auth | success | 1.776 |
| http | success | 49.719 |
| warmup | success | 2.788 |
| vault | success | 0.628 |
| webhook_prepare | success | 1.316 |

[단계별 실행 기록](s3-1-product-steps.json), [dry-run](s3-1-timeout-dry_run.txt), [push](s3-1-timeout-push.txt).

- Vault `gilmok_github_dispatch_token` 1건 저장·값 일치 확인. 값은 문서·로그·Actions Secrets에 남기지 않았다.
- pg_net 기반 Database Webhook 함수·트리거를 만들고 같은 트랜잭션에서 disabled로 커밋했다. 트리거 `tgenabled=D`, 큐는 비어 있다. Repository variable `INGEST_REMOTE_ENABLED=false`. main 머지 후 활성화 및 실제 pending 1건의 Actions 완료 확인을 한다.
- 원격 익명 사용자 2명으로 candidates·comparisons 소유자 조회, 타 사용자 조회·삭제 차단, 제품 좌표 800m RPC를 확인했다. 7.447초, 테스트 사용자 2명과 소속 데이터 삭제 완료. [결과](s3-1-product-auth-smoke.json). 실제 이메일 확인 뒤 uid·후보·비교 유지의 증거는 기존 로컬 Mailpit 검증이며 원격 이메일 발송은 하지 않았다.
- 최종 DB 890,186,899 byte, 이전 복원 직후 889,810,067 byte와 측정 시점이 다르다. [최종 상태](s3-1-product-final-state.json). 복원 7단계/18테이블 digest·디스크 확장 증거는 [기존 보고](s3-1-remote-20260926.md)에 보존했다.

## 검증·남은 작업

- `pnpm lint`, `pnpm typecheck`, `pnpm test`(TypeScript 86, Python 245), `pnpm test:db`(158) 통과.
- [코드 커밋 a09a666의 CI](https://github.com/hanbeulYou/Gilmok/actions/runs/36242954701): 위 검사와 Next.js build, 깨끗한 로컬 Supabase 시작·전체 migration까지 통과했다.
- 회귀 검증: HTTP가 사용자 JWT를 보내는지, 실패 전 표본을 보존하며 키를 기록하지 않는지, 기준 응답 변경을 거절하는지 확인했다.
- main 머지 후 웹훅 pending 1건→Actions→캐시 준비 실증. 이후 자동 적재 상시 활성화 여부는 별도 운영 결정이다.
- Vercel 연결·도메인·Auth URL 등록과 실제 배포 URL의 빈 `/compare` 렌더는 사용자 단계다. PR 설명에 필요한 값을 정리한다.
