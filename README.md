# Kurage 通話AI分析（kcallai）

電話の文字起こし（トビラフォン Cloud の着信通知メール）と、現場の会話の文字起こし（PLAUD）を毎朝取り込み、
**成約・失注・検討、失注の理由、電話応対で言えていないこと、折り返しが要る電話、現場の金額トラブルの兆し**をまとめて、
経営者の LINE とメールに届けます。画面（ダッシュボード・電話の一覧・失注の分析・担当者・現場の会話・日報）も付きます。

- **AI が無くても全部動きます。** 判定は決まった言葉で行います（`kcallai/rules.py` の KEYWORDS。設定の `keywords` で御社の言い回しを足せます）。
- AI は日報の言い換えだけです。Claude Code（`claude -p`）・Codex（`codex exec`）・OpenAI 互換の API・社内の Ollama から選べます。数字は日報の中のものだけを使わせます。
- **受け口のサーバーを外へ公開しません。** 取り込みはこちらから読みに行き（IMAP・公式 CLI）、通知は外へ送るだけ（LINE Messaging API の push・SMTP）。
- 依存は Python 3.10 以上の標準ライブラリと `requests` だけ。社内のサーバー1台（Linux）で cron か systemd で動かします。

- デモ（見本データ）: https://proto.exbridge.jp/kcallai/
- 商品ページ（Kurage App Store）: https://kappstore.exbridge.jp/app.php?id=040964c27c153ec2

## 取り込み元

| 取り込み元 | 方法 | 公式の根拠 |
|---|---|---|
| トビラフォン Cloud（着信） | 外線番号の「着信を通知」をメールにして、通知用のメールボックスを IMAP で読む | 通知には相手先名称・相手先電話番号・応答者・通話時間・通話履歴URL・音声テキスト内容が入る（cloud-faq.tobilaphone.com/pages/217）。着信方式が「コールフロー（IVR）」の番号だけ。発信は通知されない |
| トビラフォン Cloud（発信・過去分） | 通話履歴の「一括操作」でダウンロードした録音データのテキストを `import-download` で取り込む | 録音データには mp3 のほか音声テキスト・要約のテキストが入る（pages/17631） |
| PLAUD | 公式 CLI（`plaud recent` / `transcript` / `summary`）か、MCP（get_file）の結果の JSON | docs.plaud.ai/plaud-mcp-cli/ 。画面の自動操作（scraping）は規約で禁止なので使わない |

**実物の通知メールの文面と CLI の出力の細かい形は、導入時に実物で合わせます。** 項目名の表記ゆれ（全角コロン・【】・■）は読めるようにしてあり、
読めない行は `raw` に残ります（`kcallai/tobila.py` の LABELS、`kcallai/plaud.py`）。

## 判定すること

- 1件ごと: 用件（水漏れ・つまり・給湯器・害虫・害獣・電気・不用品）、結果（成約・失注・検討・不明・不在・留守電・営業電話・対象外）、
  失注・検討の理由（価格・金額が分からない・日程・他社と比較・自分で対応・不安・家族と相談）、応対の確認（名乗り・用件の確認・お名前・住所・料金の目安・到着の時刻・復唱・お礼）
- まとめ（直近7日と前の7日）: 失注の理由の内訳、**料金の目安・到着の時刻・名乗りを言った電話と言わなかった電話の成約率の差**、担当者ごとの抜け、
  **折り返しが確認できない不在着信・留守電**、営業電話の件数と時間、現場の「電話で聞いた金額と違う」などの金額トラブルの兆し、作業前の見積もりの説明の有無

## 使い方

```bash
python3 -m kcallai init                    # kcallai.json のひな形
python3 -m kcallai run                     # 取り込み → 判定 → 日報 → 通知（毎朝 cron で）
python3 -m kcallai run --ai --no-notify    # AI の要点を付けて、通知はしない
python3 -m kcallai import-download <dir>   # トビラフォンの一括ダウンロード
python3 -m kcallai web --host 0.0.0.0 --port 8080
```

見本データで試す（架空の水まわり修理会社。人名・番号・会社はすべて架空）:

```bash
cp examples/kcallai.sample.json kcallai.json
python3 -m kcallai sample && python3 -m kcallai run --no-notify && python3 -m kcallai web
python3 -m kcallai arrive -n 1             # 見本の新着を「いま届いた」ことにする
```

秘密（IMAP のパスワード・LINE のトークン・画面のパスワード）は設定ファイルに書かず、環境変数の名前だけを書きます（`examples/env.example`）。

## ライセンス

MIT。株式会社エクスブリッジ。
