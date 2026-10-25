# G ② 승격 중단 — 2026-10-22

**원격 백업 통과 후 로컬 staging 대조에서 중단했다. 원격 staging·원천 교체·COMMIT은 실행하지 않았다. ③도 실행하지 않는다.** 사용자의 ‘staging 검산 불일치 시 중단’ 조건을 적용했다.

## 완료된 단계와 발견 사항

| 단계 | 결과 | 실측 |
|---|---|---:|
| 고정 target 파일 검사 | manifest `081faf63127aca46fe5c9d716959d7ec85db03dc4ceb9c6c898b285f5a2a1da7` 및 12개 gzip/COPY BINARY 해시 일치 | 사전 확인 |
| 원격 백업 | 12테이블 COPY BINARY → gzip 재읽기 SHA → 같은 READ ONLY snapshot의 DB 재추출 전수 일치 | 25.525초 |
| 별도 로컬 DB 복원 | 원격 백업 12테이블 행수·바이너리 digest와 source fingerprint 일치 | 성공 |
| 로컬 target/backup staging | 두 묶음 COPY BINARY 파일 검산 후, 비대상 provenance 행 대조에서 아래 불일치 검출 | 4.518초 후 중단 |
| 원격 staging/승격/COMMIT | 미실행 | — |

최초 백업 시도에서는 첫 테이블의 바이트 대조 후 manifest 기록 코드의 `dict(table=t, **v)` 중복 필드로 TypeError가 발생했다(8.033초). 데이터 대조 불일치가 아니며 원격 쓰기도 없었다. 실패 파일/기록을 `rollback-attempt1-recording-error/`에 보존하고 기록 코드만 수정해 전체 백업을 다시 수행했다. 최종 백업 검산은 위와 같이 성공했다.

## 중단 원인: 분포 본체와 운영 메타데이터 불일치

고정 target의 `public.score_reference_sets`/162,032행 분포 본체는 **20261016T040000Z**다. 그런데 같은 12테이블 묶음의 `ingest_private.refresh_snapshots` 중 `source='score_reference'` 행은 다음과 같다.

| 필드 | 현재 원격 백업 | 고정 target |
|---|---|---|
| snapshot | 20261012T013000Z | **20261018T091000Z** |
| period_end | 2026-10-12 | 2026-10-18 |
| manifest | 원천 fingerprint·객체 해시·건수 등이 든 기존 전체 manifest | **{}** |
| committed_at | 2026-10-12T04:24:53.209302+00:00 | 2026-10-18T09:16:25.935924+00:00 |

검산 코드가 학원·학교 외 provenance는 불변이어야 한다고 검사하다가 이 행에서 멈췄다. 기준분포 자체도 이번 승인된 교체 대상이므로 **향후 검사 범위에는 `score_reference` 운영 메타데이터를 명시적으로 포함해야 한다**. 단순히 이 행을 검사에서 제외해 진행할 수는 없다. 원격 기존 행을 그대로 두면 10/12 운영 기록과 10/16 분포 본체가 어긋나고, frozen 행을 통째로 복사하면 10/18/빈 manifest가 된다.

10/18 로컬 release 원자성 검증 결과 파일에는 해당 실행에서 score_reference 단계가 0.001초로 기록되어 있다. 이때의 운영 메타데이터가 target에 남아 있다는 사실은 확인했다. 정확한 작성 경로 자체는 이번 읽기 전용 진단에서 확정하지 않았으며 추정으로 단정하지 않는다. 실제 source fingerprint와 10/16 분포 바이트가 손상됐다는 증거는 없다.

**해결 제안(아직 미실행):** 10/16 기준분포의 실제 manifest·출처를 바탕으로 `refresh_snapshots(score_reference)`의 snapshot/period/manifest를 정합화하고, 새 target/rollback manifest SHA를 제시한다. 학원·학교·캐시·층·검토/release·분포 본체 바이트 불변을 증명한 뒤 로컬 단일 트랜잭션·실패 롤백을 다시 검증한다. metadata를 포함한 교체 범위와 새 고정 SHA에 대한 재승인 전에는 원격 승격을 재실행하지 않는다. 이번 승인 SHA는 변경하지 않고 보존했다.

## 백업과 보존 확인

- [원격 rollback manifest](academy-g-rollback-manifest-20261022.json): SHA256 `bf759b8e4e600c133198f5c72615738caac9f5080b5f782a242f038f2db278b2`. 실제 gzip 파일은 로컬 ignored 경로 `.local/g-promotion-20261022/rollback/`에 있으며 덮어쓰지 않는다.
- `public.geocode_cache` 전체 컬럼·13,669행을 COPY BINARY로 보존했다. **Juso 기존 99행의 갱신 전 값 전부 포함**. 갱신은 아직 없었다.

| provider | 백업 행수 | 백업 시 COPY BINARY SHA256 |
|---|---:|---|
| juso | 99 | `067a9cfd55eb8672596cb969a816af50f7b2c0d1421fd25b197d2523b364fb4f` |
| kakao | 13,542 | `ac2cfca7dc9d92eda0c9dc2c2480732d38e921cab0329b8813819062cccbd5a7` |
| vworld | 28 | `35c6b26a509c15f9c9c7ef0a2b0910a11a6c8b46dec5cd5254bec99b364d0d59` |

중단 후 원격을 READ ONLY로 다시 읽었다. **12테이블 전부** 백업과 행수·바이너리 digest가 같으므로 Kakao/Vworld도 불변이다. 후보·비교·가중치 프리셋·큐/대장 캐시·활동/usage/투영·기존 ingest_runs 20행·Auth도 모두 불변이다. 사용자 행을 추가/수정/삭제하지 않았으며 검증용 익명 signup도 아직 하지 않았다.

- 현재 원격 분포: **20261012T013000Z / 162,032행**.
- 현재 원격 fingerprint: `160930013c9cf4c019bb8a8ef0835a239b9287004a28238720ff6d17ce31c6e8`.
- 목표 fingerprint(미승격): `ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`.
- `academy_layer_release`: **0행**, 미승격 gate 유지.
- a~e 승격 후 총점·순위·신뢰도·결측 및 Production 기존 비교 안내/새 채점 분포 확인은 **미실행**. 목표값을 원격 실측으로 보고하지 않는다.

## Micro 관측과 운영 영향

백업·진단 및 로컬 리허설 사이 506.453초 구간의 프로젝트 전체 누적 지표에서 CPU non-idle 평균 **5.509%**, data 장치 읽기 **223,178,752B**, 쓰기 **367,534,080B**, I/O active 시간 **2.067초**였다. 이는 다른 사용자/백그라운드 작업도 포함한 DB 전체 수치다. 원격 승격을 하지 않았으므로 **승격 CPU/IO/소요 시간으로 해석하지 않는다**. 원격 읽기 과정에도 서버 내부 통계·로그 등 디스크 쓰기는 발생할 수 있다. /data 가용 공간 **6,958,792,704B**를 관측했다. Compute/설정은 변경하지 않았다.

Production 배포도 변경하지 않았다. 실패 뒤 원격 상태를 그대로 유지하고 중단했으며, 보정 승격/롤백/재시도는 실행하지 않았다. COMMIT을 시도하지 않았으므로 commit_unknown 상황도 아니다.

[집계 증거](academy-g-promotion-stopped-20261022.json)에 단계별 상태·원격 보존 대조·측정치를 기록했다. 실행 준비 스크립트는 `.local/g-promotion-20261022/`에 고정 SHA로 보존했다. 이번 작업에서 제품 코드·DB 객체 정의 변경은 없었으며, Node22 `pnpm visibility:build`만 준비 검사로 실행했다.
