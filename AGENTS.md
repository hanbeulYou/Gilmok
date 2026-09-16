# AGENTS.md — 길목(GILMOK)

이 파일은 이 리포지토리에서 작업하는 모든 AI 에이전트가 세션 시작 시 가장 먼저 읽는다.

## 1. 기준 문서 (Single Source of Truth)

1. `docs/planning/location-simulator.md` — 기획서. 무엇을 왜 만드는지. **코드와 이 문서가 충돌하면 문서가 맞다.** 문서를 바꿔야 한다고 판단되면 코드를 고치지 말고 사용자에게 먼저 말한다.
2. `docs/planning/data-sources.md` — 데이터 소스 명세. 엔드포인트·컬럼·좌표계·적재 방식.
3. `docs/planning/scoring-spec.md` — 채점 명세 (S2 전에 작성됨). 없으면 채점 로직을 구현하지 않는다.
4. `docs/planning/screens.md` — 화면 정의 (S3 전에 작성됨). 없으면 UI를 임의로 설계하지 않는다.

## 2. 프로젝트 한 줄 정의

서비스업 창업자가 후보 점포 여러 곳을 3D 지도 위에서 같은 채점표로 비교하고, 가중치를 바꿔가며 "목"을 검증하는 입지 시뮬레이터. 첫 버전: 서울, 학원업, 후보지 최대 5곳.

## 3. 스택 (버전 고정)

- Next.js 15 (App Router), TypeScript strict, pnpm
- Supabase: Postgres 16 + PostGIS 3.4, Auth, Edge Functions (Deno)
- 지도: MapLibre GL JS 4.x, deck.gl 9.x (MapboxOverlay 모드)
- 상태: Zustand
- 스타일: Tailwind CSS 4
- 테스트: Vitest (단위), Playwright (E2E, S3부터)
- 배치 적재: Python 3.12 + PublicDataReader + psycopg / 또는 TS 스크립트. 하나로 통일하되 S1에서 결정 후 여기에 기록.
- 배포: Vercel (프론트), Supabase (DB/Functions), GitHub Actions (배치 스케줄)

버전을 올리려면 이 파일을 먼저 수정하고 이유를 커밋 메시지에 적는다.

## 4. 폴더 구조

```
/app                 Next.js 라우트
/components          UI 컴포넌트 (map/, compare/, candidate/, report/)
/lib                 클라이언트 유틸 (scoring/, visibility/, geo/)
/workers             Web Worker (가시성 레이캐스트)
/supabase
  /migrations        SQL 마이그레이션 (수기 편집 금지, supabase CLI로 생성)
  /functions         Edge Functions
/ingest              배치 적재 스크립트 (소스별 1파일)
/docs/planning       기획 문서
/tests
```

## 5. 지켜야 할 규칙

### 데이터

- 외부 API는 `/ingest` 안에서만 호출한다. 프론트·Edge Function은 Supabase만 본다.
- 좌표는 DB에 EPSG:4326으로 저장. 거리 계산은 `geography` 또는 5186 변환 후.
- 추정값에는 반드시 `estimated` 플래그. 추정 로직은 `data-sources.md`에 적힌 것만 쓴다. 새 추정이 필요하면 문서에 먼저 추가.
- 인증키·비밀은 `.env`에만. `.env.example`을 항상 최신으로 유지.
- 사용자가 입력한 임대료 등 개인 데이터는 다른 사용자 집계에 절대 쓰지 않는다. RLS로 강제.

### 코드

- 마이그레이션은 `supabase migration new`로 만든다. 기존 마이그레이션 파일은 수정하지 않는다.
- 채점 로직은 순수 함수로 `/lib/scoring`에 두고, 서버(Edge Function)와 클라이언트(가중치 재계산)가 같은 코드를 쓴다.
- 3D 지도 코드에서 외부 타일·스타일 URL은 환경변수로. 스타일은 MapLibre 호환 오픈 스타일만 쓴다.
- 새 라이브러리 추가는 이유를 PR 설명에 적는다. 3D/지도 관련 라이브러리는 MapLibre·deck.gl 외에 추가하지 않는다 (CesiumJS·Three.js 직접 사용 금지, 필요하면 사용자에게 먼저 제안).

### 작업 방식

- 스프린트 작업을 받으면 **코드보다 계획을 먼저** 낸다: 건드릴 파일, 마이그레이션, 테스트, 예상 리스크. 사용자 승인 후 구현.
- 한 PR은 하나의 스프린트 태스크. 기획서의 "완료 기준"을 PR 설명에 복사하고 각 항목 충족 여부를 체크한다.
- 완료 조건: `pnpm lint`, `pnpm typecheck`, `pnpm test` 통과. S1은 `score_inputs` RPC가 대치동 좌표 3건에서 1초 내 응답하는 테스트 포함.
- 기획서에 없는 기능을 "있으면 좋겠다"고 추가하지 않는다. 제안은 PR 설명의 "제안" 절에 적고 구현하지 않는다.
- 모르는 것(API 응답 스키마, 좌표계, 쿼터)은 추측하지 않는다. `data-sources.md`의 "확인 필요" 항목은 실제 응답을 받아 확인한 뒤 문서를 갱신하는 것까지가 작업이다.

## 6. 커밋·브랜치

- 브랜치: `s1/데이터-스키마`처럼 `s{스프린트}/짧은-설명`
- 커밋 메시지: 한국어 또는 영어, 첫 줄 50자 이내, 본문에 "왜"
- 기획 문서 수정은 코드와 별도 커밋

## 7. 현재 스프린트

- **S1 데이터 기반** (진행 전)
- 완료 기준: `docs/planning/location-simulator.md` 스프린트 계획 표 참조
- 이 절은 스프린트가 끝날 때마다 갱신한다.
