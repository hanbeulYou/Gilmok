# PR A 원격 push 사전 조건 검증

> 2026-10-01 후속 검증: Vineyard 팀으로 재연결·Preview 재배포 후 실제 icn1/Juso·Vworld200, 원격3곳 점수 일치·uid 격리·검색 한도·authenticated HTTP6조합을 통과했다. [최종 검증](s3-2-a-region-retry-20261001.md). 아래 내용은 당시 증거로 보존한다.

2026-10-01 · 대상 #22 / `52a726bdae8491316dbd39ca9c0330865b2c18f2`. **조건2 실패로 중단, 원격 push 미실행, Draft 유지**. 제품 코드와 migration 파일을 수정하지 않았다.

사용자 승인 조건: wrapper의 기존 계약/권한/설정 및 S3-1 6조합 동등성, 투영 실패 시 큐·캐시 쓰기 지속과 워커 dry-run, 롤백 SQL, 초기 적재 수를 모두 확인한 뒤에만 실행한다. 이번 검증은 조건1·3·4를 먼저 준비하고 마지막에 조건2의 실패 주입을 실행했다. 실패 확인 후 후속 실행을 중단했다.

## 1. 함수 계약과 6조합 — 통과

- 원격 기존 `public.score_inputs`와 로컬 원본/신규 wrapper를 카탈로그에서 대조했다. 인자명·순서·타입·기본값은 `lat double precision, lng double precision, radius_m integer, floor integer, address text DEFAULT NULL`로 동일하다. 반환 타입은 jsonb, 결과 schema는1.3이다.
- 원격 원본과 로컬 원본 함수 본문의 SHA-256이 같다. authenticated EXECUTE=true, SECURITY INVOKER, search_path 빈 문자열, extra_float_digits=3을 유지한다. volatility/strict/parallel/leakproof도 같다.
- computed_at·bundle_ms·total_ms를 임의로 제외하지 않았다. 로컬 트랜잭션 안에서 원본 본문을 바꾸지 않고 임시 전달 함수를 통해 원본의 반환 JSON을 수집한 다음, 같은 호출의 wrapper 출력과 비교했다. 추가 허용 필드는 meta.building_lookup.request_id 하나뿐이다. 계측 DDL/DML은 최종 ROLLBACK했다.

| S3-1 입력 | 위도 | 경도 | 반경(m) | 층 | schema | 새 필드 외 diff |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| 대치 | 37.494612 | 127.063642 | 500 | 2 | 1.3 | 0 |
| 대치 | 37.494612 | 127.063642 | 1000 | 2 | 1.3 | 0 |
| 학여울 | 37.496663 | 127.070594 | 500 | 2 | 1.3 | 0 |
| 학여울 | 37.496663 | 127.070594 | 1000 | 2 | 1.3 | 0 |
| 한티 | 37.496237 | 127.052873 | 500 | 2 | 1.3 | 0 |
| 한티 | 37.496237 | 127.052873 | 1000 | 2 | 1.3 | 0 |

6조합은 주소 인자를 생략하는 기존 S3-1 입력이다. 해당 조합에는 request_id가 추가되지 않았다. pending 관찰 ID 생성 자체를 이 대조의 실측 결과로 표현하지 않는다. 이는 출력 계약 검증이며 신규 성능 p95 측정은 아니다.

## 2. 상태 투영 강제 실패 — 실패

로컬 임시 사용자·큐 pending1건·관찰자1건을 트랜잭션 안에 준비했다. 투영 테이블 BEFORE UPDATE에 의도적으로 P0001을 발생시키는 테스트 트리거를 붙이고 큐 상태를 pending→processing으로 바꿨다.

- 결과: `preflight_forced_projection_failure` / SQLSTATE P0001이 큐 UPDATE 호출자까지 전파됐다.
- 큐 UPDATE가 실패했고 savepoint 복귀 후 큐 상태는 pending, 투영 상태도 pending이었다. **투영 실패가 본래 큐 쓰기를 막는다.**
- 원인: `app_private.refresh_candidate_lookup()`에 투영 오류를 분리하는 EXCEPTION 처리가 없다. 같은 함수를 캐시 AFTER 트리거도 사용하지만 이번 강제 실패 실측은 큐 쓰기1건이다.
- 테스트 함수/트리거·사용자·큐·관찰자 모두 ROLLBACK했다. 원래 wrapper/원본 함수 SHA와 투영 트리거2개가 복원된 상태이며 테스트 주소 잔여0행이다.
- 주소 워커 dry-run은 실패 확인 후 중단 지시에 따라 실행하지 않았다. 현재 `ingest.address_dispatch` CLI에는 --dry-run 옵션이 없다. 실제 drain을 dry-run으로 대체 실행하지 않았다.

원격 push, 원격6조합 재측정, 월간 예열, 원격3곳/uid/일일 한도 실측, Vercel API/실제 icn1 확인, Ready 전환은 모두 미실행이다. icn1은 기존 코드 설정만 확인된 상태다.

## 3. 4번 migration 롤백 SQL — 로컬 검증 통과

아래 SQL은 **4번이 적용된 DB에서만**, 프론트/Realtime 사용을 멈춘 뒤 migration 소유자로 실행한다. 현재 원격에는4번이 미적용이므로 실행하지 않는다. DROP 대상은 신규 public wrapper 하나뿐이며 원본 함수 객체/ACL/security/search_path는 스키마 이동과 개명으로 되돌린다. 새 테이블과 행은 보존하고 다른 기존 큐 트리거는 제거하지 않는다. 의존성이 추가되면 DROP RESTRICT가 실패하므로 CASCADE로 강행하지 않는다.

```sql
-- Stop the PR A/B caller before applying. Run only as the migration owner.
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

로컬 리허설에서 복귀 함수의 본문·계약·authenticated 권한·security/search_path가 원격 원본과 같고, 신규 큐/캐시 트리거0개를 확인했다. 검증 완료 후 리허설을 ROLLBACK하여 PR A 로컬 상태를 유지했다.

검증 도구 기록: 최초 리허설에서 주석 처리 오류로 로컬 롤백 SQL의 COMMIT이 실행됐다. 원본 파일에서 wrapper/트리거 정의를 복구하고 SHA 일치를 확인한 다음, 도구를 수정해 트랜잭션 ROLLBACK 방식으로 재검증했다. 원격 쓰기나 기존 데이터 행 변경은 없었다. 최종 복원 검증 값은 JSON에 보존한다.

## 4. 초기 활동 적재 대상 — 원격1행

읽기 전용 조회 시각: `2026-10-01T08:30:29.490310+00:00`. `select count(*) from auth.users` 결과는 **1행**이다. 3번의 INSERT는 새 app_private.user_activity로 이 uid들을 초기 적재하며 auth.users를 수정하지 않는다. 아직 실행하지 않았고 실제 push 시점에는 신규 가입 때문에 다시 집계해야 한다.

승인 대상5개 migration은 원격 이력에 모두 미적용이었다. 인증정보·DSN·uid·주소 검색어는 보고서에 기록하지 않았다. [숫자·카탈로그 증거](s3-2-a-push-preflight-20261001.json). 재현용 검증 스크립트/로그는 로컬 `.local/validation/s3-2-a-preflight-20261001/`에 있다.
