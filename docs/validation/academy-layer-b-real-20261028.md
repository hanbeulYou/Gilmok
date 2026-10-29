# 학원 점 레이어 B: 승격 실데이터 검증

2026-10-28 · #42 · base `main e6c4001` · **Draft 유지**

#41은 2026-10-28 18:27:53 KST에 main 머지됐다. B에 최신 main을 병합했다. G 승격·A 머지 선행 조건은 충족했으며, 이번 검증은 승격된 실제 a/b/c 학원·채점·건물·지도 RPC 응답을 사용한다. [합성 기능/FPS 이력](academy-layer-b-20261018.md)은 회귀 증거로 보존한다.

**마이그레이션 없음. 기존 DB 객체 변경 없음.** 원천·후보·비교·프리셋·쿼터·운영 이력·스키마 쓰기, R2 접근, 주소 API 호출은 하지 않았다. 기존 검증 uid의 Auth 세션 갱신만 허용 범위에서 수행했다. 후보 3개와 비교 재열기 응답은 브라우저 메모리에만 넣고 저장 API는 차단한다. 허용된 원격 RPC 외 요청은 실패시키며 모든 실제 RPC에 HTTP 200을 요구한다(401 허용 없음).

## 입력과 실측 방법

- 분포 `20261016T040000Z`, fingerprint `ca9ca0f95422c2b7fe14353cf6f4a5b38c723e0e42acad11930b6ebab1c746d0`.
- 반경 800m, 입시·검정 및 보습, 임대료 미입력, 채점 v0.4.0. 후보 좌표는 기존 G 기준점과 같다. 과거 Vworld에서 얻은 **기존 후보 기준 좌표**이며 신규 Juso 등록 좌표로 바꾼 시험이 아니다. 학원 레이어는 원격 승격된 Juso 등 공개 원천의 실제 좌표다.
- a `(37.5025721944737,127.05758573871447)` 3층, b `(37.497368428505624,127.05516718391107)` 2층, c `(37.50428792732002,127.06287290714192)` 3층. 순서는 위도/경도.
- 검증 세션 설정은 gitignore 대상 `.local/academy-real/.env`의 `ACADEMY_PROOF_CONFIG_BASE64`(기존 세션·공개 기준점 JSON)에만 둔다. Base64는 직렬화이며 암호화가 아니므로 값은 로그/문서에 남기지 않는다. 파일 권한600, 기존 JSON과 파싱값 동일성 확인.
- 로컬 Next production 빌드에서 실제 OpenFreeMap 타일과 실제 원격 RPC를 연결했다. Playwright의 허용 목록 프록시가 기존 검증 세션으로 요청을 전달한다. 신규 등록/원격 저장 실증으로 표현하지 않는다.
- 기능·모바일·슬라이더 검사는 headless/SwiftShader, FPS는 별도 headed Chrome/실제 Metal GPU다. Preview 실증과 구분한다. 원본 숫자는 [JSON](academy-layer-b-real-20261028.json).

## 렌더·숫자·근거

| 후보 | 총점 | 반경 같은 분야 N | 전 분야 feature 수 | 2D 화면 M | 3D 화면 M |
|---|---:|---:|---:|---:|---:|
| a 역삼로 460 3층 | 83.01075192604473 | 1,069 | 1,402 | 868 | 165 |
| b 도곡로 409 2층 | 92.78765813947193 | 1,156 | 1,530 | 830 | 229 |
| c 역삼로 546 3층 | 82.20961647714019 | 643 | 786 | 415 | 25 |

2D 줌15·3D 줌17, viewport 1440×1000의 한 고정 화면 값이다. M은 viewport·시점에 따라 변하며 반경 전체 N과 같아야 하는 값이 아니다. 실제 `queryRenderedFeatures`의 같은 분야 **고유 ID** 수와 화면 M을 대조했다. 3D 시점의 렌더 건물 feature 수는 a439/b602/c241이다(전체 반경 건물 수가 아님).

- 모든 RPC 학원 feature의 좌표·속성을 MapLibre source와 전수 대조했다. 표시용 `academy_id`만 원본 ID의 문자열로 추가한다.
- 세 후보의 N은 채점 `n_field` 및 cluster 근거의 `반경 N곳`과 일치한다. 데스크톱·모바일 총점도 G 복구값과 소수 넷째 자리까지 일치한다.
- a/b/c 실제 점 클릭으로 공개 기관명·분야·명시층/층 미표기 팝업을 열고 닫았다. 상세주소·전화·대표자는 전달/표시하지 않는다.
- 3D 건물·108개 노출 오버레이와 학원 레이어가 동시에 표시된다. 같은 픽셀의 클릭 우선순위, 보류 배지, 네 상태 안내, 선택 abort·줌 숨김/재사용은 기존 합성 회귀 검증도 유지한다.
- 실제 팝업에서 React 내용 삽입 후 높이 재측정이 늦어 닫기 버튼이 지도 밖으로 밀리는 문제를 발견했다. 공개 `Popup.setLngLat()`로 portal 반영 직후 재배치한다. 팝업이 숫자 패널 뒤에 가려지는 문제도 z-index로 수정하고 팝업 하단 hit-test·실제 닫기 클릭을 검증했다. 응답 좌표/점수 변경 없음.

## 슬라이더·번들

| 100회 세트 | p95 ms | max ms |
|---|---:|---:|
| 1 | 33.9 | 63.5 |
| 2 | 34.0 | 34.0 |
| 3 | 34.0 | 34.0 |

중앙값34.0ms이며 더 엄격한 production 정책(세트별≤100ms)도 통과했다. 점수 변화·원값 복원, 추가 academy RPC 0을 확인했다.

| 같은 환경으로 새 빌드한 gzip | main | B | 판정 |
|---|---:|---:|---|
| `/compare/page` 초기 JS | 200,196B | 196,120B | 증가0(−4,076B) |
| 학원 전용 lazy JS | — | 5,369B | ≤15KiB |
| 학원 전용 CSS | — | 362B | ≤2KiB |

main 대조는 프론트 변경이 없는 #43 worktree(e6c4001 기반)에서 같은 공개 환경변수로 빌드했다. 모바일 첫 화면 실제 다운로드에는 framework 등 추가 공용 파일이 있어 gzip205,190B이며 위 manifest 비교와 측정 범위가 다르다. 그 다운로드 본문에 학원 모듈은 없고 지도/학원 표시 RPC도 0이다. 지도 탭 진입 후 a의 N1069, 노출 오버레이 없음까지 확인했다.

## 실제 GPU FPS: a 통과, b/c 미완료

시작 전 `pmset -g batt`·CoreGraphics 재확인(2026-10-28 19:08:13 KST): M5 Pro, AC100%, 저전력false, 주 화면 LG HDR4K 60Hz(논리1920×1080/DPR2), 비주 내장 화면120Hz. Chrome viewport1440×1000/DPR2, renderer `ANGLE Metal Renderer: Apple M5 Pro`. 2D 줌15 / 3D 줌17·노출 포함, 각63초 중 처음3초 제외, MapLibre render 이벤트 간격으로 측정했다.

| a 모드 | 회차 | 평균 fps | 프레임 p95 ms | max ms |
|---|---:|---:|---:|---:|
| 2D | 1 | 60.00 | 18.3 | 19.3 |
| 2D | 2 | 60.00 | 18.3 | 19.5 |
| 2D | 3 | 60.00 | 18.3 | 19.3 |
| 3D | 1 | 59.95 | 18.3 | 57.1 |
| 3D | 2 | 60.00 | 17.6 | 18.7 |
| 3D | 3 | 59.96 | 18.3 | 50.0 |

a의 6회는 평균≥55fps·p95≤33.4ms 통과. 아래 지도 정리 순서 수정 전 측정이며, 해당 수정은 페이지 이탈 시 정리 시점만 바꾸고 이 정상 표시 측정 경로는 유지한다. 이어진 b에서 111~120fps가 관측되어 확인하니 측정 Chrome 창이 120Hz 내장 화면 좌표로 이동했다. 그 회차는 **무효**이며 성능 통과/실패로 판정하지 않는다. Chrome 실제 창 경계(CDP)를 회차 전후 대조하도록 보강했으나 재시도 중에도 창이 주 화면 `(0,30,1442,1050)`에서 내장 화면 `(1920,409,1512,949)`으로 이동하여 중단했다. OS 설정은 바꾸지 않았다. b/c는 창을 60Hz 화면에 유지할 수 있을 때 재측정한다.

## 남은 검증과 종료 조건

- `pnpm lint`, `pnpm typecheck`, `pnpm test`: 통과(Vitest228/Python319). 실제 렌더·모바일 시험2개, 합성 회귀8개 통과. 동시 빌드로 `.next/types`가 바뀐 타입 검사와 생성된 `* 2.ts` 중복 파일이 있던 검사는 실패로 보존했으며, 빌드 종료 후 생성 중복만 정리하고 타입·단위 검사를 다시 통과했다. 제품 소스/검사 기준을 완화하지 않았다.
- #42 CI 두 실행([첫 실행](https://github.com/hanbeulYou/Gilmok/actions/runs/40670645284), [오류 본문 확보](https://github.com/hanbeulYou/Gilmok/actions/runs/40673508697))은 비교에서 다음 후보 `/new`로 이동할 때 `Cannot read properties of undefined (reading 'getLayer')`로 실패했다. 처음 빈 `/new`만 연 로컬 검사는 통과했으나 레이어를 연 뒤 이동하는 회귀 검사는 같은 오류를 재현했다. 부모의 지도 제거 뒤 자식 레이어가 정리되는 순서가 원인이다. 학원과 3D 건물 레이어의 생성/정리를 layout effect로 옮겨 부모의 passive effect보다 먼저 정리하도록 고쳤다. 2D·3D 이동 회귀를 포함한 합성8개, 실데이터 렌더·모바일2개가 수정 후 통과했다. CI 최종 상태는 #42 checks를 따른다. 401이나 제품 오류 허용은 추가하지 않았다.
- 후속 CI에서 지도 오류는 해소됐으나 모바일 방향키 탭 선택 후 근거 제목으로 포커스를 빼앗는 실패를 확인했다. lazy 근거 패널의 무조건 autofocus가 원인이어서 명시적 점수/근거 열기의 focus request에만 반응하도록 바꿨다. 탭 포커스 유지·명시적 열기 시 제목 이동·닫을 때 원래 버튼 복귀 회귀1개와 수정 후 실데이터 렌더/모바일2개, lint/typecheck/Vitest228/Python319 통과. E2E의 기존 포커스 요구는 완화하지 않았다.
- 빠른 3D 이탈 회귀에서 두 CI가 deck.gl `null viewport.id`를 포착했다. 설치된 deck.gl의 `getViewport`/`view.makeViewport`와 페이지 이탈 경로를 확인하고 MapboxOverlay control도 부모의 지도/DOM 제거 전에 해제하도록 layout effect로 맞췄다. 수정 후 3D 이탈5회, 합성 전체9개(FPS1개는 별도), lint/typecheck/Vitest228/Python319와 production 빌드가 통과했다. 정상 표시 데이터·계산·레이어 구성은 변경하지 않았다.
- Preview `gilmok-oimf9lqc8-vineyard.vercel.app`는 Vercel SSO로 리디렉션된다. 프로젝트 읽기 결과 `all_except_custom_domains`, 기존 protection bypass 없음. 보호 설정 변경 없이 중단했다. **Preview 실제 렌더 및 HTTP→첫 점 콜드/웜 판정은 미완료**이며 로컬 production/RPC 결과로 대체해 통과 처리하지 않는다.
- b/c 유효 60Hz FPS와 Preview 실증은 미완료다. CI 결과는 PR에 별도 기록한다. #42는 Draft를 유지한다. 다음 단계는 완료된 G/A 위에서 B의 남은 실증을 마치고 사용자 머지 후 공개 전 체크리스트로 이동하는 것이다.


## 2026-10-29 후속: FPS 보류·나머지 검증 상태

사용자 지시로 FPS 측정을 보류한다. b/c의 유효 60Hz 결과는 미완료로 유지하며 재측정하지 않았다. 측정 장치·OS 설정도 변경하지 않았다.

- 코드 head `6aa49e43e4341c5dce19054c17950fe07e9d5b15`의 [CI 전체 성공](https://github.com/hanbeulYou/Gilmok/actions/runs/40679698015)을 다시 확인했다. 기존 실데이터 a/b/c 렌더·숫자·모바일·팝업·근거·오버레이 동시 표시·번들 결과는 해당 코드에 유효하므로 불필요하게 반복하지 않았다.
- 최신 Preview는 `https://gilmok-qgjs6udsx-vineyard.vercel.app/compare`, deployment `dpl_WEzchNQArjsjWJAdBsNSnse83Twv`, 상태 `READY`다. 2026-10-29 14:55:58 KST에 인증 정보 없는 GET을 재확인한 결과 **HTTP 302 → vercel.com/sso-api**였다. 이전 배포 URL만 검사한 결과가 아니다.
- 따라서 남은 비FPS 항목인 **Preview 실제 렌더·HTTP 요청 시작→첫 학원 점 표시 시간(콜드≤3초, 웜 p95≤1초)**은 접근 대기다. 배포 성공, RPC 응답 시간, 로컬 렌더 성공을 이 항목의 통과 증거로 대체하지 않는다.
- 보호 설정을 바꾸지 않고 검증할 수 있도록 기존 자동화 보호 우회 키를 로컬 `.env`의 `VERCEL_AUTOMATION_BYPASS_SECRET`에 등록해 달라고 요청했다. [Vercel 공식 방식](https://vercel.com/docs/deployment-protection/methods-to-bypass-deployment-protection/protection-bypass-automation)에 따라 검증 대상 Preview origin에만 `x-vercel-protection-bypass` 헤더로 전달하고 URL·로그·문서에는 남기지 않는다. 현재 키 발급·설정 변경·보호 우회 요청은 실행하지 않았다.

이번 후속 확인에는 Auth 갱신·RPC 호출·DB/R2 쓰기가 없다. #42는 **Draft 유지**. FPS 보류와 Preview 접근 대기는 별개 미완료 항목이다.
