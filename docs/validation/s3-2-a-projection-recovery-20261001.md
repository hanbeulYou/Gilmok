# PR A 투영 실패 분리·보정 검증

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

재현 스크립트·테스트 로그는 로컬 `.local/validation/s3-2-a-recovery-20261001/`, [수치/카탈로그 증거](s3-2-a-projection-recovery-20261001.json). 원격 push 후 결과는 이 문서와 PR에 추가한다.
