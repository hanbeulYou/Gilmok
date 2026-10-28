# 학원 레이어 A — authenticated HTTP 실자료 검증 (2026-10-28)

**실자료 8조합 SQL·HTTP·응답 크기·채점 N·TypeScript 계약 검증 통과.** SQL 측정은 [10/27 보고서](academy-layer-a-remote-20261027.md)를 재사용한다. 원천·후보·비교·프리셋·쿼터·운영 이력·스키마는 변경하지 않았다.

## 승인 범위와 재현 조건

사용자 승인에 따라 보관된 검증용 익명 uid의 세션을 1회 refresh했다(HTTP 200, uid 동일·is_anonymous=true). 신규 signup·후보/비교 저장·touch_user_activity 호출은 하지 않았다. Auth 내부 갱신만 발생했다. 이 예외 정의는 AGENTS.md에 한 줄로 기록했다. 토큰·uid는 보고서에 공개하지 않는다.

HTTP 전후 직접 SQL 연결에서 `SET TRANSACTION READ ONLY`·`SHOW transaction_read_only=on`을 확인하고 8조합의 source·채점 N·전체 academy_layer 응답이 10/27과 동일함을 대조했다. 분포는 `20261016T040000Z`, fingerprint는 `ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`로 유지됐다.

같은 익명 authenticated 세션으로 `academy_layer`를 각 30회, 총 240회 순차 호출했다. 첫 1회와 웜 29회를 구분하고 p95는 nearest-rank이다. HTTP 시간은 본문 수신 완료까지이며 기록용이다. 기존 SQL 웜 p95 28.999~129.165ms는 300ms 기준을 통과한다. 강제 콜드 캐시 측정은 아니다.

`Accept-Encoding: gzip`을 요청하고 자동 압축 해제 전 wire bytes를 측정했다. 모든 응답의 Content-Encoding은 gzip이다. 압축 전 raw는 실제 HTTP JSON이며, SQL 재직렬화 크기와 공백 등이 달라 구분한다. 실제 gzip 전송 크기는 압축 수준 등에 따라 달라 범위로 기록한다. 별도 오프라인 gzip도 JSON에 보존한다.

## 측정값

| 후보/최대셀 | 반경 m | 채점 N | 첫 HTTP ms | 웜 p95 ms | 전체 max ms | HTTP raw B | 실제 gzip 전송 B |
|---|---:|---:|---:|---:|---:|---:|---:|
| a | 800 | 1069 | 407.854 | 279.274 | 407.854 | 527,276 | 56,985~57,068 |
| a | 1000 | 1178 | 210.321 | 275.161 | 279.720 | 598,041 | 64,594~64,652 |
| b | 800 | 1156 | 201.579 | 274.867 | 313.623 | 574,436 | 61,047~61,115 |
| b | 1000 | 1261 | 212.154 | 228.561 | 280.187 | 635,425 | 68,010~68,077 |
| c | 800 | 643 | 132.275 | 141.477 | 307.275 | 296,613 | 31,774~31,844 |
| c | 1000 | 885 | 139.613 | 178.990 | 184.219 | 420,038 | 44,726~44,760 |
| max-800 | 800 | 1225 | 199.126 | 211.451 | 211.991 | 592,479 | 62,875~62,929 |
| max-1000 | 1000 | 1290 | 210.807 | 224.497 | 231.121 | 655,765 | 70,560~70,631 |

전체 240응답 HTTP 200·status ready. 8조합의 HTTP JSON은 직접 SQL JSON과 구조적 diff 0이며 고유 ID·같은 분야 수는 `score_inputs.compete.academies_by_field`와 일치한다. 제품의 `parseAcademyLayer`로 실제 HTTP 응답을 읽어 8/8 통과했다. 숨겨야 하는 상세주소·전화·대표자 필드가 없는 것도 이 parser의 필드 허용 목록 검사에 포함된다.

최대 raw 655,765B는 1.5MiB의 41.69%, 실제 gzip 최대 70,631B는 256KiB의 26.94%다. 초과·부분 반환·자동 LIMIT는 없었다. 101건 보류 플래그 계약은 기존 합성 검증을 유지하며 이 8반경 내 실제 보류 점은 0이다.

## CI와 후속 경계

10/27 head `4a772f3`의 CI는 `test_changed_sources_never_replace_reference`에서 `public.academies` NOWAIT 잠금 실패 1건(290 passed)로 실패했다. HTTP·점수 오류와 구분한다. 최종 문서 커밋에서 CI를 재확인하며 통과 전에는 Ready로 전환하지 않는다. 이번 작업은 제품 코드·SQL을 변경하지 않는다.

완료 기준: SQL 30회×8·HTTP 30회×8·bytes·채점 N·실제 TS 계약 통과. #41 Ready 이후 한별이 머지하며, 후속 B는 G 승격 후 실데이터 a/b/c 재측정 단계로 이어간다.

[기계 판독 결과](academy-layer-a-http-20261028.json). 시작/종료 UTC와 모든 HTTP 시간·바이트를 포함한다.
