# ingest의 Vworld 키 의존 제거·대체안 — 2026-10-27

**계획만 작성. 실행·원격 쓰기·기존 자료 삭제·키 삭제 없음.** 프론트 `app/`·`lib/`의 `VWORLD_API_KEY` 읽기는0곳이며 Vercel 삭제는 한별이 수행한다. 아래4파일 때문에 `.env`와 Actions Secrets의 전역 삭제 조건은 아직 충족되지 않는다.

공식 [지오코더 API 카탈로그](https://www.data.go.kr/catalog/15101106/openapi.json)는 실시간 사용 및 별도 저장장치/DB 저장 불가를 명시한다(2026-10-27 재확인, 카탈로그 수정일2025-07-01). **이 문구는 지오코더 API에 대한 근거이며 WFS 전체의 저장 금지까지 입증하지 않는다.** WFS는 별도 제공조건 검토가 필요하다. 키 의존 자체를 없애려면 다음 대체를 승인·검산 후 순차 적용한다.

| 파일·읽기 위치 | 현재 하는 일·저장 | 제거·대체 제안 | 승인 전 검산 |
| --- | --- | --- | --- |
| `ingest/verify_juso_transition.py:29,47` | A0 3곳 비교용. Juso 검색 후 **Vworld 주소→좌표**를 호출하는 JusoProvider에 키를 전달. 응답을 로컬 journal에 기록하고 PNU 도형 포함·이동거리·8축을 대조. PNU 자체는 Juso 식별자로 조합하며 Vworld PNU조회가 아님 | 기존 검증 경로의 좌표 공급자를 이미 구현된 Juso 좌표 API 어댑터로 교체. 키는 `JUSO_COORD_API_KEY`. Vworld 폴백 제거, 옛 journal은 신규 결과로 오인 재사용하지 않도록 provider별 분리 | 3곳 건물관리번호/PNU/도형 포함과 전체8축·순위 대조. 과거 journal/보고서는 역사 자료로 보존하고 삭제는 별도 manifest 승인 |
| `ingest/address_provider_diagnostic.py:22` | 해외IP 진단용 Juso 검색→**Vworld 지오코더** 호출. parse_vworld로 주소/응답을 판별하고 상태·bounded 오류코드만 출력. 좌표를 진단 결과에 출력하거나 DB에 쓰지 않음 | 진단 대상을 Juso 검색+좌표로 변경하고 `bdMgtSn` 일치·5179 응답 검사를 추가. 공급자 단계명을 juso로 변경. 실시간·무저장 Vworld 진단 자체가 위 저장금지의 위반이라고 단정하지 않으나 신규경로에서 불필요한 호출이므로 제거 추천 | 정상/NOT_FOUND/키없음/HTTP실패 fixture, URL·주소·키·응답좌표 로그 금지 검사. 실제 Juso 호출은 승인된 진단1건만 |
| `ingest/legal_boundaries.py:136` | **법정동 경계 WFS** `lt_c_ademd_info`, GetFeature·bbox·EPSG4326. GeoJSON을 파일에 캐시하고 검산 후 법정동 공간 연결에 사용. 주소지오코딩/PNU조회 API가 아님 | 저장 허용 조건을 확인한 공식 법정동 경계 전체 파일을 수동 확보→R2 raw→기존 DuckDB/Postgres 경계 처리로 전환. 현재 WFS를 조용히 삭제하지 않음 | 법정동코드·CRS·기준일·포함범위, 기존14개 법정동 및 실거래/후보 공간귀속 변화, geometry digest·롤백 원본. 새 다운로드 자료/조건을 확인하기 전 공급자·라이선스를 확정하지 않음 |
| `ingest/building_footprints.py:170` | **누락 건물 보조 WFS** `lt_c_bldginfo`, bbox 도형/속성 조회. SHP에 없는 도형을 보조 차폐·3D 입력으로 적재. PNU속성이 있어도 PNU로 대장을 조회하는 API는 아니며 주소→좌표 폴백도 아님 | 주 원천의 최신 건물 SHP/공식 배포 파일로 보조 도형까지 확보하는 안을 검토. 승인 전까지 기존WFS 도형 유지. 대체 없는 건물을 삭제해 노출을 과대평가하지 않음 | 기존보조1,885개와 최신실제개수 대조, 겹침/미확보/높이unknown/PNU연결 및 a~e·무작위5셀8축, 3D/노출샘플 변화. 원천·기준분포 동시승격/롤백 manifest를 별도 승인 |

## 적용 순서 제안

1. 작은 코드 PR: 위 **지오코더 검증·진단2파일**의 Juso 전환, 대응 테스트, 실제 독립 키 읽기0 검증. 사용자 승인 후 구현한다.
2. 데이터 전환 PR: **WFS2소스**의 제공조건/공식파일 조사·로컬 영향·전체 rollback manifest 제출. 데이터 품질이 동등하게 확보된 후만 원격 승격 승인 요청한다. 지오코더 저장금지를 WFS 금지로 단순 확대 적용하지 않는다.
3. 잔여 호출 그래프 확인: `ingest/juso.py`의 교체형 Vworld 어댑터·`ingest/geocode.py` request_vworld는 직접 env를 읽지 않아4파일 수에 포함되지 않지만, 승인된 제거 PR에서 호출자0인지 검사한다. 과거 기록을 고쳐 출처를 소급 juso로 바꾸지 않는다.
4. `.github/workflows/{address-queue,refresh-monthly,refresh-source}.yml`의 env 전달, `.env.example`, 운영 문서를 맞춘다. active WFS가 남아 있는 동안 `.env`/Actions 키를 먼저 제거하지 않는다.
5. 저장소 전체 **실제 읽기0 + 승인된 배치/수동 경로 검증** 후 삭제 대상 목록(서비스·환경·변수명만)을 제출한다. 실제 키 삭제는 한별이 수행한다. 기존 DB/R2 Vworld 유래 데이터의 삭제·교체는 기존 inventory와 새 재산출/차이/manifest 승인을 따른다.
