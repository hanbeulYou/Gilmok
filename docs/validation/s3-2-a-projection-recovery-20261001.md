# PR A 투영 실패 분리·보정 검증

> 2026-10-01 후속 검증: Vineyard 팀으로 재연결·Preview 재배포 후 실제 icn1/Juso·Vworld200, 원격3곳 점수 일치·uid 격리·검색 한도·authenticated HTTP6조합을 통과했다. [최종 검증](s3-2-a-region-retry-20261001.md). 아래 내용은 당시 증거로 보존한다.

2026-10-01. 사용자 승인에 따라 원본 migration4를 보존하고 후속 migration6으로 고쳤다. 기존5개+보완1개, 총6개가 원격 적용 대상이다. 아래는 원격 실행 전 로컬 검증이며 원격 결과는 별도 절로 추가한다.

## 구현

- 큐/캐시의 기존 AFTER 트리거를 유지한다. 상태 갱신을 BEGIN…EXCEPTION WHEN OTHERS 안에서 실행하고 RETURN NEW로 종료한다. app_private.projection_errors에 시각·원천 테이블·행 식별자·SQLSTATE·메시지를 남긴다. 기록 테이블은 private/RLS이고 Data API 역할은 접근하지 못한다.
- 오류 기록 자체도 실패하면 SQLSTATE만 warning으로 남기고 원래 쓰기를 유지한다. 함수 범위 lock_timeout250ms로 투영/오류 기록의 잠금 대기가 원천 쓰기에 오래 붙지 않게 한다. 오류 메시지와 행 식별자는 운영 로그/공개 응답에 출력하지 않는다.
- 보정 함수는 모든 관찰자와 미해결 오류를 대조한다. 현재 유효 캐시를 우선하고 없으면 큐 상태를 사용한다. 누락/불일치 상태를 고친 뒤 해당 오류를 resolved_at으로 종료한다. 주소별 기존 advisory lock을 공유한다. 오류 기록이 누락돼도 모든 관찰자를 검사하므로 상태를 복구한다.
- sweep의 drain 뒤 always 보정 단계를 추가했다. scanned/mismatched/repaired/errors_resolved/unresolved_errors를 보고하며 보정 실패나 미해결 오류가 남으면 실패 종료한다. 체크아웃은 기존 main이고 INGEST_REMOTE_ENABLED=false를 유지한다. B 실증 전 상시 운영/6시간 주기 전환은 실행하지 않는다.
- 주소 워커 --dry-run은 읽기 전용 큐 수만 조회하고 claim/API/원본 적재를 하지 않는다. 보정 --dry-run 역시 쓰지 않는다.

## 로컬 조건 재검증

- 큐에 강제 P0001: 원천 UPDATE 성공(processing), 투영은 pending, 오류1행. 보정 dry-run 불일치1, 실제 보정 repaired1/errors_resolved1/unresolved0, 투영 processing 복구.
- 캐시 INSERT 강제 실패도 원천 not_found 저장 성공·오류1행·보정 복구를 별도 DB 테스트로 확인했다. 오류 기록까지 실패하는 경우와 보정 재실패/재실행 idempotency/접근 권한도 검사한다.
- S3-1 6조합 원본과 wrapper의 동일 호출 출력은 schema1.3, 추가 필드 외 diff0. 시간 필드를 제외하지 않았다. 시그니처·authenticated EXECUTE·SECURITY INVOKER·빈 search_path·extra_float_digits3을 유지한다.
- 주소 워커 dry-run: processed0/pending0/needs_review0. 보정 빈 큐 dry-run: scanned0/mismatched0/unresolved0.
- 원격 초기 activity INSERT 대상: 1행(조회시각 2026-10-01T08:44:45.617623+00:00). 읽기 전용 조회이며 아직 초기 적재를 실행한 결과가 아니다.

검증 게이트: lint(로컬 worktree ignore를 해제한 Ruff 포함), typecheck, build, Vitest101/Python259/DB198 통과.

## 최종 dry-run·해시

2026-10-01T08:45:26.650290+00:00, exit0, 1.050초. db push --linked --include-all --dry-run에 아래6개만 표시됐다. 이전 승인5개 해시는 그대로다.

| 파일 | SHA-256 |
| --- | --- |
| `20260930072813_registration_reference_percentiles.sql` | `5ac5e84e0f45e8ce05d65d4829afad6663477459a7fc8a93a962e643da5df9d7` |
| `20260930073201_registration_candidate_context.sql` | `bf18dafd1a2e368e877ce5310525662cedd6e36fa210d1d86f3a1c0462f01718` |
| `20260930110600_registration_usage_and_candidate_fields.sql` | `7df31b4645104715a6d20b64c256891d86e55ee88a54f8172f9673c3739a0d2b` |
| `20260930112203_registration_lookup_projection.sql` | `d3d96e6b5be4d5fcd432f4cd6ab8d2465e4e64dea8105e222e207d1f31e514ca` |
| `20260930112543_registration_lookup_conflict_target.sql` | `a6a010af91425ffe5f523effe5420c678693eb7c43d9b6eeb12510322028dcde` |
| `20261001083920_projection_failure_isolation_and_reconcile.sql` | `ba11ea015bf44da0d0c2423d5810eace6595718c44526d7fca1bce4a3113cb00` |

## 롤백 SQL — 로컬 검증

적용된 DB에서만 사용한다. 먼저 호출 UI/보정 workflow를 중단하고 실행한다. 신규 wrapper와 두 원천 트리거를 제거하고 원본 객체·ACL·보안 설정을 복귀한다. 로그/관찰자/후보 데이터는 보존하며 오류 전파가 있던 트리거 함수 구현으로 되돌리지 않는다. 현재 원격에서는 승인된 push 전까지 실행하지 않는다.

```sql
-- Stop the PR A/B caller before applying. Run only as the migration owner.
-- Includes migration 6: retain projection_errors and repair helpers for inspection.
-- Disable the reconciliation workflow before reverting. Do not restore unsafe trigger code.
-- Retains all candidate, quota, activity and watcher rows. Existing other triggers remain.
begin;
set local lock_timeout = '5s';
drop trigger if exists candidate_lookup_request_update on ingest_private.building_address_requests;
drop trigger if exists candidate_lookup_cache_update on ingest_private.building_address_cache;
drop function public.score_inputs(double precision,double precision,integer,integer,text);
alter function score_internal.score_inputs_registration_base(double precision,double precision,integer,integer,text)
  rename to score_inputs;
alter function score_internal.score_inputs(double precision,double precision,integer,integer,text)
  set schema public;
-- Original function ACL/security/search_path travel with the original object.
commit;
```

## 리전 확인 방법

Route Handler 응답의 X-Gilmok-Function-Region은 서버의 VERCEL_REGION을 읽어 제공한다. preferredRegion=icn1은 설정값이고 이 헤더를 실제 Vercel 요청에서 확인해야 실증 완료다. [Vercel 공식 런타임 변수](https://vercel.com/docs/environment-variables/system-environment-variables#vercel_region). 키나 인증 토큰은 헤더에 넣지 않는다.

재현 스크립트·테스트 로그는 로컬 `.local/validation/s3-2-a-recovery-20261001/`, [수치/카탈로그 증거](s3-2-a-projection-recovery-20261001.json). 원격 결과는 아래 절과 PR에 기록한다.

## 원격 실행 결과 — Vercel 등록 단계에서 중단

검증 코드 `ebb31a2`, Preview HEAD `6a62bdda83c1db8bad7729db4571915258a0cf7c`. [CI](https://github.com/hanbeulYou/Gilmok/actions/runs/36838852108)·Preview 빌드는 성공했다. 원격 단계는 아래 순서로 수행했고, 등록 실패 후 다음 검증과 Ready 전환을 중단했다. [원격 숫자 증거](s3-2-a-remote-20261001.json).

| 단계 | 결과 | 소요 |
| --- | --- | ---: |
| 최종 dry-run | 승인된 기존5개+보완1개, exit0 | 1.050초 |
| 원격 push | 6개 적용·초기 활동 이력1행·투영 오류0·authenticated EXECUTE 확인 | 2.559초 |
| 직접 SQL 6조합 | 조합별 첫 실행1회+웜30회, 전부 웜 p95<1초 | 57.118초 |
| 월간 예열 단계 수동1회 | `ingest.warm_score_inputs.warm()` 6조합 성공 | 1.693초 |
| 익명 세션 | 실제 anonymous signup2회 성공 | 1.449초 |
| Preview 첫 후보 등록 | 검색200, 좌표조회502, 점수 화면 도달 실패 | 68.666초 |

월간 전체 데이터 갱신 워크플로는 실행하지 않았고, 그 워크플로가 호출하는 예열 단계만 수동 실행했다. `INGEST_REMOTE_ENABLED=false`는 유지했다. 예열6회 SQL 왕복은 76.809~301.967ms였다.

### 직접 SQL 성능

authenticated 역할로 `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`을 사용했다. 각 조합은 새 연결이며 첫 실행을 별도로 기록하고 이후30회 웜 p95/max를 계산했다. PostgreSQL/OS 캐시를 비우지 않았으므로 첫 실행을 물리적 콜드 캐시라고 단정하지 않는다. 측정 트랜잭션만 timeout60초이며 기존 authenticated15초 설정은 유지됐다. 같은 호출의 payload를 GUC에 담는 작은 계측 비용이 포함된다.

| 좌표 | 반경 | 첫 실행 ms | 웜 p95 ms | 웜 max ms |
| --- | ---: | ---: | ---: | ---: |
| 대치 | 500m | 4039.893 | 50.685 | 57.875 |
| 대치 | 1000m | 3775.637 | 155.886 | 174.047 |
| 학여울 | 500m | 89.143 | 42.063 | 58.018 |
| 학여울 | 1000m | 622.442 | 123.217 | 126.788 |
| 한티 | 500m | 347.045 | 335.558 | 399.847 |
| 한티 | 1000m | 3195.687 | 368.835 | 406.870 |

첫 실행이3초를 넘은 것은 대치500/1000m, 한티1000m다. 세 조합의 가장 긴 `meta.bundle_ms`는 각각 market1,477.742/2,350.801/2,241.039ms이고 building은560.294/906.641/769.352ms였다. 개별 묶음3초 초과는 없었다. EXPLAIN 실행 시간에는 묶음 바깥 처리도 포함되므로 묶음 합과 같지 않다. 웜은 모두 통과했고 컴퓨트 변경은 하지 않았다. 이번 authenticated HTTP6조합 재측정은 등록 중단 이후 실행하지 않았다.

### Vercel 실제 응답과 중단 사유

[검증 Preview](https://gilmok-hgxl2lgp9-hanbeulyous-projects.vercel.app/new)는 Production이 아니다. Vercel 계정의 같은 프로젝트 development OIDC 단기 인증으로 보호된 Preview에 접근했다. 보호 설정·도메인·Production 배포는 변경하지 않았다. 토큰은 메모리에서만 사용했다.

| 요청 | 결과 | 실제 VERCEL_REGION |
| --- | --- | --- |
| 익명 세션의 Juso 주소 검색: 서울 강남구 역삼로460 | HTTP200, 결과 중 정확한 도로명주소 선택 | iad1 |
| 같은 선택의 등록용 좌표 조회 | HTTP502, `address_provider_unavailable` | iad1 |

- 리전: 코드에는 `preferredRegion=icn1`이 있지만 프로젝트 API의 `resourceConfig.functionDefaultRegions=[iad1]`, `fluid=true`, 배포 API의 `regions=[iad1]` 및 실제 응답 헤더가 모두 미국 iad1이었다. 설정 선언과 실제 실행이 불일치한다. 프레임워크 선언이 배포 설정에 반영되지 않은 더 낮은 단계의 원인은 아직 확정하지 않았다.
- 좌표 조회 경로는 Juso 재검증 뒤 Vworld를 호출한다. 현재 코드는 공급자 네트워크/비200/JSON 오류를 동일한502로 반환한다. Vercel 요청 로그도200·502 상태만 있고 함수 로그0건이라, Juso 재검증과 Vworld 중 실패한 호출이나 서비스 URL/IP 제한 여부를 이 증거로 구분할 수 없다. Vworld 실증 통과로 기록하지 않는다.
- `Cache-Control: private, no-store`를 두 응답에서 확인했다. JUSO_API_KEY·VWORLD_API_KEY의 Production/Preview 등록은 이름으로 확인했다. 미사용 KAKAO_REST_API_KEY도 남아 있으며 삭제하지 않았다.
- 원격3곳 등록/점수 비교, 두 uid RLS 격리, 원격 검색100회 한도 검증은 미완료다. 로컬 동등성 검증 결과를 원격 통과로 대체하지 않는다. PR #22는 Draft를 유지한다.

재개 시에는 `vercel.json`의 `regions:["icn1"]` 등 명시적 배포 리전 설정을 반영하고 실제 헤더를 재검증하는 안을 제안한다. Vercel 공식 문서는 프로젝트 기본 리전이 iad1이며 프로젝트 설정 또는 `vercel.json`으로 변경할 수 있다고 설명한다. [공식 리전 설정](https://vercel.com/docs/functions/configuring-functions/region). 공급자 오류는 단계·HTTP 상태·안전한 오류 코드만 기록해 원인을 구분해야 한다. 이번 중단 후 해당 수정·리전 변경·재호출은 실행하지 않았다.

검증용 익명 uid2개와 그 종속 활동 이력을 정리했다. 정리 후 원래 auth.users1행/활동 이력1행, candidates0/comparisons0/사용량0/관찰자0/투영0/투영 오류0, 공용 geocode_cache13,570행을 확인했다. 기존 사용자·공공 캐시 데이터는 삭제하거나 교체하지 않았다. Auth 감사 로그까지 제거했다는 의미는 아니다.
