# S3-1 원격 실행 기록 — 2차 복원 실패로 중단

최신 상태: 사용자 재시도 승인 후 migration 29개 push 성공. 복원 도중 SSL 연결이 끊겨 중단했고, 재접속 읽기 전용 조회로 대상 18개 테이블이 모두 0행임을 확인했다. 아래 1차 기록은 이력으로 보존한다.

## 1차 — 사전 확인 실패

승인 대상: migration 29개와 manifest SHA256 `f5b48dd9d6a79bc91b91bfddb2b9a086f900edbb703924754990132c3a1a32ba`.

사용자 지시: push → 복원 → VACUUM ANALYZE → 6조합 DB/HTTP → Auth → Vault 순서. 어느 단계든 실패하면 후속 단계로 진행하지 않고 보고한다.

| 단계 | 결과 | 소요 시간 |
| --- | --- | --- |
| 1. migration push 전 사전 확인 | 실패 — 아래 원인. CLI push는 호출되지 않음 | 0.409초 |
| 2. 고정 manifest 복원 | 미실행 | — |
| 3. VACUUM ANALYZE | 미실행 | — |
| 4. 6조합 RPC DB/HTTP | 미실행 | — |
| 5. Auth anonymous 활성화 | 미실행 | — |
| 6. Vault 토큰 저장 | 미실행 | — |
| Database Webhook 준비·활성화 | 미실행 | — |

발생 시각: 2026-09-26 10:52:32 UTC (19:52:32 KST).

실행 스크립트의 사전 확인이 `supabase_migrations.schema_migrations`에 바로 `count(*)`를 호출해 PostgreSQL `UndefinedTable` 오류를 받았다. migration이 아직 없는 프로젝트에서는 이 테이블 자체가 없을 수 있는데, 실행 스크립트가 존재한다고 가정한 오류다. Supabase CLI나 migration SQL의 실행 실패가 아니다.

이후 읽기 전용 트랜잭션으로 확인한 상태:

- `to_regclass('supabase_migrations.schema_migrations')`: NULL.
- 원격 public 테이블: 0개.
- 이 실행에서 migration CLI, 데이터 적재, 유지보수, Auth/Vault/webhook 변경은 호출되지 않았다.

로컬 실행 스크립트의 사전 확인은 `to_regclass`로 존재 여부를 먼저 확인하도록 수정했다. **push 재시도 및 후속 단계는 실행하지 않았다.** 실패 기록은 보존하며 PR #20은 Draft로 유지한다. 원격 실측값은 아직 없고, 기존 로컬 검증 수치를 원격 결과로 대체하지 않는다.

## 2차 — 사용자 재시도 승인 후 실행

사전 확인 수정과 동일 승인 범위의 재시도를 사용자에게 승인받아 실행했다. manifest SHA256은 동일하다. [단계별 원문](s3-1-remote-attempt2-steps.json), [push 로그](s3-1-remote-push.txt), [실패 후 읽기 전용 상태](s3-1-remote-attempt2-state.json)를 따른다.

| 단계 | 결과 | 소요 시간 |
| --- | --- | --- |
| 1. 사전 확인 + migration push + 이력 대조 | 성공 — 로컬과 원격 29개 일치 | 5.978초 |
| 2. 고정 manifest 복원 | 실패 — SSL 연결 끊김, 적재 롤백 확인 | 232.403초 |
| 3. VACUUM ANALYZE | 미실행 | — |
| 4. 6조합 RPC DB/HTTP | 미실행 | — |
| 5. Auth anonymous 활성화 | 미실행 | — |
| 6. Vault 토큰 저장 | 미실행 | — |
| Database Webhook 준비·활성화 | 미실행 | — |

복원 실패 시각: 2026-09-26 10:59:34 UTC (19:59:34 KST). psycopg 오류는 `OperationalError: consuming input failed: SSL connection has been closed unexpectedly`다. 복원 성공·커밋 기록은 없으며 후속 단계를 호출하지 않았다. 연결 종료의 근본 원인은 아직 확인되지 않았다.

첫 상태 확인 연결도 실패했다. 이후 읽기 전용 재접속으로 11:01:33 UTC에 확인한 결과(조회 26.563초):

- Supabase Management API 프로젝트 상태 `ACTIVE_HEALTHY`.
- migration 이력 29개 유지.
- 복원 대상 원천·기준 분포 테이블 18개 모두 0행. 적재 트랜잭션의 롤백 확인.
- `pg_database_size`: **566,889,619 byte**. 실패 후 관측 용량이며, 복원된 유효 데이터 용량이나 최종 유지보수 후 용량이 아니다. VACUUM은 실행하지 않았다.
- `pg_postmaster_start_time`: `2026-09-26T08:54:10.488023+00:00`. 이 값만으로 연결 종료 원인을 특정하지 않는다.

PR #20은 원격 복원 및 후속 검증 미완료로 Draft를 유지한다. 원격 복원 재시도, 유지보수, Auth/Vault/webhook 변경은 이 실패 이후 실행하지 않았다.
