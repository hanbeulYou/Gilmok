# S3-2 A0 — Juso 전환·카카오 유래 데이터 교체 계획

base: main

작성: 2026-09-30. **계획 승인 대기이며 구현·재지오코딩·원격 변경은 미실행이다.** 기준 main은 `e937407`(#21). A0 브랜치 `s3/juso-transition`에는 현재 계획 문서만 두며 승인 후 같은 PR에 구현을 별도 커밋으로 추가한다. A의 [Draft #22](https://github.com/hanbeulYou/Gilmok/pull/22)는 보존한다. A0를 먼저 머지한 뒤 A를 최신 main에 동기화하며, A의 백분위/context RPC WIP를 A0에 섞지 않는다.

## 1. 승인 요청 범위와 완료 기준

사용자·배치의 카카오 호출과 활성 데이터 의존성을 제거하고, 행안부 검색→사용자 선택→좌표제공→PNU→기존 도형 검증으로 교체한다. Vworld는 검증된 폴백으로 남긴다. 채점 수식·가중치·cluster 고정 상수·exposure 모델은 그대로다. A/B/C 기능 분할에 데이터 전환 A0를 선행하는 구조다.

- 모든 활성 지오코딩 경로가 Juso 우선이며 카카오 키 없이 동작한다.
- 기존 공용 `public.geocode_cache`에 `provider='juso'`를 추가한다. Vworld 좌표를 juso로 위장하지 않는다. uid별 응답 캐시는 만들지 않는다.
- 대치동 3곳의 새 좌표·PNU·같은 도형 포함 여부·이동 거리와 v0.3 8축/총점/신뢰도/순위 차이를 보고한다. 결과를 옛 점수에 맞추거나 PNU 중심으로 몰래 옮기지 않는다.
- 학원·학교 등 파생 데이터, reference, R2 원본/복원 manifest의 전환 범위와 실패 행을 모두 계수한다. 재실행·중단 복구·롤백을 로컬에서 검증한다.
- 원격은 최종 migration dry-run·데이터 변경 manifest·검산 보고 후 별도 승인으로 적용한다. **이 계획 승인만으로 원격 삭제를 실행하지 않는다.**

## 2. 확인한 공급자 조건

자세한 출처·확인 한계는 [data-sources §2.8](data-sources.md#28-지오코딩--juso-전환-계약)을 따른다.

| 항목 | 확인 결과·구현 조건 |
| --- | --- |
| 저장/캐시 | 공식 좌표 저장 답변과 공공데이터포털 API 이용허락범위에 근거해 저장·재사용. 공급자 TTL 제약 없음. 최신성은 별도 운영 정책이며 무한히 최신이라는 뜻은 아님 |
| 호출량 | 검색 API는 호출 건수 제한 없음 안내, 과도한 호출은 IP 차단 가능. 좌표 API는 **5초당 10건**. uid 일100회는 자체 남용 방지이며 공급자 한도와 별개 |
| 키 | 검색용 `JUSO_API_KEY`, 좌표제공용 `JUSO_COORD_API_KEY`를 구분한다. 좌표 키로 검색 API를 호출할 수 없다는 공식 답변 확인. 하나의 키가 둘 다 된다고 가정하지 않음 |
| 출처 | 「주소정보 제공에 관한 규정」 제15조에 따라 저작권·출처 표시. `주소정보: 행정안전부 주소정보누리집(도로명주소·출입구 좌표), 조회일 YYYY-MM-DD`와 원문 링크를 데이터 출처 화면/근거 및 산출물 metadata에 기록 |
| 원격 저장 위치 | 2023년 공식 API Q&A의 공간정보 해외 서버 업로드 제한 안내가 있음. 현 Supabase 도쿄 및 R2/백업/CI에 대한 **현행 API 응답 적용 범위 확인이 원격 반영 선행 조건**. 현재 자료만으로 모든 공개 API 좌표에 대한 현행 법적 금지를 단정하지 않음. 서울 Route Handler만으로 DB/백업 위치 문제가 해소되지 않음 |
| 실제 응답 | 키 미발급. 새 Juso 검색·좌표 실호출, 3곳 재산출, 계정 한도/에러코드 실증은 미실행. 공식 문서 확인과 실응답 검증을 구분 |

## 3. 현재 의존성 목록

2026-09-30 로컬·원격 DB를 `default_transaction_read_only=on`으로 조회했다. 비밀·사용자 식별자는 기록하지 않았다. [목록·행수·해시 JSON](../validation/s3-2-a0-inventory-20260930.json)은 코드/문서 검색 당시 A WIP 브랜치의 파일 목록도 포함한다.

| 저장소/경로 | 로컬 / 원격 현황 | A0 처리 |
| --- | --- | --- |
| `public.geocode_cache`, kakao | 각각 **13,542행**: 성공13,481·실패61. 정렬한 주소/provider/성공여부/좌표/실패사유 SHA256 동일 | 성공·실패 전부 재판정 대상. Juso shadow 결과 검증 후 교체. 기존 성공값 provider만 변경 금지 |
| 같은 테이블, vworld | 각각 성공11·실패17 | 독립 출처로 보존·약관/주소 동일성 재확인. Juso 우선순위로 소비자 수정 |
| `academies` | 각각 kakao 성공25,412·실패86, vworld 성공10 | 원천 주소로 재연결. 기관25,508행과 ID/분류/원문 보존, geom/provider/reason만 계수해 교체 |
| `schools` | 각각 kakao 성공1,312·실패7 | 원천 주소로 재연결. 학교1,319행·ID·학교급 보존. 출입구 대표점 변경이 학교 반경/동선에 미치는 영향 계수 |
| `ingest_private.geocode_requests` | 각각 kakao 성공13,480·ambiguous26·invalid8·not_found27 | provider CHECK 확장, 새 juso claim은 별도 키. 구 카카오 실패/중단을 Juso 실패로 복제하지 않음 |
| `ingest_private.building_address_cache` | 각각1행. source가 대장 출처라 geocoder를 직접 식별하지 못함 | `raw_key`→저장 geocode 응답의 계보 대조. 대장 payload는 보존하며 좌표/PNU/provider 계보 재검증 |
| `public.candidates` | 각각0행 | 적용 직전 재계수. 그 사이 사용자 행이 생기면 소유권·임대료·비교 연결 보존하며 별도 전환 명세 필요 |
| `ingest/geocode.py` | 요청/파서/기본 provider/claim/journal/CLI가 kakao | 공용 Juso 파서·PNU·좌표 변환·provider 선택으로 교체 |
| `ingest/building_on_demand.py` | `request_kakao`, `address_parcel`, 키 검사, `geocode.json` 저장 | Juso 주소 검증/좌표/PNU를 사용. 건축HUB 호출은 계속 `/ingest` |
| `ingest/commerce_education_database.py` | 성공 캐시 중 kakao 우선 | juso→vworld 명시적 순위. 기존 kakao로 암묵 fallback 금지 |
| `ingest/refresh_sources.py` | 학원·학교 갱신에서 Kakao 키 전달 | Juso 키/제한기 주입. 일괄 갱신과 on-demand에 같은 판정 규칙 |
| `ingest/verify_s2_4.py`, A의 `verify_registration_reference.py` | 저장 카카오 응답/좌표를 재현 입력으로 소비 | 새 Juso 기준 fixture를 별도 생성. 기존 fixture는 전환 전 비교 증거로 구분 |
| `.github/workflows/{address-queue,refresh-source}.yml`, `.env.example` | Kakao 키 주입/계약 | Juso 키 두 종류로 변경. `.env`·Actions의 `KAKAO_REST_API_KEY` 제거는 전환 검증 후 작업 목록. 이번에는 값/Secrets 변경 없음 |
| R2·로컬 raw/journal | `raw/academies/`, `raw/schools/`, 주소 워커 geocode 응답 및 과거 고정 복원 manifest | 활성 원본/파생 Parquet/reference/복원 manifest를 새 버전으로 재발행. 객체·버전·해시·파생관계의 전수 목록은 A0에서 확정. 원격 객체 삭제는 별도 검토된 목록으로 승인 |
| 문서·fixture | PR4 지오코딩, S2-3 exposure 보고서, S2-4 원본/v0.3 JSON·MD, S3 검증·계획·운영 문서 | 현행 기준은 Juso로 교체하고 기존 실측을 사후에 Juso 결과처럼 고쳐 쓰지 않음. 역사 기록은 구 공급자/대체 문서 링크로 구분. 공개 raw 정리와 Git 이력 재작성은 별개이며 이력 강제 재작성은 범위 밖 |

대상 cache digest: `90c26f4a3b1c7be5f5163102e16c3d2825f83dce659bacc989b4959e84131d7a`. 캐시 목록 전체를 사용자 화면이나 문서에 노출하지 않고 승인용 manifest에서 키·행수·해시로 대조한다.

### 대치동 3곳의 전환 전 기준

| 후보 | 기존 위도, 경도 | PNU | 기존 total / confidence |
| --- | --- | --- | --- |
| a 역삼로460 3층 | 37.5025724504279, 127.057585738094 | 1168010600109120013 | 85.085005 / 90 |
| b 도곡로409 2층 | 37.4973692137569, 127.055167024731 | 1168010600109380022 | 93.372948 / 90 |
| c 역삼로546 덕일빌딩 3층 | 37.5042868910393, 127.062872712855 | 1168010600109670000 | 83.863983 / 85 |

세 좌표는 과거 S2-4에서 해당 PNU 도형 내부였다. **Juso 좌표/포함 여부/점수 차이는 아직 값 없음**이다. 정확한 숫자가 등장하는 추적 파일/행 목록을 inventory에 넣었다. 반올림 좌표·다른 과거 좌표의 계보는 문자열 검색만으로 확정할 수 없으므로 생성 스크립트와 raw manifest를 함께 대조한다. 최초 요청의 오인 좌표와 후속 도형 중심점은 카카오 원응답과 구분한다.

## 4. 새 주소·좌표 계약

1. 서버에서 `addrLinkApi.do`로 도로명·지번·건물명 검색. 후보는 `roadAddrPart1/jibunAddr/bdNm/bdMgtSn/admCd/rnMgtSn/udrtYn/buldMnnm/buldSlno/mtYn/lnbrMnnm/lnbrSlno`를 유지한다. 사용자가 선택하거나 배치에서 원문과 유일하게 일치한 항목만 좌표 조회한다. 정규화는 NFKC/공백만, 도로명·번지 자동 보정/임의 첫 결과 선택 없음.
2. 좌표 요청은 `admCd+rnMgtSn+udrtYn+buldMnnm+buldSlno`. `buld*`는 **건물번호**, PNU의 `lnbr*`는 **지번**으로 혼용하지 않는다. 반환 `bdMgtSn`과 선택 주소의 식별자를 대조하며 다중 출입구/다동이면 임의 평균·첫 점을 쓰지 않는다.
3. `PNU = admCd(10) + (mtYn='1' ? '2' : '1') + lnbrMnnm.padStart(4,'0') + lnbrSlno.padStart(4,'0')`. 산여부0/1을 PNU에 그대로 붙이지 않는다. 본번/부번 범위·19자리·행정구역 코드 검증. `bdMgtSn` 잘라서 PNU라고 가정하지 않는다.
4. 출입구 `entX/entY`는 EPSG:5179. 원좌표/원CRS/조회일/응답 해시를 provenance에 남긴다. Python `pyproj(always_xy=True)`와 PostGIS `ST_Transform`을 독립 대조하고 DB geom은4326. 브라우저는 서버에서 검증한4326만 받으며 기존 exposure RPC는5186, 거리 비교는 geography/5186이다.
5. PNU 도형이 유일한지와 `ST_Covers(geom, point)`를 별도 판정한다. **같은 PNU라도 출입구가 외부이면 불일치로 기록**한다. 경계 최소거리·기존점 이동거리·공급자별 결과를 보고하고 후보 중심점/최근접 건물로 바꾸지 않는다. 3곳 중 미포함 사례가 생기면 현재 포함 조건을 통과했다고 하지 않으며 좌표 기준 변경을 별도 결정한다. PNU 자체가 다른 경우 자동 교체 중단.
6. Juso의 확정적인 검색0건/공개 좌표 미제공에 한해 Vworld를 1회 검토한다. 검색 다중/식별자 불일치, 인증·제한·장애를 폴백으로 숨기지 않는다. 도로명/지번 요청 유형·구·건물번호·PNU를 검증하고 `provider='vworld'`, fallback 사유/호출량을 기록한다. Vworld 저장 조건은 Juso 허용 조건으로 대신하지 않고 A0에서 현행 계약을 대조한다.

## 5. 캐시·제한·접근권한

- `public.geocode_cache(address,provider)`를 유지하고 canonical 주소의 확정 지오코딩 결과만 공유한다. 여러 자동완성 결과를 기존 단일 Point에 덮어쓰지 않는다. 검색 목록은 라이브 응답, 선택된 주소/좌표는 공용 캐시를 활용한다. 사용자 별칭·임대료·검색 이력은 공유 캐시에 넣지 않는다.
- additive migration으로 필요한 Juso 식별자/PNU/원CRS/좌표/조회일/출처를 보존한다. 기존 consumer가 새 컬럼을 몰라도 읽을 수 있게 한다. 성공·확정 실패/애매함과 재시도 가능한 장애를 분리하고, 원천 갱신/명시적 재확인 때 실패 캐시도 갱신 가능하게 한다. 자동 만료 TTL은 두지 않는다.
- DB의 uid별 일100회 제한은 인증 후 검색·선택 좌표 요청에 적용한다. 캐시 hit도 서비스 요청 수에 포함하고 공급자 호출 수는0으로 기록한다. 검색/좌표/Vworld/오류·재시도 수를 구분한다. 기존 건축물 주소 큐 일10건 제한은 별도 유지.
- 좌표 API는 배치+Route Handler 전체가 사용하는 DB 기반 원자적 허가 슬롯으로 직렬 제한한다. 안전 여유를 둔 **600ms 간격(최대9건/임의5초)**, 재시도도 같은 슬롯 사용. 오래된 예약으로 한꺼번에 실행되지 않게 실제 호출 직전에 다시 허가한다. 동시 프로세스 테스트로5초10건 이하를 검증한다. 13,542건 전부 좌표 호출 시 이 간격만 약135분이며 실측 시간이 아닌 하한 추정이다. API 실패/검색/네트워크 시간은 별도다.
- Route Handler `preferredRegion='icn1'`, Node runtime. 한국 사용자·국내 공급자 왕복을 위한 선택이며 Tokyo DB와 같은 리전이라는 뜻은 아니다. 서버 cache hit도 uid 인증/할당량을 통과한다. API 키·사용자 JWT·주소 원문을 URL/오류 로그에 남기지 않는다.
- **공용 캐시 쓰기 신뢰 경계:** A0의 writer는 기존 `/ingest` DB 역할뿐이며 익명/일반 authenticated 직접 INSERT/UPDATE는 금지한다. A의 Route Handler가 인증된 사용자의 JWT만으로 캐시를 덮어쓰게 하면 다른 사용자를 오염시킬 수 있다. A 연결 시 추천은 캐시 쓰기 한정 서버 서명키를 Vault와 Route Handler에 두고, 좁은 RPC가 서명·만료·payload hash·nonce를 검증하는 방식이다. 이는 추가 서버 변수 `GEOCODE_CACHE_WRITE_SECRET` 허용이 필요한 **제안**이며 현재 키2개 규칙을 자동 확대하지 않는다. 대안은 `/ingest`만 쓰고 Route Handler는 라이브 조회/캐시 읽기만 하며 배치가 후속 보충하는 방식이다. Supabase 관리자 키를 Vercel에 추가하지 않는다.

## 6. 구현·전환 순서와 롤백

1. **문서/키/정책 게이트.** 본 계획 승인, 검색/좌표 키 확보, 공급자 실응답·Vworld 조건·원격 저장 위치 적용 범위 확인. A0 시작 때3주소·지번·건물명·산지/부번0·좌표 미제공/인증 오류를 소량 실증한다. 비밀 없는 응답 구조·날짜·상태만 증거에 남긴다.
2. **목록과 기준 고정.** read-only snapshot에서 현 cache/claim/기관/주소 캐시/R2/fixture/candidate 행수·hash·의존관계를 manifest로 고정한다. 기존 프리셋/데이터로 옛 결과 재현을 확인. 승인 전/실행 직전 값이 다르면 manifest를 갱신해 차이를 보고한다.
3. **확장 migration·수집기.** `supabase migration new`로 provider CHECK 확장 및 provenance/제한/전환 상태 구조를 추가한다. 기존 migration 수정 없음. Juso 순수 파서→배치 어댑터→worker/월간 갱신→테스트 순서, 로컬 격리 DB에서 확인하고 코드 WIP 커밋을 남긴다.
4. **shadow 재산출.** 원천 주소 기준 한 번만 호출하고 `(address,provider,input_hash,transform_version)` 단위 claim·응답 journal·완료 상태로 재개한다. 승인 없는 원격 승격 없음. 각 성공/실패/보류 수 합계가 원래 대상 수와 같아야 한다. provider 불명 좌표도 조사대상에 포함. 실패 주소를 이전 카카오 좌표로 채우지 않으며 NULL/사유 후보를 먼저 보고한다.
5. **대조.** §7의 세 단계 점수 대조와 공간/행수 검증을 실행한다. 학원·학교 격자/반경 개수·reference 전체를 새 source fingerprint로 재생성한다. 과거 고정 복원 manifest는 새 manifest로 대체하고 활성 복원 경로가 카카오 산출물을 다시 넣지 않게 한다. 새 raw/R2 게시는 저장 위치 확인 후 수행한다.
6. **승격 전 보고.** 최종 `db push --dry-run`, SQL/digest/갱신·삭제 예정 행수·key 집합, provider별 성공률·호출수·소요·용량,3곳+5셀 대조표, 롤백 명령/검증을 보고하고 원격 적용 승인을 받는다.
7. **승인된 적용.** writer 일시 정지 여부/시간을 실행안에 명시하고 경쟁 업데이트를 방지한다. additive schema→juso cache→기관/주소 캐시→reference/metadata를 일관된 snapshot으로 전환한다. 절반만 바뀐 데이터와 이전 reference로 점수를 만들지 않도록 작업창 또는 검증된 atomic promotion을 사용한다. 단계·manifest hash·행수·소요 시간을 기록하고 실패 시 다음 단계 중단.
8. **검증 후 정리.** 읽기 경로가 juso/vworld만 사용함을 확인한 뒤 승인 manifest의 kakao cache/claims/raw/fixture 의존성을 제거한다. 사용자 후보가 생겼으면 별도 보호 검증 후 처리. `.env`/Actions Kakao 키 제거는 Juso workflow 통과 후 실행 목록으로 보고한다. Git 이력 강제 변경이나 출처 불명 객체 일괄 삭제는 하지 않는다.

롤백은 삭제 전에 검증한 전환 전 snapshot/행수/hash로 로컬 복원 검산한다. 원격 적용 실패 시 새 입력 writer를 멈추고 마지막 일관된 DB snapshot으로 되돌리는 운영 절차를 둔다. 이는 기존 카카오 API 재호출·영구 재사용 승인과 다르며, 임시 보존본의 보관/정리 범위를 최종 manifest에 명시한다. 키 제거/원본 삭제 같은 축소 단계는 확대·이관·검증 후 별도 승인된 목록만 실행한다.

## 7. 좌표·점수 차이 검증

고정: v0.3 수식·가중치, `cluster.p50=3.332204510175204`, upper=`7.070653980704802`(p99.97), 반경800m/학교1000m, 임대료NULL, exposure0.2.2, 무작위5셀 시드20260926. **새 분포로 cluster 상수를 재보정하지 않는다.**

| 단계 | 후보 좌표 | 학원·학교/reference | 목적 |
| --- | --- | --- | --- |
| T0 | 기존 fixture | 기존 snapshot | 기존 v0.3 완전 재현, 공급자 교체 전 기준 |
| T1 | Juso 새 출입구 | 기존 snapshot | 후보 좌표 변경만의 영향. 도형 미포함/다른 PNU는 실패 사유와 함께 표시 |
| T2 | Juso 새 출입구 | Juso로 재산출한 기관 + 같은 원천에 맞는 새 reference | 최종 데이터 전환 효과. T2−T1은 배경 데이터/분포 변경, T2−T0은 전체 변화 |

보고 표: 후보·old/new lat/lng·PNU·building ID·ST_Covers·도형까지 거리·이동거리(m), demand/flow/transit/cluster/exposure/building/environment/rent_efficiency 각각 old/T1/T2/Δ, total/confidence/reasons·순위. NULL을0으로 빼지 않는다. 기준 b>a>c와 결과 순위를 나란히 쓰고 해석·프리셋 조정은 하지 않는다. 링별 가시점 수와 역별 첫 노출 거리도 새 scene과 함께 보관한다.

무작위5셀은 좌표/seed를 그대로 유지하고 T0/T2 총점·신뢰도·결측/0·100 변화를 기록한다. 새 source fingerprint가 old reference와 섞이면 오류/잠정 상태로 노출하고 비교를 억지로 통과시키지 않는다. A/B/C 브라우저 완료 기준은 **A0에서 검증·승인된 새 fixture**와 동일한지이며, 옛85.085005 등과 같아야 한다는 조건으로 새 좌표를 조정하지 않는다.

## 8. 변경 파일·검증

- 코드: `ingest/geocode.py`, `building_on_demand.py`, `commerce_education_database.py`, `refresh_sources.py`, `verify_s2_4.py`, Juso 순수 파서/전환 명령(필요한 작은 모듈), 새 SQL migration. 저장된 raw에는 인증 URL/키 없음.
- CI/설정: `.github/workflows/{address-queue,refresh-source}.yml`, `.env.example`. 테스트에서 live 외부 호출은 금지하고 익명 DB RLS/공유 캐시 위조/claim 경합/동시 제한을 검증한다.
- 문서: 이 계획, `s3-2-plan.md`, `data-sources.md`, `docs/data-attribution.md`, `AGENTS.md` 현행 공급자 안내, `docs/operations/{s3-foundation,address-worker,data-refresh}.md`, `docs/development.md`, 새 검증보고/manifest. 문서·코드 별도 커밋.
- 단위: 주소 정규화·도로명/지번/건물명 다중결과·PNU 산0/1·부번0·자리수·좌표 축 순서·서울 밖·API 오류·오래된 응답·식별자 불일치.
- DB/전환: 기존 row/column/RLS 보존, anon 직접 cache 쓰기 거부, 업서트 재실행,50000행 COPY 단위와 단계별 digest(기존 복원 구조 재사용), 중단/재개, 실패 카운트 합계, provider CHECK 전환, school/academy ID·원문 보존.
- 실제:3곳 Juso 응답·독립 pyproj/PostGIS·PNU/도형·T0/T1/T2와 고정5셀, 카카오 키 없이 월간/주소 워커 실행. `pnpm lint/typecheck/test/build`, `pnpm test:db`. 새 UI/E2E는 A/B/C 범위.

## 9. 사용자가 처리할 단계·승인 항목

1. A0 범위·순서와 **배경 기관/reference까지 전환하는 계획**을 승인한다. 코드는 승인 후 착수한다.
2. Juso **검색 API와 검색API(좌표)**를 각각 신청해 `JUSO_API_KEY`/`JUSO_COORD_API_KEY`로 `.env`에 넣고 완료만 알린다. 키를 채팅/문서에 보내지 않는다. A 서버 배포 때 Vercel의 서버 변수로 등록한다. 사용자 Vworld 폴백에는 기존 `VWORLD_API_KEY`와 등록 도메인 설정도 서버 전용으로 필요하며, 배포 전 필요한 변수 이름만 확정해 안내한다. `KAKAO_REST_API_KEY`는 Vercel에 등록하지 않는다.
3. 도움센터에 API 출입구 좌표의 **Tokyo Supabase·R2 저장/백업·해외 CI artifact 적용 범위**를 확인한다. 해외 저장 제한이 현 경로에 적용되면 국내 저장 구성 또는 허용 범위를 별도 결정한다. 지금 DB 리전/요금제를 바꾸지 않는다.
4. 공용 캐시 서버 writer는 §5의 서명키 방식(추천) 또는 배치 전용 writer 중 A 연결 전에 결정한다. 이는 uid별 캐시 폐기를 다시 묻는 것이 아니라 공용 데이터 위조를 막는 쓰기 권한 결정이다.
5. 원격 전환은 실제 최종 dry-run·manifest·점수 대조 후 승인한다. Juso 결과가 같은 PNU 도형 밖이면 좌표 처리 기준도 그 실제 표를 보고 결정한다.

이번 문서 작성에서는 로컬/원격 SELECT 및 공개 문서 조회만 했다. 새 외부 주소 조회·배치 실행·migration·원격/R2 데이터 삭제·Secrets 변경·Vercel 변경은 하지 않았다.
