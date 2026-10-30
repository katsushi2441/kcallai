import datetime as dt
import json
import os
import re

JST = dt.timezone(dt.timedelta(hours=9))


def now_jst():
    return dt.datetime.now(JST)


def today_jst():
    return now_jst().date()


def parse_date(s):
    if s in (None, "", "yesterday"):
        return today_jst() - dt.timedelta(days=1)
    if s == "today":
        return today_jst()
    return dt.date.fromisoformat(s)


def ymd(d):
    return d.strftime("%Y-%m-%d")


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)
    return p


def dump_json(path, obj):
    ensure_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def norm(s):
    """照合用に正規化する（全角英数→半角、空白除去）。表示には使わない。"""
    if not s:
        return ""
    s = s.translate(str.maketrans("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ：",
                                    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz:"))
    return re.sub(r"[\s　]+", "", s)


def digits(s):
    return re.sub(r"\D", "", s or "")


def parse_duration(s):
    """「00:03:12」「3分12秒」「192秒」「192」を秒にする。読めなければ None。"""
    if s is None:
        return None
    s = norm(str(s))
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+)", s)
    if m:
        h, mi, se = int(m.group(1) or 0), int(m.group(2)), int(m.group(3))
        return h * 3600 + mi * 60 + se
    m = re.fullmatch(r"(?:(\d+)時間)?(?:(\d+)分)?(?:(\d+)秒)?", s)
    if m and any(m.groups()):
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    if s.isdigit():
        return int(s)
    return None


def fmt_dur(sec):
    if sec is None:
        return "-"
    return f"{sec // 60}分{sec % 60:02d}秒"


def pct(a, b):
    return (a / b) if b else 0.0


def fmt_pct(v):
    return f"{v * 100:.0f}%"
