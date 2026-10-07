# 저장 비교의 채점 모델 버전

S3-3 PR 1(M). [확정 계획](../planning/s3-3-plan.md) §9를 따른다. 구현·로컬 검증 후 원격 migration 승인 전에는 Draft로 둔다.

## 두 버전의 의미

- `preset_version=0.3`: 기존 후보 입력·8축 가중치 저장 계약. #29 이후에도 유지하며 모델 변경 여부를 판정하는 값으로 사용하지 않는다.
- `scoring_model_version`: 마지막 명시적 저장 시 클라이언트가 사용했다고 기록한 채점 모델. 현재는0.4.0이며 서버가 점수를 다시 계산해 인증한 값은 아니다. 신규 nullable 열이고 과거 기록은 NULL(미기록)이다. 모델을 시각이나 기존0.3 필드로 추정하여 백필하지 않는다.
- 불완전한 채점·오류·조회 진행 중·구클라이언트 저장은 NULL이다. 데이터의 건물 pending은 현재 모델로 `scored_provisional` 결과를 만든 경우 모델 버전을 기록할 수 있다. 데이터 잠정 상태와 모델 버전 기록은 다르다.

재열기는 원래 후보/가중치/순서를 현재 모델로 재계산한다. 버전 불일치·미기록이면 계산 중/완료/실패 배지를 표시하고 같은 버전은 모델 전환 배지를 표시하지 않는다. 결과 저장은 사용자의 “비교 저장”으로만 수행한다. 재계산 실패 시 구버전 점수 캐시를 현재 점수로 표시하지 않으며, 기존 전체 실패 시 현재 모델의 저장 스냅샷만 읽기 전용으로 복구하는 규칙은 유지한다. 배지의 재시도는 부분 실패 후보만 재조회해 가중치를 보존하고, 전체 실패 읽기 전용 복구 상태이면 저장 비교를 다시 연다.

## 확장·배포 순서

1. migration `20261007085130_comparison_scoring_model.sql`의 해시·dry-run·원격 기존 비교 수를 보고한다.
2. **기존 객체 변경 있음:** `comparisons`에 nullable 열/CHECK 추가, 기존 `save_comparison` 함수 교체(NULL 초기화만 추가), 새 `save_comparison_v2` 함수/권한 추가. 기존 행 백필·삭제·기존 열/테이블 DROP·새 트리거 없음.
3. 승인 후 migration push → 원격 구·신 저장/재열기·uid 격리 확인 → 프론트 배포 순서. 원격 migration 전에 새 프론트는 v2 RPC가 없어 저장에 실패하므로 이 Draft를 먼저 머지하지 않는다.
4. `save_comparison_v2`는 기존 저장 함수를 호출하고 같은 트랜잭션에서 모델 태그를 기록한다. 기존 함수 시그니처·EXECUTE 권한·security definer·빈 search_path를 유지한다. 새 RPC는 authenticated만 실행한다.
5. 구클라이언트는 기존 RPC를 그대로 사용할 수 있고 저장 시 모델 태그가 NULL로 초기화된다. 이렇게 해야 이전 클라이언트가 남의 시점의 모델 태그를 유지하지 않는다. 서버 RLS의 uid 소유권은 두 경로 모두 동일하다.

모델 태그 쓰기는 저장 정합성이므로 예외를 삼키지 않는다. 태그 쓰기에 실패하면 후보·비교·가중치 변경도 롤백한다. 기존 활동/투영 AFTER 트리거의 부수 기록 예외 격리, 후보 삭제→비교 정리 strict 규칙, updated_at 갱신은 그대로다.

## 롤백

이전 프론트로 복귀하면 구RPC를 사용하므로 확장 열·제약·기록은 보존한다. 구RPC의 NULL 초기화 보완도 유지한다. 함수나 열을 DROP하거나 기존 기록을 일괄 수정할 필요가 없다. 필요하면 새 프론트 트래픽 종료 후 새 RPC만 비활성화한다(원격 SQL 실행은 별도 승인).

```sql
begin;
revoke execute on function public.save_comparison_v2(uuid,jsonb,jsonb,uuid[],text,boolean,text)
  from authenticated;
notify pgrst, 'reload schema';
commit;
```

재개는 같은 함수 시그니처에 authenticated EXECUTE를 GRANT하고 새 프론트를 다시 배포한다. 서비스/비밀키 또는 사용자 uid를 운영 문서에 기록하지 않는다.
