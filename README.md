# 원자력발전소 실시간 온배수 현황

공공데이터포털의 「한국수력원자력(주)_원자력발전소 실시간 온배수 현황」 API 데이터를 본부별(월성·고리·한빛·한울)로 보여주는 웹앱입니다. 취수구·배수구의 수온과 염분, 두 수온의 차이, 최근 24시간·7일·30일 추이를 제공합니다.

## 데이터 출처와 표시 원칙

- 출처: 공공데이터포털(data.go.kr) 「한국수력원자력(주)_원자력발전소 실시간 온배수 현황」
- 수치는 원천 데이터를 가공하지 않고 표시합니다. 온도차는 화면에서 배수구 수온에서 취수구 수온을 뺀 값입니다.
- 항목 시각은 한국표준시(KST)이며, 시각이 **60분 넘게** 갱신되지 않은 항목은 값을 표시하지 않고 "수신 중단"으로 표기합니다.
- 추이 차트는 24시간은 수집된 원본 값, 7일·30일은 1시간 평균입니다. 값이 수신·저장되지 않은 구간은 선을 이어 그리지 않습니다.
- 수집은 이 저장소가 가동된 시점부터 시작되므로 그 이전 기간의 이력은 없습니다.
- 정상/이상 같은 판단이나 기준선은 표시하지 않습니다.
- 수치의 정확성과 최신성은 원천 데이터에 따릅니다. 수온·염분의 단위는 원천 데이터에 표기되어 있지 않습니다.

## 앱으로 설치하기

별도 앱스토어 없이 브라우저에서 홈 화면에 추가해 앱처럼 쓸 수 있습니다(PWA). 주소창 없이 전체 화면으로 열리고, 네트워크가 없을 때는 마지막으로 저장된 값을 보여줍니다. 저장된 값도 시각이 60분을 넘으면 "수신 중단"으로 표시되며 최신 값처럼 보이지 않습니다.

| 환경 | 방법 |
|---|---|
| Android Chrome·삼성 인터넷 | 화면 하단의 **앱으로 설치** 버튼 또는 브라우저 메뉴(⋮)의 "앱 설치"/"홈 화면에 추가" |
| iPhone·iPad Safari | 공유 버튼 → **홈 화면에 추가** |
| 카카오톡·네이버 등 앱 안에서 연 경우 | 설치 불가. 주소를 Chrome·삼성 인터넷·Safari 등 기본 브라우저에서 다시 여세요 |

HTTPS 주소(GitHub Pages)에서만 설치할 수 있습니다. 값과 화면 코드는 항상 네트워크에서 먼저 받고, 네트워크가 안 될 때만 저장본을 씁니다. 아이콘을 바꾸려면 `node scripts/make_icons.js`로 다시 만들어 커밋하세요.

## 구성

```
공공데이터포털 API
      │  10분마다 호출 (GitHub Actions: collect.yml)
      ▼
scripts/collect.py ──▶ scripts/history.py ──▶ 안전 검사 ──▶ data 브랜치(매번 커밋 1개로 덮어씀)
                                                   data/YYYY-MM-DD.csv (누적 이력), latest.json, history.json
                                                        │ raw.githubusercontent.com
                                                        ▼
web/ ──(화면 코드가 바뀔 때만)──▶ GitHub Pages ──▶ 브라우저가 위 data 파일을 직접 읽음
```

화면(Pages)과 측정 데이터(data 브랜치)를 분리했습니다. 10분마다 같은 커밋으로 Pages 를 다시 배포하면 배포가 "성공"으로 끝나고도 사이트가 갱신되지 않는 일이 반복돼(2026-11-05, 11-10) 값이 오래된 채로 보였기 때문입니다.

| 경로 | 설명 |
|---|---|
| `web/` | 정적 화면(빌드 도구·외부 라이브러리 없음). `logic.js`(순수 함수), `chart.js`(SVG 차트), `trend.js`(추이 영역), `app.js`(화면), `sw.js`·`manifest.webmanifest`·`icons/`(설치형 웹앱) |
| `scripts/collect.py` | 4개 본부 수집기. 중복 행과 오래된 값은 이력에 저장하지 않음 |
| `scripts/history.py` | 추이용 `history.json`(원본 48시간 + 1시간 평균 30일) 생성, 오래된 CSV(120일 초과) 정리 |
| `scripts/check_data_dir.py` | data 브랜치를 덮어쓰기 전 안전 검사(CSV 행 수가 줄었는지, JSON 이 올바른지) |
| `scripts/build_site.py` | 배포용 사이트(`web/` 복사) 생성. 측정 데이터는 포함하지 않음 |
| `scripts/make_icons.js` | 앱 아이콘(PNG) 생성기(Playwright 필요, 아이콘을 바꿀 때만 실행) |
| `scripts/verify_api.py` | API 응답 형식 확인용 수동 실행 스크립트 |
| `scripts/verify_live.py` | 화면 배포 직후 공개 사이트의 `sw.js` 가 배포본과 같아질 때까지 확인(150초 안에 안 되면 실행 실패로 알림) |
| `scripts/probe_stale.py` | 수신 중단 진단용 수동 스크립트(`Probe stale` 워크플로) |
| `.github/workflows/collect.yml` | 수집(10분 주기) → 이력 생성 → 안전 검사 → data 브랜치 게시 |
| `.github/workflows/deploy-site.yml` | `web/` 가 바뀔 때만 Pages 배포 후 공개 사이트 확인 |
| `.github/workflows/verify-api.yml` | API 확인용 수동 워크플로 |
| `tests/` | 단위 테스트(Python·Node)와 실제 응답을 바탕으로 한 픽스처 |

## 데이터 파일

측정 데이터는 `data` 브랜치에 있으며 화면이 아래 주소를 직접 읽습니다.

- `latest.json` — 본부별 최신 값과 수신 상태
- `history.json` — 추이용 이력(원본 48시간 + 1시간 평균 30일)
- `data/YYYY-MM-DD.csv` — 일별 누적 원본 값(최근 120일 보관)

주소 형식: `https://raw.githubusercontent.com/<사용자>/<저장소>/data/latest.json`. `data` 브랜치는 수집할 때마다 커밋 1개로 덮어쓰므로 커밋 이력으로 과거 값을 찾을 수 없고, 과거 값은 CSV 파일로만 남습니다. 데이터의 이용 조건은 공공데이터포털에 게시된 해당 API의 이용허락범위를 따릅니다.

## 수신 중단 진단

API 가 오류 없이 **옛 시각의 값**을 돌려주는 경우가 있습니다(예: 한울 2026-11-07 13:00 이후, 고리 2026-07-07 이후). 수집기는 모든 항목이 멈춘 본부를 발견하면(최근 7일 이내) 호출 주소·헤더를 바꾼 요청으로 한 번 더 조회해, 원천 쪽 정지인지 중간 캐시인지 판정하고 `latest.json`의 `probe`와 실행 로그(`[진단]`)에 남깁니다. 같은 상태의 진단은 60분간 재사용합니다. 수동으로 확인하려면 Actions 탭의 `Probe stale`을 실행하세요.

## 설정

1. **인증키:** 공공데이터포털에서 발급받은 **Decoding 인증키**를 저장소 Secret `DATA_GO_KR_SERVICE_KEY`로 등록합니다 (Settings → Secrets and variables → Actions). 키는 코드·이슈·로그에 남기지 마세요.
2. **수집 주기:** `collect.yml`의 `schedule`은 GitHub 사정으로 지연·누락될 수 있습니다. 안정적인 주기가 필요하면 외부 스케줄러가 `workflow_dispatch` API(`POST /repos/{owner}/{repo}/actions/workflows/collect.yml/dispatches`)를 호출하게 할 수 있습니다. 이때 Actions 쓰기 권한만 가진 저장소 한정 토큰을 쓰고 만료일을 관리하세요.
3. **Pages 배포:** Settings → Pages → Source를 `GitHub Actions`로 두고, 저장소 변수 `PAGES_ENABLED`를 `true`로 설정하면 `web/` 변경을 푸시할 때 자동 배포됩니다(수집 때는 배포하지 않습니다).

## 테스트

```bash
python3 -I -m unittest discover -s tests   # 수집기·이력 빌드
node --test tests/logic.test.js            # 화면 로직
```

로컬에서 화면을 보려면 `python3 scripts/build_site.py --out site` 후 `python3 -m http.server --directory site` 를 실행합니다. 데이터는 기본적으로 `data` 브랜치(raw 주소)에서 읽으며, 다른 주소를 쓰려면 페이지 로드 전에 `window.NPP_DATA_BASE` 를 지정합니다.

`tests/synthetic_history.py`는 화면 점검용 합성 이력 생성기이며 실제 데이터가 아닙니다.
