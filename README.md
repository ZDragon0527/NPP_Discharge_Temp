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

## 구성

```
공공데이터포털 API
      │  10분마다 호출 (GitHub Actions: collect.yml)
      ▼
scripts/collect.py ──▶ data 브랜치: data/YYYY-MM-DD.csv (누적 이력), latest.json (최신값)
      │
      ▼
scripts/build_site.py ──▶ site/ (web/ + latest.json + history.json) ──▶ GitHub Pages
```

| 경로 | 설명 |
|---|---|
| `web/` | 정적 화면(빌드 도구·외부 라이브러리 없음). `logic.js`(순수 함수), `chart.js`(SVG 차트), `trend.js`(추이 영역), `app.js`(화면) |
| `scripts/collect.py` | 4개 본부 수집기. 중복 행과 오래된 값은 이력에 저장하지 않음 |
| `scripts/build_site.py` | 배포용 사이트와 추이용 `history.json`(최근 30일) 생성 |
| `scripts/verify_api.py` | API 응답 형식 확인용 수동 실행 스크립트 |
| `.github/workflows/collect.yml` | 수집(10분 주기) 후 선택적으로 Pages 배포 |
| `.github/workflows/verify-api.yml` | API 확인용 수동 워크플로 |
| `tests/` | 단위 테스트(Python·Node)와 실제 응답을 바탕으로 한 픽스처 |

## 설정

1. **인증키:** 공공데이터포털에서 발급받은 **Decoding 인증키**를 저장소 Secret `DATA_GO_KR_SERVICE_KEY`로 등록합니다 (Settings → Secrets and variables → Actions). 키는 코드·이슈·로그에 남기지 마세요.
2. **수집 주기:** `collect.yml`의 `schedule`은 GitHub 사정으로 지연·누락될 수 있습니다. 안정적인 주기가 필요하면 외부 스케줄러가 `workflow_dispatch` API(`POST /repos/{owner}/{repo}/actions/workflows/collect.yml/dispatches`)를 호출하게 할 수 있습니다. 이때 Actions 쓰기 권한만 가진 저장소 한정 토큰을 쓰고 만료일을 관리하세요.
3. **Pages 배포:** Settings → Pages → Source를 `GitHub Actions`로 두고, 저장소 변수 `PAGES_ENABLED`를 `true`로 설정하면 수집 직후 자동 배포됩니다.

## 테스트

```bash
python3 -I -m unittest discover -s tests   # 수집기·이력 빌드
node --test tests/logic.test.js            # 화면 로직
```

로컬에서 화면을 보려면 `data` 브랜치의 `latest.json`과 `data/*.csv`를 한 폴더에 두고 `python3 scripts/build_site.py --data-dir <폴더> --out site` 실행 후 `python3 -m http.server --directory site`를 사용합니다.

`tests/synthetic_history.py`는 화면 점검용 합성 이력 생성기이며 실제 데이터가 아닙니다.
