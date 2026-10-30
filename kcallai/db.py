import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id TEXT PRIMARY KEY,          -- 取り込み元ごとに一意（メールの Message-ID など）
  source TEXT,                  -- tobila_mail / tobila_download / manual
  started_at TEXT,              -- ISO8601（JST）
  direction TEXT,               -- in / out
  action TEXT,                  -- 応答 / 不在着信 / 留守番電話 など（通知の「実行されたアクション」）
  caller_name TEXT, caller_number TEXT, line_name TEXT, ivr TEXT,
  staff TEXT, duration_sec INTEGER, history_url TEXT,
  transcript TEXT, summary TEXT, raw TEXT, sample INTEGER DEFAULT 0,
  imported_at TEXT);
CREATE TABLE IF NOT EXISTS visits (
  id TEXT PRIMARY KEY, source TEXT, name TEXT, started_at TEXT, duration_sec INTEGER,
  segments TEXT,                -- JSON [{speaker, start_ms, text}]
  note TEXT,                    -- PLAUD の AI 要約（Markdown）
  staff TEXT, raw TEXT, sample INTEGER DEFAULT 0, imported_at TEXT);
CREATE TABLE IF NOT EXISTS analysis (
  kind TEXT, item_id TEXT, analyzed_at TEXT, category TEXT, outcome TEXT,
  reasons TEXT, checks TEXT, evidence TEXT, flags TEXT,
  PRIMARY KEY (kind, item_id));
CREATE TABLE IF NOT EXISTS ingest_log (
  at TEXT, source TEXT, added INTEGER, skipped INTEGER, note TEXT);
"""


def connect(path):
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert(con, table, row, replace=False):
    cols = list(row.keys())
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    cur = con.execute(f"{verb} INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
    return cur.rowcount


def q(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def loads(s, default=None):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default
