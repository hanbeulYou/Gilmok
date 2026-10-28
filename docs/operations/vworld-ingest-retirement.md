# Vworld 키 없는 ingest 운영

신규 좌표는 Juso 검색/좌표 API, 경계·건물 보조는 기존 R2 원본 재생으로 처리한다. **migration·기존 DB 객체 변경 없음.** 원격 DB/R2 게시·행 교체·키 삭제 없음.

- 공급자 진단: Juso 검색+좌표1건, 건물관리번호 일치·EPSG:5179 양수/유한 수 검사. 키·주소·좌표·공급자 오류 본문은 로그에 남기지 않는다.
- `verify_juso_transition`: Juso 좌표 사용, 새 journal `.local/validation/juso-coordinates`. Vworld journal 재사용 거부. 원래 S2 v0.3 T1 분포 전용 도구이므로 현재 v0.4 원천에서는 fingerprint 검사로 중단한다. 역사 보고서를 새 채점 결과로 재작성하지 않는다.
- 법정동 입력 GeoJSON이 없으면 R2 고정 원본68행을 복원하고 강남14개 법정동을 검증한다.
- 건물 수동 refresh/검증은 신규 WFS bbox 요청 대신 전체33,345개 원본을 재생해 기존 SHP/공간 중복 제거를 거친다. 현재 보조1,885개를 삭제하는 변경이 아니다.

`archived_wfs.py`는 원본 key·SHA256·행수·2026-09-20 기준일을 고정한다. R2 설정이 없으면 RawStore 로컬 원장 경로를 쓴다. 캐시가 없으면 다운로드, 있으면 SHA 검산 후 재사용하며 실패 시 중단한다. 다른 지역/새 날짜 수집을 이 원본으로 대체했다고 주장하지 않는다. 최신 SHP와 조합하더라도 보조 WFS 행은 옛 수집일을 유지한다. 새 원본 채택은 별도 검산·승인 후 핀을 변경한다.

롤백은 코드 revert이며 원본·기존 DB 좌표는 그대로다. 키 삭제 후 옛 코드를 복귀하면 과거 API 의존 경로가 실패하므로 동결 원본 재생 경로를 유지하거나 키 복구를 별도 결정해야 한다. 자동 키 복구·재수집은 하지 않는다.

## 한별이 삭제할 대상

**이 PR을 main에 머지한 뒤** GitHub `hanbeulYou/Gilmok` repository Actions Secret `VWORLD_API_KEY`를 삭제할 수 있다. `address-queue`·`refresh-monthly`·`refresh-source`의 전달을 제거했다. Environment 수준의 같은 이름이 별도로 있다면 함께 확인한다(이번 세션 삭제 없음). 미사용 repository variable `VWORLD_SERVICE_URL`, 로컬 `.env`의 `VWORLD_API_KEY`·`VWORLD_SERVICE_URL`·`VWORLD_WFS_URL`도 정리 대상이다. Vercel 삭제는 앞선 사용자 작업과 별개로 재실행하지 않는다. 기존 Vworld DB/R2 자료는 키 정리 대상이 아니다.
