import os

from .util import load_json

DEFAULT_RULES = {
    "report_days": 7,          # 日報の「直近7日 vs その前7日」
    "min_calls_compare": 5,    # 比較（料金の目安あり/なし など）に要る最低件数
    "compare_gap": 0.15,       # 成約率の差がこの値（15ポイント）以上なら指摘
    "callback_hours": 24,      # 不在着信のあと、この時間内に同じ番号と話していなければ「折り返し未確認」
    "staff_prefixes": ["担当", "自分", "オペレーター", "スタッフ", "当社"],
    "customer_prefixes": ["お客様", "相手", "顧客", "お客さま"],
    "plaud_staff_speaker": "auto",   # PLAUD の話者のうちどれが担当か。auto=最初に話した人
}


class Config:
    def __init__(self, path):
        self.path = path
        self.raw = load_json(path) or {}
        self.base = os.path.dirname(os.path.abspath(path))
        self.name = self.raw.get("name", "")                  # 画面に出す会社名・呼び名
        self.company_words = self.raw.get("company_words", [])  # 名乗りの判定に使う社名（例: ["アスリンク"]）
        self.outputs = self._abs(self.raw.get("outputs", "outputs"))
        self.db = self._abs(self.raw.get("db", os.path.join(self.outputs, "kcallai.db")))
        self.sample = bool(self.raw.get("sample", False))      # 見本データで動かしているとき true（画面に帯を出す）
        self.rules = dict(DEFAULT_RULES)
        self.rules.update(self.raw.get("rules", {}))
        self.keywords = self.raw.get("keywords", {})          # 判定語の追加・上書き（rules.py の KEYWORDS と同じ形）
        self.tobila = self.raw.get("tobila", {}) or {}
        self.plaud = self.raw.get("plaud", {}) or {}
        self.ai = self.raw.get("ai", {}) or {}
        self.line = self.raw.get("line", {}) or {}
        self.email = self.raw.get("email", {}) or {}
        self.web = self.raw.get("web", {}) or {}

    def _abs(self, p):
        if not p:
            return p
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(self.base, p)

    def path_of(self, p):
        return self._abs(p)


EXAMPLE = {
    "name": "（会社の呼び名）",
    "company_words": ["（電話で名乗る社名）"],
    "outputs": "outputs",
    "sample": False,
    "rules": {k: v for k, v in DEFAULT_RULES.items()},
    "keywords": {},
    "tobila": {
        "mode": "imap",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_user_env": "KCALLAI_IMAP_USER",
        "imap_password_env": "KCALLAI_IMAP_PASSWORD",
        "imap_folder": "INBOX",
        "subject_contains": "",
        "from_contains": "",
        "dir": "inbox/tobila",
        "download_dir": "inbox/tobila_download",
    },
    "plaud": {
        "mode": "cli",
        "command": "plaud",
        "days": 2,
        "dir": "inbox/plaud",
    },
    "ai": {
        "enabled": False,
        "command": "claude -p",
        "openai_base_url": "",
        "openai_model": "",
        "openai_api_key_env": "OPENAI_API_KEY",
        "ollama_url": "",
        "ollama_model": "",
        "timeout": 300,
    },
    "line": {
        "enabled": False,
        "channel_access_token_env": "LINE_CHANNEL_ACCESS_TOKEN",
        "to": [],
    },
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "user_env": "SMTP_USER",
        "password_env": "SMTP_PASSWORD",
        "from": "",
        "to": [],
    },
    "web": {
        "password": "",
        "password_env": "KCALLAI_WEB_PASSWORD",
        "host": "127.0.0.1",
        "port": 8080,
    },
}
