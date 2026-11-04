#!/usr/bin/env node
/* 앱 아이콘(PNG) 생성기. 사용: node scripts/make_icons.js [출력 폴더(기본 web/icons)]
 * Playwright(Chromium)로 SVG 를 PNG 로 렌더링한다. 아이콘을 바꿀 때만 다시 실행하고 결과물(PNG)은 커밋한다.
 *   icon.svg                SVG 원본(투명 모서리, 파비콘 겸용)
 *   icon-192.png / -512.png 일반 아이콘(모서리 둥글고 바깥은 투명)
 *   icon-maskable-512.png   마스크 가능 아이콘(꽉 찬 배경 + 안전 영역 안쪽 그림)
 *   apple-touch-icon.png    iOS 홈 화면용 180px(꽉 찬 배경, iOS 가 모서리를 깎음)
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BLUE = '#0b6e99';
// 물결 두 줄(32x32 좌표). 파비콘과 같은 모양.
const WAVES = '<path d="M5 12c4-3 6 3 11 0s7 3 11 0M5 20c4-3 6 3 11 0s7 3 11 0" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>';

function svg(size, { rounded, scale }) {
  const rect = rounded
    ? `<rect width="32" height="32" rx="7" fill="${BLUE}"/>`
    : `<rect width="32" height="32" fill="${BLUE}"/>`;
  const art = scale === 1 ? WAVES : `<g transform="translate(16 16) scale(${scale}) translate(-16 -16)">${WAVES}</g>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">${rect}${art}</svg>`;
}

async function main() {
  const out = process.argv[2] || path.join(__dirname, '..', 'web', 'icons');
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'icon.svg'), svg(512, { rounded: true, scale: 1 }) + '\n');

  const targets = [
    ['icon-192.png', 192, { rounded: true, scale: 1 }, true],
    ['icon-512.png', 512, { rounded: true, scale: 1 }, true],
    ['icon-maskable-512.png', 512, { rounded: false, scale: 0.85 }, false],  // 안전 영역(중앙 80%) 안에 그림을 둔다
    ['apple-touch-icon.png', 180, { rounded: false, scale: 1 }, false]
  ];
  const browser = await chromium.launch();
  for (const [name, size, opts, transparent] of targets) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await page.setContent(`<body style="margin:0;background:transparent">${svg(size, opts)}</body>`);
    await page.screenshot({ path: path.join(out, name), omitBackground: transparent, clip: { x: 0, y: 0, width: size, height: size } });
    await page.close();
    console.log('생성:', name, `${size}x${size}`);
  }
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
