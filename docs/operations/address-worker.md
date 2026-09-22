# 주소 대장 워커 배포 절차

승인안: **Database Webhook → repository_dispatch → 기존 Python 워커**, 매시 23분 sweep 보완. 외부 대장·지오코딩 API 호출은 계속 `/ingest`에 있다. Edge Function 수집기는 만들지 않는다. 이 문서는 원격 전환 이후의 절차이며 PR 8에서 webhook을 활성화하지 않았다.

GitHub Actions는 기존 Python·R2·30일 캐시·영속 claim을 재사용하고 Secrets를 한곳에서 관리할 수 있다. 대신 runner 대기 지연·실행 분 비용과 기본 브랜치 반영이 필요하다. Edge Function은 낮은 지연이 장점이지만 외부 API 규칙 예외, Deno 중복 구현·실행 시간 제한이 생긴다. 사용자 결정에 따라 Actions를 유지한다.

## 활성화 순서

1. 워크플로우가 main에 머지되고 [원격 전환](remote-supabase.md)·Secrets·R2 준비가 끝난 상태인지 확인한다.
2. 해당 저장소에만 Contents: write 권한을 가진 fine-grained GitHub 토큰을 발급한다. repo를 private으로 바꿀 경우에도 같은 대상 접근 권한을 확인한다. 토큰 값을 문서·SQL 파일·로그에 적지 않는다.
3. Supabase Vault에 `gilmok_github_dispatch_token` 이름으로 안전하게 저장하고 pg_net을 활성화한다. Vault/pg_net private 데이터 접근을 anon/authenticated에 허용하지 않는다. 인증 헤더는 전송 대기 중 내부 pg_net 요청에 존재하므로 DB 운영자 권한도 제한한다.
4. [enable-address-dispatch.sql](sql/enable-address-dispatch.sql)을 검토 후 원격 DB에서 실행한다. 고정 저장소·event_type만 전송하고 주소/PNU를 payload에 넣지 않는다. pending INSERT 또는 다른 상태에서 pending으로 변경될 때만 깨운다.
5. Repository variable `INGEST_REMOTE_ENABLED=true`를 설정하고 테스트 후보 등록 → pending → Actions → done 및 30일 ready 캐시를 확인한다. 이벤트 기록과 Actions 실행, 실제 큐 처리 결과를 각각 확인한다.

Supabase Dashboard의 기본 Database Webhook payload는 테이블 이벤트 구조다. 이를 GitHub에 그대로 보내면 필수 `event_type`이 없으므로 사용할 수 없다. 제공 SQL은 같은 pg_net 기반 webhook에 GitHub용 JSON을 지정한다. pg_net 요청은 DB 트랜잭션 커밋 후 시작하며 네트워크 장애가 후보 등록을 롤백시키지 않게 한다.

```json
{"event_type":"gilmok_address_pending","client_payload":{"source":"supabase_queue"}}
```

## 검증과 복구

```sh
# main 반영 여부와 무관하게 REST 접수 여부를 확인할 수 있다.
printf '%s' '{"event_type":"gilmok_address_pending","client_payload":{"source":"local_validation"}}' > /tmp/gilmok-dispatch.json
gh api --include --method POST repos/hanbeulYou/Gilmok/dispatches --input /tmp/gilmok-dispatch.json
# main에 워크플로우가 있어야 실제 workflow run이 생성된다.
gh run list --workflow address-queue.yml --limit 5
```

HTTP 204는 이벤트 접수 확인이다. 워크플로우 실행 성공이나 DB 처리 성공을 의미하지 않는다. 로컬 worker 이벤트 파일은 GitHub envelope처럼 `{"action":"gilmok_address_pending"}` 형태로 만들어 `python -m ingest.address_dispatch --target local --event-name repository_dispatch --event-file FILE --max-requests 1`로 검증한다. CLI는 정상 큐를 실제 처리하므로 테스트 대상 확인 후 사용한다.

워커 concurrency로 동시 실행을 제한하며 한 번에 최대 10건 처리한다. 중복 이벤트는 빈 큐에서 종료하고 누락·남은 pending은 hourly sweep이 처리한다. API 호출 도중 죽어 processing/failed가 된 항목은 자동 재시도하지 않는다. 기존 claim과 제공자 응답을 운영자가 확인한 후 복구한다. 무조건 pending으로 돌리면 중복 외부 호출 위험이 있다. 이 정책과 10건 한도 때문에 처리 지연이 생길 수 있으며 S3에서 사용자 안내를 정의한다.

중지: `INGEST_REMOTE_ENABLED=false`로 새 원격 job을 중지하고 필요하면 실행 중 job을 취소한다. SQL 파일의 disable trigger 명령으로 wake를 중지한다. 큐와 30일 캐시는 삭제하지 않는다. 토큰 유출 시 Vault 토큰 폐기·교체 후 수동 dispatch와 sweep을 확인한다.

근거: [GitHub dispatch 이벤트](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#repository_dispatch), [REST 권한](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event), [Database Webhooks](https://supabase.com/docs/guides/database/webhooks), [pg_net](https://supabase.com/docs/guides/database/extensions/pg_net), [Vault](https://supabase.com/docs/guides/database/vault).
