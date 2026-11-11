#!/usr/bin/env python3
"""GitHub Pages 배포용 사이트 폴더를 만든다 (표준 라이브러리만 사용).

  web/  →  <out>/   (정적 화면: html·css·js·아이콘·서비스 워커·매니페스트)

측정 데이터(latest.json·history.json)는 사이트에 넣지 않는다.
화면이 저장소의 data 브랜치에서 직접 읽는다(raw.githubusercontent.com).
이유: 같은 커밋으로 10분마다 Pages 를 다시 배포하면 배포가 "성공"으로 끝나고도 사이트에 반영되지 않는 일이
반복돼(2026-11-05, 11-10) 값이 오래된 채로 보였다. Pages 는 화면 코드가 바뀔 때만 배포한다.
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(out, web_dir=None):
    web_dir = web_dir or os.path.join(ROOT, "web")
    if not os.path.isfile(os.path.join(web_dir, "index.html")):
        raise FileNotFoundError(f"web 폴더에 index.html 이 없다: {web_dir}")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(web_dir, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site", help="생성할 사이트 디렉터리")
    args = ap.parse_args(argv)
    try:
        out = build(args.out)
    except FileNotFoundError as e:
        print(f"오류: {e}")
        return 1
    count = sum(len(files) for _, _, files in os.walk(out))
    print(f"사이트 생성 완료: {out} (파일 {count}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
