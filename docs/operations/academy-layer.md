# 학원 점 레이어 A 운영 인계

2026-10-16 · 합성 검증 단계 · 원격 실행 없음

현재 PR은 신규 RPC와 계약만 제공한다. UI 연결은 B, 실제 좌표·명시층·기준분포 교체는 G다. Juso 해외 저장 회신과 G 원격 승격 전까지 Draft를 유지한다. 이번 작업은 원격 DB/R2 조회·쓰기·키 접근을 하지 않았다.

## 적용 범위와 호환성

`20261016084609_academy_layer_rpc.sql`: **신규 private 테이블 2개 + RPC 1개와 해당 권한만 추가. 기존 객체/행 변경·DROP·트리거 없음.** 기존 채점/저장/지도 RPC는 그대로 동작한다. 클라이언트에서 신규 RPC를 호출하는 UI도 아직 연결하지 않았다.

`academy_coordinate_reviews`는 `(entity_kind,entity_id,review_version)`별 보류 이유와 원천 revision/SHA를 저장한다. `academy_layer_release`는 표시 허용 원천 descriptor·revision/SHA·검토 버전·학원/학교 검토 행수를 묶는 singleton이다. 두 테이블 모두 RLS 활성, PUBLIC/anon/authenticated 직접 접근 금지다. RPC는 `auth.uid()` 필수, authenticated EXECUTE만 허용하며 SECURITY DEFINER와 빈 search_path를 사용한다.

G의 표시 테이블이 아직 없는 main에도 A migration을 적용할 수 있다. RPC는 테이블 존재를 먼저 확인해 `coordinate_replacement_pending`을 반환한다. 자동 backfill이나 실제 좌표 노출은 없다. G 표시 스키마의 복제본은 **합성 테스트 fixture**에만 있으며 A migration으로 생성하지 않는다.

## G 승격에 필요한 연결 — 실행 보류

다음은 후속 G 인계 조건이며 이번 PR에서 원격 실행하거나 기존 G 승격 스크립트를 수정하지 않았다.

1. G manifest에 학원 원천 revision/SHA, 실제 학원·학교 보류 ID 목록과 각각의 원천 revision/SHA, 검토 버전을 담는다. 초기 101행은 학원 99 + 학교 2이며 영구 고정 카운터로 가정하지 않는다.
2. G의 원천·층 파생·기준분포 atomic promotion 트랜잭션에 `academy_coordinate_reviews`와 `academy_layer_release` 게시를 함께 넣는다. 실패 시 모두 이전 버전을 유지한다. A metadata는 정합성 자료이며 실패를 무시하는 부수 기록이 아니다. 트리거를 새로 만들지 않았다.
3. `academy_source`는 같은 트랜잭션의 `score_internal.sources()->'academies'`로 기록한다. `source_revision/raw_sha256`는 G의 학원 표시 release와 같아야 한다. 학교만 보완한 score_reference revision으로 학원 원천 revision을 덮어쓰지 않는다.
4. G gate, 원천 provider=juso, 표시 층 revision/SHA, 보류 버전/행수를 확인한다. 학교 보류 목록은 검토 inventory로만 보관하며 academy feature로 조인하지 않는다. 학교 전용 다른 보류 사유는 G 학교 정책에 남긴다.
5. 원격 읽기 허용 후 A migration 원격 dry-run을 보고하고 push 승인 절차를 따른다. G 승인·승격 후 실제 a/b/c와 최대밀도 셀의 800/1000m SQL 30회·HTTP·크기·채점 N 대조를 별도로 수행한다. 통과 전 A/B Ready 전환 금지.

## 롤백

- 새 레이어만 닫을 때는 승인 후 `REVOKE EXECUTE ON FUNCTION public.academy_layer(double precision,double precision,integer,text,jsonb) FROM authenticated;`를 적용하고 UI 연결을 끈다. 기존 채점 RPC에는 영향이 없다. 복구는 검산 후 동일 시그니처에 GRANT EXECUTE한다.
- G 데이터 롤백 시 기존 원천·표시·기준분포와 함께 **A의 release/review 두 테이블도 rollback manifest에서 같은 트랜잭션으로 복구**한다. 과거 검토 manifest를 삭제하지 않는다. 원천 mismatch로 닫힌 상태를 정상 0건으로 취급하지 않는다.
- 원격에서 테이블/데이터 DROP이나 캐시·키 삭제를 실행하지 않는다. 현재 migration은 비활성 빈 metadata만 만드는 단계이므로 원격 데이터 롤백 자체가 발생하지 않았다.

## 재현과 예산

합성 전용 별도 Supabase project/ports를 준비하고 전체 migration을 로컬 적용한다. 기본 개발 DB를 재사용하지 않는다. 벤치마크는 loopback DB/API 외 주소를 거부하며 실제 학원 원천이 이미 있으면 seed를 거부한다. 출력 디렉터리는 새 경로를 지정한다.

```sh
supabase db push --local --workdir .local/academy-layer-supabase --dry-run
.venv/bin/python -m ingest.verify_academy_layer \
  --database-url postgresql://postgres:postgres@127.0.0.1:55422/postgres \
  --workdir .local/academy-layer-supabase \
  --output .local/academy-layer-validation-new
```

800m/1000m 공통: SQL 웜 p95 ≤300ms 목표(>1,000ms면 중단·원인 보고), raw ≤1.5MiB, gzip ≤256KiB. 5,000기관 초과 또는 SQL JSONB 직렬화 1.5MiB 초과는 `too_dense`와 전체 건수/byte 진단만 반환한다. 부분 점 목록을 정상 응답으로 내보내지 않는다. gzip은 실제 전송 압축 보장이 아니며 A의 로컬 증거는 오프라인 압축 크기다. 실제 밀도가 예산을 넘으면 속성 경량화/MVT 대안을 먼저 보고하고 기준을 임의 완화하지 않는다.

## 2026-10-18 승인 범위 확대·G 연결 상태

로컬 실자료 읽기와 원격 migration dry-run이 승인되었다. A 브랜치 dry-run exit 0/대기 1개, push 없음. [결과](../validation/academy-layer-a-density-20261018.md). G에는 같은 migration 파일/hash를 공유하고 strict release callback·12테이블 rollback 코드를 로컬 커밋으로 추가했다. G 기존 명시층 migration까지 합친 최종 dry-run/원격 적용은 Juso 회신 후 승인 대상이다. 월간 승격 시 새 검토 manifest를 함께 제공하지 않으면 기존 gate의 source mismatch로 표시가 닫히며, 보류 해제를 자동 추정하지 않는다.
