# S3-1 원격 실행 기록 — 사전 확인 실패로 중단

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
