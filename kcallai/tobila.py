"""トビラフォン Cloud の取り込み。

本命は「着信通知メール」。トビラフォン Cloud は外線番号ごとに着信をメール・Slack・Teams へ通知でき、
通知には相手先名称・相手先電話番号・応答者・通話時間・通話履歴URL・音声テキスト内容が入る（公式ヘルプ
cloud-faq.tobilaphone.com/pages/217。着信方式が「コールフロー（IVR）」の番号だけ。発信は通知されない）。
メールなので、こちらから IMAP で読みに行くだけで済む（受け口のサーバーを外へ公開しない・Webhook 不要）。

**実物の通知メールの文面は未確認。** 項目名は公式ヘルプの一覧から作り、表記ゆれ（全角コロン・【】・■）を許す。
実物を1通もらったら LABELS を合わせること。読めなかった行は raw に残る。

補助として「一括操作」のダウンロード（録音データ＝mp3＋音声テキスト・要約のテキストファイル。公式ヘルプ
pages/17631）のテキストを取り込む import_download も持つ（こちらも実物の形は未確認）。
"""
import datetime as dt
import email
import email.policy
import hashlib
import html
import imaplib
import os
import re
from email.utils import parsedate_to_datetime

from . import db
from .util import JST, now_jst, parse_duration

LABELS = {
    "caller_name": ["相手先名称", "相手先名", "相手先"],
    "caller_number": ["相手先電話番号", "相手先番号", "発信者番号", "電話番号"],
    "ivr": ["選択した番号"],
    "ivr_name": ["着信番号名"],
    "action": ["実行されたアクション", "アクション", "着信結果"],
    "line_name": ["着信した外線番号の名称", "着信した外線番号", "外線番号名", "外線番号"],
    "staff": ["応答者", "対応者", "担当者"],
    "duration": ["通話時間"],
    "history_url": ["対象の通話履歴画面へ遷移するURL", "通話履歴URL", "通話履歴", "URL"],
    "started_at": ["着信日時", "発着信日時", "通話日時", "日時"],
    "transcript": ["音声テキスト内容", "音声テキスト化", "音声テキスト", "通話内容"],
    "summary": ["要約"],
}
_ALIAS = sorted(((a, k) for k, al in LABELS.items() for a in al), key=lambda x: -len(x[0]))
# 項目名のあとには区切り（】・]・コロン・空白）か行末が要る。「要約すると…」のような文中の言葉を項目と取り違えない
_LABEL_RE = re.compile(r"^[\s　]*[【\[■◆●・\-]*[\s　]*(" + "|".join(re.escape(a) for a, _ in _ALIAS) + r")(?:[】\]:：\s　]|$)[】\]\s　]*[:：]?[\s　]*(.*)$")
_KEY = {a: k for a, k in _ALIAS}


def html_to_text(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s)


# 音声テキスト・要約の途中で出てきても項目の切り替えとみなさない短い別名（会話の中に普通に出る言葉）
_WEAK = {"相手先", "電話番号", "アクション", "外線番号", "通話履歴", "URL", "日時", "担当者", "通話内容"}


def parse_body(text):
    """通知本文を項目ごとに読む。音声テキストと要約は、次の項目名が出るまでの複数行。"""
    out = {}
    cur = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _LABEL_RE.match(line)
        if m and not (cur in ("transcript", "summary") and m.group(1) in _WEAK):
            cur = _KEY[m.group(1)]
            val = m.group(2).strip()
            out[cur] = (val + "\n" if val else "") if cur in ("transcript", "summary") else val
            continue
        if cur in ("transcript", "summary"):
            out[cur] = out.get(cur, "") + line + "\n"
    for k in ("transcript", "summary"):
        if k in out:
            out[k] = out[k].strip()
    return out


def _iso(d):
    if d.tzinfo is None:
        d = d.replace(tzinfo=JST)
    return d.astimezone(JST).isoformat(timespec="seconds")


def _started(fields, msg_date):
    s = fields.get("started_at")
    if s:
        s2 = s.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d  %H:%M"):
            try:
                return _iso(dt.datetime.strptime(re.sub(r"\s+", " ", s2.strip()), fmt))
            except ValueError:
                pass
    return _iso(msg_date) if msg_date else _iso(now_jst())


def message_to_call(msg, source="tobila_mail"):
    """email.message.EmailMessage → calls の1行。トビラフォンの通知に見えなければ None。"""
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = html_to_text(text)
    f = parse_body(text)
    if not (f.get("caller_number") or f.get("transcript") or f.get("action")):
        return None
    try:
        md = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        md = None
    mid = (msg["Message-ID"] or "").strip() or hashlib.sha1(text.encode("utf-8")).hexdigest()
    action = f.get("action", "")
    tr = f.get("transcript", "")
    return dict(
        id="mail:" + mid, source=source, started_at=_started(f, md), direction="in",
        action=action or ("応答" if tr else ""), caller_name=f.get("caller_name", ""), caller_number=f.get("caller_number", ""),
        line_name=f.get("line_name", ""), ivr=" ".join(x for x in (f.get("ivr", ""), f.get("ivr_name", "")) if x),
        staff=f.get("staff", ""), duration_sec=parse_duration(f.get("duration")), history_url=f.get("history_url", ""),
        transcript=tr, summary=f.get("summary", ""), raw=text[:20000],
        sample=1 if (msg["X-Kcallai-Sample"] or "").strip() == "1" else 0, imported_at=now_jst().isoformat(timespec="seconds"))


def _want(cfg, msg):
    t = cfg.tobila
    if t.get("subject_contains") and t["subject_contains"] not in (msg["Subject"] or ""):
        return False
    if t.get("from_contains") and t["from_contains"] not in (msg["From"] or ""):
        return False
    return True


def _store(cfg, msgs, source_label):
    con = db.connect(cfg.db)
    added = skipped = notcall = 0
    for msg in msgs:
        if not _want(cfg, msg):
            skipped += 1
            continue
        row = message_to_call(msg)
        if not row:
            notcall += 1
            continue
        n = db.upsert(con, "calls", row)
        added += n
        skipped += 0 if n else 1
    con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?)", (now_jst().isoformat(timespec="seconds"), source_label, added, skipped, f"通知でないメール {notcall}"))
    con.commit()
    con.close()
    return dict(added=added, skipped=skipped, not_call=notcall)


def ingest_dir(cfg, path=None):
    """フォルダの .eml を読む（見本データや、メールソフトから書き出した通知の取り込みに使う）。"""
    d = cfg.path_of(path or cfg.tobila.get("dir", "inbox/tobila"))
    if not os.path.isdir(d):
        return dict(added=0, skipped=0, not_call=0, note=f"{d} がありません")
    msgs = []
    for name in sorted(os.listdir(d)):
        if name.endswith(".eml"):
            with open(os.path.join(d, name), "rb") as fh:
                msgs.append(email.message_from_binary_file(fh, policy=email.policy.default))
    return _store(cfg, msgs, "tobila_dir")


def ingest_imap(cfg, days=3):
    """通知用のメールボックスを IMAP で読む。既読にはしない（読み取り専用で開く）。取り込み済みは Message-ID で飛ばす。"""
    t = cfg.tobila
    user = os.environ.get(t.get("imap_user_env", "KCALLAI_IMAP_USER"), "")
    pw = os.environ.get(t.get("imap_password_env", "KCALLAI_IMAP_PASSWORD"), "")
    if not (t.get("imap_host") and user and pw):
        raise RuntimeError("IMAP の接続先・ユーザー・パスワード（環境変数）がそろっていません")
    since = (now_jst() - dt.timedelta(days=days)).strftime("%d-%b-%Y")
    m = imaplib.IMAP4_SSL(t["imap_host"], int(t.get("imap_port", 993)))
    try:
        m.login(user, pw)
        m.select(t.get("imap_folder", "INBOX"), readonly=True)
        typ, data = m.search(None, "SINCE", since)
        msgs = []
        for num in (data[0].split() if data and data[0] else []):
            typ, parts = m.fetch(num, "(BODY.PEEK[])")
            for p in parts:
                if isinstance(p, tuple):
                    msgs.append(email.message_from_bytes(p[1], policy=email.policy.default))
    finally:
        try:
            m.logout()
        except Exception:  # noqa
            pass
    return _store(cfg, msgs, "tobila_imap")


def import_download(cfg, path=None):
    """「一括操作」でダウンロードした録音データのテキストファイル（音声テキスト・要約入り）を取り込む。
    1ファイル＝1通話として、通知メールと同じ項目名で読む。項目名が無ければ全文を音声テキストとみなす。"""
    d = cfg.path_of(path or cfg.tobila.get("download_dir", "inbox/tobila_download"))
    con = db.connect(cfg.db)
    added = skipped = 0
    for root, _, files in os.walk(d):
        for name in sorted(files):
            if not name.lower().endswith(".txt"):
                continue
            p = os.path.join(root, name)
            raw = open(p, "rb").read()
            for enc in ("utf-8-sig", "cp932", "utf-16"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    text = None
            if text is None:
                skipped += 1
                continue
            f = parse_body(text)
            mt = dt.datetime.fromtimestamp(os.path.getmtime(p), JST)
            row = dict(id="dl:" + hashlib.sha1(raw).hexdigest(), source="tobila_download", started_at=_started(f, mt),
                       direction="", action=f.get("action", "応答"), caller_name=f.get("caller_name", ""), caller_number=f.get("caller_number", ""),
                       line_name=f.get("line_name", ""), ivr="", staff=f.get("staff", ""), duration_sec=parse_duration(f.get("duration")),
                       history_url=f.get("history_url", ""), transcript=f.get("transcript") or text.strip(), summary=f.get("summary", ""),
                       raw=text[:20000], sample=0, imported_at=now_jst().isoformat(timespec="seconds"))
            n = db.upsert(con, "calls", row)
            added += n
            skipped += 0 if n else 1
    con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?)", (now_jst().isoformat(timespec="seconds"), "tobila_download", added, skipped, ""))
    con.commit()
    con.close()
    return dict(added=added, skipped=skipped)


def ingest(cfg):
    mode = cfg.tobila.get("mode", "dir")
    if mode == "imap":
        return ingest_imap(cfg, int(cfg.tobila.get("days", 3)))
    if mode == "dir":
        return ingest_dir(cfg)
    return dict(added=0, skipped=0, note="tobila.mode が off")
