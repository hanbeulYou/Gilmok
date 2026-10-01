# S3-2 B — 비교 매트릭스·실시간 상태 검증

- base: `main` (`337c7ea`, #22 머지 확인), 브랜치 `s3/comparison-matrix`.
- 구현: `6d686d3`. 명세/프리셋 v0.3 변경 없음. 계획 §3 B·§5·§6 범위.
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
- 최종 로컬 payload 직접 확인·원격 Realtime·Next 배포 화면: 진행 중. 완료 실측은 이 문서에 추가한다.

## D5 전환 계획 — 실행 전 사용자 승인 필요

B의 로컬·원격 실증 통과 및 머지 후, 사용자가 승인하면 다음을 별도 실행한다.

1. 원격 Database Webhook 상태·Vault 토큰 유효성·main 워크플로우·Actions Secrets/DB 연결 확인. `INGEST_REMOTE_ENABLED` 현재값 기록.
2. `.github/workflows/address-queue.yml`의 보완 sweep을 `23 * * * *`에서 `23 */6 * * *`(UTC 00/06/12/18시23분, KST 03/09/15/21시23분)으로 변경. 처리 상한·동시성·실패한 projection 보정 단계는 유지. GitHub schedule 지연 가능성을 운영 문서에 기록.
3. 필요 시 webhook 활성화, repository variable `INGEST_REMOTE_ENABLED=true`. 실제 pending 공개 주소1건→repository_dispatch→main Actions run→cache ready→RPC/화면 무새로고침을 확인하고 run URL·소요 시간을 남긴다.
4. 통과하면 true를 유지하여 이벤트 즉시 처리+6시간 누락 보완으로 상시 운영. 실패하면 false로 복귀하고 webhook/Actions 상태와 원인을 보고한다. 변경 전 설정을 보존하여 cron 복귀도 가능하게 한다.

**이번 B에서는 variable/원격 webhook/cron을 바꾸지 않는다.** 사용자가 요청한 ‘계획 포함, 실행은 승인 후’를 따른다. 합성 Realtime 시험은 위 운영 전환의 실제 대장 워커 실증과 구분한다.
