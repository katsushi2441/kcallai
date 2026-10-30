"""取り込み → 判定 → 日報 → （AI）→ 通知 の一連。コマンドと画面の「今すぐ実行」が同じものを呼ぶ。"""
from . import ai as ai_mod, notify, plaud, report, rules, tobila
from .util import parse_date


def ingest(cfg, log=print):
    out = {}
    for name, fn in (("トビラフォン", tobila.ingest), ("PLAUD", plaud.ingest)):
        try:
            r = fn(cfg)
        except Exception as ex:  # noqa: 取り込みの片方が落ちても、もう片方と分析は続ける
            r = dict(error=str(ex))
        out[name] = r
        if "error" in r:
            log(f"取り込み {name}: 失敗（{r['error']}）")
        else:
            log(f"取り込み {name}: 新しく {r.get('added', 0)}件" + (f"（{r['note']}）" if r.get("note") else ""))
    return out


def analyze(cfg, date=None, use_ai=None, log=print):
    d = parse_date(date)
    n = rules.analyze_all(cfg)
    s, findings = rules.summarize(cfg, d)
    md = report.markdown(cfg, s, findings)
    text = None
    want_ai = cfg.ai.get("enabled") if use_ai is None else use_ai
    if want_ai:
        try:
            text = ai_mod.summarize(cfg, md, force=True)
        except Exception as ex:  # noqa: AI が落ちても日報は出す
            log(f"AI の要点は作れませんでした: {ex}")
    report.write_all(cfg, s, findings, text)
    log(f"判定 {n}件 → {s['date']} の日報（指摘 {len(findings)}件{'・AI の要点あり' if text else ''}）")
    return s, findings, text


def send(cfg, s, findings, text, log=print):
    url = (cfg.web or {}).get("public_url")
    msg = report.short_text(cfg, s, findings, text, url)
    res = {}
    for name, fn in (("LINE", lambda: notify.line_send(cfg, msg)), ("メール", lambda: notify.email_send(cfg, f"電話と現場の日報 {s['date']}", report.markdown(cfg, s, findings, text)))):
        try:
            r = fn()
            res[name] = "送信" if r else "無効"
        except Exception as ex:  # noqa
            res[name] = f"失敗: {ex}"
        log(f"通知 {name}: {res[name]}")
    return res


def run(cfg, date=None, use_ai=None, do_notify=True, log=print):
    ingest(cfg, log)
    s, findings, text = analyze(cfg, date, use_ai, log)
    if do_notify:
        send(cfg, s, findings, text, log)
    return s, findings, text
