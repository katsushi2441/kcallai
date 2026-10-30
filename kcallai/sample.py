"""見本データ（当社が作った架空のデータ）。架空の水まわり修理会社「サンプル水道サービス」の
着信通知メール（トビラフォン Cloud の通知の項目に合わせた形）と、現場の会話（PLAUD の get_file の項目に合わせた JSON）。

**実物の通知メールの文面は未確認なので、この見本の文面は当社の想定。** 人名・電話番号・会社はすべて架空
（電話番号は 090-0000-xxxx という存在しない番号）。メールには X-Kcallai-Sample: 1 を付け、本文の先頭にも見本と書く。
"""
import datetime as dt
import json
import os
import random
import shutil
from email.message import EmailMessage
from email.utils import format_datetime

from .util import JST, ensure_dir, now_jst

COMPANY = "サンプル水道サービス"
STAFF = {  # 担当者ごとの癖（確率）。名乗り・料金の目安・到着時刻・復唱・お礼
    "山田": dict(greet=1.0, price=0.9, eta=0.9, confirm=0.85, thanks=0.95),
    "佐藤": dict(greet=0.95, price=0.7, eta=0.8, confirm=0.6, thanks=0.9),
    "鈴木": dict(greet=0.9, price=0.2, eta=0.5, confirm=0.4, thanks=0.8),
    "高橋": dict(greet=0.35, price=0.6, eta=0.75, confirm=0.5, thanks=0.7),
}
NAMES = ["田中", "伊藤", "渡辺", "中村", "小林", "吉田", "山本", "松本", "井上", "木村", "林", "清水", "山崎", "森", "池田",
         "橋本", "阿部", "石川", "前田", "藤田", "後藤", "岡田", "長谷川", "村上", "近藤", "坂本", "遠藤", "青木", "西村", "福田"]
WARDS = ["中村区", "中川区", "北区", "西区", "港区", "南区", "緑区", "名東区", "天白区", "千種区", "昭和区", "守山区"]
SYMPTOM = {
    "水漏れ": ["台所の蛇口の根元から水が漏れてて、ポタポタ止まらないんです。", "洗面所の下の配管から水漏れしていて、床が濡れてしまって。"],
    "つまり": ["トイレが詰まって水が流れないんです。", "お風呂の排水の流れが悪くて、逆流してきちゃって。"],
    "給湯器": ["朝から給湯器のお湯が出ないんです。リモコンにエラーが出てて。"],
    "害虫": ["軒下にハチの巣ができてて、子どもがいるので怖くて。"],
    "害獣": ["夜になると天井裏でネズミが走る音がするんです。"],
    "電気": ["ブレーカーがすぐ落ちてしまって、電子レンジが使えないんです。"],
    "不用品": ["引っ越しで不用品の回収をお願いしたくて。"],
}
CAT_W = {"水漏れ": 6, "つまり": 6, "給湯器": 2, "害虫": 2, "害獣": 2, "電気": 1, "不用品": 1}
PRICE = {
    "水漏れ": "基本料金は8,800円からで、パッキン交換なら部品込みで1万5千円前後が目安です。お見積もりは無料です。",
    "つまり": "基本料金は8,800円からで、軽いつまりでしたら1万2千円前後が目安です。お見積もりは無料です。",
    "給湯器": "点検は出張費込みで5,500円です。交換になる場合は機種によって変わりますので、現地でお見積りします。",
    "害虫": "ハチの巣の駆除は、高さにもよりますが1万6,500円からが目安です。",
    "害獣": "まず無料で調査に伺って、侵入口の数でお見積りします。封鎖と消毒で3万円台からが多いです。",
    "電気": "点検は出張費込みで5,500円です。漏電でしたら修理費が別にかかります。",
    "不用品": "軽トラック1台分で1万9,800円からが目安です。",
}


def _num(rng, used):
    while True:
        n = f"090-0000-{rng.randint(1000, 9999)}"
        if n not in used:
            used.add(n)
            return n


def _dialog(rng, staff, cat, name, ward, number, plan):
    """plan: outcome（成約/失注/検討）と reason。返り値 (行のリスト, 料金を言ったか, 到着時刻を言ったか)。"""
    p = STAFF[staff]
    L = []
    greet = rng.random() < p["greet"]
    L.append(("担当", f"お電話ありがとうございます。{COMPANY}の{staff}です。" if greet else "はい、お電話ありがとうございます。"))
    L.append(("お客様", "すみません、" + rng.choice(SYMPTOM[cat])))
    L.append(("担当", rng.choice(["それはお困りですね。どのような状況でしょうか。", "承知しました。いつからそのような状態でしょうか。"])))
    L.append(("お客様", rng.choice(["昨日の夜からです。", "今朝気づきました。", "2、3日前からです。"])))
    L.append(("担当", "お名前と、お伺い先のご住所をお願いできますか。"))
    L.append(("お客様", f"{name}です。名古屋市{ward}です。"))
    said_price = rng.random() < p["price"]
    said_eta = rng.random() < p["eta"]
    reason = plan.get("reason")
    if reason == "金額が分からない":
        said_price = False
    if reason == "価格":
        said_price = True
    if reason == "日程":
        said_eta = True
    if rng.random() < 0.8 or reason in ("価格", "金額が分からない"):
        L.append(("お客様", "いくらくらいかかりますか？"))
        if said_price:
            L.append(("担当", PRICE[cat]))
        else:
            L.append(("担当", "そうですね、現地で見てみないと、ちょっと何とも言えないですね。"))
    elif said_price:
        L.append(("担当", PRICE[cat]))
    if said_eta:
        if reason == "日程":
            L.append(("担当", "本日は予約が埋まっておりまして、明日の午前10時頃のお伺いになります。"))
        else:
            L.append(("担当", rng.choice(["今からですと40分ほどで到着できます。", "本日15時頃にお伺いできます。", "1時間ほどでお伺いできます。"])))
    o = plan["outcome"]
    if o == "成約":
        L.append(("お客様", rng.choice(["じゃあお願いします。", "それでお願いします。", "ではお願いします。急ぎでお願いします。"])))
        if rng.random() < p["confirm"]:
            L.append(("担当", f"確認させていただきます。名古屋市{ward}の{name}様、お電話番号は{number}でよろしいでしょうか。"))
            L.append(("お客様", "はい、大丈夫です。"))
        L.append(("担当", "承知しました。それでは担当がお伺いします。" if said_eta else "承知しました。手配して、改めて到着時間をご連絡します。"))
    elif o == "失注":
        line = {
            "価格": "思ってたより高いですね…。今回はやめておきます。",
            "金額が分からない": "金額が分からないとちょっと頼みにくいので、今回は結構です。",
            "日程": "今日中に来てもらえないと困るので、他を当たります。",
            "自分で": "それなら自分でやってみます。結構です。",
        }.get(reason, "今回は見送ります。")
        L.append(("お客様", line))
    else:
        line = {"他社": "他の業者さんにも聞いてみて、また連絡します。", "家族": "家族と相談して、また連絡します。"}.get(reason, "少し考えます。")
        L.append(("お客様", line))
    if rng.random() < p["thanks"]:
        L.append(("担当", "お電話ありがとうございました。失礼いたします。" if o == "成約" else "承知しました。またいつでもご連絡ください。ありがとうございました。"))
    else:
        L.append(("担当", "はい、失礼します。"))
    return L, said_price, said_eta


def _plan(rng, staff):
    p = STAFF[staff]
    # 料金の目安・到着時刻を言わない担当ほど失注が増えるように（実際によくある形を見本にしたもの）
    won_p = 0.35 + 0.35 * p["price"] + 0.15 * p["eta"]
    r = rng.random()
    if r < won_p:
        return dict(outcome="成約")
    if r < won_p + (1 - won_p) * 0.65:
        reason = rng.choices(["金額が分からない", "価格", "日程", "自分で"], weights=[3 * (1 - p["price"]) + 0.2, 2, 2 * (1 - p["eta"]) + 0.5, 0.7])[0]
        return dict(outcome="失注", reason=reason)
    return dict(outcome="検討", reason=rng.choice(["他社", "家族"]))


def _mail(no, at, fields, transcript):
    m = EmailMessage()
    m["Subject"] = "【トビラフォン Cloud】着信のお知らせ（見本）"
    m["From"] = "見本データ <sample@example.invalid>"
    m["To"] = "notify@example.invalid"
    m["Date"] = format_datetime(at)
    m["Message-ID"] = f"<sample-{no}@kcallai.invalid>"
    m["X-Kcallai-Sample"] = "1"
    body = ["※ Kurage 通話AI分析の見本データです（当社が作った架空のデータ。実在の人物・会社・番号ではありません）", ""]
    for k, v in fields:
        body.append(f"{k}: {v}")
    if transcript:
        body.append("音声テキスト内容:")
        body.extend(f"{w}: {t}" for w, t in transcript)
    m.set_content("\n".join(body) + "\n")
    return m


def generate(out_dir, end=None, days=14, seed=7, pending=3):
    """out_dir/tobila/*.eml・out_dir/plaud/*.json（取り込み用）と out_dir/pending/*.eml（デモで「新着」として届ける分）を作る。"""
    rng = random.Random(seed)
    end = end or (now_jst().date() - dt.timedelta(days=1))
    for sub in ("tobila", "plaud", "pending"):
        p = os.path.join(out_dir, sub)
        if os.path.isdir(p):
            shutil.rmtree(p)
        ensure_dir(p)
    used, no, n_mail = set(), 1000, 0
    staffs = list(STAFF)
    later_callers = []   # 不在のあと掛け直してきた人
    for di in range(days):
        day = end - dt.timedelta(days=days - 1 - di)
        n = rng.randint(2, 5)
        times = sorted(dt.datetime.combine(day, dt.time(8, 0), JST) + dt.timedelta(minutes=rng.randint(0, 11 * 60)) for _ in range(n + 2))
        events = ["call"] * n
        if rng.random() < 0.55:
            events.append("missed")
        if rng.random() < 0.35:
            events.append("voicemail")
        if rng.random() < 0.2:
            events.append("sales")
        if rng.random() < 0.12:
            events.append("scope")
        rng.shuffle(events)
        for ev, at in zip(events, times + [times[-1] + dt.timedelta(minutes=30 * k) for k in range(1, 6)]):
            no += 1
            name, ward = rng.choice(NAMES), rng.choice(WARDS)
            num = _num(rng, used)
            staff = rng.choice(staffs)
            url = f"https://example.invalid/tobila/history/{no}"
            if ev == "missed":
                fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "不在着信"), ("着信した外線番号の名称", "代表"), ("通話時間", "00:00:00"), ("通話履歴URL", url)]
                msg = _mail(no, at, fields, None)
                if rng.random() < 0.5:
                    later_callers.append((at + dt.timedelta(minutes=rng.randint(20, 180)), name, ward, num))
            elif ev == "voicemail":
                cat = rng.choices(list(CAT_W), weights=list(CAT_W.values()))[0]
                tr = [("お客様", f"もしもし、{ward}の{name}です。{SYMPTOM[cat][0]} 折り返しお電話いただけますか。番号は{num}です。")]
                fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "留守番電話"), ("着信した外線番号の名称", "代表"), ("通話時間", "00:00:38"), ("通話履歴URL", url)]
                msg = _mail(no, at, fields, tr)
            elif ev == "sales":
                tr = [("担当", f"お電話ありがとうございます。{COMPANY}の{staff}です。"), ("お客様", "お忙しいところすみません。ホームページ集客のご提案でお電話しました。ご担当の方はいらっしゃいますか。"), ("担当", "そういったお電話はお断りしております。失礼します。")]
                fields = [("相手先名称", ""), ("相手先電話番号", "03-0000-" + str(rng.randint(1000, 9999))), ("実行されたアクション", "応答"), ("着信した外線番号の名称", "代表"), ("応答者", staff), ("通話時間", f"00:0{rng.randint(1, 4)}:{rng.randint(10, 59)}"), ("通話履歴URL", url)]
                msg = _mail(no, at, fields, tr)
            elif ev == "scope":
                tr = [("担当", f"お電話ありがとうございます。{COMPANY}の{staff}です。"), ("お客様", "岐阜の高山なんですけど、トイレが詰まってしまって来てもらえますか。"), ("担当", "申し訳ございません。高山市は対応エリア外でして、お伺いできないんです。"), ("お客様", "そうですか、わかりました。")]
                fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "応答"), ("着信した外線番号の名称", "代表"), ("応答者", staff), ("通話時間", "00:01:05"), ("通話履歴URL", url)]
                msg = _mail(no, at, fields, tr)
            else:
                cat = rng.choices(list(CAT_W), weights=list(CAT_W.values()))[0]
                plan = _plan(rng, staff)
                tr, _, _ = _dialog(rng, staff, cat, name, ward, num, plan)
                dur = 60 + 18 * len(tr) + rng.randint(0, 60)
                fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "応答"), ("着信した外線番号の名称", "代表"), ("応答者", staff), ("通話時間", f"00:{dur // 60:02d}:{dur % 60:02d}"), ("通話履歴URL", url)]
                msg = _mail(no, at, fields, tr)
            with open(os.path.join(out_dir, "tobila", f"{at:%Y%m%d-%H%M}-{no}.eml"), "wb") as fh:
                fh.write(bytes(msg))
            n_mail += 1
    # 不在のあと、お客様から掛け直してきた電話（折り返し確認の判定に使う）
    for at, name, ward, num in later_callers:
        no += 1
        staff = rng.choice(staffs)
        cat = rng.choices(list(CAT_W), weights=list(CAT_W.values()))[0]
        tr, _, _ = _dialog(rng, staff, cat, name, ward, num, dict(outcome="成約"))
        tr.insert(1, ("お客様", "さっきお電話したんですけど、つながらなくて。"))
        fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "応答"), ("着信した外線番号の名称", "代表"), ("応答者", staff), ("通話時間", "00:03:40"), ("通話履歴URL", f"https://example.invalid/tobila/history/{no}")]
        with open(os.path.join(out_dir, "tobila", f"{at:%Y%m%d-%H%M}-{no}.eml"), "wb") as fh:
            fh.write(bytes(_mail(no, at, fields, tr)))
        n_mail += 1
    # デモで「いま届いた」ことにする分（届けるときに日時を今に書き換える）
    for k in range(pending):
        no += 1
        name, ward = rng.choice(NAMES), rng.choice(WARDS)
        num = _num(rng, used)
        staff = ["鈴木", "山田", "高橋"][k % 3]
        cat = ["水漏れ", "つまり", "害獣"][k % 3]
        plan = [dict(outcome="失注", reason="金額が分からない"), dict(outcome="成約"), dict(outcome="検討", reason="他社")][k % 3]
        tr, _, _ = _dialog(random.Random(seed + k), staff, cat, name, ward, num, plan)
        fields = [("相手先名称", f"{name}様"), ("相手先電話番号", num), ("実行されたアクション", "応答"), ("着信した外線番号の名称", "代表"), ("応答者", staff), ("通話時間", "00:03:05"), ("通話履歴URL", f"https://example.invalid/tobila/history/{no}")]
        with open(os.path.join(out_dir, "pending", f"pending-{k + 1}-{no}.eml"), "wb") as fh:
            fh.write(bytes(_mail(no, now_jst(), fields, tr)))
    n_visit = _visits(rng, os.path.join(out_dir, "plaud"), end, days)
    return dict(mails=n_mail, visits=n_visit, pending=pending)


def _seg(i, spk, text):
    return {"speaker": spk, "start_time": i * 9000, "end_time": i * 9000 + 8000, "content": text}


VISITS = [
    ("水漏れ", "good", [("話者1", f"{COMPANY}の山田です。本日はよろしくお願いいたします。"), ("話者2", "よろしくお願いします。台所なんです。"),
                      ("話者1", "拝見しますね。蛇口の中のパッキンが傷んでいます。作業前にお見積りをお伝えします。パッキン交換で、出張費込みで税込16,500円です。追加料金はかかりません。"),
                      ("話者2", "電話で聞いていた目安どおりですね。お願いします。"), ("話者1", "ありがとうございます。では作業に入らせていただきます。"),
                      ("話者1", "ついでに、シンク下の給水管も点検しておきましょうか。点検は無料です。"), ("話者2", "じゃあそれもお願いします。")]),
    ("つまり", "trouble", [("話者1", f"{COMPANY}の鈴木です。トイレのつまりですね。"), ("話者2", "はい、朝から全然流れなくて。"),
                         ("話者1", "奥のほうで詰まっていて、便器を外しての作業になります。税込38,500円になります。"),
                         ("話者2", "えっ、電話で聞いた金額と違いますね。そんなにかかるんですか。電話では金額を聞いてないんですけど。"),
                         ("話者1", "現地で見ないと分からないもので、申し訳ありません。"), ("話者2", "…じゃあ今日は見積もりだけでいいです。考えさせてください。")]),
    ("給湯器", "no_estimate", [("話者1", f"{COMPANY}の高橋です。給湯器ですね、さっそく作業に取りかかりますね。"), ("話者2", "お願いします。"),
                             ("話者1", "点火部の部品を交換しました。お湯が出るようになりました。"), ("話者1", "合計で22,000円になります。"),
                             ("話者2", "あ、そうなんですね。わかりました。")]),
    ("害獣", "lost", [("話者1", f"{COMPANY}の佐藤です。天井裏を調査しますね。"), ("話者2", "お願いします。毎晩うるさくて。"),
                    ("話者1", "侵入口が3か所ありました。作業前にお見積りをお伝えします。封鎖と消毒で税込55,000円です。追加料金はかかりません。"),
                    ("話者2", "うーん、思ったより高いので、考えさせてください。")]),
    ("つまり", "good", [("話者1", f"{COMPANY}の佐藤です。お風呂の排水ですね。"), ("話者2", "はい、流れが悪くて。"),
                      ("話者1", "排水管の途中に髪の毛がたまっています。作業前にお見積りをお伝えします。高圧洗浄で税込13,200円です。これ以上はかかりません。"),
                      ("話者2", "お願いします。"), ("話者1", "では作業を始めますね。")]),
    ("水漏れ", "good", [("話者1", f"{COMPANY}の山田です。洗面所の水漏れですね。"), ("話者2", "床が濡れてしまって。"),
                      ("話者1", "排水のナットがゆるんでいました。作業前にお見積りをお伝えします。締め直しとパッキン交換で税込9,900円です。追加料金はかかりません。"),
                      ("話者2", "お願いします。"), ("話者1", "あわせて、止水栓も点検しておきますね。")]),
    ("害虫", "good", [("話者1", f"{COMPANY}の高橋です。ハチの巣ですね。"), ("話者2", "軒下なんです。"),
                    ("話者1", "高さが3メートルほどなので、作業前にお見積りをお伝えします。税込16,500円です。追加料金はかかりません。"),
                    ("話者2", "それでいいです。お願いします。"), ("話者1", "では作業に取りかかります。")]),
    ("水漏れ", "trouble", [("話者1", f"{COMPANY}の鈴木です。キッチンの水漏れですね。"), ("話者2", "はい。"),
                         ("話者1", "水栓本体の交換が必要です。本体と工事で税込48,000円です。"),
                         ("話者2", "最初に言った話と違いますよね。電話では1万円くらいって。"), ("話者1", "パッキンだけで済めばその金額だったのですが…。"),
                         ("話者2", "今日はやめておきます。")]),
]
NOTES = {
    "good": "## 要約\n- 作業前に見積もりを伝え、了承を得て作業\n- 追加料金なしを説明\n## 次の対応\n- なし",
    "trouble": "## 要約\n- 見積もり金額が、電話で伝わっていた目安と違うと指摘あり\n- 本日は見積もりのみ\n## 次の対応\n- 電話での説明内容を確認",
    "no_estimate": "## 要約\n- 部品交換で給湯器が復旧\n- 金額は作業後に伝達\n## 次の対応\n- なし",
    "lost": "## 要約\n- 侵入口3か所、封鎖と消毒を提案\n- お客様は検討\n## 次の対応\n- 3日後に連絡",
}


def _visits(rng, d, end, days):
    for i, (cat, kind, lines) in enumerate(VISITS):
        day = end - dt.timedelta(days=days - 1 - (i * days // len(VISITS)) - 1)
        at = dt.datetime.combine(day, dt.time(10 + i % 6, 15), JST)
        segs = [_seg(k, s, t) for k, (s, t) in enumerate(lines)]
        obj = dict(sample=True, id=f"sample{i + 1:03d}", name=f"{at:%m/%d} {cat}の現場（見本）", created_at=at.isoformat(), start_at=at.isoformat(),
                   duration=len(lines) * 9000 + 60000, serial_number="SAMPLE", source_list=segs, note_list=[{"content": NOTES[kind]}])
        with open(os.path.join(d, f"visit-{i + 1:03d}.json"), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
    return len(VISITS)


def arrive(src_dir, inbox_dir, n=1):
    """pending の見本メールを n 通、inbox に「いま届いた」ものとして移す（日時を今に書き換える）。"""
    import email
    import email.policy
    ensure_dir(inbox_dir)
    files = sorted(f for f in os.listdir(src_dir) if f.endswith(".eml")) if os.path.isdir(src_dir) else []
    moved = []
    for f in files[:n]:
        p = os.path.join(src_dir, f)
        msg = email.message_from_binary_file(open(p, "rb"), policy=email.policy.default)
        del msg["Date"]
        msg["Date"] = format_datetime(now_jst())
        with open(os.path.join(inbox_dir, f"{now_jst():%Y%m%d-%H%M%S}-{f}"), "wb") as fh:
            fh.write(bytes(msg))
        os.remove(p)
        moved.append(f)
    return moved
