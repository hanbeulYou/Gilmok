# 익명 사용자 정리 — S3-2 C

2026-10-02: `AUTH_CLEANUP_ENABLED=false`. 원격은 read-only dry-run만 실행했다. 삭제·정리 스케줄은 활성화하지 않았다. 주소 워커의 `INGEST_REMOTE_ENABLED`와 별도 수명주기다.

## 정책과 활동

미저장 uid는 미활동 30일, 후보 또는 비교를 저장한 uid는 90일 보존한다. 정확히 30일/90일인 경계는 보존하고, 그보다 오래된 경우만 대상이다. 현재 DB의 `auth.users.is_anonymous=true`인 사용자만 고려한다. 이메일·전화·외부 identity, email/phone 변경 중, Auth flow가 존재하면 제외한다. 이메일 승격 뒤 uid·소유 데이터는 그대로 유지된다.

최근 활동은 `greatest(created_at,last_sign_in_at,user_activity.last_active_at,소유 후보/비교 updated_at)`이다. `auth.users.updated_at`이나 토큰 자동 갱신을 활동으로 쓰지 않는다. 앱 진입·전경 복귀·전경 1시간 간격에 서버 시각을 touch하며 검색/등록/저장도 기록한다. 숨겨진 탭의 타이머는 touch하지 않는다. 기존 activity가 없는 uid는 마이그레이션 적용 시각부터 유예한다. 이후 활동 불명 uid는 보수적으로 제외한다.

Supabase의 익명 계정 설명과 SQL 정리 예시는 [공식 문서](https://supabase.com/docs/guides/auth/auth-anonymous)를 참고했다. 위 30/90일·실제 활동·승격 중 보호 정책은 사용자 승인 사항이다.

## 실행 위치·주기

`ingest/cleanup_anonymous.py`가 Session pooler의 직접 DB 연결로 실행된다. Vercel에 관리자키/DB URL/추가 환경변수를 넣지 않는다. `.github/workflows/cleanup-anonymous.yml`은 현재 **workflow_dispatch dry-run만** 제공한다. 제안 주기는 일 1회 `0 19 * * *`(04:00 KST)이며 주석으로만 남겼다. 스케줄 추가·실제 삭제는 별도 승인 후다.

```sh
uv run --frozen python -m ingest.cleanup_anonymous --target remote --dry-run
```

실행 환경의 `SUPABASE_DB_URL`은 로컬 .env 기본값을 그대로 쓰지 않고 승인된 원격 프로젝트의 TLS Session pooler URI여야 한다. 스크립트는 project ref/host/user/5432/TLS를 대조하며, dry-run 트랜잭션은 read only다. 출력은 기준시각·대상 수·후보/비교 수·공용 캐시 삭제 0·활동 범위·제외 사유 수·선정 SHA256뿐이다. 이메일·주소·임대료·토큰·uid는 출력하지 않는다.

승인용 uid 목록이 필요하면 `--manifest .local/retention/manifest.json`으로 접근 모드 0600인 파일에만 쓴다. 공개 docs나 Actions artifact에 이 파일을 올리지 않는다. `--apply`는 `AUTH_CLEANUP_ENABLED=true`, 이 manifest, 일치하는 `--approved-sha256`를 모두 요구한다. 이번 PR에서는 원격 apply를 실행하지 않았다.

적용 구현은 최대 500uid, 100uid씩 트랜잭션이다. auth.users를 uid 순으로 잠그고 현재 활동/승격 조건을 다시 검사한다. 다른 트랜잭션이 활동/승격 중인 행은 `SKIP LOCKED`로 보존한다. 저장 RPC와 touch도 사용자 행을 먼저 잠근다. 이미 지운 uid는 재실행 시 건너뛴다. 후보/비교/명명 프리셋/사용량/상태 관찰자는 FK로 정리되고, 공용 주소 캐시와 원천 데이터는 삭제하지 않는다. 큐의 requester uid는 기존 FK 정책대로 NULL이 된다.

## 검증·중단·롤백

[검증 문서](../validation/s3-2-c-save-retention-20261002.md)에 원격 dry-run 수치와 로컬 실제 삭제·승격 보존·GoTrue refresh/stale JWT 거부를 기록했다. 원격 dry-run 결과는 마이그레이션 전에도 기존 스키마에서 조회 가능하다.

문제가 있으면 `AUTH_CLEANUP_ENABLED=false`를 유지하고 workflow_dispatch dry-run만 사용한다. 애플리케이션 롤백은 C 이전 배포로 복귀하고 확장된 DB 열·저장 데이터를 보존한다. C의 새 테이블/열을 DROP하는 자동 역마이그레이션이나 사용자 행 삭제는 하지 않는다. 현재 원격에는 C 마이그레이션을 적용하지 않았다.

## 활동 기록 장애 처리

활동 기록은 AFTER·예외 격리이며 `projection_errors`의 source_table=`app_private.user_activity`, row_id=uid로 실패를 기록한다. 미해결 기록이 있으면 dry-run은 `activity_record_failed`로 제외한다. 다음 정상 활동 기록이 해당 오류를 해결 처리한다. 인증/사용자 존재 확인과 후보 삭제→비교 정리는 strict이고 `updated_at` BEFORE는 유지한다. 오류 로그가 불능이어도 본 쓰기는 통과하며 DB에는 키/주소를 포함하지 않는 경고 코드만 남긴다. 실제 정리·스케줄은 계속 비활성이다.
