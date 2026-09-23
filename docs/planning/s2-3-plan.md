# S2-3 가시성 Worker — 승인 범위와 구현

2026-09-23 사용자 승인. GitHub #13·#14 머지 후 main에서 `s2/visibility-worker`로 분기했다. 기준은 scoring-spec.md v0.1.4다.

- PostGIS `visibility_inputs(lng,lat)`가 기존 `buildings_in_radius(1000)` 건물 집합을 EPSG:5186으로 변환한다. 역·학교 대표점도 같은 좌표계로 제공한다. 기존 4326 RPC·DB 저장 계약은 유지한다.
- `/lib/visibility`의 순수 계산을 Node와 module Worker가 공유한다. 링 180점·역 20점·학교별 10점, 명세 가중치, 눈높이 1.5m·층별 목표 높이, 가까운 도형 경계점, 후보 제외, WFS/unknown 4m, 내부·경계 샘플 제거를 따른다.
- 실제 후보 도형 부재 fallback은 근거 코드 `candidate_footprint_missing_self_occlusion_unaccounted`와 신뢰도 −5를 남긴다. Worker 대기/소스 미적재/유효 샘플 0으로 실제 fallback 시선을 계산하지 않은 경우 이 감점은 적용하지 않는다.
- hand fixture: 원점 3층 목표 8.6m, 벽 footprint x=[1,2], y=[−12,12]. h=7은 79/81, h=9는 19/36. Node·Worker 결과와 실제 310개 시선을 독립 PostGIS 연산으로 대조한다.
- 완료 기준: 역삼로460 3층 실제 visible_ratio·시간·가중치 집계, 역 20점·링 36방향 현장 대조표, ScoreResult 주입, lint/typecheck/test/test:db 통과. [검증](../validation/s2-3-visibility-20260923.md).

마이그레이션은 CLI 생성 신규 파일 1개이며 기존 함수/데이터는 바꾸지 않는다. 롤백은 새 RPC/Worker 호출을 멈추고 기존 visibility pending/NULL 주입으로 복귀한다. 라이브러리 추가·3D 엔진·UI·원격 전환·서울 전체 건물 적재·임대료 보정은 이번 범위에 포함하지 않는다.
