# G 원격 승격 사전 확인 — 2026-10-21

**1단계 완료 / 원격 쓰기 승인 대기.** [ADR](../decisions/20261021-juso-api-coordinates-tokyo.md)에 따라 공식 회신 대기를 종결했다. 이번 실행은 `supabase db push --linked --dry-run`과 원격 `REPEATABLE READ READ ONLY` 조회, 로컬 파일 hash 대조뿐이다. 실제 migration push·데이터 승격·R2 게시·#40 배포·#41 Ready 전환은 하지 않았다. 연결 pooler는 도쿄 `ap-northeast-1`, DB 세션 `transaction_read_only=on`을 확인했다.

## Migration dry-run

**기존 객체 변경 여부: 기존 테이블·열·함수·트리거·정책 교체/DROP/기존 행 변경 없음. 신규 private 테이블4개·조회 RPC1개와 신규 객체의 RLS/권한·comment만 추가한다.** 실제 데이터 승격의 기존 행 변경은 아래 별도 범위다.

CLI2.72.7, 최종 exit0, **0.542초**. 동일 조회의 최초 실행은0.655초였다. 대기 파일은2개다.

| 파일 | 내용 | SHA256 |
|---|---|---|
| `20261012150926_academy_display_provenance.sql` | `academy_display`, `academy_display_release` | `fec8fe2a028645d2430acf1ab381311efda8297266495adb4c3df2af73f2f00b` |
| `20261016084609_academy_layer_rpc.sql` | `academy_coordinate_reviews`, `academy_layer_release`, `public.academy_layer` | `add798767fb4375416b349adea70a157ce8dacce07175a4b14cf93309b274e45` |

두 번째는 #41과 **동일 이름/동일 hash**의 공유 migration이다. 중복 파일을 만들거나 #41 머지 때 다시 실행하지 않는다. `create schema if not exists app_private`는 기존 schema를 교체하지 않는다. 새 테이블은 직접 anon/authenticated 접근을 허용하지 않고, 새 RPC만 authenticated EXECUTE다. 이 단계에는 #40의 `claim_address_call` 교체 migration을 섞지 않는다.

```text
DRY RUN: migrations will *not* be pushed to the database.
Would push these migrations:
 • 20261012150926_academy_display_provenance.sql
 • 20261016084609_academy_layer_rpc.sql
```

## 고정 승격 자료와 원격 대조

대상 manifest: `.local/academy-transition/layer-release-20261018/after/rollback/manifest.json`

- manifest SHA256: `081faf63127aca46fe5c9d716959d7ec85db03dc4ceb9c6c898b285f5a2a1da7`
- 대상 12파일의 **gzip SHA·해제한 COPY BINARY SHA 전부 일치**.
- 현재 원격 분포: `20261012T013000Z`, source fingerprint `160930013c9cf4c019bb8a8ef0835a239b9287004a28238720ff6d17ce31c6e8`.
- 로컬 목표 분포: `20261016T040000Z`, source fingerprint `ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`.
- 학원·학교 외 원천 메타 차이 **0**, 250m 격자 동일. 목표 manifest와 로컬 검증 DB fingerprint 일치.
- 이 manifest는 **승격할 로컬 자료**다. 현재 원격의 rollback 백업이 아니다. 승인 후 쓰기 직전에 원격 상태를 별도 COPY BINARY manifest로 보존하고, 이번 확인 이후 fingerprint/소스/행수 변화를 재확인한다.

| 테이블 | 현재 원격 | 목표/실제 쓰기 방침 |
|---|---:|---|
| `public.academies` | 25,527 | 동일 기관 집합의 검증된 Juso 좌표/출처 등 반영,25,527행 |
| `public.schools` | 1,320 | Juso 유지분+교육시설 표준 위치 보완/보류 상태,1,320행 |
| `public.geocode_cache` | 13,669 | Juso99행 갱신+13,492행 추가 → 총27,161행. Kakao13,542/Vworld28행 보존 |
| `public.score_reference` | 162,032 | 목표 분포162,032행으로 원자 교체 |
| `public.score_reference_sets` | 1 | 목표 source fingerprint/분포 메타1행 |
| `ingest_private.place_snapshots` | 3 | 학원·학교 해당 메타만 갱신, 다른 소스 보존 |
| `ingest_private.refresh_snapshots` | 6 | 이번 대상 소스/release 메타만 반영, 다른 소스 보존 |
| `ingest_private.ingest_runs` | **20** | **20행 보존 + 이번 승격 실행 기록**. 로컬 manifest2행으로 덮어쓰지 않음 |
| `app_private.academy_display` | 없음 | 25,527행 |
| `app_private.academy_display_release` | 없음 | 1행 |
| `app_private.academy_coordinate_reviews` | 없음 | 101행(학원99/학교2) |
| `app_private.academy_layer_release` | 없음 | 1행, 원천·명시층·분포와 같은 transaction |

**로컬12테이블을 원격에 통째로 restore하는 실행은 승인 요청 대상이 아니다.** 원격 실행 이력20행이 로컬2행보다 많으므로 그대로 복원하면 운영 이력이 사라진다. 캐시도 provider/address 기준 Juso 대상만 upsert한다. 현재 원격 Juso99주소는 목표13,591주소에 모두 포함(교집합99, 원격만 존재0)되며, 승인 후 재확인 시 새 원격 전용 행이 생기면 보존한다.

기존 로컬 rollback 함수는 실험용 전체 복원 도구다. 실제 원격 승격은 target snapshot을 staging에 검증한 뒤 위 범위만 반영하고, **승격 직전 원격 백업**으로 롤백해야 한다. 서비스 사용자 후보/비교/Auth·대장 캐시/큐는 쓰기 대상이 아니다. 원격 실행 이력 보존과 신규 캐시 추가를 무시한 전체12테이블 hash 일치를 성공 조건으로 삼지 않고, 교체 대상 digest + 보존 대상 불변 + 최종 source fingerprint/채점 결과를 각각 검증한다.

## 승인 후 2단계 실행·중단 기준

1. 코드/두 migration/hash/target manifest를 고정하고 원격 상태를 재조회한다. 변경된 원천이 있으면 승인 대상과 차이를 보고한다.
2. 두 migration push. 실패하면 데이터 승격으로 넘어가지 않는다. schema 추가와 데이터 승격은 서로 다른 단계이며, 데이터 실패 시 새 테이블/RPC는 비어 있는 상태(gate 닫힘)로 남긴다.
3. 실제 원격 기존 상태의 12테이블 backup(신규4테이블은 빈 상태)을 생성한다. 임시 staging에서 목표 파일·열/형·행수/digest와 보존 범위를 검산한다. 원격 운영 이력20행 보존, 비Juso cache 보존을 검증할 로컬 리허설도 실제 원격 적용 전에 통과시킨다.
4. 학원·학교·좌표/명시층·캐시 대상·기준분포·품질검토·release를 같은 transaction으로 반영한다. release 삽입 등 어느 단계든 실패하면 모두 rollback한다. 승인 없이 Kakao/Vworld cache/키를 삭제하지 않는다. 원본 source 메타와 승격 실행 시각을 구분해 기록한다.
5. 원격 익명 로그인 세션(authenticated)으로 동일 후보/반경/층/미입력 임대료 프리셋의 a~e를 채점한다. 원시 총점·신뢰도·8축을 남기고 아래4자리 총점/순위를 대조한다. 불일치는 원인과 함께 보고하고 다음 단계로 넘어가지 않는다.

| 후보 | 로컬 목표 총점 | 목표 순위 |
|---|---:|---:|
| a 역삼로460 3층 | 83.0108 | 3 |
| b 도곡로409 2층 | 92.7877 | 1 |
| c 역삼로546 3층 | 82.2096 | 4 |
| d 역삼로460 4층 | 81.7561 | 5 |
| e 역삼로460 1층 | 84.9937 | 2 |

순위 **b > e > a > c > d**. 위 값은 로컬 검증/사용자 지정 목표이며 현재 원격 승격 후 결과라고 표시하지 않는다. 2단계 종료 후 멈춰 보고한다.

## 후속 순서 — 이번 실행 없음

- **3단계 #40**: 앞 단계 보고 후 진행. 머지 전에 Vercel Production/Preview의 서버 전용 `JUSO_API_KEY`, `JUSO_COORD_API_KEY` 존재 확인을 사용자에게 요청한다(값 불필요). #40 최종 dry-run/교체 함수 검증 → 승인된 migration push → 사용자 즉시 머지·Production 배포를 한 세트로 진행한다. DB/구 UI 혼재 오류는 #40 운영 절차대로 관리한다. 끝나면 멈춰 보고한다.
- **4단계 #41**: G 승격/앞 단계 확인 후 실제 데이터 RPC/권한/반경N·출처·응답 예산 등 남은 완료 기준을 확인하고 Ready로 전환한다. 합성 결과만으로 자동 Ready 처리하지 않는다. 끝나면 보고하며 사용자 머지 권한은 유지한다.

집계 증거는 [JSON](academy-g-remote-preflight-20261021.json)에 기록했다. 새 원격 COPY/적재·API 호출·R2 변경은 없었다. 이 문서는 승인 요청 자료이며 실행 승인을 대신하지 않는다.

## 2026-10-22 후속

① 두 migration 원격 적용과 기존 45건 불변 확인을 완료했다. ② 검증에 Production 구 코드의 저장 비교 불일치 안내·새 채점 분포 ID 확인 및 Juso 99행의 갱신 전 rollback 검증을 추가했다. [실행 기록](academy-g-migrations-20261022.md)을 따른다. ②는 별도 승인 대기다.

## 2026-10-23 현재 승격 후보 정정 — 원격 재개 전

이 문서의 10/18 target manifest `081faf63…a1da7`은 시험 메타데이터 혼입으로 승격 후보에서 제외했다. 원천/분포 바이트는 같고 운영 메타데이터만 정정했다. 새 정본은 `gilmok_academy_transition_canonical_20261023`, 분포 **20261016T040000Z**, manifest SHA256 **b5d8d7d636a262a2c986be00a5d0ce52dcc09696435e9251968ba062bd1af604**다. [원인·검산](academy-g-metadata-repair-20261023.md)을 최신 기준으로 삼는다. 10/22 원격 백업은 재개용으로 만료했으며 재승인 후 새로 생성한다. ②는 재개하지 않았다.
