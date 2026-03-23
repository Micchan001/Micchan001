# AI秘書アシスタント

Gmail・Google Calendarを使ったAI秘書システムです。

## セットアップ

```bash
# 依存関係インストール
pip install -r requirements.txt

# 環境変数設定
cp .env.example .env
# .env を編集して各APIキーを設定
```

## Google API 認証設定

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. Gmail API と Google Calendar API を有効化
3. OAuth 2.0 クライアント認証情報をダウンロードして `credentials.json` として保存
4. 初回実行時にブラウザで認証を行う（`token.json` が自動生成される）

## 使い方

### Claude Code スラッシュコマンド（推奨）

Claude Codeで `/secretary` を実行すると、MCP経由でGmail・Calendarにアクセスします。

### スタンドアロンスクリプト

```bash
# 1回だけ実行
./run_secretary.sh --once

# 60分ごとに定期実行
./run_secretary.sh --interval 60
```

## Slack連携

Slack連携には追加で `slack-sdk` のインストールと `SLACK_BOT_TOKEN` の設定が必要です。

```bash
pip install slack-sdk
# .env に SLACK_BOT_TOKEN=xoxb-... を追加
```

## 定期実行（cron）

`crontab.example` を参照してください。
