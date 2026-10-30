"""日報。Markdown（全文）・LINE 用の短文・HTML（画面と単体の両方で使う本文）。"""
import html
import os

from .util import dump_json, ensure_dir

SEV_LABEL = {"high": "重要", "mid": "注意", "low": "参考"}
e = html.escape


def _diff(cur, prev):
    if not prev:
        return ""
    d = cur - prev
    return f"（前の期間 {prev}件、{'+' if d >= 0 else ''}{d}）"


def markdown(cfg, s, findings, ai=None):
    c, p, d = s["cur"], s["prev"], s["day"]
    L = [f"# 電話と現場の日報 {s['date']}", ""]
    if s.get("sample"):
        L += ["※ 見本データです（当社が作った架空のデータ）", ""]
    if ai:
        L += ["## AI の要点", "", ai, ""]
    L += [f"## {s['date']} の電話", "",
          f"- 着信 {d['total']}件（成約 {d['成約']}・失注 {d['失注']}・検討 {d['検討']}・不明 {d['不明']}・不在 {d['不在']}・留守電 {d['留守電']}・営業電話 {d['営業電話']}）", ""]
    L += [f"## 直近{s['days']}日（{s['d_from']}〜{s['date']}）", "",
          f"- 着信 {c['total']}件{_diff(c['total'], p['total'])}",
          f"- 成約 {c['成約']}件{_diff(c['成約'], p['成約'])}・成約率 {c['win_rate'] * 100:.0f}%（前の期間 {p['win_rate'] * 100:.0f}%）",
          f"- 失注 {c['失注']}件・検討 {c['検討']}件・不在 {c['不在']}件・留守電 {c['留守電']}件・営業電話 {c['営業電話']}件"]
    if s["reasons"]:
        L.append("- 失注・検討の理由: " + "、".join(f"{k} {v}件" for k, v in s["reasons"]))
    v = s["visits"]
    if v["total"]:
        L.append(f"- 現場の会話 {v['total']}件（成約 {v['won']}・失注 {v['lost']}・金額トラブルの兆し {v['trouble']}）")
    L += ["", "## 指摘", ""]
    if not findings:
        L.append("指摘はありません。")
    for f in findings:
        L += [f"### [{SEV_LABEL[f['severity']]}] {f['title']}", "", f["detail"]]
        if f.get("suggestion"):
            L.append(f"→ {f['suggestion']}")
        L.append("")
    if s["staff"]:
        L += ["## 担当者別", "", "| 担当 | 件数 | 成約率 | 料金の目安 | 到着の時刻 | 名乗り |", "|---|---:|---:|---:|---:|---:|"]
        for r in s["staff"]:
            ck = r["checks"]
            f_ = lambda k: f"{ck[k][0]}/{ck[k][1]}" if ck.get(k) and ck[k][1] else "-"
            L.append(f"| {r['staff']} | {r['calls']} | {r['win_rate'] * 100:.0f}% | {f_('料金の目安')} | {f_('到着の時刻')} | {f_('名乗り')} |")
    L += ["", "数字は通知メールと現場の録音の文字起こしから、決まった言葉で数えたものです。AI の要点はその言い換えです。"]
    return "\n".join(L) + "\n"


def short_text(cfg, s, findings, ai=None, url=None):
    d, c = s["day"], s["cur"]
    L = []
    if s.get("sample"):
        L.append("【見本データ】")
    L.append(f"{s['date']} の電話 {d['total']}件（成約{d['成約']}・失注{d['失注']}・検討{d['検討']}・不在{d['不在'] + d['留守電']}）")
    L.append(f"直近{s['days']}日の成約率 {c['win_rate'] * 100:.0f}%（前の期間 {s['prev']['win_rate'] * 100:.0f}%）")
    if ai:
        L += ["", ai]
    else:
        imp = [f for f in findings if f["severity"] in ("high", "mid")][:3]
        if imp:
            L.append("")
            L += ["・" + f["title"] for f in imp]
    if s["callbacks"]:
        L += ["", f"折り返しが確認できない電話 {len(s['callbacks'])}件:"]
        for cb in s["callbacks"][:3]:
            L.append(f"・{cb['at'][5:16].replace('T', ' ')} {cb['name'] or cb['number']}")
    if url:
        L += ["", url]
    return "\n".join(L)


def html_body(cfg, s, findings, ai=None, link=None):
    """画面と単体 HTML で共通の本文。link(id) で各通話へのリンクを作る（None ならリンクなし）。"""
    c, p, d = s["cur"], s["prev"], s["day"]
    o = []
    if ai:
        o.append(f"<div class=ai><b>AI の要点</b><br>{e(ai)}</div>")
    o.append(f"<h2>{e(s['date'])} の電話</h2><div class=kpi>"
             + "".join(f"<div><small>{k}</small><b>{d[k]}</b></div>" for k in ("成約", "失注", "検討", "不在", "留守電", "営業電話"))
             + "</div>")
    o.append(f"<h2>直近{s['days']}日 <span class=sub>{e(s['d_from'])}〜{e(s['date'])}</span></h2><div class=kpi>"
             f"<div><small>着信</small><b>{c['total']}</b><small>前の期間 {p['total']}</small></div>"
             f"<div><small>成約</small><b>{c['成約']}</b><small>前の期間 {p['成約']}</small></div>"
             f"<div><small>成約率</small><b>{c['win_rate'] * 100:.0f}%</b><small>前の期間 {p['win_rate'] * 100:.0f}%</small></div>"
             f"<div><small>失注・検討</small><b>{c['失注'] + c['検討']}</b><small>前の期間 {p['失注'] + p['検討']}</small></div>"
             f"<div><small>不在・留守電</small><b>{c['不在'] + c['留守電']}</b><small>前の期間 {p['不在'] + p['留守電']}</small></div></div>")
    o.append("<h2>指摘</h2>")
    if not findings:
        o.append("<p class=muted>指摘はありません。</p>")
    for f in findings:
        items = ""
        if link and f.get("items"):
            items = "<p class=sub>該当: " + " ".join(f"<a href='{link(i)}'>#{k + 1}</a>" for k, i in enumerate(f["items"][:20])) + (" ほか" if len(f["items"]) > 20 else "") + "</p>"
        o.append(f"<div class=f><h3><span class='tag {f['severity']}'>{SEV_LABEL[f['severity']]}</span>{e(f['title'])}</h3>"
                 f"<p>{e(f['detail'])}</p>" + (f"<p class=sug>→ {e(f['suggestion'])}</p>" if f.get("suggestion") else "") + items + "</div>")
    return "".join(o)


def write_all(cfg, s, findings, ai=None):
    d = ensure_dir(os.path.join(cfg.outputs, "reports", s["date"]))
    md = markdown(cfg, s, findings, ai)
    open(os.path.join(d, "report.md"), "w", encoding="utf-8").write(md)
    open(os.path.join(d, "short.txt"), "w", encoding="utf-8").write(short_text(cfg, s, findings, ai))
    body = html_body(cfg, s, findings, ai)
    css = open(os.path.join(os.path.dirname(__file__), "static", "style.css"), encoding="utf-8").read() if os.path.exists(os.path.join(os.path.dirname(__file__), "static", "style.css")) else ""
    open(os.path.join(d, "report.html"), "w", encoding="utf-8").write(
        f"<!doctype html><html lang=ja><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><meta name=robots content='noindex,nofollow'>"
        f"<title>電話と現場の日報 {e(s['date'])}</title><style>{css}</style></head><body><main><h1>電話と現場の日報 {e(s['date'])}</h1>{body}</main></body></html>")
    dump_json(os.path.join(d, "findings.json"), dict(summary=s, findings=findings, ai=ai))
    return d
