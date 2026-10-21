# 신규 등록 Juso 전환과 Vworld 저장 데이터 교체 계획

- 기준: main, 2026-10-16. 신규 등록 코드는 구현 승인, 기존 데이터는 계획만.
- 별도 PR. #39는 학원/학교 원천 전환과 학교 표준데이터 검토를 담당한다.
- 원격 DB/R2 쓰기·삭제, 키 삭제, 기존 데이터 재산출은 이번 실행 범위가 아니다. Juso 해외 저장 공식 답변 전 원격 승격 보류.

## 1. 신규 등록 코드

`app/api/address-search/route.ts`와 `lib/geo/address-server.ts`에서 Juso 검색 → 선택 식별자 서버 재검증 → `addrCoordApi.do` 1회 → 출입구 EPSG:5179 → PostGIS RPC EPSG:4326 → 기존 PNU 도형 검증을 사용한다. 점수·마커 좌표는 검증된 출입구 좌표를 사용하며 출입구 원좌표/CRS/공급자는 provenance에 보존한다. 후보 저장은 기존 uid RLS/저장 RPC를 유지한다. 검색/좌표 응답은 no-store, 공용 `geocode_cache`에는 쓰지 않는다. 등록 실패에 Vworld 폴백은 없다.

`icn1` 고정, 인증 세션 검증, uid/KST 일 100회, 키·주소·원문을 제외한 오류 로그를 유지한다. UI 검색 1회와 등록 시 선택 재검증 검색 1회·좌표 1회는 각기 쿼터를 차감한다. 기존 `vworld_coordinate` 카운터와 과거 provenance 타입은 보존하며 신규 경로에서는 사용하지 않는다. 키/쿼터 실패 시 외부 호출하지 않는다.

### migration

**기존 객체 변경 있음:** `app_private.address_daily_usage`에 `juso_coordinate` 열(default 0, 기존 행의 새 열도 0) 추가, `public.claim_address_call(text)` 본문 교체, `public.project_juso_coordinate(float8,float8)` 신규 추가. 기존 열/행 삭제·기존 좌표 교체 없음. 트리거 없음.

`20261021000000_juso_registration_coordinates.sql`은 CLI로 생성했다. 호출 한도 RPC의 시그니처·SECURITY DEFINER·빈 search_path·authenticated EXECUTE·일일 합계100·부수 활동 기록을 유지한다. 투영 RPC는 STABLE/SECURITY INVOKER/빈 search_path/authenticated 전용이며 외부 IO/DB 쓰기가 없다. 5179 범위, 변환 후 한국 범위, NULL/NaN/Infinity를 거부한다. 새 라이브러리는 없다.

원격 dry-run은 이 migration 1개만 표시, exit 0. 적용/배포는 별도 승인 대기. [실측·해시](../validation/juso-registration-20261016.md).

## 2. 기존 저장 데이터 전수 목록

2026-10-16 02:09:53 UTC, 원격 명시적 READ ONLY 트랜잭션과 R2 LIST/GET으로 확인했다. [객체별 manifest](../validation/vworld-retirement-inventory-20261016.json). 개인 후보의 uid·주소·좌표·원문은 GitHub에 싣지 않고 로컬 `.local/academy-transition/retirement-20261016`에 보관했다. 이는 조사 목록이며 교체/삭제 실행 manifest 승인이 아니다.

| 위치 | Vworld 관련 저장 범위 | 처리 계획 |
|---|---|---|
| `candidates.address_provenance.location` | 6행, 고유 주소3개. provider=vworld | Juso 재산출 후 원 출처를 소급 변경하지 말고 새 provenance로 명시적 교체 |
| 후보 `geom`/`registration_context` | 위 6행. geom과 registration_context는 별도 저장 좌표이며 Vworld provenance 원점과 6/6 다름 | 새 선택/PNU/도형 검증과 대조. 기존 저장 좌표와 provenance 차이는 개별 검토하며 일괄 덮어쓰지 않음 |
| `comparisons` | 해당 후보 참조3행. 자체 좌표 사본 없음 | 참조 유지·재열기·점수/모델/분포 버전 검증 |
| `academies` | 10행/10주소, geocode_provider=vworld | #39와 단일 기관ID 대조·원천/층 파생/기준 분포 원자적 교체 계획으로 통합 |
| `schools` | Vworld 0행 | 표준데이터 제안은 #39에서 별도 검토 |
| `geocode_cache` | provider=vworld 28행: 좌표 있는 성공11, 실패17 | 성공11 재산출 결과 대조, 실패17은 실패 이력 정리 별도 승인. 기존 행 일괄 삭제 금지 |
| 캐시의 Juso provenance | 문자열 검색에 잡힌 99행은 provider=juso, `call_counts.vworld_coordinate` 키 등이 원인 | 성공53/실패46. Vworld 좌표로 오분류하거나 삭제하지 않음 |
| 주소 큐/대장 캐시 | 등록 좌표 전달1건(PNU 1168010100106490007), 각각 큐1·캐시1 | provider 필드가 없어 명시적 확정과 구분. D5 당시 등록 구현·검증 기록상 Vworld 경유로 추론하여 재검증 대상 포함 |
| 기타 주소 큐/캐시 | 큐1은 좌표 NULL, 캐시1은 Kakao 과거 경로 | Vworld 데이터로 처리하지 않음. 기존 Kakao 전환 승인 범위에서 별도 관리 |

큐/캐시의 등록 유래 1건은 [D5 실증](../validation/s3-2-d5-20261002.md)의 2026-10-06 PNU/원본과 연결된다. 원본에는 `registered_queue_input`, `coordinate_source=registration`, `coordinate_api_calls=0`만 있고 명시적 Vworld 표시는 없다. 삭제된 당시 후보까지 복구하여 공급자를 확정했다고 주장하지 않는다.

### R2 전체 키 104개 분류

LIST 전체104개, 좌표/지오코딩/파생 가능성이 있는21개 내용 확인·SHA 기록. 나머지는 소스 계약별로 분류했으며 **104개 전체 바이트를 재검사했다는 뜻은 아니다**. 실행 전 이 목록의 ETag/행수/참조와 불명 출처를 다시 대조한다.

- `academies_profile/revisions/20261009T230110Z/2026-10.parquet`: 25,527행 중 Vworld10, Juso145(좌표64), Kakao25,372. 원천 객체 전체 재게시를 계획하며 기존 객체 삭제는 별도 승인.
- `public_place_geocodes/revisions/20260926T095229Z/2026-09.parquet`: payload 13,570개 중 Vworld28(성공11/실패17). DB 캐시와 함께 대조한다.
- `address_building_1168010100106490007/revisions/20261006T102014Z/2026-10.parquet`: 12행 중 geocode payload에 등록 전달 좌표. 공급자 추론 대상1객체. 대장 원문을 없애지 않고 좌표 출처 부분의 교체/보존 정책을 승인받는다.
- `address_building_...9110013`·`...9120013`: geocode 응답은 `documents/meta`의 Kakao 형식. Vworld로 분류하지 않는다.
- `schools_profile`: 1,320행 중 Vworld0. `restore_provenance`의 Vworld 표시는 WFS/법정동 등 도형 출처이며 지오코더 좌표로 단정하지 않는다.
- score_reference/inputs/manifest 각4객체, rollback12객체는 파생 통계/복원 이력. 학교·학원 수가 좌표에 의존하므로 신규 기준 분포를 원천과 원자적으로 생성하되 기존 롤백 객체 삭제는 별도 승인. 입력은 격자 기반 집계이며 기관 원좌표를 보관하는 계약이 아니다.
- `vworld_building_footprints`, SHP, 법정동은 **지오코더 API가 아닌 도형 소스**다. Vworld라는 이름만으로 키·객체를 삭제하지 않는다.

## 3. 기존 데이터 교체 PR의 승인 순서 (아직 미실행)

1. 신규 등록 전환을 먼저 배포/검증하여 Vworld 신규 저장을 멈춘다. Juso 해외 저장 회신과 원격 migration 승인을 선행한다.
2. 불변 inventory를 다시 고정한다: 대상PK·provider·원값 hash·R2 ETag·참조 후보/비교·기준 분포 fingerprint. 신규/수정된 행이 있으면 실행 manifest 재작성. 민감한 행 목록은 로컬만.
3. **후속 승인 후** 로컬 Juso 재산출: 후보6행/3주소, 학원10행/10주소, 성공 캐시11행, 등록 전달1건. 중복 주소는 합쳐 호출하되 대상 행 ID는 유지. PNU·출입구·도형 중심·이동거리·다른 건물/불명/실패를 기록. 불일치 행은 자동 덮어쓰지 않는다.
4. a~e 8축/총점/신뢰도/순위, 무작위5셀, 대상 후보/저장 비교 재열기를 대조한다. #39 학교 표준 좌표와 결합할 경우 두 변경의 영향도 각각 보고한다. 채점 모델/가중치 변경 없음.
5. 원천·좌표 공급자/품질 플래그·층 파생·분포를 격리 DB에서 단일 트랜잭션으로 승격·실패 주입·롤백 검증. R2는 새 불변 revision을 먼저 준비하되 원격 게시는 승인 후. DB commit이 참조할 manifest/hash를 고정한다. DB/R2에 분산 트랜잭션이 있다고 가정하지 않으며 실패 시 활성 참조를 이전 revision으로 유지한다.
6. 교체/삭제 대상별 before/after hash·행수·FK·예상 점수와 rollback manifest를 제출하고 **원격 쓰기/삭제를 별도 승인받는다**. DB는 대상 행 잠금 및 원값 비교 후 교체, 다른 사용자 데이터 손실/재소유 없음. 캐시/키 정리는 성공 확인 후 별도 승인.

## 4. 롤백과 사용자 단계

신규 코드 장애 시 등록을 일시 중지하고 저장된 비교 조회는 유지한다. Vworld 새 저장을 재개하는 자동 롤백은 금지한다. 이전 좌표/기관 원천/분포로의 데이터 롤백은 약관 및 사용자 승인 범위에 따라 manifest 단위로 결정한다. 조사 자체는 대상 데이터에 아무 쓰기도 하지 않아 데이터 롤백이 필요 없다.

migration은 호환 확장이므로 원격 적용 후 문제가 있어도 `juso_coordinate` 이력과 projection RPC를 남긴 채 신규 등록만 중지하는 방식을 권장한다. 새 앱이 중지된 뒤에만 함수 복귀를 검토한다. `vworld_coordinate` 열을 지우거나 `provider`를 소급 Juso로 바꾸지 않는다.

사용자 단계: Juso 해외 저장 공식 회신 전달 → migration push 승인 → Vercel Production/Preview `JUSO_COORD_API_KEY` 서버 전용 확인(기존 검색키 유지) → 새 배포의 실제 등록/저장 승인. Vercel에 키를 등록했다는 과거 진술은 있으나 현재 값/존재를 재확인했다고 주장하지 않는다. 키 값은 채팅에 보내지 않는다. Vercel의 기존 `VWORLD_API_KEY` 삭제는 별도 승인, `.env`/Actions의 WFS용 키는 유지 대상이다.

## 5. 완료 기준

- [x] 신규 경로 Juso만 호출, EPSG5179→4326·PNU 검증·uid 일일 한도·오류 비밀 보호
- [x] 실제 공개 주소3건 로컬 어댑터 성공, migration 로컬 적용·DB 회귀·원격 dry-run
- [x] 원격 DB/R2 읽기 목록·불명 출처·별도 교체/삭제 승인 경계 기록
- [ ] 원격 migration/Preview/Production 실증 (승인 전 보류)
- [ ] 기존 데이터 재산출·교체/삭제 (이번 구현 범위 아님)
