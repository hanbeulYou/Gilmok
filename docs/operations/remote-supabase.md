# 원격 Supabase 전환 절차

2026-09-26 S3-1: 사용자가 Pro 전환을 완료했다. link·읽기 전용 사전 점검·기존 28개 dry-run은 성공했고, 원격 DB 쓰기는 아직 하지 않았다. [사전 점검](../validation/s3-1-preflight-20260926.md)과 [S3-1 실행 절차](s3-foundation.md)가 현재 기준이다.

## 실행 순서

1. link → 로컬/원격 migration 이력 대조 → 신규 S3 파일을 포함한 최종 `supabase db push --linked --dry-run`.
2. 최종 적용 목록과 [R2 복원 manifest](../validation/s3-1-restore-manifest.json)를 사용자에게 보고하고 원격 쓰기 승인을 받는다.
3. 승인된 코드·manifest로 migration push → R2 원본 복원 → 원본 전수 대조 → 6조합 RPC 검증. 원본 API 재수집은 하지 않는다.
4. 익명 Auth 설정 → main 워크플로우/Secrets 대조 → Vault·웹훅 활성화 → 실제 pending 1건 처리 검증. Repository Variable은 검증 창 종료 시 false로 복귀한다.
5. 프론트 main 머지 후 사용자가 Vercel 연결·도메인·Auth URL을 설정한다. 배포된 /compare 응답과 원격 이메일 승격을 확인한다.

복원 순서는 경계→인구→교통→상가·학원·학교→건물→실거래·임대→기준 분포다. 이번 사용자 지시는 **R2 원본 복원**이며, PR 8에서 작성한 로컬 pg_dump 중심 절차를 대체한다. 주소 좌표와 원천 이력 등 필요한 공개 데이터 보완도 R2에 고정하여 재읽기 검증한다. auth·사용자 후보/비교·개인 임대료·private 주소 큐/캐시는 이관하지 않는다.

Session pooler 5432/TLS를 사용하고 프로젝트 ref와 연결 대상을 대조한다. .env의 로컬 DB URL을 바꾸거나 transaction pooler 6543을 배치에 쓰지 않는다. 비밀은 프로세스 환경 또는 표준입력으로만 전달하며 값은 로그에 남기지 않는다.

## 검증·복구

원격 적재 전후 DB·테이블·인덱스 bytes와 원본·작업/임시 디스크, 단계별 경과 시간을 실측한다. 3좌표×500/1,000m의 각 조합 30회 DB p95 <1,000ms가 기준이며 HTTP 왕복은 별도로 기록한다. 로컬 통과를 원격 성능으로 간주하지 않는다.

복원은 전체 트랜잭션으로 검증 후 커밋한다. 실패하면 부분 데이터를 남기지 않는다. 커밋 후 별도 연결의 VACUUM ANALYZE를 수행하며 VACUUM FULL은 하지 않는다. 원격 사용을 열기 전에 검증을 끝내고, 실패하면 프론트 전환·워커를 보류한다. 기존 로컬 DB와 R2 원본은 유지한다. 용량을 이유로 범위·해상도를 줄이거나 플랜을 자동 변경하지 않는다.

실제 실행 명령, 승인된 manifest SHA256 사용법, 익명 인증·Vault·웹훅 검증과 사용자 설정값은 [S3-1 운영 문서](s3-foundation.md)를 따른다. 원격 적재 소요 시간은 승인 후 실측한다.
