# 초기 activity401 진단 — 2026-10-27

**세션 대기 누락은 확인되지 않았다.** `ActivityTracker.tsx`와 `CandidateForm.tsx` 두 호출 지점 모두 이미 `await ensureSession()` 다음에 touch RPC를 호출한다. 이번에는 이를 중복 수정하는 코드 PR을 만들지 않았다. E2E에서401 허용 금지도 유지한다.

## 실제 클라이언트 재현

현재 main의 두 React 컴포넌트와 session/client 모듈, 설치된 Supabase SDK를 묶어 실제 로컬 Supabase Auth/RPC에 연결했다. Next 라우터만 이동 없는 스텁으로 대체했고, 가입/활동 응답은 mock하지 않았다. 원격 키·Auth·DB는 사용하지 않았다.

신규 브라우저 컨텍스트12개: 정상6개 + 로컬 signup 응답을1500ms 지연한6개. 총24회 touch 모두 가입 응답 이후에 전송됐으며 JWT role=authenticated·sub 있음, HTTP204였다. 가입1회를 여러 호출자가 공유하는 로직도 유지됐다. 원격Production의 401은 재현되지 않았다. Next production 번들 전체를 재현한 시험은 아니므로 빌드/호스팅 경합까지 배제했다고 주장하지 않는다.

## 원격 로그 읽기

[Supabase 공식 Logs API](https://supabase.com/docs/guides/observability/advanced-log-filtering)의 GET 질의로 2026-10-26 14:53:45~14:54:10 UTC만 조회했다. 토큰/원문 인증 헤더는 요청·출력하지 않았다.

- 14:53:53.200 touch POST401의 JWT payload role은 **authenticated**, issued_at1793026433·expires_at1793030033으로 당시 만료 전이다.
- 14:53:53.201 다음 touch는204이고 동일한 발급/만료 시각·role을 관측했다.
- 따라서 '세션 이전에 무토큰으로 호출'이라는 가설은 관측과 맞지 않는다. gateway가 payload를 기록했다는 사실만으로 서명/서버 검증까지 정상이라고 단정하지 않는다.
- 해당3초 구간 postgrest_logs는0건, API 오류 코드 필드도 빈 값이었다. 요청 응답 본문을 당시 수집하지 않아401의 정확한 서버 거부 사유는 **미확정**이다.

후속이 필요하면 별도 승인된 실증 창에서 **401 응답의 bounded code/message·요청 ID·JWT role/만료 여부만** 수집하고 토큰·키는 제외한다. 현재 증거 없이 retry/401 무시/세션 재발급을 추가하지 않는다. [재현·로그 결과](activity-session-diagnosis-20261027.json). 원격 쓰기0, 제품 코드 변경0, 수정 PR 없음.
