"""画面。標準ライブラリだけの小さな HTTP サーバー。社内 LAN か、透過プロキシ（proto.exbridge.jp/kcallai/ など）の後ろで動かす。
リンクはすべて相対パス（プロキシのサブパスの下でも動くように）。"""
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import threading
import urllib.parse
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, pipeline, report, rules, sample
from .report import SEV_LABEL
from .util import ensure_dir, fmt_dur, load_json, now_jst, parse_date, today_jst, ymd

STATIC = os.path.join(os.path.dirname(__file__), "static")
e = html.escape
RUN = {"running": False, "log": [], "started": None, "finished": None}
LOCK = threading.Lock()
NAV = [("", "ダッシュボード"), ("calls", "電話"), ("lost", "失注の分析"), ("staff", "担当者"), ("visits", "現場の会話"), ("report", "日報"), ("settings", "仕組みと設定")]
OC_CLASS = {"成約": "won", "失注": "lost", "検討": "pend", "不明": "unk", "不在": "miss", "留守電": "miss", "営業電話": "other", "対象外": "other"}
OC_COLOR = {"成約": "#1e8e5a", "失注": "#c0392b", "検討": "#d68910", "不明": "#95a5a6", "不在": "#7f8c8d", "留守電": "#5d6d7e", "営業電話": "#bdc3c7", "対象外": "#d5dbdb"}


def cid(i):
    return "call?id=" + urllib.parse.quote(i, safe="")


def vid(i):
    return "visit?id=" + urllib.parse.quote(i, safe="")


def link_for(i):
    return vid(i) if i.startswith("plaud:") else cid(i)


def report_dates(cfg):
    d = os.path.join(cfg.outputs, "reports")
    if not os.path.isdir(d):
        return []
    return sorted([x for x in os.listdir(d) if os.path.exists(os.path.join(d, x, "findings.json"))], reverse=True)


def load_report(cfg, date):
    return load_json(os.path.join(cfg.outputs, "reports", date, "findings.json"))


def badge(o):
    return f"<span class='oc {OC_CLASS.get(o, 'unk')}'>{e(o or '-')}</span>"


def fmt_at(s):
    return (s or "")[5:16].replace("T", " ").replace("-", "/")


# ---------------------------------------------------------------- 図
def svg_daily(calls, end, days=14):
    W, H, L, B, T = 900, 250, 40, 34, 14
    start = end - dt.timedelta(days=days - 1)
    by = defaultdict(Counter)
    for c in calls:
        by[(c["started_at"] or "")[:10]][c["outcome"]] += 1
    order = ["成約", "失注", "検討", "不明", "不在", "留守電", "営業電話", "対象外"]
    mx = max([sum(by[ymd(start + dt.timedelta(days=i))].values()) for i in range(days)] + [1])
    bw = (W - L - 10) / days
    o = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="日別の着信の内訳（成約・失注・検討・不在など）">']
    for k in range(mx + 1):
        if mx > 8 and k % 2:
            continue
        y = H - B - (H - T - B) * k / mx
        o.append(f'<line x1="{L}" y1="{y:.1f}" x2="{W - 10}" y2="{y:.1f}" stroke="#e3e8ee"/><text x="{L - 6}" y="{y + 4:.1f}" font-size="11" text-anchor="end" fill="#5b6774">{k}</text>')
    for i in range(days):
        d = ymd(start + dt.timedelta(days=i))
        x = L + i * bw
        y = H - B
        for oc in order:
            n = by[d][oc]
            if not n:
                continue
            h = (H - T - B) * n / mx
            y -= h
            o.append(f'<rect x="{x + 3:.1f}" y="{y:.1f}" width="{bw - 6:.1f}" height="{h:.1f}" fill="{OC_COLOR[oc]}"><title>{d} {oc} {n}件</title></rect>')
        o.append(f'<text x="{x + bw / 2:.1f}" y="{H - B + 16}" font-size="11" text-anchor="middle" fill="#5b6774">{d[5:].replace("-", "/")}</text>')
    o.append("</svg>")
    leg = "".join(f"<span class=lg><i style='background:{OC_COLOR[k]}'></i>{k}</span>" for k in order)
    return "".join(o) + f"<div class=legend>{leg}</div>"


def bars(items, total=None, color="#2f6fd1", unit="件"):
    if not items:
        return "<p class=muted>まだありません。</p>"
    mx = max(v for _, v in items) or 1
    rows = "".join(f"<div class=bar><span class=bl>{e(str(k))}</span><span class=bt><i style='width:{v / mx * 100:.0f}%;background:{color}'></i></span><span class=bv>{v}{unit}</span></div>" for k, v in items)
    return f"<div class=bars>{rows}</div>"


def flow_svg():
    """データの流れの図。受け口を外へ開けず、こちらから読みに行くことが要点。"""
    return """<figure class=flow><svg viewBox="0 0 900 300" role="img" aria-label="トビラフォンの着信通知メールと PLAUD の録音を、社内のサーバーから読みに行き、規則で判定して日報を LINE とメールで届ける流れ">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5b6774"/></marker></defs>
<g font-size="13" fill="#1f2a37" text-anchor="middle">
<rect x="10" y="30" width="170" height="54" rx="10" fill="#fff" stroke="#9aa7b4"/><text x="95" y="53">トビラフォン Cloud</text><text x="95" y="72" font-size="11" fill="#5b6774">着信・文字起こし</text>
<rect x="250" y="30" width="170" height="54" rx="10" fill="#fff" stroke="#9aa7b4"/><text x="335" y="53">通知用メールボックス</text><text x="335" y="72" font-size="11" fill="#5b6774">着信のたびに1通</text>
<rect x="10" y="190" width="170" height="54" rx="10" fill="#fff" stroke="#9aa7b4"/><text x="95" y="213">PLAUD</text><text x="95" y="232" font-size="11" fill="#5b6774">現場の録音・要約</text>
<rect x="490" y="100" width="190" height="96" rx="12" fill="#e9f1fd" stroke="#2f6fd1" stroke-width="2"/><text x="585" y="128" font-weight="700">Kurage 通話AI分析</text><text x="585" y="150" font-size="12">社内のサーバー1台</text><text x="585" y="170" font-size="11" fill="#5b6774">規則で判定 → 日報</text><text x="585" y="186" font-size="11" fill="#5b6774">AI は言い換えだけ（任意）</text>
<rect x="740" y="60" width="150" height="50" rx="10" fill="#fff" stroke="#1e8e5a"/><text x="815" y="90">LINE（経営者）</text>
<rect x="740" y="130" width="150" height="50" rx="10" fill="#fff" stroke="#1e8e5a"/><text x="815" y="160">メール</text>
<rect x="740" y="200" width="150" height="50" rx="10" fill="#fff" stroke="#1e8e5a"/><text x="815" y="230">この画面</text>
</g>
<g stroke="#5b6774" stroke-width="1.6" fill="none">
<line x1="180" y1="57" x2="246" y2="57" marker-end="url(#ar)"/>
<path d="M420,57 C470,57 470,120 486,128" marker-end="url(#ar)"/>
<path d="M180,217 C330,217 400,180 486,170" marker-end="url(#ar)"/>
<path d="M680,130 L736,90" marker-end="url(#ar)"/><line x1="680" y1="150" x2="736" y2="155" marker-end="url(#ar)"/><path d="M680,175 L736,222" marker-end="url(#ar)"/>
</g>
<g font-size="11" fill="#5b6774" text-anchor="middle">
<text x="213" y="48">通知（公式機能）</text><text x="470" y="80">IMAPで読みに行く</text><text x="330" y="236">公式 CLI・MCP で取り出す</text><text x="715" y="268">外向きの送信だけ</text>
</g></svg><figcaption>受け口のサーバーを外へ公開しません。こちらから読みに行き、外へは送るだけです。Zapier などのつなぎのサービスは要りません。</figcaption></figure>"""


# ---------------------------------------------------------------- 枠
def shell(cfg, title, body, active="", notice=None):
    nav = "".join(f'<a href="{k or "."}" class="{"on" if k == active else ""}">{v}</a>' for k, v in NAV)
    acct = f"<small>{e(cfg.name)}</small>" if cfg.name else ""
    n = f'<div class="notice {"ok" if notice[0] == "ok" else ""}">{e(notice[1])}</div>' if notice else ""
    band = ("<div class=sampleband>見本データで動いています。人名・電話番号・会社はすべて当社が作った架空のものです。"
            "通知メールの文面は、トビラフォン Cloud の公式ヘルプにある項目から当社が想定した形です。</div>") if cfg.sample else ""
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{e(title)} | Kurage 通話AI分析</title><link rel="stylesheet" href="static/style.css"><link rel="stylesheet" href="static/kcallai.css"><link rel="icon" href="static/mascot.png"></head>
<body><header class="top"><div class="topin"><a class="brand" href="."><img src="static/logo-mark-128.png" width="36" height="36" alt="株式会社エクスブリッジ"><img class="mascot" src="static/mascot.png" width="34" height="38" alt="Kurage">Kurage 通話AI分析{acct}</a><nav class="tabs">{nav}</nav></div></header>
{band}<main>{n}{body}</main>
<footer class="foot">Kurage 通話AI分析 kcallai {__version__}。成約・失注・理由・応対の確認は、文字起こしの言葉から決まった規則で判定しています。AI の要点は、その結果の言い換えです。</footer></body></html>"""


def kpi(label, value, sub=""):
    return f"<div><small>{e(label)}</small><b>{value}</b><small>{sub}</small></div>"


def latest_date(cfg):
    calls = rules.load_calls(cfg)
    if not calls:
        return today_jst() - dt.timedelta(days=1)
    last = max((c["started_at"] or "")[:10] for c in calls)
    y = ymd(today_jst() - dt.timedelta(days=1))
    return parse_date(min(last, y) if last >= y else last)


# ---------------------------------------------------------------- ページ
def page_dashboard(cfg, notice=None):
    end = latest_date(cfg)
    s, findings = rules.summarize(cfg, end)
    today = rules.load_calls(cfg, ymd(today_jst()), ymd(today_jst()))
    dates = report_dates(cfg)
    rep = load_report(cfg, dates[0]) if dates else None
    allc = rules.load_calls(cfg, ymd(end - dt.timedelta(days=13)), ymd(today_jst()))
    c, p, d = s["cur"], s["prev"], s["day"]
    o = [f"<h1>ダッシュボード <span class=sub>{e(s['date'])} までの直近{s['days']}日</span></h1>"]
    o.append("<div class=kpi>" + kpi("直近7日の着信", c["total"], f"前の期間 {p['total']}") + kpi("成約", c["成約"], f"前の期間 {p['成約']}")
             + kpi("成約率", f"{c['win_rate'] * 100:.0f}%", f"前の期間 {p['win_rate'] * 100:.0f}%") + kpi("失注・検討", c["失注"] + c["検討"], f"前の期間 {p['失注'] + p['検討']}")
             + kpi("不在・留守電", c["不在"] + c["留守電"], f"折り返し未確認 {len(s['callbacks'])}") + kpi("現場の会話", s["visits"]["total"], f"トラブルの兆し {s['visits']['trouble']}") + "</div>")
    act = []
    if cfg.sample:
        act.append("<form method=post action='arrive' class=inline><button class='btn sm'>見本の新着を1通受信して分析</button></form>")
    act.append(f"<form method=post action='run' class=inline><button class='btn sec sm' {'disabled' if RUN['running'] else ''}>今すぐ取り込んで分析{'（実行中）' if RUN['running'] else ''}</button></form>")
    if today:
        tl = "".join(f"<tr><td>{fmt_at(x['started_at'])}</td><td><a href='{cid(x['id'])}'>{e(x.get('caller_name') or x.get('caller_number') or '-')}</a></td><td>{e(x.get('staff') or '-')}</td><td>{e(x.get('category') or '')}</td><td>{badge(x['outcome'])}</td><td class=sub>{e('・'.join(x['reasons']))}</td></tr>" for x in reversed(today))
        act.append(f"<h3>今日届いた電話（{len(today)}件）</h3><div class=tw><table><tr><th>時刻</th><th>相手</th><th>担当</th><th>用件</th><th>結果</th><th>理由</th></tr>{tl}</table></div>")
    o.append("<div class='card' style='margin-top:12px'>" + " ".join(act[:2]) + "".join(act[2:]) + "</div>")
    o.append(f"<div class='card chart' style='margin-top:12px'><h3 style='margin-top:0'>日別の着信の内訳（14日）</h3>{svg_daily(allc, end)}</div>")
    o.append("<div class='grid g2' style='margin-top:12px'>")
    o.append(f"<div class=card><h3 style='margin-top:0'>指摘（{len(findings)}件）</h3>")
    if rep and rep.get("ai") and rep["summary"]["date"] == s["date"]:
        o.append(f"<div class=ai><b>AI の要点</b><br>{e(rep['ai'])}</div>")
    for f in findings[:7]:
        it = f" <a class=sub href='{link_for(f['items'][0])}'>例を見る</a>" if f.get("items") else ""
        o.append(f"<p><span class='tag {f['severity']}'>{SEV_LABEL[f['severity']]}</span>{e(f['title'])}{it}</p>")
    o.append("<p><a class='btn sec sm' href='report'>日報を全部見る</a></p></div>")
    cb = "".join(f"<div class=cb><b>{fmt_at(x['at'])}</b> {badge(x['outcome'])} <a href='{cid(x['id'])}'>{e(x['name'] or x['number'] or '-')}</a> <span class=sub>{e(x['number'] or '')}</span>"
                 + (f"<div class=sub>{e(x['text'])}</div>" if x["text"] else "") + "</div>" for x in s["callbacks"])
    o.append(f"<div class=card><h3 style='margin-top:0'>折り返しが確認できない電話（{len(s['callbacks'])}件）</h3>{cb or '<p class=muted>ありません。</p>'}"
             "<p class=sub>不在・留守電のあと、同じ番号と話した記録が無いものです。通知メールは着信だけなので、こちらから掛けた折り返しはここでは見えません。</p></div>")
    o.append("</div><div class='grid g2' style='margin-top:12px'>")
    o.append(f"<div class=card><h3 style='margin-top:0'>失注・検討の理由（直近7日）</h3>{bars(s['reasons'], color='#c0392b')}<p><a class='btn sec sm' href='lost'>失注の分析へ</a></p></div>")
    o.append(f"<div class=card><h3 style='margin-top:0'>用件の内訳（直近7日）</h3>{bars(s['categories'])}</div>")
    o.append("</div>")
    return shell(cfg, "ダッシュボード", "".join(o), "", notice)


def page_calls(cfg, qs):
    days = int(qs.get("days", ["14"])[0] or 14)
    oc = qs.get("outcome", [""])[0]
    st = qs.get("staff", [""])[0]
    cat = qs.get("category", [""])[0]
    end = today_jst()
    rows = rules.load_calls(cfg, ymd(end - dt.timedelta(days=days)), ymd(end))
    staffs = sorted({r["staff"] for r in rows if r.get("staff")})
    cats = sorted({r["category"] for r in rows if r.get("category")})
    if oc == "失注・検討":
        rows = [r for r in rows if r["outcome"] in ("失注", "検討")]
    elif oc:
        rows = [r for r in rows if r["outcome"] == oc]
    if st:
        rows = [r for r in rows if r.get("staff") == st]
    if cat:
        rows = [r for r in rows if r.get("category") == cat]
    opt = lambda v, cur, label=None: f'<option value="{e(v)}" {"selected" if v == cur else ""}>{e(label or v or "すべて")}</option>'
    o = [f"<h1>電話 <span class=sub>{len(rows)}件</span></h1>",
         "<form method=get action='calls' class='card filters'>期間 <select name=days>" + "".join(opt(str(x), str(days), f"{x}日") for x in (1, 7, 14, 30, 90)) + "</select>"
         " 結果 <select name=outcome>" + "".join(opt(x, oc) for x in ["", "成約", "失注・検討", "失注", "検討", "不明", "不在", "留守電", "営業電話", "対象外"]) + "</select>"
         " 担当 <select name=staff>" + "".join(opt(x, st) for x in [""] + staffs) + "</select>"
         " 用件 <select name=category>" + "".join(opt(x, cat) for x in [""] + cats) + "</select> <button class='btn sm'>表示</button></form>",
         "<div class=tw><table><tr><th>日時</th><th>相手</th><th>担当</th><th>用件</th><th>結果</th><th>理由</th><th>言えていないこと</th><th class=n>通話</th></tr>"]
    for r in reversed(rows):
        miss = [k for k, v in r["checks"].items() if v is False and k in ("名乗り", "料金の目安", "到着の時刻", "用件の確認", "お名前", "住所")]
        o.append(f"<tr><td>{fmt_at(r['started_at'])}</td><td><a href='{cid(r['id'])}'>{e(r.get('caller_name') or r.get('caller_number') or '-')}</a></td><td>{e(r.get('staff') or '-')}</td>"
                 f"<td>{e(r.get('category') or '')}</td><td>{badge(r['outcome'])}</td><td class=sub>{e('・'.join(r['reasons']))}</td><td class=sub>{e('・'.join(miss))}</td><td class=n>{fmt_dur(r.get('duration_sec'))}</td></tr>")
    if not rows:
        o.append("<tr><td colspan=8 class=muted>該当する電話がありません。</td></tr>")
    o.append("</table></div>")
    return shell(cfg, "電話", "".join(o), "calls")


def highlight(text, words):
    t = e(text)
    for w in sorted({w for w in words if w}, key=len, reverse=True):
        t = t.replace(e(w), f"<mark>{e(w)}</mark>")
    return t


def page_call(cfg, qs):
    i = qs.get("id", [""])[0]
    r = next((x for x in rules.load_calls(cfg) if x["id"] == i), None)
    if not r:
        return shell(cfg, "見つかりません", "<h1>その電話はありません</h1><p><a href='calls'>電話の一覧へ</a></p>", "calls")
    ev = r["evidence"]
    words = list(ev.values())
    o = [f"<p><a href='calls'>← 電話の一覧</a></p><h1>{e(r.get('caller_name') or r.get('caller_number') or '電話')} {badge(r['outcome'])}</h1>",
         "<div class='grid g2'><div class=card><table class=kv>"
         f"<tr><th>日時</th><td>{e((r['started_at'] or '').replace('T', ' ')[:16])}</td></tr><tr><th>電話番号</th><td>{e(r.get('caller_number') or '-')}</td></tr>"
         f"<tr><th>担当</th><td>{e(r.get('staff') or '-')}</td></tr><tr><th>通話時間</th><td>{fmt_dur(r.get('duration_sec'))}</td></tr>"
         f"<tr><th>アクション</th><td>{e(r.get('action') or '-')}</td></tr><tr><th>用件</th><td>{e(r.get('category') or '-')}</td></tr>"
         f"<tr><th>結果</th><td>{badge(r['outcome'])} <span class=sub>{('決め手の言葉: 「' + e(ev['outcome']) + '」') if ev.get('outcome') else ''}</span></td></tr>"
         f"<tr><th>理由</th><td>{e('・'.join(r['reasons']) or '-')}</td></tr>"
         + (f"<tr><th>通話履歴</th><td class=sub>{e(r['history_url'])}</td></tr>" if r.get("history_url") else "") + "</table></div>"]
    ck = "".join(f"<div class=ck><span class='{'yes' if v else 'no'}'>{'✓' if v else '✗'}</span>{e(k)}" + (f" <span class=sub>「{e(ev.get('check:' + k))}」</span>" if ev.get("check:" + k) else "") + "</div>"
                 for k, v in r["checks"].items() if v is not None)
    o.append(f"<div class=card><h3 style='margin-top:0'>応対の確認</h3>{ck or '<p class=muted>この電話は応対の確認の対象外です。</p>'}"
             + "".join(f"<p class=warn>{e(fl)}</p>" for fl in r["flags"]) + "</div></div>")
    turns = rules.split_turns(r.get("transcript") or "", cfg)
    if turns:
        tl = "".join(f"<div class='turn {w}'><small>{'担当' if w == 'staff' else 'お客様' if w == 'customer' else ''}</small><p>{highlight(t, words)}</p></div>" for w, t in turns)
        o.append(f"<h2>音声テキスト</h2><div class=talk>{tl}</div><p class=sub>黄色は判定に使った言葉です。</p>")
    else:
        o.append("<p class=muted>音声テキストはありません（不在着信など）。</p>")
    return shell(cfg, "電話", "".join(o), "calls")


def page_lost(cfg, qs):
    days = int(qs.get("days", ["30"])[0] or 30)
    end = latest_date(cfg)
    rows = rules.load_calls(cfg, ymd(end - dt.timedelta(days=days - 1)), ymd(end))
    dec = [r for r in rows if r["outcome"] in rules.DECIDED]
    lost = [r for r in dec if r["outcome"] in ("失注", "検討")]
    rc = Counter(x for r in lost for x in r["reasons"]).most_common()
    o = [f"<h1>失注の分析 <span class=sub>直近{days}日・結果が出た電話 {len(dec)}件のうち失注・検討 {len(lost)}件</span></h1>",
         "<form method=get action='lost' class='card filters'>期間 <select name=days>" + "".join(f"<option value={x} {'selected' if x == days else ''}>{x}日</option>" for x in (7, 14, 30, 90)) + "</select> <button class='btn sm'>表示</button></form>",
         "<div class='grid g2' style='margin-top:12px'>", f"<div class=card><h3 style='margin-top:0'>理由</h3>{bars(rc, color='#c0392b')}<p class=sub>お客様の言葉に出た語で分けています。1件に理由が2つ以上つくこともあります。</p></div>"]
    t = ["<div class=card><h3 style='margin-top:0'>言ったか・言わなかったかで成約率を比べる</h3><div class=tw><table><tr><th>項目</th><th class=n>言った</th><th class=n>言わなかった</th></tr>"]
    for chk in ("料金の目安", "到着の時刻", "名乗り", "用件の確認"):
        rr = [r for r in dec if r["checks"].get(chk) is not None]
        y = [r for r in rr if r["checks"][chk]]
        n = [r for r in rr if not r["checks"][chk]]
        f = lambda xs: (f"{sum(1 for r in xs if r['outcome'] == '成約') / len(xs) * 100:.0f}% <span class=sub>({sum(1 for r in xs if r['outcome'] == '成約')}/{len(xs)})</span>" if xs else "-")
        t.append(f"<tr><td>{chk}</td><td class=n>{f(y)}</td><td class=n>{f(n)}</td></tr>")
    t.append("</table></div><p class=sub>成約率＝成約 ÷（成約＋失注＋検討）。件数が少ないうちは差が偶然のこともあります。</p></div>")
    o += t + ["</div>", "<h2>失注・検討の電話</h2><div class=tw><table><tr><th>日時</th><th>相手</th><th>担当</th><th>用件</th><th>結果</th><th>理由</th><th>お客様の最後の言葉</th></tr>"]
    for r in reversed(lost):
        last = [t2 for w, t2 in rules.split_turns(r.get("transcript") or "", cfg) if w == "customer"]
        o.append(f"<tr><td>{fmt_at(r['started_at'])}</td><td><a href='{cid(r['id'])}'>{e(r.get('caller_name') or '-')}</a></td><td>{e(r.get('staff') or '-')}</td><td>{e(r.get('category') or '')}</td><td>{badge(r['outcome'])}</td><td class=sub>{e('・'.join(r['reasons']))}</td><td>{e(last[-1] if last else '')}</td></tr>")
    o.append("</table></div>")
    return shell(cfg, "失注の分析", "".join(o), "lost")


def page_staff(cfg, qs):
    days = int(qs.get("days", ["30"])[0] or 30)
    end = latest_date(cfg)
    s, _ = rules.summarize(cfg, end, days)
    cols = ["名乗り", "用件の確認", "お名前", "住所", "料金の目安", "到着の時刻", "復唱", "お礼"]
    o = [f"<h1>担当者 <span class=sub>直近{days}日</span></h1>",
         "<form method=get action='staff' class='card filters'>期間 <select name=days>" + "".join(f"<option value={x} {'selected' if x == days else ''}>{x}日</option>" for x in (7, 14, 30, 90)) + "</select> <button class='btn sm'>表示</button></form>",
         "<div class=tw><table><tr><th>担当</th><th class=n>電話</th><th class=n>成約率</th>" + "".join(f"<th class=n>{c}</th>" for c in cols) + "</tr>"]
    for r in s["staff"]:
        cells = ""
        for c in cols:
            ok, n = r["checks"].get(c, [0, 0])
            v = ok / n if n else None
            cls = "" if v is None else ("good" if v >= 0.8 else "bad" if v < 0.5 else "")
            cells += f"<td class='n {cls}'>{'-' if v is None else f'{v * 100:.0f}%'}<br><span class=sub>{ok}/{n}</span></td>"
        o.append(f"<tr><td><a href='calls?staff={urllib.parse.quote(r['staff'])}&days={days}'>{e(r['staff'])}</a></td><td class=n>{r['calls']}</td><td class=n>{r['win_rate'] * 100:.0f}%<br><span class=sub>{r['won']}/{r['decided']}</span></td>{cells}</tr>")
    o.append("</table></div><p class=sub>応対の確認は、担当の発言に決まった言葉があるかで見ています。緑は8割以上、赤は5割未満。「名乗り」は設定の社名で判定します。"
             "担当者を責めるためではなく、電話の型をそろえるための表です。</p>")
    return shell(cfg, "担当者", "".join(o), "staff")


def page_visits(cfg, qs):
    rows = rules.load_visits(cfg)
    o = [f"<h1>現場の会話 <span class=sub>PLAUD の録音 {len(rows)}件</span></h1>",
         "<div class=tw><table><tr><th>日時</th><th>録音</th><th>用件</th><th>結果</th><th>作業前の見積もり</th><th>追加料金の説明</th><th>気になる点</th></tr>"]
    for v in reversed(rows):
        ck = v["checks"]
        yn = lambda b: "<span class=yes>✓</span>" if b else "<span class=no>✗</span>"
        o.append(f"<tr><td>{fmt_at(v['started_at'])}</td><td><a href='{vid(v['id'])}'>{e(v['name'] or v['id'])}</a></td><td>{e(v['category'] or '')}</td><td>{badge(v['outcome'])}</td>"
                 f"<td>{yn(ck.get('作業前に見積もり'))}</td><td>{yn(ck.get('追加料金の説明'))}</td><td class=sub>{e('・'.join(v['flags']))}</td></tr>")
    if not rows:
        o.append("<tr><td colspan=7 class=muted>まだありません。</td></tr>")
    o.append("</table></div>")
    return shell(cfg, "現場の会話", "".join(o), "visits")


def page_visit(cfg, qs):
    i = qs.get("id", [""])[0]
    v = next((x for x in rules.load_visits(cfg) if x["id"] == i), None)
    if not v:
        return shell(cfg, "見つかりません", "<h1>その録音はありません</h1>", "visits")
    ev = v["evidence"]
    words = list(ev.values())
    st = rules.visit_staff_speaker(v["segments"], cfg)
    o = [f"<p><a href='visits'>← 現場の会話</a></p><h1>{e(v['name'] or v['id'])} {badge(v['outcome'])}</h1><div class='grid g2'><div class=card><table class=kv>"
         f"<tr><th>日時</th><td>{e((v['started_at'] or '').replace('T', ' ')[:16])}</td></tr><tr><th>長さ</th><td>{fmt_dur(v.get('duration_sec'))}</td></tr>"
         f"<tr><th>用件</th><td>{e(v['category'] or '-')}</td></tr><tr><th>担当とみなした話者</th><td>{e(st or '-')}</td></tr></table>"
         + "".join(f"<div class=ck><span class='{'yes' if b else 'no'}'>{'✓' if b else '✗'}</span>{e(k)}" + (f" <span class=sub>「{e(ev.get('check:' + k))}」</span>" if ev.get("check:" + k) else "") + "</div>" for k, b in v["checks"].items())
         + "".join(f"<p class=warn>{e(fl)}</p>" for fl in v["flags"] if "トラブル" in fl) + "</div>"]
    o.append(f"<div class=card><h3 style='margin-top:0'>PLAUD の AI 要約</h3><pre class=note>{e(v['note'] or 'なし')}</pre></div></div>")
    tl = "".join(f"<div class='turn {'staff' if s.get('speaker') == st else 'customer'}'><small>{e(s.get('speaker') or '')}</small><p>{highlight(s['text'], words)}</p></div>" for s in v["segments"])
    o.append(f"<h2>文字起こし</h2><div class=talk>{tl}</div><p class=sub>黄色は判定に使った言葉です。</p>")
    return shell(cfg, "現場の会話", "".join(o), "visits")


def page_report(cfg, qs):
    dates = report_dates(cfg)
    date = qs.get("date", [dates[0] if dates else ""])[0]
    r = load_report(cfg, date) if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
    sel = "".join(f'<option value="{e(d)}" {"selected" if d == date else ""}>{e(d)}</option>' for d in dates)
    head = f"<h1>日報</h1><form class=inline method=get action='report'><select name=date onchange='this.form.submit()'>{sel}</select></form>"
    if not r:
        return shell(cfg, "日報", head + "<p class=muted>日報がありません。「仕組みと設定」から今すぐ実行できます。</p>", "report")
    short = report.short_text(cfg, r["summary"], r["findings"], r.get("ai"))
    links = f" <a class='btn sec sm' href='report-file?date={e(date)}&f=report.md'>Markdown</a> <a class='btn sec sm' href='report-file?date={e(date)}&f=report.html' target=_blank>単体の HTML</a>"
    body = (head + links + "<div class='grid g2' style='margin-top:10px'><div>" + report.html_body(cfg, r["summary"], r["findings"], r.get("ai"), link_for)
            + f"</div><div><div class=card><h3 style='margin-top:0'>LINE に届く文面</h3><pre class=line>{e(short)}</pre></div></div></div>")
    return shell(cfg, f"日報 {date}", body, "report")


def page_settings(cfg, notice=None):
    raw = json.loads(json.dumps(cfg.raw))
    if (raw.get("web") or {}).get("password"):
        raw["web"]["password"] = "********"
    K = rules.kw(cfg)
    kws = "".join(f"<tr><th>{e(k)}</th><td class=sub>{e('、'.join(v) if v else '（社名の設定を使う）')}</td></tr>" for k, v in K["check"].items())
    rs = "".join(f"<tr><th>{e(k)}</th><td class=sub>{e('、'.join(v))}</td></tr>" for k, v in K["reason"].items())
    log = "\n".join(RUN["log"][-30:])
    o = ["<h1>仕組みと設定</h1>", "<h2>データの流れ</h2>", flow_svg(),
         "<div class='grid g2'><div class=card><h3 style='margin-top:0'>取り込み元</h3><ul>"
         "<li><b>トビラフォン Cloud</b>: 外線番号ごとの「着信を通知」（メール）。通知には相手先・応答者・通話時間・音声テキストが入ります（公式ヘルプの項目）。着信方式が「コールフロー（IVR）」の番号で使えます。発信は通知されません。</li>"
         "<li><b>トビラフォンの一括ダウンロード</b>: 通話履歴の「一括操作」で落とせる録音データには、音声テキストと要約のテキストが入ります。発信の分はこれで補います。</li>"
         "<li><b>PLAUD</b>: 公式の CLI（plaud recent / transcript / summary）か MCP で、録音・文字起こし・要約を取り出します。画面の自動操作はしません。</li></ul></div>"
         "<div class=card><h3 style='margin-top:0'>判定と AI</h3><ul><li>成約・失注・検討・理由・応対の確認は、決まった言葉で判定します。AI が無くても全部動きます。</li>"
         "<li>AI は日報の言い換えだけです。Claude Code（claude -p）・Codex・OpenAI 互換の API・社内の Ollama から選べます。数字は日報の中のものだけを使わせます。</li>"
         "<li>判定の言葉は設定の keywords で足せます（御社の言い回しに合わせる）。</li></ul></div></div>",
         f"<div class=card style='margin-top:12px'><h3 style='margin-top:0'>今すぐ実行</h3><form method=post action='run' class=inline><button class='btn sm' {'disabled' if RUN['running'] else ''}>取り込んで分析（通知はしない）</button></form>"
         f" <span class=sub>最終実行: {e(RUN['finished'] or '-')}</span><pre class=log>{e(log)}</pre></div>",
         f"<div class='grid g2' style='margin-top:12px'><div class=card><h3 style='margin-top:0'>応対の確認に使う言葉</h3><div class=tw><table>{kws}</table></div></div>"
         f"<div class=card><h3 style='margin-top:0'>失注の理由に使う言葉</h3><div class=tw><table>{rs}</table></div></div></div>",
         f"<div class=card style='margin-top:12px'><h3 style='margin-top:0'>設定ファイル</h3><pre class=log>{e(json.dumps(raw, ensure_ascii=False, indent=2))}</pre><p class=sub>パスワードやトークンは設定ファイルに書かず、環境変数の名前だけを書きます。</p></div>"]
    return shell(cfg, "仕組みと設定", "".join(o), "settings", notice)


def page_login(cfg, bad=False):
    msg = "<div class=notice>パスワードが違います。</div>" if bad else ""
    return shell(cfg, "ログイン", f"<div class='login card'><h1>ログイン</h1>{msg}<form method=post action='login'><p><input type=password name=password autofocus style='width:100%'></p><p><button class=btn>ログイン</button></p></form></div>")


# ---------------------------------------------------------------- 実行
def start_run(cfg, arrive_n=0):
    with LOCK:
        if RUN["running"]:
            return False
        RUN.update(running=True, log=[], started=now_jst().strftime("%Y-%m-%d %H:%M:%S"))

    def work():
        log = lambda m: RUN["log"].append(f"{now_jst():%H:%M:%S} {m}")
        try:
            if arrive_n:
                sd = cfg.path_of(cfg.raw.get("sample_dir", "sample"))
                moved = sample.arrive(os.path.join(sd, "pending"), cfg.path_of(cfg.tobila.get("dir", "sample/tobila")), arrive_n)
                log(f"見本の新着メール: {len(moved)}通を受信" if moved else "見本の新着メール: 使い切りました（見本データを作り直すとまた届きます）")
            pipeline.ingest(cfg, log)
            # 画面からの実行は通知しない（見本のデモで LINE が飛ばないように。通知は毎朝の run で送る）
            pipeline.analyze(cfg, ymd(latest_date(cfg)), None, log)
        except Exception as ex:  # noqa
            log(f"エラー: {ex}")
        finally:
            RUN.update(running=False, finished=now_jst().strftime("%Y-%m-%d %H:%M:%S"))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------- サーバー
def make_handler(cfg):
    web = cfg.web
    password = web.get("password") or os.environ.get(web.get("password_env", "KCALLAI_WEB_PASSWORD"), "")
    secret = hashlib.sha256(("kcallai|" + password + "|" + cfg.path).encode()).hexdigest()
    token = hmac.new(secret.encode(), b"ok", hashlib.sha256).hexdigest()

    class H(BaseHTTPRequestHandler):
        server_version = "kcallai/" + __version__

        def log_message(self, fmt, *a):
            pass

        def _authed(self):
            return (not password) or f"kcallai_s={token}" in self.headers.get("Cookie", "")

        def _send(self, body, status=200, ctype="text/html; charset=utf-8", extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, to, extra=None):
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()

        def _path(self):
            u = urllib.parse.urlsplit(self.path)
            return u.path.strip("/"), urllib.parse.parse_qs(u.query)

        def _form(self):
            n = min(int(self.headers.get("Content-Length") or 0), 100000)
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

        def do_GET(self):
            path, qs = self._path()
            if path.startswith("static/"):
                return self._static(path[7:])
            if path == "login":
                return self._send(page_login(cfg))
            if not self._authed():
                return self._redirect("login")
            pages = {"": lambda: page_dashboard(cfg), "calls": lambda: page_calls(cfg, qs), "call": lambda: page_call(cfg, qs),
                     "lost": lambda: page_lost(cfg, qs), "staff": lambda: page_staff(cfg, qs), "visits": lambda: page_visits(cfg, qs),
                     "visit": lambda: page_visit(cfg, qs), "report": lambda: page_report(cfg, qs), "settings": lambda: page_settings(cfg)}
            try:
                if path in pages:
                    return self._send(pages[path]())
                if path == "report-file":
                    date, f = qs.get("date", [""])[0], qs.get("f", ["report.html"])[0]
                    if f not in ("report.html", "report.md", "short.txt") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                        return self._send("not found", 404, "text/plain")
                    p = os.path.join(cfg.outputs, "reports", date, f)
                    if not os.path.exists(p):
                        return self._send("not found", 404, "text/plain")
                    return self._send(open(p, "rb").read(), 200, "text/html; charset=utf-8" if f.endswith(".html") else "text/plain; charset=utf-8")
                if path == "api/summary.json":
                    s, f = rules.summarize(cfg, latest_date(cfg))
                    return self._send(json.dumps(dict(summary=s, findings=f), ensure_ascii=False), 200, "application/json; charset=utf-8")
                if path == "logout":
                    return self._redirect("login", [("Set-Cookie", "kcallai_s=; Max-Age=0; Path=/")])
                return self._send(shell(cfg, "見つかりません", "<h1>ページがありません</h1><p><a href='.'>ダッシュボードへ</a></p>"), 404)
            except Exception as ex:  # noqa
                return self._send(shell(cfg, "エラー", f"<h1>エラー</h1><pre>{e(str(ex))}</pre>"), 500)

        def _static(self, name):
            p = os.path.join(STATIC, os.path.basename(name))
            if not os.path.isfile(p):
                return self._send("not found", 404, "text/plain")
            ct = {"css": "text/css; charset=utf-8", "png": "image/png", "svg": "image/svg+xml", "js": "text/javascript"}.get(p.rsplit(".", 1)[-1], "application/octet-stream")
            self._send(open(p, "rb").read(), 200, ct, [("Cache-Control", "public, max-age=3600")])

        def do_POST(self):
            path, _ = self._path()
            form = self._form()
            if path == "login":
                if password and hmac.compare_digest(form.get("password", ""), password):
                    return self._redirect(".", [("Set-Cookie", f"kcallai_s={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000")])
                return self._send(page_login(cfg, bad=True), 401)
            if not self._authed():
                return self._redirect("login")
            if path in ("run", "arrive"):
                if path == "arrive" and not cfg.sample:
                    return self._send("bad request", 400, "text/plain")
                t = start_run(cfg, 1 if path == "arrive" else 0)
                if t:
                    t.join(timeout=50)   # 見本なら数秒で終わる。終わってから画面を返す
                    return self._send(page_dashboard(cfg, ("ok", " / ".join(x.split(" ", 1)[1] for x in RUN["log"][-4:]))))
                return self._send(page_dashboard(cfg, ("warn", "すでに実行中です。")))
            return self._send("bad request", 400, "text/plain")

    return H


def serve(cfg, host="127.0.0.1", port=8080):
    ensure_dir(cfg.outputs)
    srv = ThreadingHTTPServer((host, port), make_handler(cfg))
    print(f"kcallai web: http://{host}:{port}/  (Ctrl+C で停止)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
