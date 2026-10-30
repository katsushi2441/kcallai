"""規則での判定。AI は使わない。判定語は KEYWORDS にまとめ、設定の keywords で足したり上書きしたりできる。

1件ごと: 用件の種類・結果（成約／失注／検討／不在／営業電話／対象外／不明）・失注の理由・応対の確認項目。
まとめ: 期間の件数と、指摘（失注の理由、料金の目安を言った電話と言わなかった電話の成約率の差、
担当者ごとの抜け、折り返しが確認できない不在着信、現場の金額トラブルの兆し など）。
"""
import datetime as dt
import json
import re
from collections import Counter, defaultdict

from . import db
from .util import JST, now_jst, pct, ymd

KEYWORDS = {
    "category": {
        "水漏れ": ["水漏れ", "水もれ", "漏れて", "漏れる", "ポタポタ", "水が止まらない"],
        "つまり": ["詰まり", "詰まっ", "つまっ", "流れない", "流れが悪", "逆流", "あふれ"],
        "給湯器": ["給湯器", "お湯が出な"],
        "害虫": ["ハチ", "蜂", "ゴキブリ", "シロアリ", "害虫", "ムカデ"],
        "害獣": ["ネズミ", "ねずみ", "ハクビシン", "イタチ", "コウモリ", "害獣", "天井裏", "屋根裏"],
        "電気": ["ブレーカー", "コンセント", "停電", "漏電", "電気がつかない"],
        "不用品": ["不用品", "粗大ごみ", "粗大ゴミ", "片付け", "回収をお願い"],
    },
    # 結果。会話の最後のほうに出た合図を採る（「高いですね…でもお願いします」なら成約）
    "won_staff": ["お伺いします", "お伺いいたします", "伺います", "向かいます", "手配します", "手配いたします", "ご予約を承りました", "お待ちしております"],
    "won_customer": ["じゃあお願い", "ではお願い", "それでお願い", "来てもらえますか", "来てください", "それで大丈夫です"],
    "lost_customer": ["やめておきます", "今回は結構", "結構です", "今回は見送", "他に頼", "他を当た", "自分でやって", "キャンセル"],
    "pending_customer": ["考えます", "検討します", "また連絡", "相談して", "家族と", "見積もりだけ"],
    "scope_staff": ["対応エリア外", "エリア外", "対応しておりません", "お受けできません"],
    "sales_caller": ["ご案内でお電話", "営業のお電話", "ご提案でお電話", "ご紹介したく", "広告のご案内"],
    # 失注・検討の理由（お客様の言葉）
    "reason": {
        "価格": ["高い", "高すぎ", "高額", "予算", "安く", "相場"],
        "日程・到着": ["今日中", "今すぐ", "すぐ来", "間に合わ", "遅い", "待てない", "明日以降"],
        "他社と比較": ["他の業者", "他社", "相見積", "比べ", "ほかにも聞", "他にも聞"],
        "自分で対応": ["自分でやって", "自分で直"],
        "不安・不信": ["追加料金", "ぼったくり", "高額請求", "口コミ", "怪しい", "不安"],
        "金額が分からない": ["金額が分からない", "値段が分からない", "いくらかかるか分からない", "金額がわからない"],
        "家族と相談": ["家族と相談", "主人と相談", "妻と相談", "大家さんに", "管理会社に"],
    },
    "price_ask": ["いくら", "料金", "費用", "金額", "値段"],
    # 応対の確認項目（担当の言葉）
    "check": {
        "名乗り": [],   # 設定の company_words を使う
        "用件の確認": ["どのような", "どういった", "どちらの", "いつから", "どんな状況", "どの辺り"],
        "お名前": ["お名前"],
        "住所": ["ご住所", "どちらにお住まい", "お伺い先"],
        "復唱": ["でよろしいでしょうか", "でよろしいですか", "お間違いない", "確認させていただ", "復唱"],
        "料金の目安": ["基本料金", "目安", "お見積もりは無料", "お見積りは無料", "見積もり無料", "出張費"],
        "到着の時刻": ["本日中", "今から向か", "すぐに向か"],
        "お礼": ["ありがとうございま"],
    },
    "ng_staff": ["わかりません", "分かりません", "無理です", "できません"],
    # 現場（PLAUD）
    "visit_price_first": ["作業前に", "作業の前に", "先にお見積", "お見積りをお伝え", "お見積もりをお伝え"],
    "visit_no_extra": ["追加料金はかかりません", "追加の費用はかかりません", "これ以上はかかりません", "この金額から増えることはありません"],
    "visit_upsell": ["ついでに", "あわせて", "他にも", "点検しておき", "交換もおすすめ"],
    "visit_won": ["お願いします", "お願いいたします", "やってください", "それでいいです"],
    "visit_won_staff": ["作業を始め", "作業に入ら", "作業に取りかか"],
    "visit_lost": ["見積もりだけ", "今日はやめ", "今日は結構", "考えさせて", "やめておきます"],
    "visit_trouble": ["聞いてない", "聞いていない", "話が違", "電話で聞いた", "最初に言った", "そんなにかかる", "高すぎ"],
}
CHECKS = list(KEYWORDS["check"].keys())
OUTCOMES = ["成約", "失注", "検討", "不明", "不在", "留守電", "営業電話", "対象外"]
DECIDED = ("成約", "失注", "検討")
YEN = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)円")
ETA = re.compile(r"\d+\s*分(?:ほど|くらい|程度|で|後)|\d+\s*時(?:頃|ごろ|に|まで)|\d+時半")


def kw(cfg):
    k = json.loads(json.dumps(KEYWORDS))
    for key, val in (cfg.keywords or {}).items():
        if isinstance(val, dict) and isinstance(k.get(key), dict):
            for kk, vv in val.items():
                k[key][kk] = list(dict.fromkeys((k[key].get(kk) or []) + vv))
        elif isinstance(val, list) and isinstance(k.get(key), list):
            k[key] = list(dict.fromkeys(k[key] + val))
    k["check"]["名乗り"] = list(cfg.company_words or [])
    return k


# ---------------------------------------------------------------- 発話の分け方
def split_turns(text, cfg):
    """「担当: …」「お客様: …」の行に分ける。話者の印が無い行は直前の話者の続き。印が1つも無ければ話者不明の1かたまり。"""
    sp, cp = cfg.rules["staff_prefixes"], cfg.rules["customer_prefixes"]
    pat = re.compile(r"^\s*[【\[]?(" + "|".join(re.escape(x) for x in sp + cp) + r")[】\]]?\s*[:：]\s*(.*)$")
    turns, found = [], False
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = pat.match(line)
        if m:
            found = True
            who = "staff" if m.group(1) in sp else "customer"
            turns.append([who, m.group(2).strip()])
        elif turns:
            turns[-1][1] += " " + line.strip()
        else:
            turns.append(["unknown", line.strip()])
    if not found:
        return [("unknown", " ".join(t[1] for t in turns))] if turns else []
    return [tuple(t) for t in turns]


def _find(words, text):
    for w in words:
        if w and w in text:
            return w
    return None


def _last_pos(words, turns, who):
    """turns の中で words のどれかが最後に出た位置（発話番号, 語）。"""
    best = None
    for i, (w0, t) in enumerate(turns):
        if who and w0 != who and w0 != "unknown":
            continue
        for w in words:
            if w and w in t:
                best = (i, w)
    return best


# ---------------------------------------------------------------- 1件の判定
def analyze_call(c, cfg, K):
    act = c.get("action") or ""
    text = c.get("transcript") or ""
    turns = split_turns(text, cfg)
    staff_t = " ".join(t for w, t in turns if w in ("staff", "unknown"))
    cust_t = " ".join(t for w, t in turns if w in ("customer", "unknown"))
    ev = {}
    flags = []
    # 用件
    cnt = Counter()
    for cat, words in K["category"].items():
        for w in words:
            if w in (cust_t or text):
                cnt[cat] += 1
                ev.setdefault("category", w)
    category = cnt.most_common(1)[0][0] if cnt else "その他"
    reasons, checks = [], {}
    if "留守" in act:
        outcome = "留守電"
    elif ("不在" in act or "応答なし" in act or "不応答" in act) or (not text and not (c.get("duration_sec") or 0)):
        outcome = "不在"
    elif _find(K["sales_caller"], cust_t or text):
        outcome = "営業電話"
        ev["outcome"] = _find(K["sales_caller"], cust_t or text)
    elif _find(K["scope_staff"], staff_t):
        outcome = "対象外"
        ev["outcome"] = _find(K["scope_staff"], staff_t)
        reasons.append("対応エリア外・対象外")
    else:
        cands = []
        for name, words, who in (("成約", K["won_staff"], "staff"), ("成約", K["won_customer"], "customer"),
                                 ("失注", K["lost_customer"], "customer"), ("検討", K["pending_customer"], "customer")):
            p = _last_pos(words, turns, who)
            if p:
                cands.append((p[0], name, p[1]))
        if cands:
            cands.sort()
            _, outcome, w = cands[-1]
            ev["outcome"] = w
        else:
            outcome = "不明"
    if outcome in DECIDED + ("不明",):
        # 応対の確認項目
        staff_turns = [t for w, t in turns if w in ("staff", "unknown")]
        first2 = " ".join(staff_turns[:2])
        lastst = " ".join(staff_turns[-2:])
        for name, words in K["check"].items():
            hit = None
            if name == "名乗り":
                hit = _find(words, first2) if words else None
                if not words:
                    checks[name] = None   # 社名が設定に無いと判定しない
                    continue
            elif name == "お礼":
                hit = _find(words, lastst)
            elif name == "料金の目安":
                m = YEN.search(staff_t)
                hit = m.group(0) if m else _find(words, staff_t)
            elif name == "到着の時刻":
                m = ETA.search(staff_t)
                hit = m.group(0) if m else _find(words, staff_t)
            else:
                hit = _find(words, staff_t)
            checks[name] = bool(hit)
            if hit:
                ev["check:" + name] = hit
        ng = _find(K["ng_staff"], staff_t)
        if ng:
            flags.append("担当の言い方: 「" + ng + "」")
            ev["ng"] = ng
    if outcome in ("失注", "検討"):
        for r, words in K["reason"].items():
            w = _find(words, cust_t)
            if w:
                reasons.append(r)
                ev["reason:" + r] = w
        if _find(K["price_ask"], cust_t) and not checks.get("料金の目安") and "金額が分からない" not in reasons:
            reasons.append("金額が分からない")
            ev["reason:金額が分からない"] = _find(K["price_ask"], cust_t)
        if not reasons:
            reasons.append("理由が会話に出ていない")
    return dict(category=category, outcome=outcome, reasons=reasons, checks=checks, evidence=ev, flags=flags)


def visit_staff_speaker(segs, cfg):
    want = cfg.rules.get("plaud_staff_speaker", "auto")
    if want and want != "auto":
        return want
    for s in segs:
        if s.get("speaker"):
            return s["speaker"]
    return ""


def analyze_visit(v, cfg, K):
    segs = db.loads(v.get("segments"), []) or []
    st = visit_staff_speaker(segs, cfg)
    staff_t = " ".join(s["text"] for s in segs if not st or s.get("speaker") == st)
    cust_t = " ".join(s["text"] for s in segs if st and s.get("speaker") != st)
    allt = " ".join(s["text"] for s in segs)
    ev, flags = {}, []
    cnt = Counter()
    for cat, words in K["category"].items():
        for w in words:
            if w in allt:
                cnt[cat] += 1
    category = cnt.most_common(1)[0][0] if cnt else "その他"
    amounts = [int(x.replace(",", "")) for x in YEN.findall(staff_t)]
    checks = {
        "金額を伝えた": bool(amounts),
        "作業前に見積もり": bool(_find(K["visit_price_first"], staff_t)),
        "追加料金の説明": bool(_find(K["visit_no_extra"], staff_t)),
    }
    for k2, words in (("作業前に見積もり", K["visit_price_first"]), ("追加料金の説明", K["visit_no_extra"])):
        w = _find(words, staff_t)
        if w:
            ev["check:" + k2] = w
    if amounts:
        ev["check:金額を伝えた"] = YEN.search(staff_t).group(0)
    up = _find(K["visit_upsell"], staff_t)
    if up:
        flags.append("追加の提案")
        ev["upsell"] = up
    tr = _find(K["visit_trouble"], cust_t or allt)
    if tr:
        flags.append("金額トラブルの兆し")
        ev["trouble"] = tr
    # 結果: 最後に出た合図
    order = []
    for i, s in enumerate(segs):
        t = s["text"]
        is_staff = (not st) or s.get("speaker") == st
        if not is_staff and _find(K["visit_won"], t):
            order.append((i, "成約", _find(K["visit_won"], t)))
        if is_staff and _find(K["visit_won_staff"], t):
            order.append((i, "成約", _find(K["visit_won_staff"], t)))
        if not is_staff and _find(K["visit_lost"], t):
            order.append((i, "失注", _find(K["visit_lost"], t)))
    if order:
        _, outcome, w = sorted(order)[-1]
        ev["outcome"] = w
    else:
        outcome = "不明"
    return dict(category=category, outcome=outcome, reasons=[], checks=checks, evidence=ev, flags=flags,
                amounts=amounts, staff_speaker=st)


# ---------------------------------------------------------------- 全件の判定とまとめ
def analyze_all(cfg):
    K = kw(cfg)
    con = db.connect(cfg.db)
    now = now_jst().isoformat(timespec="seconds")
    n = 0
    for c in db.q(con, "SELECT * FROM calls"):
        a = analyze_call(c, cfg, K)
        db.upsert(con, "analysis", dict(kind="call", item_id=c["id"], analyzed_at=now, category=a["category"], outcome=a["outcome"],
                                        reasons=json.dumps(a["reasons"], ensure_ascii=False), checks=json.dumps(a["checks"], ensure_ascii=False),
                                        evidence=json.dumps(a["evidence"], ensure_ascii=False), flags=json.dumps(a["flags"], ensure_ascii=False)), replace=True)
        n += 1
    for v in db.q(con, "SELECT * FROM visits"):
        a = analyze_visit(v, cfg, K)
        db.upsert(con, "analysis", dict(kind="visit", item_id=v["id"], analyzed_at=now, category=a["category"], outcome=a["outcome"],
                                        reasons="[]", checks=json.dumps(a["checks"], ensure_ascii=False),
                                        evidence=json.dumps(a["evidence"], ensure_ascii=False),
                                        flags=json.dumps(a["flags"] + ([f"金額 {','.join(str(x) for x in a['amounts'])}円"] if a["amounts"] else []), ensure_ascii=False)), replace=True)
        n += 1
    con.commit()
    con.close()
    return n


def load_calls(cfg, d_from=None, d_to=None):
    """calls と判定を結合して返す。日付は started_at の JST 日付で絞る。"""
    con = db.connect(cfg.db)
    rows = db.q(con, """SELECT c.*, a.category, a.outcome, a.reasons, a.checks, a.evidence, a.flags
                        FROM calls c LEFT JOIN analysis a ON a.kind='call' AND a.item_id=c.id ORDER BY c.started_at""")
    con.close()
    out = []
    for r in rows:
        d = (r["started_at"] or "")[:10]
        if d_from and d < d_from:
            continue
        if d_to and d > d_to:
            continue
        for k in ("reasons", "checks", "evidence", "flags"):
            r[k] = db.loads(r[k], {} if k in ("checks", "evidence") else [])
        out.append(r)
    return out


def load_visits(cfg, d_from=None, d_to=None):
    con = db.connect(cfg.db)
    rows = db.q(con, """SELECT v.*, a.category, a.outcome, a.checks, a.evidence, a.flags
                        FROM visits v LEFT JOIN analysis a ON a.kind='visit' AND a.item_id=v.id ORDER BY v.started_at""")
    con.close()
    out = []
    for r in rows:
        d = (r["started_at"] or "")[:10]
        if (d_from and d < d_from) or (d_to and d > d_to):
            continue
        for k in ("checks", "evidence", "flags"):
            r[k] = db.loads(r[k], {} if k != "flags" else [])
        r["segments"] = db.loads(r["segments"], [])
        out.append(r)
    return out


def counts(calls):
    c = Counter(r["outcome"] for r in calls)
    dec = sum(c[o] for o in DECIDED)
    return dict(total=len(calls), **{o: c.get(o, 0) for o in OUTCOMES}, decided=dec, win_rate=pct(c.get("成約", 0), dec))


def _rate(rows):
    dec = [r for r in rows if r["outcome"] in DECIDED]
    won = sum(1 for r in dec if r["outcome"] == "成約")
    return won, len(dec), pct(won, len(dec))


def _t(c):
    try:
        return dt.datetime.fromisoformat(c["started_at"])
    except (TypeError, ValueError):
        return None


def callbacks(cfg, calls_all, d_from, d_to):
    """不在・留守電のあと callback_hours 以内に、同じ番号と話した記録（応答した着信・取り込んだ発信）が無いもの。"""
    hrs = cfg.rules["callback_hours"]
    talked = defaultdict(list)
    for c in calls_all:
        if c["outcome"] not in ("不在", "留守電") and c.get("caller_number"):
            t = _t(c)
            if t:
                talked[re.sub(r"\D", "", c["caller_number"])].append(t)
    out = []
    for c in calls_all:
        d = (c["started_at"] or "")[:10]
        if c["outcome"] not in ("不在", "留守電") or d < d_from or d > d_to:
            continue
        num = re.sub(r"\D", "", c.get("caller_number") or "")
        t = _t(c)
        ok = any(t and t < x <= t + dt.timedelta(hours=hrs) for x in talked.get(num, []))
        if not ok:
            out.append(c)
    return out


def summarize(cfg, date, days=None):
    """date（その日まで）の直近 days 日と、その前の days 日。指摘の一覧も返す。"""
    days = days or cfg.rules["report_days"]
    d_to = ymd(date)
    d_from = ymd(date - dt.timedelta(days=days - 1))
    p_to = ymd(date - dt.timedelta(days=days))
    p_from = ymd(date - dt.timedelta(days=2 * days - 1))
    all_calls = load_calls(cfg)
    cur = [c for c in all_calls if d_from <= (c["started_at"] or "")[:10] <= d_to]
    prev = [c for c in all_calls if p_from <= (c["started_at"] or "")[:10] <= p_to]
    day = [c for c in all_calls if (c["started_at"] or "")[:10] == d_to]
    visits = load_visits(cfg, d_from, d_to)
    findings = []
    mn, gap = cfg.rules["min_calls_compare"], cfg.rules["compare_gap"]
    cc, pc = counts(cur), counts(prev)
    # 1) 失注・検討の理由
    lost = [c for c in cur if c["outcome"] in ("失注", "検討")]
    if lost:
        rc = Counter(r for c in lost for r in c["reasons"])
        top = "・".join(f"{k}{v}件" for k, v in rc.most_common(4))
        sev = "high" if cc["decided"] and len(lost) / cc["decided"] >= 0.3 else "mid"
        findings.append(dict(kind="lost_reasons", severity=sev, title=f"失注・検討が{len(lost)}件。理由は {top}",
                             detail=f"成約{cc['成約']}件・失注{cc['失注']}件・検討{cc['検討']}件（成約率{cc['win_rate'] * 100:.0f}%）。理由は、お客様の言葉に出た語で分けています。",
                             suggestion="多い理由から順に、電話での言い方（料金の目安の出し方・到着時刻の伝え方）を決めておく。",
                             items=[c["id"] for c in lost]))
    # 2) 確認項目ごとに、あり/なしの成約率
    # 結果が決まる前に言うものだけ比べる（復唱・住所の確認は「お願いします」のあとに来るので、比べると成約の結果を見ているだけになる）
    for chk in ("料金の目安", "到着の時刻", "名乗り"):
        rows = [c for c in cur if c["outcome"] in DECIDED and c["checks"].get(chk) is not None]
        yes = [c for c in rows if c["checks"].get(chk)]
        no = [c for c in rows if not c["checks"].get(chk)]
        if len(yes) >= mn and len(no) >= mn:
            wy, ny, ry = _rate(yes)
            wn, nn, rn = _rate(no)
            if ry - rn >= gap:
                findings.append(dict(kind="check_gap", severity="high" if chk in ("料金の目安", "到着の時刻") else "mid",
                                     title=f"「{chk}」を伝えた電話は成約率{ry * 100:.0f}%、伝えなかった電話は{rn * 100:.0f}%",
                                     detail=f"伝えた {wy}/{ny}件、伝えなかった {wn}/{nn}件（直近{days}日、結果が出た電話だけ）。",
                                     suggestion=f"電話の型に「{chk}」を入れる。伝えなかった電話の一覧から聞き直すと、どこで言えばよいかが分かる。",
                                     items=[c["id"] for c in no]))
    # 3) 担当者ごとの抜け
    by = defaultdict(list)
    for c in cur:
        if c["outcome"] in DECIDED + ("不明",) and c.get("staff"):
            by[c["staff"]].append(c)
    for chk in ("料金の目安", "到着の時刻", "名乗り"):
        worst = None
        for s, rows in by.items():
            rr = [c for c in rows if c["checks"].get(chk) is not None]
            if len(rr) < 3:
                continue
            ok = sum(1 for c in rr if c["checks"][chk])
            if ok / len(rr) < 0.5 and (worst is None or ok / len(rr) < worst[1]):
                worst = (s, ok / len(rr), ok, len(rr), [c["id"] for c in rr if not c["checks"][chk]])
        if worst:
            findings.append(dict(kind="staff_gap", severity="mid", title=f"{worst[0]}さんの電話で「{chk}」が {worst[2]}/{worst[3]}件",
                                 detail="担当者ごとの比較です。責めるためではなく、型をそろえるための材料にしてください。",
                                 suggestion=f"「{chk}」が言えている電話の言い回しを共有する。", items=worst[4]))
    # 4) 折り返しが確認できない不在着信
    cb = callbacks(cfg, all_calls, d_from, d_to)
    if cb:
        lst = "、".join(f"{c['started_at'][5:16].replace('T', ' ')} {c.get('caller_name') or c.get('caller_number')}" for c in cb[:6])
        findings.append(dict(kind="callback", severity="high", title=f"折り返しが確認できない不在着信・留守電が{len(cb)}件",
                             detail=f"{lst}{' ほか' if len(cb) > 6 else ''}。通知メールは着信だけなので、こちらから掛けた折り返しはここでは見えません。一括ダウンロードを取り込むと消えます。",
                             suggestion="留守電の中身（下の一覧）を見て、急ぎの人から折り返す。", items=[c["id"] for c in cb]))
    # 5) 担当の言い方
    ng = [c for c in cur if c["flags"]]
    if ng:
        findings.append(dict(kind="ng", severity="low", title=f"言い方に注意が要る電話が{len(ng)}件（「できません」「分かりません」など）",
                             detail="お客様に断りや分からないを伝える場面です。代わりの案（いつならできる・誰が分かる）を添えると失注が減ります。",
                             suggestion="代わりの言い方を1つ決めておく。", items=[c["id"] for c in ng]))
    # 6) 営業電話
    sales = [c for c in cur if c["outcome"] == "営業電話"]
    if sales:
        mins = sum((c.get("duration_sec") or 0) for c in sales) // 60
        findings.append(dict(kind="sales_calls", severity="low", title=f"営業電話が{len(sales)}件（合計{mins}分）",
                             detail="お客様の電話と同じ回線に入っています。", suggestion="番号を拒否リストに入れる・IVR で振り分ける。",
                             items=[c["id"] for c in sales]))
    # 7) 現場（PLAUD）
    tr = [v for v in visits if "金額トラブルの兆し" in v["flags"]]
    if tr:
        findings.append(dict(kind="visit_trouble", severity="high", title=f"現場で金額のトラブルになりかけた会話が{len(tr)}件",
                             detail="「電話で聞いた金額と違う」「聞いていない」などの言葉が出ています。高額請求の苦情や口コミにつながりやすい場面です。",
                             suggestion="電話で伝える目安と、現場の見積もりの差の説明の仕方を決める。", items=[v["id"] for v in tr]))
    nf = [v for v in visits if not v["checks"].get("作業前に見積もり")]
    if nf:
        findings.append(dict(kind="visit_no_estimate", severity="mid", title=f"作業前の見積もりの説明が会話に無い現場が{len(nf)}件",
                             detail="作業の前に金額を伝えて了承をもらった記録が無い現場です。", suggestion="作業前に「お見積りをお伝えします」と言ってから金額を言う。",
                             items=[v["id"] for v in nf]))
    up = [v for v in visits if "追加の提案" in v["flags"]]
    if up:
        won = sum(1 for v in up if v["outcome"] == "成約")
        findings.append(dict(kind="visit_upsell", severity="low", title=f"追加の提案をした現場が{len(up)}件（うち成約{won}件）",
                             detail="ついでの点検・交換の提案です。", suggestion="", items=[v["id"] for v in up]))
    sev_order = {"high": 0, "mid": 1, "low": 2}
    findings.sort(key=lambda f: sev_order[f["severity"]])
    reasons_c = Counter(r for c in lost for r in c["reasons"])
    cats = Counter(c["category"] for c in cur if c["outcome"] not in ("営業電話", "不在") and c.get("transcript"))
    staff_rows = []
    for s, rows in sorted(by.items()):
        w, n_, r_ = _rate(rows)
        cr = {}
        for chk in CHECKS:
            rr = [c for c in rows if c["checks"].get(chk) is not None]
            cr[chk] = [sum(1 for c in rr if c["checks"][chk]), len(rr)]
        staff_rows.append(dict(staff=s, calls=len(rows), won=w, decided=n_, win_rate=r_, checks=cr))
    summary = dict(date=d_to, d_from=d_from, days=days, cur=cc, prev=pc, day=counts(day),
                   reasons=reasons_c.most_common(), categories=cats.most_common(), staff=staff_rows,
                   visits=dict(total=len(visits), won=sum(1 for v in visits if v["outcome"] == "成約"),
                               lost=sum(1 for v in visits if v["outcome"] == "失注"),
                               trouble=len(tr)),
                   callbacks=[dict(id=c["id"], at=c["started_at"], name=c.get("caller_name"), number=c.get("caller_number"),
                                   outcome=c["outcome"], text=(c.get("transcript") or "")[:120]) for c in cb],
                   sample=any(c.get("sample") for c in cur) or any(v.get("sample") for v in visits))
    return summary, findings
