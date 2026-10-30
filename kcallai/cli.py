import argparse
import json
import os
import sys

from . import __version__, pipeline, sample, tobila
from .config import EXAMPLE, Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kcallai", description="Kurage 通話AI分析 — 電話と現場の会話から成約・失注・応対の抜けを毎朝まとめる")
    ap.add_argument("-c", "--config", default=os.environ.get("KCALLAI_CONFIG", "kcallai.json"))
    ap.add_argument("--version", action="version", version=__version__)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("init", help="設定ファイルのひな形を書く")
    p = sp.add_parser("sample", help="見本データ（架空の水まわり修理会社）を作る")
    p.add_argument("--end", default=None, help="最後の日（既定は昨日）")
    p.add_argument("--days", type=int, default=14)
    p = sp.add_parser("arrive", help="見本の新着メールを n 通「いま届いた」ことにする（デモ用）")
    p.add_argument("-n", type=int, default=1)
    sp.add_parser("ingest", help="取り込み（トビラフォンの通知メール・PLAUD）")
    p = sp.add_parser("import-download", help="トビラフォンの一括ダウンロードのテキストを取り込む")
    p.add_argument("path")
    p = sp.add_parser("analyze", help="判定して日報を作る")
    p.add_argument("--date", default=None)
    p.add_argument("--ai", action="store_true", help="AI の要点を付ける（設定で無効でも）")
    p = sp.add_parser("notify", help="日報を LINE・メールで送る")
    p.add_argument("--date", default=None)
    p.add_argument("--ai", action="store_true")
    p = sp.add_parser("run", help="取り込み → 判定 → 日報 → 通知（毎朝これを cron で）")
    p.add_argument("--date", default=None)
    p.add_argument("--ai", action="store_true")
    p.add_argument("--no-notify", action="store_true")
    p = sp.add_parser("web", help="画面を開く")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "init":
        if os.path.exists(a.config):
            print(f"{a.config} はすでにあります", file=sys.stderr)
            return 1
        with open(a.config, "w", encoding="utf-8") as f:
            json.dump(EXAMPLE, f, ensure_ascii=False, indent=2)
        print(f"{a.config} を書きました。社名・取り込み元・通知先を書き換えてください。")
        return 0
    cfg = Config(a.config)
    os.makedirs(cfg.outputs, exist_ok=True)
    if a.cmd == "sample":
        from .util import parse_date
        sd = cfg.path_of(cfg.raw.get("sample_dir", "sample"))
        r = sample.generate(sd, parse_date(a.end) if a.end else None, a.days)
        print(f"見本データを {sd} に作りました: {r}")
        return 0
    if a.cmd == "arrive":
        sd = cfg.path_of(cfg.raw.get("sample_dir", "sample"))
        moved = sample.arrive(os.path.join(sd, "pending"), cfg.path_of(cfg.tobila.get("dir", "sample/tobila")), a.n)
        print(f"届けた見本メール: {moved or 'なし（pending が空です。sample を作り直してください）'}")
        return 0
    if a.cmd == "ingest":
        pipeline.ingest(cfg)
        return 0
    if a.cmd == "import-download":
        print(tobila.import_download(cfg, a.path))
        return 0
    if a.cmd == "analyze":
        pipeline.analyze(cfg, a.date, True if a.ai else None)
        return 0
    if a.cmd == "notify":
        s, f, t = pipeline.analyze(cfg, a.date, True if a.ai else None)
        res = pipeline.send(cfg, s, f, t)
        return 0 if not any(str(v).startswith("失敗") for v in res.values()) else 1
    if a.cmd == "run":
        pipeline.run(cfg, a.date, True if a.ai else None, not a.no_notify)
        return 0
    if a.cmd == "web":
        from .web import serve
        w = cfg.web
        serve(cfg, a.host or w.get("host", "127.0.0.1"), a.port or int(w.get("port", 8080)))
        return 0
    return 1
