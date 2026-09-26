# S3-1 복원 구조 변경·재시도 전 보고

후속: 사용자 승인으로 8GB 확장·원격 복원을 완료했다. 현재 HTTP timeout 검증 중단 상태는 [최신 실행 보고](s3-1-remote-20260926.md)를 따른다. 아래는 재시도 전 판단 근거다.

## 연결 종료 원인

브라우저 도구가 없어 Dashboard Logs Explorer와 동일한 로그 저장소를 Management API로 조회했다. 2026-09-26 10:55~11:02 UTC의 Postgres·Supavisor·PgBouncer 로그 480개를 확인했다. [발췌 원문](s3-1-connection-failure-logs.json).

| 시각 UTC | 실제 로그 |
| --- | --- |
| 10:59:34.730 | `could not write to file "pg_wal/xlogtemp.5666": No space left on device` |
| 10:59:34.734 | WAL writer process가 signal 6으로 중단 |
| 10:59:34.734 | 다른 활성 서버 프로세스 종료 |
| 10:59:34.747 | Supavisor `db_termination`, 당시 `busy` |
| 10:59:34.753 이후 | SQLSTATE 57P03, database system is in recovery mode |

복원 클라이언트의 232.403초 SSL 종료와 시각이 일치한다. 원인은 **WAL 쓰기 중 디스크 공간 소진과 DB 복구 진입**이다. 이 구간에서 idle timeout 종료는 관찰되지 않았고, 조회한 `idle_in_transaction_session_timeout`·`idle_session_timeout`은 모두 0이다. TCP keepalive는 추가하지만 디스크 부족 자체를 해결하는 조치는 아니다.

공식 [로그 조회](https://supabase.com/docs/guides/observability/advanced-log-filtering)와 [필드 명세](https://supabase.com/docs/guides/observability/log-field-reference)를 사용했다. 실제 API는 `logs` 테이블의 `source` 필드를 받았다. `source_name` 쿼리는 오류였고, 폐기된 `logs.all`은 HTTP 410이었다. 이 오류들을 빈 로그 결과로 해석하지 않았다.

## 변경한 복원 구조

고정 manifest는 변경하지 않았다: SHA256 `f5b48dd9d6a79bc91b91bfddb2b9a086f900edbb703924754990132c3a1a32ba`, 55개 R2 객체.

| 순서 | 단계 | 최종 digest 대조 대상 |
| --- | --- | --- |
| 1 | 경계 | admin_dongs, legal_dongs |
| 2 | 인구 | population_age, population_cells, living_pop |
| 3 | 교통 | transit_stops, transit_boardings |
| 4 | 상가·학원·학교 | stores, academies, schools |
| 5 | 건물 | buildings, building_registers, building_floors |
| 6 | 실거래·임대 | commercial_trade_stats, rent_areas, rent_survey |
| 7 | 기준 분포·원천 메타데이터 | score_reference, score_reference_sets |

- 각 단계마다 새 연결·자체 트랜잭션을 사용한다. 데이터와 `ingest_private.restore_stages` 완료 기록(단계·순서·manifest 해시·테이블별 행수/digest·시간)은 같은 트랜잭션으로 커밋한다.
- 같은 manifest 재실행은 완료 단계의 실제 digest와 기록을 다시 대조한 뒤 건너뛴다. 다른 해시, 완료 기록 불일치, 기록 없는 기존 데이터 덮어쓰기, 잘못된 단계 순서를 거절한다. advisory transaction lock으로 동시 적재를 막는다.
- COPY는 **최대 50,000행마다 종료하고 새 COPY**를 연다. COPY 경계에서 트랜잭션을 커밋하지 않으므로 실패 단계 전체가 롤백된다.
- DB 연결은 TCP keepalive idle 30초 / interval 10초 / count 5다.
- 원래 `ingested_at`은 각 단계에서 복원하고 이미 같은 값은 다시 UPDATE하지 않는다. 건물 EWKB·생활인구 float·임대 Decimal을 보존한다. 완료 후 18개 테이블 전체 digest를 다시 대조한다.
- 신규 마이그레이션은 `20260926112125_restore_stage_manifest.sql` 1개다. 기존 원격 29개는 유지하고, [dry-run](s3-1-staged-dry-run.txt)은 신규 1개 적용 예정으로 **0.590초 성공**했다. 원격에는 아직 적용하지 않았다.

## 로컬 격리 DB 검증

새 DB `gilmok_s3_replay_staged`에 30개 마이그레이션을 적용했다. 1~3단계 커밋 후 4단계의 실제 데이터 COPY가 끝난 지점에 의도적으로 예외를 발생시켰다. 앞의 3개 완료 기록은 유지되고 stores·geocode_cache는 0행으로 롤백됨을 확인했다. 재실행은 1~3단계를 건너뛰고 4~7단계를 완료했다. 이후 재실행은 7개 모두 건너뛰었다.

**18개 테이블 digest 전부 일치**. [재개 증거](s3-1-staged-resume-proof.json), [복원 결과](s3-1-staged-local-restore.json), [6조합 RPC](s3-1-staged-local-rpc.json).

| 단계 | 최초 성공 커밋 시간 |
| --- | ---: |
| 경계 | 0.170초 |
| 인구 | 35.742초 |
| 교통 | 5.601초 |
| 상가·학원·학교(재개) | 20.068초 |
| 건물 | 25.354초 |
| 실거래·임대 | 0.317초 |
| 기준 분포 | 2.517초 |

재개 실행 75.989초(완료 단계 검사·전수 검증·유지보수 포함), 최종 DB **823,037,075 byte**. 의도적인 4단계 실패를 포함한 DB 실측이며 이전 718MB 복원의 단순 성능 비교값이 아니다. 로컬 6조합 DB p95 **9.818~61.859ms**, 응답 대조 통과.

`pnpm lint`, `pnpm typecheck`, `pnpm test`(TypeScript 86 / Python 243), `pnpm test:db`(158) 통과. 추가 회귀 검증은 COPY 두 번째 배치의 실패가 앞 배치까지 롤백됨, 단계 실패 시 완료 기록 미생성, 완료 단계 재개, 해시·완료 기록 변조 거부를 포함한다.

## 원격 VACUUM 및 재시도 조건

사용자가 승인한 `VACUUM (ANALYZE)` **1회 성공, 38.308초**. FULL은 실행하지 않았다. [원문](s3-1-pre-retry-vacuum.json).

| 관측값 | 결과 |
| --- | ---: |
| DB 크기 전 → 후 | 566,889,619 → 184,618,131 byte |
| WAL 디렉터리 | 956,301,712 byte |
| `/data` 파일시스템 전체 | 2,077,073,408 byte |
| `/data` 비관리자 가용 공간 | 745,742,336 byte |

DB 크기와 WAL은 별도 측정이다. `pg_stat_user_tables.n_dead_tup` 합계는 0이었으며, 실패 후의 566MB 전체를 dead tuple·WAL이라고 단정하지 않는다. [파일시스템 실측](s3-1-disk-after-vacuum.txt)은 Supabase Metrics API에서 가져왔다.

새 구조의 로컬 최종 DB와 원격 VACUUM 후 DB 차이만 약 638MB다. 현 가용 공간에서 이를 빼면 WAL 증가·임시 공간 여유가 약 107MB다. 이미 디스크 부족으로 DB가 중단된 근거가 있으므로, **8GB 이상 확장 여부를 사용자에게 확인했으며 답변 전 복원 재시도는 하지 않는다.** 크기·원본·해상도·적재 범위를 축소하지 않는다. 디스크나 플랜을 자동 변경하지 않는다.

디스크 조건 확인 후: 새 마이그레이션 1개 push → 같은 manifest 7단계 복원 → VACUUM ANALYZE → 6조합 DB/HTTP → Auth → Vault 순서다. 웹훅 활성화는 main 머지 이후이며, 실패하면 다음 단계로 진행하지 않는다.
