# S3-2 C 저장·익명 정리 검증 — 2026-10-02

base main `2f6b631`(#24). 브랜치 `s3/comparison-save-retention`. 채점 명세/프리셋 v0.3과 ScoreResult는 변경하지 않았다. 코드와 문서는 별도 커밋한다.

## 구현 계약

- `save_comparison(uuid,jsonb,jsonb,uuid[],boolean,text)`는 후보 1~5개·비교·순서를 한 트랜잭션으로 저장한다. 기존 소유 후보와 비교 ID만 갱신하며 타 uid ID/관찰 request_id를 거부한다. 재시도는 같은 비교 ID를 사용한다. NULL 임대료와 0을 구분한다.
- `load_comparison(uuid default null)`은 RLS로 자기 비교/후보만 반환한다. 생략 시 가장 최근 비교를 읽는다. 새 RPC·Worker로 다시 채점하고 원시 0~40 슬라이더와 수동 순서를 복원한다. 후보 삭제의 AFTER 트리거는 소유 비교들의 배열과 빈 비교를 같은 트랜잭션에서 정리한다.
- 명명 프리셋은 owner RLS의 `user_weight_presets`. 원시 가중치와 생성 열의 정규화 비율을 함께 보존한다. 전부 0인 프리셋은 거부하지만 비교 저장은 허용한다. 기본 academy_v0/v0.3은 그대로다.
- 첫 익명 저장에서 브라우저 변경/저장소 초기화 시 복구 불가와 미활동 30/90일 안내. 이메일 승격/공유 UI는 S3-5 범위다.
- 마지막 채점 스냅샷은 uid+비교별 로컬 캐시다. 모든 후보의 새 채점이 실패하고 입력·가중치·순서가 같을 때만 전체 읽기 전용으로 복원한다. 부분 새 결과와 과거 결과를 섞지 않으며 다른 uid 캐시는 읽지 않는다.
- 정리는 [운영 문서](../operations/anonymous-retention.md)대로 dry-run 기본·별도 gate·스케줄 없음. 새로운 Vercel 환경변수는 없다.

## 로컬 실제 검증

단위 Vitest 121개, Python 259개, DB 212개 통과. lint/typecheck/build 통과. DB에는 저장 원자성(두 번째 후보가 타 uid이면 첫 번째 INSERT도 롤백), 2uid 조회·쓰기 격리, 후보 삭제 시 모든 비교 수정·빈 비교 삭제, NULL/0, 0 가중치, 명명 프리셋 원시값/비율, 실제 계정 상태 승격 후 데이터 보존을 포함한다.

정리는 30일/31일·저장 90일/91일·최근 활동·이메일/진행 중 승격 제외를 검증했다. 로컬 테스트 uid만 실제 삭제하고 FK 정리·재실행 안전성을 확인했다. 로컬 GoTrue로 생성한 익명 세션을 삭제한 뒤 refresh가 거부되고, 남은 JWT의 `touch_user_activity` 쓰기도 거부됐다. 원격 삭제는 없었다.

Playwright는 한 시나리오로 **등록→3곳 실제 SQL RPC/Worker 채점→슬라이더→명명 프리셋→수동 순서→익명 저장→같은 uid 새로고침/재열기**를 통과했다. Juso/Vworld 외부 호출만 공개 응답 fixture로 대체했고 Route Handler 인증/쿼터/위치 RPC, 채점 RPC, 순수 함수, Worker, 저장 RPC는 실제다. 이 증거는 Vercel의 실시간 공급자 호출 실증과 구분한다.

| 후보 | 총점 | 신뢰도 |
| --- | ---: | ---: |
| a 역삼로 460 3층 | 85.08500496915157 | 90 |
| b 도곡로 409 2층 | 93.3997327394482 | 90 |
| c 역삼로 546 3층 | 83.86448162784299 | 85 |

A0 승인 Juso/Vworld 입력의 v0.3 결과와 동일하다. 등록·재열기 모두 익명 signup은 1회였다. 슬라이더 100회 p95 **33.60ms**, max **33.90ms**(로컬 Chromium; 원시 JSON에 userAgent)이며 조작 중 RPC 추가 호출 0이다. 수동 후보 순서와 demand=17을 복원했고, 명명 프리셋 선택 시 17이 정규화된 백분율로 바뀌지 않았다.

CI용 `tests/e2e/fixtures/snapshot/`은 기존 공개 원천의 대치동 주변 1850m, 후보 3곳 층별개요, 서울 전체 경계/기준 분포를 보존한 고정 부분집합이다. 23개 테이블, gzip 합계 **4,580,087 byte**. Auth·소유 후보/비교·주소 캐시는 포함하지 않는다. 빈 로컬 소스 테이블에만 load하고 gzip SHA256·행 수·정렬된 COPY binary SHA256을 확인한다. 실제 DB를 삭제/교체하거나 RPC 결과를 예상 총점으로 대체하지 않는다. fixture의 .env 키 값 포함 검사에서 일치 0이었다.

최종 실시간 요구 사항은 B의 [로컬·원격 실제 Realtime 증거](s3-2-b-comparison-20261001.md)를 유지한다. Micro 합본 시험은 B/C 완료 기준에 재도입하지 않으며, Small 전환 후 공개 전 재시험 조건을 유지한다. D5 실제 워커 전환은 [별도 PR #25](https://github.com/hanbeulYou/Gilmok/pull/25)에서 실패 원인 확인 중이다.

## 원격 dry-run — push 승인 대기

**기존 객체 변경 있음:** candidates/comparisons 열·트리거/인덱스를 추가하고 `touch_user_activity()`를 사용자 행 잠금·존재 확인으로 교체한다. 기존 행 삭제/DROP은 없고, 누락 activity의 보수적 초기 INSERT는 현재 원격 기준 **0행**이다. 새 저장/삭제 트리거의 동작은 로컬에서 검증했다.

`supabase migration list`에서 기존 버전 일치, `supabase db push --dry-run` exit 0. 표시된 대상은 정확히 아래 2개이며 **원격 push는 하지 않았다**.

| 파일 | SHA256 |
| --- | --- |
| 20261002064719_comparison_save_presets.sql | da102bfe39f22f4abca987e45488d5f3bb5ee912cb79593c1aa867b07c20925d |
| 20261002064828_anonymous_retention_guards.sql | 9588c4eff857a206383ecacb8d20063ce75c6e28c705d0de2fdfa21b0de22636 |

정리 remote dry-run 기준시각 `2026-10-02T13:03:16.460281+00:00`: 대상 **0 uid**, 최근 활동 제외 **6 uid**, 후보/비교/공용 캐시 삭제 예정 **0/0/0**. 선정 SHA256 `a78322a15ce4c3bae04489705bbc21ab39905474a52e985314cd30433259109e`. Repository variable `AUTH_CLEANUP_ENABLED=false` 확인. 정리 schedule/apply 없음.

## 완료 기준

- [x] 익명 비교 저장·같은 uid 재열기·owner RLS
- [x] 명명 가중치 프리셋·원시 슬라이더/정규화 비율 보존
- [x] Playwright 1개(등록→채점→슬라이더→익명 저장→재열기)
- [x] 정리 dry-run 선정/제외·로컬 실제 삭제·승격 보존
- [x] 정리 원격 dry-run, 실제 삭제·스케줄 비활성
- [x] 실제 3곳 점수·성능·기존 Realtime 증거 연결
- [ ] 원격 마이그레이션 push 승인·적용 후 원격 저장 검증

원격 단계는 사용자 승인 후 진행한다. C PR은 Draft이며 사용자가 머지한다.

## CI fixture 정밀도 회귀 검증

최초 CI에서는 b=93.39795311864867로 기준보다 0.00177962 낮았다. 로컬 DB 기본 `extra_float_digits=0`으로 CSV를 내보내 지하철 승하차 raw가 25642.30434782609에서 25642.304347826084로 달라졌고, 기준 분포의 동점 백분위가 바뀌었다. 채점식·허용 오차·기대 총점은 변경하지 않았다. fixture export/load에 `extra_float_digits=3`을 적용하고, 새 격리 DB에 재적재한 23개 테이블의 행 수와 정렬된 COPY binary 해시가 모두 원본과 일치함을 확인했다. CI에서도 적재 후 같은 검증을 수행한다.

## 2026-10-04 push 직전 트리거 조건 확인 — 중단

사용자 승인에 붙은 “B처럼 예외 시 projection_errors 기록·본 쓰기 통과” 조건과 현재 C migration을 대조했다. **조건 미충족으로 2개 모두 push하지 않았다.** 기존 migration 파일·SHA256은 그대로이며 #26은 Draft를 유지한다.

| 새 트리거 | 시점·역할 | 예외 격리 / projection_errors | 결과 |
| --- | --- | --- | --- |
| candidate/comparison/weight_preset_updated_at | BEFORE UPDATE, NEW.updated_at 직접 대입 | 없음 | B의 상태 투영과 다른 본 행 타임스탬프 처리 |
| candidate/comparison/weight_preset_owner_activity | BEFORE INSERT/UPDATE, touch_user_activity 호출 | 없음 | 활동 기록 실패가 본 쓰기를 롤백 |
| remove_comparison_candidate | AFTER DELETE, 비교 배열·빈 비교 정리 | 없음 | 정리 실패가 후보 삭제를 롤백 |

로컬 트랜잭션에서 활동 테이블/비교 테이블에 합성 P0001을 발생시킨 뒤 각각 SAVEPOINT로 대조했다. 각 시험의 사용자·행·합성 트리거는 외부 트랜잭션 rollback으로 모두 제거했다. 원격 DB에는 쓰지 않았다.

| 강제 실패 경로 | 본 쓰기 통과 | SQLSTATE | projection_errors 추가 | 후보 보존 |
| --- | --- | --- | --- | --- |
| 후보 UPDATE → 활동 기록 | false | P0001 | 0 | true |
| 비교 UPDATE → 활동 기록 | false | P0001 | 0 | true |
| 후보 DELETE → 비교 정리 | false | P0001 | 0 | true |

추천 조정안(아직 구현하지 않음): 활동 기록의 부가 쓰기는 AFTER·예외 격리·오류 기록으로 바꾸되, 인증/사용자 존재 확인과 비교 배열의 정합성은 실패 시 롤백을 유지한다. 삭제 정리까지 오류를 무시하면 없는 후보를 가리키는 비교가 남아 C의 원자적 삭제 계약을 깨뜨린다. updated_at 직접 대입은 BEFORE를 유지해야 한다. 이 구분을 사용자에게 확인하고, 기존 migration을 수정하지 않는 추가 migration으로 보완한 뒤 새 dry-run/해시를 보고해야 한다.

## 2026-10-04 승인된 트리거 분류 보완

앞 절의 중단 사유를 새 migration `20261004114404_owner_activity_failure_isolation.sql`로 보완했다. 기존 migration 2개는 수정하지 않았다. **기존 객체 변경 있음:** 활동 트리거 3개를 DROP 후 AFTER로 재생성하고 활동 기록 함수 2개를 교체한다. 데이터 행·테이블·열 삭제는 없다. `updated_at` BEFORE와 후보 삭제→비교 정리 AFTER는 strict 유지한다. AGENTS.md에 두 부류의 규칙을 추가했다.

인증/사용자 존재 확인은 strict로 유지한다. `touch_user_activity`의 활동 시각 쓰기는 오류 기록 후 통과하므로 save_comparison의 선행 호출도 활동 기록 장애 때문에 저장을 막지 않는다. 오류 로그 자체의 실패도 본 쓰기를 막지 않는다. 미해결 활동 오류가 있는 uid는 정리에서 보수적으로 제외하고 다음 정상 활동 기록이 오류를 해결 처리한다.

강제 P0001 검증: 후보 UPDATE·비교 UPDATE·프리셋 INSERT 각각 본 쓰기 성공 + `projection_errors` 정확히 1행. 후보 DELETE→비교 정리 실패는 삭제 롤백·후보/비교 보존. 오류 로그까지 실패하는 경우에도 저장은 통과. 기존 인증/삭제 후 JWT 차단·승격 보존 시험도 통과했다. lint/typecheck, Vitest121·Python259·DB218 통과.

원격 `supabase db push --dry-run` exit 0, 대상은 기존 2개 + 보완 1개 총 **3개**. 아직 push하지 않았다.

| 파일 | SHA256 |
| --- | --- |
| 20261002064719_comparison_save_presets.sql | da102bfe39f22f4abca987e45488d5f3bb5ee912cb79593c1aa867b07c20925d |
| 20261002064828_anonymous_retention_guards.sql | 9588c4eff857a206383ecacb8d20063ce75c6e28c705d0de2fdfa21b0de22636 |
| 20261004114404_owner_activity_failure_isolation.sql | db36bf63b0b092a9169d7de5ca60950f3cc1609b651ac27d4f99bbe779b353b2 |

롤백은 애플리케이션을 이전 배포로 복귀하고 확장 스키마·저장 데이터를 보존한다. 승인된 부수 기록 격리를 되돌려 BEFORE 실패 전파를 복원하지 않는다. 원격 3개 push 승인을 받은 뒤 원격 E2E·3곳 점수·정리 dry-run을 재확인하고 Ready로 바꾼다.
