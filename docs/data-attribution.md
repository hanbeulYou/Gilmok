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
