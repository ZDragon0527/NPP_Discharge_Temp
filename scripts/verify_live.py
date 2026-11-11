#!/usr/bin/env python3
"""화면 배포 직후 공개 사이트가 실제로 갱신됐는지 확인 (표준 라이브러리만 사용).

방금 배포한 파일(--expected)과 공개 사이트의 같은 파일(--path)의 내용(sha256)이 같아질 때까지
--interval 초마다 다시 읽는다. --timeout 초 안에 같아지지 않으면 실패(종료코드 1)로 끝내 워크플로를 실패로 표시한다(알림 메일).

배경: GitHub Pages 가 같은 커밋으로 반복 배포한 뒤 배포를 "성공"으로 받고도 사이트에 반영하지 않는 일이 있었다
(2026-11-05, 11-10). 배포 단계의 성공만으로는 알 수 없어 공개 사이트를 직접 다시 읽는다.
측정 데이터는 사이트가 아니라 data 브랜치에서 제공하므로 여기서는 화면 코드(sw.js)만 비교한다.

사용: python3 scripts/verify_live.py --url https://<사용자>.github.io/<저장소>/ --path sw.js --expected site/sw.js
"""
import argparse
import hashlib
import random
import sys
import time
import urllib.error
import urllib.request


def sha12(data):
    return hashlib.sha256(data).hexdigest()[:12]


def fetch_live(base_url, path, timeout=20):
    """공개 사이트의 파일 내용을 받아 (bytes, None) 반환. 실패하면 (None, 사유)."""
    url = base_url.rstrip("/") + "/" + path.lstrip("/") + f"?cb={int(time.time())}{random.randint(0, 9999)}"
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "npp-discharge-verify-live/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"연결 실패: {getattr(e, 'reason', e)}"


def verify(base_url, path, expected, timeout=150, interval=15,
           fetch=fetch_live, sleep=time.sleep, clock=time.monotonic, log=print):
    """공개 사이트의 파일이 expected 와 같아지면 True. 시간 안에 같아지지 않으면 False."""
    want = sha12(expected)
    deadline = clock() + timeout
    attempt = 0
    last = "응답 없음"
    while True:
        attempt += 1
        live, err = fetch(base_url, path)
        if live is None:
            last = err
            log(f"[{attempt}] 공개 사이트 {path} 읽기 실패: {err}")
        else:
            got = sha12(live)
            last = f"{path}: 공개 사이트 {got} / 배포본 {want}"
            if got == want:
                log(f"[{attempt}] {last} → 일치")
                log("통과: 공개 사이트가 방금 배포한 내용으로 갱신됐다.")
                return True
            log(f"[{attempt}] {last} → 불일치")
        if clock() >= deadline:
            break
        sleep(interval)
    log(f"::error::배포는 성공으로 보고됐지만 공개 사이트에 반영되지 않았습니다. {last}")
    log("같은 커밋으로 반복 배포하면 막힐 수 있다. 화면 코드와 무관한 빈 커밋을 하나 푸시해 배포 식별자를 바꾸면 풀린 적이 있다.")
    return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="공개 사이트 주소(예: https://<사용자>.github.io/<저장소>/)")
    ap.add_argument("--path", required=True, help="비교할 파일의 사이트 안 경로(예: sw.js)")
    ap.add_argument("--expected", required=True, help="방금 배포한 파일의 로컬 경로")
    ap.add_argument("--timeout", type=int, default=150)
    ap.add_argument("--interval", type=int, default=15)
    args = ap.parse_args(argv)
    try:
        with open(args.expected, "rb") as f:
            expected = f.read()
    except OSError as e:
        print(f"오류: 배포본 파일을 읽을 수 없다: {e}")
        return 1
    ok = verify(args.url, args.path, expected, args.timeout, args.interval)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
