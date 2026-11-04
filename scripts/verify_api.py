#!/usr/bin/env python3
"""온배수 현황 API 검증 스크립트 (표준 라이브러리만 사용).

확인 목적
  1. 실행 환경(GitHub 러너)에서 apis.data.go.kr 호출이 되는가 (해외 IP 차단 여부)
  2. 인증키(Decoding 키를 코드에서 1회 인코딩) 방식이 맞는가
  3. 본부 코드 파라미터명과 응답 필드 구조는 무엇인가

주의: 이 저장소는 공개 저장소이므로 로그가 공개된다.
  - 인증키와 그 인코딩 변형은 ::add-mask:: 로 등록해 로그에서 가린다.
  - 키가 들어간 요청 URL은 절대 출력하지 않는다.
"""
import hashlib
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://apis.data.go.kr/B552041/inoutwater/getinoutwater"
PLANTS = {"WS": "월성", "KR": "고리", "YK": "한빛", "UJ": "한울"}
# 본부 코드 파라미터명은 아직 확인되지 않아 후보를 순서대로 시험한다.
PARAM_CANDIDATES = ["plantCode", "genName", "genCode", "plant", "plantcd", "powerPlant", "siteCd", "hqCode"]
TIMEOUT = 20
BODY_PREVIEW = 1500

summary_rows = []


def mask_key(key):
    variants = {key, urllib.parse.quote(key, safe=""), urllib.parse.quote_plus(key),
                urllib.parse.unquote(key)}
    for v in variants:
        if v:
            print(f"::add-mask::{v}")
    return [v for v in variants if v]


def scrub(text, secrets):
    for s in secrets:
        text = text.replace(s, "***")
    return text


def fetch(key, secrets, extra):
    """GET 한 번. (분류, HTTP 상태, 본문) 반환. 키가 든 URL은 출력하지 않는다."""
    params = [("serviceKey", key)] + list(extra.items())
    url = BASE + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={"User-Agent": "npp-discharge-verify/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return "ok", resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return "http_error", e.code, body
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        reason = scrub(str(getattr(e, "reason", e)), secrets)
        return "connection_error", 0, reason


def tag(body, name):
    m = re.search(rf"<{name}>(.*?)</{name}>", body, re.S)
    return m.group(1).strip() if m else ""


def describe(label, kind, status, body, secrets):
    body = scrub(body, secrets)
    code, msg = tag(body, "resultCode"), tag(body, "resultMsg")
    items = len(re.findall(r"<item[ >]", body))
    digest = hashlib.sha1(body.encode()).hexdigest()[:8]
    print(f"[{label}] 분류={kind} HTTP={status} resultCode={code or '-'} "
          f"resultMsg={msg or '-'} item수={items} 본문길이={len(body)} 해시={digest}")
    summary_rows.append((label, kind, status, code or "-", msg or "-", items))
    return body, items


def main():
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "").strip()
    if not key:
        print("오류: 환경변수 DATA_GO_KR_SERVICE_KEY 가 비어 있다. "
              "저장소 Settings → Secrets and variables → Actions 에 등록했는지 확인할 것.")
        return 1
    secrets = mask_key(key)
    print(f"키 길이={len(key)}자, '%' 포함={'%' in key} "
          "(% 가 있으면 Encoding 키일 가능성이 높다. Decoding 키를 사용할 것)")

    # 실행 환경의 국가 정보 (해외 IP 차단 가능성 판단용). 실패해도 계속 진행한다.
    try:
        with urllib.request.urlopen("https://ipinfo.io/country", timeout=10) as r:
            print("러너 국가 코드:", r.read().decode().strip())
    except Exception as e:  # noqa: BLE001
        print("러너 국가 조회 실패:", type(e).__name__)

    # 1) 기준선: 키만으로 호출
    kind, status, body = fetch(key, secrets, {})
    body, base_items = describe("기준선(키만)", kind, status, body, secrets)
    print("--- 응답 본문 미리보기 ---")
    print(body[:BODY_PREVIEW])
    print("--------------------------")
    if kind == "connection_error":
        print("연결 자체가 실패했다. 해외 IP 차단 또는 네트워크 문제 가능성. 이후 시험을 중단한다.")
        write_summary()
        return 0
    time.sleep(1)

    # 2) 페이지 파라미터 포함
    kind, status, body = fetch(key, secrets, {"pageNo": "1", "numOfRows": "10"})
    describe("기준선(+pageNo/numOfRows)", kind, status, body, secrets)
    time.sleep(1)

    # 3) 본부 코드 파라미터명 후보 시험 (값: WS)
    found = None
    for name in PARAM_CANDIDATES:
        kind, status, body = fetch(key, secrets, {name: "WS", "pageNo": "1", "numOfRows": "10"})
        body, items = describe(f"후보 {name}=WS", kind, status, body, secrets)
        if items > 0 and found is None:
            found = name
            print(f"--- {name} 응답 미리보기 ---")
            print(body[:BODY_PREVIEW])
            print("--------------------------")
        time.sleep(1)

    # 4) 4개 본부 시험
    param = found or "(미확정)"
    print(f"본부 코드 파라미터 후보: {param}")
    if found:
        for code, name in PLANTS.items():
            kind, status, body = fetch(key, secrets, {found: code, "pageNo": "1", "numOfRows": "10"})
            describe(f"{name}({code})", kind, status, body, secrets)
            time.sleep(1)
    else:
        print("item 이 반환된 후보가 없다. 위 resultMsg 로 올바른 파라미터명을 추정해야 한다.")

    write_summary()
    return 0


def write_summary():
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## API 검증 결과", "", "| 시험 | 분류 | HTTP | resultCode | resultMsg | item 수 |",
             "|---|---|---|---|---|---|"]
    for r in summary_rows:
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
