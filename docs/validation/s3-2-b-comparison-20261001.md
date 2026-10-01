# S3-2 B — 비교 매트릭스·실시간 상태 검증

- base: `main` (`337c7ea`, #22 머지 확인), 브랜치 `s3/comparison-matrix`.
- 구현: `6d686d3`, 실패 표시 보완 `e0c1419`, 검증 경로 분리 `5cea9db`. 명세/프리셋 v0.3 변경 없음. 계획 §3 B·§5·§6 범위.
- **마이그레이션 없음. 기존 DB 객체 변경 없음.** A의 owner RLS·상태 투영·publication을 재사용한다. 로컬 `supabase/config.toml`의 Realtime만 켰다.
- 저장·프리셋 저장·익명 정리는 C, 지도는 S3-3. 현재 화면은 새로고침 시 초기화 안내를 표시한다.

## 검증 방법

`tests/compare/build-browser.mjs`는 실제 ComparisonMatrix/store/subscriptions와 실제 exposure Worker를 production React로 번들한다. 테스트 진입점은 Next.js 라우트가 아니며 배포 앱에 포함되지 않는다. Next Link만 독립 검증 페이지용 링크로 연결하고 Worker 파일 경로만 번들 산출물로 바꾼다. DB·RPC·Auth·Realtime·Worker·채점은 mock을 사용하지 않는다. 등록 화면과 Next.js 배포 경로는 별도 시험한다.

```sh
pnpm exec node tests/compare/build-browser.mjs
python3 -m http.server 4173 --bind 127.0.0.1 --directory .local/compare-browser/dist
# 다른 터미널
uv run --frozen --with playwright python tests/compare/verify_browser.py
```

로컬 CLI 2.72.7/Kong에서 sb_publishable 키의 WebSocket 연결은 `MalformedJWT`였다. 검증 번들에는 CLI의 JWT 형식 공개 anon API key를 사용하되, 두 브라우저 컨텍스트는 각각 실제 익명 로그인한 **authenticated uid**다. service_role로 구독하지 않는다. 원격은 제품과 같은 publishable API key와 authenticated 세션으로 별도 확인한다.

검증은 새 uid 2개·무작위 합성 주소만 만들고 cache ready fixture는 DB 소유자 연결로 커밋한다. 기존 주소/캐시를 덮어쓰지 않고 생성한 watcher/cache/queue/uid만 finally에서 지운다. 실제 외부 대장 수집과 Actions 실증을 대신하는 시험은 아니다. DB→상태 투영→WebSocket→800m 재조회→점수/신뢰도 갱신 경로를 검증한다.

## 로컬 1차 실측

- macOS, Headless Chrome 154, 독립 브라우저 컨텍스트 2개. 데스크톱 1440×1050, 모바일 390×844, reduced-motion.
- 실제 projection UPDATE·동일 주소의 다른 uid request_id·owner 상태 뷰·pending→ready·재접속 동안 발생한 ready·구독 전 ready·실제 역순 timestamp UPDATE 통과.
- 180초 실제 대기 후 지연 안내, 구독 유지 후 ready 갱신 통과.
- ready 갱신은 uid별 `score_inputs(800m)` 1회. Worker·1000m·분포 재호출 0. `building_address`의 조회 시각 변화는 학교/기준 분포/도형 원천 갱신과 구분한다. 해당 공통 원천이 바뀌면 묶음을 다시 받는다.
- 5개 후보(a,b,c,a,b), 100회 연속 슬라이더 입력→두 rAF까지 p50 **33.3ms**, p95 **33.5ms**, max **121.6ms**. p95≤100ms 통과. max는 별도 기록하며 통과 기준으로 바꾸지 않는다. JS heap 48,904,923 byte. RPC·Worker 재호출 0, 드래그 중 순서 유지.
- 데스크톱·모바일 총점/8축/근거 동일. 3곳은 승인된 A0 좌표의 v0.3 결과와 일치한다.

| 축 | a 역삼로 460 3층 | b 도곡로 409 2층 | c 역삼로 546 3층 |
|---|---:|---:|---:|
| 총점 | 85.08500496915157 | 93.3997327394482 | 83.86448162784299 |
| 신뢰도 | 90 | 90 | 85 |
| 수요 | 96.56364174977782 | 99.76300977584674 | 84.41789276192357 |
| 유동 | 99.33406222045522 | 98.87685120763344 | 97.18715833416161 |
| 교통 | 38.336803260049486 | 81.70108973489597 | 60.78723216127797 |
| 학원 집적 | 97.47740578011093 | 98.41003619754652 | 85.91014431805627 |
| 노출 | 38.38383838383838 | 51.399491094147585 | 63.28124999999998 |
| 건물 | 100 | 100 | 100 |
| 환경 | 93.40459174952771 | 87.65344088005983 | 91.98293991698833 |
| 임대료 효율 | NULL | NULL | NULL |

순위 b > a > c. 임대료 미입력, 반경800m, 학교1000m, exposure0.2.2. 비교 기준은 [A0 재산출](s3-2-a0-juso-20260930.md)과 [A 검증](s3-2-a-registration-20260930.md)의 승인 좌표다. 구 S2-4 좌표를 되돌리지 않는다.

## 검증 진행 상황

- lint/typecheck 통과, Vitest115·Python259 통과, Next production build 통과.
- 단위 검증: Worker 실패 재시도·실패한 RPC만 재시도·원천 snapshot 변경 시 무효화·abort 늦은 응답·삭제/층 변경 세대·microsecond 역순/중복 무시·수동 순서·전 가중치0.
- 최종 로컬 실제 WebSocket frame의 record 키는 request_id/status/updated_at만 있었다. 같은 주소의 uid별 다른 request_id와 다른 주소 이벤트의 소유자 격리를 확인했다.
- Next Vercel Preview 실제 등록 5회(a,b,c,a,b), 점수/모바일 근거 동일, 모바일 시트 키보드 조작·초기화·가로 넘침0·pageerror0 확인. 주소 search/locate 10회 모두 HTTP200·icn1. [검증 배포](https://gilmok-6wxhw6kdn-vineyard.vercel.app/compare), SHA `2266eed`(검증 당시 구현 `6d686d3`). 마지막 실패 셀 표시는 이후 `e0c1419`에서 보완했으며 정상 채점 경로는 같다.
- 실제 Next production 5후보×100회: p50 **33.3ms**, p95 **33.9ms**, max **34.0ms**, JS heap32,108,543 byte. 입력 이벤트→두 rAF까지, 드래그 중 열 순서 유지, RPC/Worker 추가0. 실제 브라우저 CPU·네트워크 환경을 고정한 보편 성능 보장은 아니다.
- 로컬 최종 합본: p95 33.8ms/max33.9ms. raw WebSocket payload 추가 확인 실행: p95 33.6ms/max33.8ms(3분 대기만 이전 합본에서 이미 수행). 최초 max121.6ms도 위에 보존했다.

## 원격 Realtime 분리 실증

원격 publishable key + 실제 익명 authenticated uid 2개에서 소유자 격리(같은 주소/다른 주소), wire record3필드, pending→ready 무새로고침, 이전 timestamp 이벤트 무시, 연결 단절 중 ready 복구, 구독 전 ready, **실제180초 지연 안내→이후 ready 반영**을 통과했다. HTTP500 없이 분리 실증을 완료했고 시험 uid/큐/캐시/관찰자는 finally에서 정리했다. 합성 캐시의 총점 58.891881857688006→62.57609238400379, 신뢰도 60→75 갱신을 관측했다. 이 건물 수치는 통제 fixture이며 실제 건물 평가로 해석하지 않는다.

[원시 실측 요약 JSON](s3-2-b-comparison-20261001.json)에 분리 통과와 합본 실패를 함께 보존했다. 원격 webhook `gilmok_address_dispatch`는 D, `INGEST_REMOTE_ENABLED=false`, sweep cron은 기존 매시간으로 유지한다.

## 원격 실패와 남은 범위

**원격 합본 시나리오는 실패했다. B의 운영 완료 선언은 보류한다.** 두 uid Realtime 검증을 유지한 채 b 컨텍스트에서 대치동 5후보를 연속 채점하면 `score_inputs`와 `exposure_inputs_v022`가 HTTP500, SQLSTATE`57014`, `canceling statement due to statement timeout`을 반환했다. 실패 실행과 재실행 모두 기록했다. 별도의 Vercel 한 브라우저 5등록은 같은 코드/서버 설정으로 통과했다. 이 통과를 합본 시험의 통과로 바꾸지 않는다.

- 원격 분리 검증은 `PROOF_REALTIME_ONLY=1`로 Realtime 경로만 시험한다. 실제 3분 대기는 유지한다. 브라우저를 mock으로 바꾸거나 ready 이벤트를 직접 주입하지 않는다. 점수/슬라이더는 위 Vercel 실측으로 검증 범위를 구분한다.
- 진단 중 연결 대기 잠금·JIT를 주 원인으로 확인하지 못했다. `authenticated.statement_timeout=15s`, 관련 pg_stat_statements JIT 집계0, 조회 당시 active 쿼리의 lock 대기 없음. 역할·timeout·함수·컴퓨트 변경 없음.
- `exposure_inputs_v022` 직접 SQL(EXPLAIN ANALYZE), 새로운 연결의 첫/둘째 실행: a5618.158/957.723ms, b1065.277/787.209ms, c563.403/509.291ms. 이는 각2회이며 p95나 물리적 디스크 cold라고 부르지 않는다.
- 별도 순차 authenticated HTTP 진단 b3회: exposure3.468/8.112/7.440초(각2,707,710byte), score_inputs800m7.717/4.656/5.087초, 모두200. SQL 실행 시간과 HTTP 왕복을 혼동하지 않는다. 처리량·실행 계획/리소스의 원인 확정은 아직 하지 않았다.
- 현재는 승인된 병렬 RPC 구조와 프리셋을 유지했다. 서버 성능 원인 확인 및 조정 방안은 B 머지 전 검토 대상으로 남긴다. 병렬 구조/마이그레이션/컴퓨트 변경이 필요하면 계획 차이를 먼저 보고하고, 원격 migration은 dry-run 후 승인을 받는다.
- 실패 시 UI는 후보별 재시도와 조회 실패를 표시한다. 성공한 입력은 보존하고 실패한 RPC/Worker만 재시도하는 동작은 단위 검증했다. 자동 무한 재시도는 없다.

## D5 전환 계획 — 실행 전 사용자 승인 필요

B의 로컬·원격 실증 통과 및 머지 후, 사용자가 승인하면 다음을 별도 실행한다.

1. 원격 Database Webhook 상태·Vault 토큰 유효성·main 워크플로우·Actions Secrets/DB 연결 확인. `INGEST_REMOTE_ENABLED` 현재값 기록.
2. `.github/workflows/address-queue.yml`의 보완 sweep을 `23 * * * *`에서 `23 */6 * * *`(UTC 00/06/12/18시23분, KST 03/09/15/21시23분)으로 변경. 처리 상한·동시성·실패한 projection 보정 단계는 유지. GitHub schedule 지연 가능성을 운영 문서에 기록.
3. 필요 시 webhook 활성화, repository variable `INGEST_REMOTE_ENABLED=true`. 실제 pending 공개 주소1건→repository_dispatch→main Actions run→cache ready→RPC/화면 무새로고침을 확인하고 run URL·소요 시간을 남긴다.
4. 통과하면 true를 유지하여 이벤트 즉시 처리+6시간 누락 보완으로 상시 운영. 실패하면 false로 복귀하고 webhook/Actions 상태와 원인을 보고한다. 변경 전 설정을 보존하여 cron 복귀도 가능하게 한다.

**이번 B에서는 variable/원격 webhook/cron을 바꾸지 않는다.** 사용자가 요청한 ‘계획 포함, 실행은 승인 후’를 따른다. 합성 Realtime 시험은 위 운영 전환의 실제 대장 워커 실증과 구분한다.
