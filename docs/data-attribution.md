# 데이터 출처

## 서울 행정동 경계

원자료: 통계청 통계지리정보서비스 [SGIS](https://sgis.kostat.go.kr), 공공누리 제1유형.
가공·행정구역 변경 반영: [vuski/admdongkor](https://github.com/vuski/admdongkor), CC BY 4.0.
정부가 직접 배포한 최신 경계 파일과 구분한다.

- 사용 파일: `ver20260701/HangJeongDong_ver20260701.geojson`
- 고정 커밋: `dd1881663fcabc69b81393604e91ebf3a4202e9a`
- [해당 버전 이용 조건](https://github.com/vuski/admdongkor/blob/dd1881663fcabc69b81393604e91ebf3a4202e9a/LICENSE-DATA)
- 길목 처리: 서울 427개 피처 선택, `adm_cd2`의 행안부 코드 말미 `00` 제거, 원래 CRS84 좌표를 DB EPSG:4326으로 명시. 경계 보정·분할·단순화 없음.
- R2 Parquet에 원래 속성·GeoJSON 기하·출처·버전·커밋·출처 표시를 함께 보존한다.
- 이후 UI·파일 내보내기에서도 SGIS와 가공자 출처 표시를 유지한다.

## 250m 격자와 인구

- 서울 열린데이터광장: [내국인 서울생활인구(250m), OA-22784](https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do), 2026년 6~8월.
- 격자 경계: [서울생활인구 안내](https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do)의 250m SHP. 제공 경계 10,125개는 원형 보존하고, 관측되지만 파일에 없는 두 셀은 전체 경계에서 검증한 생성 규칙으로 별도 생성했다.
- 주민등록 인구: [행정안전부 주민등록 인구통계](https://jumin.mois.go.kr/ageStatMonth.do), 2026년 8월 단일 연령 CSV. 원천 결측·연령 구간 처리는 `docs/planning/data-sources.md`를 따른다.

## 지하철·버스

제공: 서울특별시 서울 열린데이터광장. 아래 네 소스의 이용허락은 공공누리 제1유형(출처표시)이다. 승하차 원본시스템은 교통카드 정산시스템이다.

- 시간대 승하차: [지하철 OA-12252](https://data.seoul.go.kr/dataList/OA-12252/S/1/datasetView.do), [버스 OA-12913](https://data.seoul.go.kr/dataList/OA-12913/S/1/datasetView.do), 2026년 6~8월.
- 위치: [서울시 역사마스터 정보 OA-21212](https://data.seoul.go.kr/dataList/OA-21212/S/1/datasetView.do), [버스정류소 위치정보 OA-15067](https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do), 2026-09-19 API 조회본.
- 길목 가공: 노선 안의 역명 정규화·버스 내부 ID 조인, 정확한 복제 행 제거, 서울 경계 필터, 시간대 월 합계의 합÷92일. R2에는 원래 컬럼·원천 ID·복제 행을 유지한다.
- 신분당선 승하차 미제공 및 위치 미매칭은 대체 추정하지 않았다. 과거 6~8월 위치와 9월 조회 좌표의 동일성을 보장하지 않는다. 후속 화면·내보내기에도 출처·기간·결측 한계를 표시한다.


## PR 4 상가·학원·학교 및 지오코딩

- 상가: 소상공인시장진흥공단, [공공데이터포털 15083033](https://www.data.go.kr/data/15083033/fileData.do), 2026-06-30 기준 서울 CSV. 원본 전체 컬럼을 R2에 보존하고 DB에는 업소번호·업종 코드·층·위치만 투영했다. 최신 분류와 표준산업분류를 합치지 않는다.
- 학원·교습소: NEIS 원천, [서울 열린데이터광장 OA-20528](https://data.seoul.go.kr/dataList/OA-20528/S/1/datasetView.do), 2026-09-19 조회. 분야·계열·과정명과 원천 갱신일 원문을 보존한다.
- 학교: [나이스 교육정보 개방포털](https://open.neis.go.kr/), schoolInfo/B10, 2026-09-19 조회. 초·중·고 원천 학교급만 대응하며 그 외 학교급도 R2 원본에 보존한다.
- 주소 좌표: [Kakao 주소 검색](https://developers.kakao.com/docs/ko/kakaomap/rest-api), [Vworld 지오코더](https://www.vworld.kr/dev/v4dv_geocoderguide2_s001.do). provider와 조회일을 캐시에 기록한다. 반환 도로명·건물번호가 원문과 다른 결과는 수용하지 않으며 좌표를 추정 보정하지 않는다. 캐시·journal은 배치용이고 프론트·Edge Function은 외부 서비스를 직접 호출하지 않는다.
- 이후 화면·내보내기에서도 데이터 제공자·기준일·지오코딩 provider와 위치 미확보를 표시해야 한다. 캠퍼스 대표 좌표를 개별 교문 위치로 표시하지 않는다. 상세 품질·제약은 [검증 기록](validation/pr4-places-20260920.md)을 따른다.

## 건물 도형·건축물대장 (PR 5)

- 주 도형: 국토교통부 **GIS건물통합정보**, 기존 국가공간정보포털 제공 자료의 [Vworld 파일 배포](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=NA&dsId=18). 사용자 제공 서울 전체 `AL_D010_11_20260909.zip`, 배포 2026-09-09·행 기준 2026-09-06. 사용자 승인 근거는 **CC BY**다. 원천 기관·배포 경로·파일 기준일을 표시하며 SHP 중복 1행 제거, 자기 교차 4건 수리, 좌표 변환과 높이 추정이 적용됐음을 함께 표시한다. 원본 ZIP·원문 속성·원천 geometry는 수정 없이 R2에 보존한다. **수동 다운로드 후 R2 raw/에 게시, 갱신 주기 분기**다.
- 보조 도형: [Vworld WFS](https://www.vworld.kr/dev/v4dv_wmsguide2_s001.do)의 `lt_c_bldginfo`, 2026-09-20 조회. SHP와 겹치지 않는 도형만 추가하고 `source=vworld_wfs_supplement`로 표시한다. [데이터셋 명세](https://www.data.go.kr/catalog/15123970/openapi.json)의 이용허락범위와 별도 [Vworld 이용약관](https://www.vworld.kr/v4po_prcint_a001.do)을 함께 기록한다. SHP의 API 비의존·CC BY를 WFS API의 이용조건으로 확대하지 않는다.
- 표제부·층별개요: 국토교통부 [건축HUB 건축물대장정보 서비스](https://www.data.go.kr/data/15134735/openapi.do), `getBrTitleInfo`·`getBrFlrOulnInfo`, 2026-09-20 조회. PK·PNU가 일치하는 SHP만 대장 기반 집계에 연결한다. 조회일은 원천의 측량·생성일을 뜻하지 않는다.
- 높이는 원천 양수값/층수 추정/unknown을 구분하며 추정값을 실측으로 표시하지 않는다. OSM은 비교 검증에만 사용했고 이번 조회 DB에는 적재하지 않았다. 조사에서 관측한 SHP 배포 화면의 CC BY와 라이선스 바로가기 불일치 등은 [사전 기록](validation/pr5-footprints-20260920.md)에 보존한다. 실제 원본·수리·제외·연결률은 [적재 검증](validation/pr5-buildings-20260920.md)을 따른다.


## 실거래·법정동·임대동향 (PR 6)

- 국토교통부 [상업업무용 부동산 매매 실거래가 자료](https://www.data.go.kr/data/15126463/openapi.do), 2026-09-20 조회, 2024-09~2026-08 계약월. 포털 이용허락범위는 제한 없음. 금액 원문은 만원이며 원/㎡ 단가·중앙값은 이 프로젝트에서 계산했다. 취소·지분·결측 제외와 표본수를 함께 표시한다. 매매를 임대료로 표시하지 않는다.
- 국토교통부/Vworld [행정구역도 WFS](https://www.data.go.kr/data/15059008/openapi.do), `lt_c_ademd_info`, 2026-09-20 조회. 명칭과 달리 이 레이어의 읍면동은 법정동이며 행정동 경계와 구분한다. [카탈로그](https://www.data.go.kr/catalog/15059008/openapi.json)의 공공누리 제1유형 출처표시와 [Vworld 이용약관](https://www.vworld.kr/v4po_prcint_a001.do)을 함께 따른다. DB는 강남구 14개 경계, 원응답은 R2에 보존한다.
- 한국부동산원 [R-ONE OpenAPI](https://www.reb.or.kr/r-one/portal/openapi/openApiDevPage.do), 상업용부동산 임대동향조사 2026년 2분기. 임대료 천원/㎡를 원/㎡로 변환하고 공실률은 %를 유지한다. 통계표·분류 코드·건물유형·분기·조회시점을 보존한다.
- 상권 도형·분류 연결은 [공식 통계지도](https://www.reb.or.kr/r-one/portal/gis/rcsGisViewerPage.do)와 공식 분류 메타데이터다. 원천 도형의 기준연도는 2024이며 2026Q2 적용 및 강남 권역 공간 정의를 확정하지 못했으므로 후보 값으로 활성화하지 않았다. 상권 구획도의 별도 배포 이용조건 확인도 남아 있다. 검증용 원응답을 보존한 것과 공개 서비스에 공간 자료를 제공할 수 있다는 판단을 구분한다.

실제 응답·변환·결측과 보존 증거는 [PR 6 검증](validation/pr6-rent-20260920.md)을 따른다.
