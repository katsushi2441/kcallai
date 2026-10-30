#!/usr/bin/env python3
"""画面を実際の端末幅で撮り、横のはみ出し（scrollWidth）を数字で確かめる。使い捨てのブラウザで開く。

  /usr/bin/python3 scripts/shot.py <ベースURL> <出力先>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = {"dashboard": "", "calls": "calls", "call": "call?id=mail%3A%3Csample-1005%40kcallai.invalid%3E", "lost": "lost", "staff": "staff",
         "visits": "visits", "visit": "visit?id=plaud%3Asample002", "report": "report", "settings": "settings"}
WIDTHS = {"d": 1280, "m": 390, "s": 320}


def main():
    base = sys.argv[1].rstrip("/") + "/"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "outputs/shots")
    out.mkdir(parents=True, exist_ok=True)
    bad = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, path in PAGES.items():
            for tag, w in WIDTHS.items():
                pg = b.new_page(viewport={"width": w, "height": 900}, device_scale_factor=1)
                pg.goto(base + path, wait_until="networkidle")
                sw = pg.evaluate("document.documentElement.scrollWidth")
                over = pg.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect();
                    return r.right > window.innerWidth + 1 && !e.closest('.tw') && getComputedStyle(e).position !== 'fixed'; }).slice(0, 5).map(e => e.tagName + '.' + e.className)""")
                if tag != "s":
                    pg.screenshot(path=str(out / f"{name}_{tag}.png"), full_page=True)
                ok = sw <= w
                bad += 0 if ok else 1
                print(f"{'OK ' if ok else 'NG '} {name:9s} {w:4d}px scrollWidth={sw} {'' if ok else over}")
                pg.close()
        b.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
