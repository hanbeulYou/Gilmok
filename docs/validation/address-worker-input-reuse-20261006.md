# D5 선행 주소 워커 검증 — 2026-10-06

base main `1efad8454d45efd423632a22099bfbbad85aed3b`(#26 머지), 브랜치 `s3/address-worker-input-reuse`. 사용자가 #25의 전체 webhook 실증 전에 워커 변경만 main에 먼저 반영하도록 승인했다. **migration 없음·기존 DB 객체 변경 없음·운영값 변경 없음.** 운영 gate/trigger/cron과 프론트/PNU 전달 migration은 #25에 남긴다. 사용자가 머지한다.

## 워커 경로와 적용 순서

주소 큐에 PNU·4326 좌표가 있으면 그대로 건축물 대장 표제부/층별개요만 조회한다. 좌표가 없으면 JUSO_COORD_ENABLED=true와 검색/좌표 키가 모두 필요하다. 승인 전에는 needs_coord로 보류하며 좌표/대장 API를 호출하지 않는다. 월간 신규 주소도 같은 정책이며 보류 주소가 있으면 새 소스 snapshot 승격을 중단해 기존 snapshot을 보존한다. 기존 승인 캐시는 이후 교체 manifest 승인 전까지 계속 사용한다.

큐의 선택 필드는 row JSON으로 읽어 D5 열 추가 전의 기존 fixture replay도 가능하다. 실제 needs_coord 기록과 등록 PNU 전달에는 #25 migration이 필요하므로 **이 PR 머지만으로 워커를 켜면 안 된다**. 테스트 DB 외의 큐 상태나 기존 캐시는 변경하지 않았다. KST 일일 쿼터 경계와 공급자별 원본 journal 경로를 유지했다. 로그는 키/응답 원문 없이 고정 오류 코드만 기록한다.

이 선행 PR 머지 → #25 최신 main 동기화 → D5 migration 최종 dry-run/해시 보고 → 사용자 push 승인 → 실제 등록→webhook→Actions→ready→화면 자동 갱신 → 상시 운영 시작일 기록/6시간 sweep → #25 Ready 순서다. repository_dispatch/default-branch와 main checkout 제약을 우회하지 않는다.

## 월간 배치 좌표 공급자 실제 1건

[원시 수치](address-worker-input-reuse-20261006.json). 월간 resolve_one이 쓰는 batch_request_address 함수를 로컬에서 1건 호출했고 좌표 변환/도형 조회 DB 연결은 read-only였다. 원격 큐 drain, 월간 snapshot 실행, 공용 geocode_cache 쓰기, 13,542건 재산출은 실행하지 않았다.

| 항목 | 관측 |
|---|---|
| 공개 주소 | 서울특별시 강남구 역삼로 460 |
| Juso 검색 | 1회, HTTP 200, errorCode 0, 0.117초 |
| Juso 좌표 | 1회, HTTP 200, errorCode 0, 결과 1개, 0.056초 |
| Vworld 호출 | 0회 |
| PNU | 1168010600109120013 |
| 출입구 원본 EPSG:5179 | X=960896.1846965668, Y=1944903.6257312004 |
| PostGIS 변환 EPSG:4326 | 위도 37.5025724246771, 경도 127.057585444512 |
| 같은 PNU 도형 | 1개 중 1개 ST_Covers=true, 거리 0m |
| DB/캐시 쓰기 | 0건 |

검색 응답의 정확 주소를 선택한 뒤 좌표 응답 bdMgtSn을 대조했다. 실제 좌표 응답은 admCd/rnMgtSn/udrtYn/buldMnnm/buldSlno/bdMgtSn/entX/entY를 포함하며 기존 parser를 그대로 통과했다. 실제 응답을 이용한 1건 조회 승인이며 전체 월간 좌표 경로의 상시 활성화 승인은 아니다.

.env의 JUSO_COORD_API_KEY는 확인했다. GitHub repository와 ingest-production Secrets에는 이름이 조회되지 않았고 사용자가 Vercel에 등록한 것으로 정정했다. Actions는 Vercel 환경변수를 읽지 못한다. GitHub Secret 등록은 별도 승인을 요청했으며 키 값은 로그/문서에 쓰지 않는다. JUSO_COORD_ENABLED는 계속 비활성이다.

## 검증과 운영 경계

로컬 lint/typecheck, Vitest 121개·Python 265개·DB 218개가 통과했다. CI는 이 선행 PR의 migration 목록만으로 기존 스키마 호환과 build/E2E를 다시 확인한다. PNU 재사용 unit은 Juso/Vworld/geocoder에 호출 금지 spy를 걸고 대장 2회만 허용한다. 잘못된 도로명 응답이면 층별개요/캐시 게시 전에 실패한다. 좌표 없는 주소 워커/월간 경로 모두 키 존재와 활성화 승인을 구분한다.

운영값 INGEST_REMOTE_ENABLED=false·AUTH_CLEANUP_ENABLED=false, 주소 dispatch 트리거 D, 실제 cron은 main의 hourly를 유지한다. 원격 D5 migration/웹훅 실증은 아직 미실행이다. 원복이 필요하면 이 코드 PR을 revert하되 DB/큐/캐시/R2 원본은 삭제하지 않는다. 상시 운영 시작일은 #25 실증 통과 후 기록한다.
