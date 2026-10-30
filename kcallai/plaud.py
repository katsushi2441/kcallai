"""PLAUD（現場・商談の録音）の取り込み。

PLAUD は公式に MCP と CLI を出していて（docs.plaud.ai/plaud-mcp-cli/）、自分の録音・文字起こし・AI 要約を取り出せる。
法人向け規約は画面からの抜き出し（scraping）を禁じているので、画面の自動操作は使わない。

- dir モード: get_file と同じ項目（id・name・start_at・duration[ms]・source_list・note_list）の JSON を読む。
  MCP（get_file）で取り出した結果を置く場合や、見本データに使う。
- cli モード: 公式 CLI（`plaud recent --days N`・`plaud transcript <id> -o`・`plaud summary <id> -o`）を呼ぶ。
  ログインは最初に一度 `plaud login`（ブラウザで許可）。トークンは ~/.plaud/tokens.json に保存される。
  **CLI の出力の細かい形は実アカウントで未確認。** 一覧から録音 ID を拾う正規表現は plaud.id_regex で変えられる。
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile

from . import db
from .util import now_jst

SEG_TEXT = ("content", "text", "sentence", "transcript")
SEG_SPK = ("speaker", "speaker_name", "speaker_label", "role")
SEG_START = ("start_time", "start", "start_ms", "begin_time", "offset")


def _first(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def segments_from_list(source_list):
    out = []
    for s in source_list or []:
        if isinstance(s, str):
            out.append(dict(speaker="", start_ms=None, text=s))
            continue
        t = _first(s, SEG_TEXT, "")
        if not t:
            continue
        st = _first(s, SEG_START)
        try:
            st = int(float(st))
        except (TypeError, ValueError):
            st = None
        out.append(dict(speaker=str(_first(s, SEG_SPK, "")), start_ms=st, text=str(t).strip()))
    return out


_LINE = re.compile(r"^\s*(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*)?(?:([^:：\s][^:：]{0,20})[:：]\s*)?(.+)$")


def segments_from_text(text):
    """「[00:01:23] 話者1: こんにちは」のような行を区切る。形が違っても本文は落とさない。"""
    out = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = _LINE.match(line)
        ts, spk, body = m.group(1), m.group(2), m.group(3)
        ms = None
        if ts:
            p = [int(x) for x in ts.split(":")]
            ms = (p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]) * 1000
        out.append(dict(speaker=(spk or "").strip(), start_ms=ms, text=body.strip()))
    return out


def notes_text(note_list):
    parts = []
    for n in note_list or []:
        parts.append(n if isinstance(n, str) else str(_first(n, ("content", "markdown", "text", "note"), "")))
    return "\n\n".join(p for p in parts if p).strip()


def _row(d, source):
    rid = str(d.get("id") or hashlib.sha1(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
    dur = d.get("duration")
    try:
        dur = int(float(dur) / 1000) if dur is not None else None
    except (TypeError, ValueError):
        dur = None
    segs = segments_from_list(d.get("source_list")) if d.get("source_list") else segments_from_text(d.get("transcript", ""))
    return dict(id="plaud:" + rid, source=source, name=d.get("name", ""), started_at=d.get("start_at") or d.get("created_at") or "",
                duration_sec=dur, segments=json.dumps(segs, ensure_ascii=False), note=notes_text(d.get("note_list")) or d.get("summary", ""),
                staff=d.get("staff", ""), raw=json.dumps(d, ensure_ascii=False)[:50000], sample=1 if d.get("sample") else 0,
                imported_at=now_jst().isoformat(timespec="seconds"))


def ingest_dir(cfg, path=None):
    d = cfg.path_of(path or cfg.plaud.get("dir", "inbox/plaud"))
    if not os.path.isdir(d):
        return dict(added=0, skipped=0, note=f"{d} がありません")
    con = db.connect(cfg.db)
    added = skipped = 0
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(d, name), encoding="utf-8"))
        except ValueError:
            skipped += 1
            continue
        for item in data if isinstance(data, list) else [data]:
            n = db.upsert(con, "visits", _row(item, "plaud_dir"))
            added += n
            skipped += 0 if n else 1
    con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?)", (now_jst().isoformat(timespec="seconds"), "plaud_dir", added, skipped, ""))
    con.commit()
    con.close()
    return dict(added=added, skipped=skipped)


def _run(cmd, timeout=120):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode == 2:
        raise RuntimeError("PLAUD の認証が切れています。`plaud login` をやり直してください")
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} が失敗 ({p.returncode}): {p.stderr[-300:]}")
    return p.stdout


def ingest_cli(cfg):
    pc = cfg.plaud
    exe = pc.get("command", "plaud")
    days = str(int(pc.get("days", 2)))
    listing = _run([exe, "recent", "--days", days])
    ids = list(dict.fromkeys(re.findall(pc.get("id_regex", r"\b[0-9a-f]{16,}\b"), listing)))
    con = db.connect(cfg.db)
    have = {r["id"] for r in db.q(con, "SELECT id FROM visits")}
    added = skipped = 0
    with tempfile.TemporaryDirectory() as tmp:
        for rid in ids:
            if "plaud:" + rid in have:
                skipped += 1
                continue
            tp, sp = os.path.join(tmp, rid + ".txt"), os.path.join(tmp, rid + ".md")
            _run([exe, "transcript", rid, "-o", tp])
            try:
                _run([exe, "summary", rid, "-o", sp])
                summary = open(sp, encoding="utf-8").read()
            except RuntimeError:
                summary = ""
            meta = {}
            try:
                info = _run([exe, "file", rid])
                for k in ("name", "start_at", "duration"):
                    m = re.search(rf"{k}\s*[:：]\s*(.+)", info)
                    if m:
                        meta[k] = m.group(1).strip()
            except RuntimeError:
                pass
            d = dict(id=rid, name=meta.get("name", ""), start_at=meta.get("start_at", ""), duration=meta.get("duration"),
                     transcript=open(tp, encoding="utf-8").read(), summary=summary)
            added += db.upsert(con, "visits", _row(d, "plaud_cli"))
    con.execute("INSERT INTO ingest_log VALUES (?,?,?,?,?)", (now_jst().isoformat(timespec="seconds"), "plaud_cli", added, skipped, f"一覧のID {len(ids)}"))
    con.commit()
    con.close()
    return dict(added=added, skipped=skipped, listed=len(ids))


def ingest(cfg):
    mode = cfg.plaud.get("mode", "dir")
    if mode == "cli":
        return ingest_cli(cfg)
    if mode == "dir":
        return ingest_dir(cfg)
    return dict(added=0, skipped=0, note="plaud.mode が off")
