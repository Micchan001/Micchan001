# 発注自動化システム セットアップ手順

## 全体構成

```
Google Form or Slack @メンション
        ↓（自動）
Google Apps Script（Googleクラウド上）
        ↓ マスターシートを参照
注文ログシートに記録
        ↓（隔週月曜 9時 自動）
Gmail 下書き作成（業者ごと）
        ↓
確認して送信 ✓
```

---

## 前提

- 発注用の **別Googleアカウント** でログインして作業すること
- 以下のGoogleサービスをそのアカウントで使用します
  - Google スプレッドシート（マスターシート + 注文ログ）
  - Google Apps Script
  - Gmail（下書き作成先）
  - Google フォーム（任意）

---

## STEP 1: スプレッドシートの準備

1. 既存のマスターシートを **発注用Googleアカウント** のドライブに移動（またはコピー）
2. シート名を `マスター` に変更（または `Code.gs` の `MASTER_SHEET_NAME` を実際のシート名に変更）
3. マスターシートの列順を確認：

| A | B | C | D | E | F（任意） |
|---|---|---|---|---|---|
| 注文した商品 | メーカー | 商品ナンバー | 個数 | 発注業者 | メールアドレス |

※ F列（メールアドレス）は空欄のままでOK。下書きに宛先が入らないので送信前に手動入力。

---

## STEP 2: Google Apps Script の作成

1. スプレッドシートを開く
2. メニュー「拡張機能」→「Apps Script」を開く
3. `Code.gs` の内容を全コピーして貼り付け、保存（Ctrl+S）

---

## STEP 3: Slack アプリの作成

1. [https://api.slack.com/apps](https://api.slack.com/apps) にアクセス（Slackアカウントでログイン）
2. 「Create New App」→「From scratch」
3. アプリ名（例：`発注bot`）とワークスペースを選択

### Bot Token の取得
1. 左メニュー「OAuth & Permissions」
2. 「Bot Token Scopes」に以下を追加：
   - `chat:write`（メッセージ送信）
   - `app_mentions:read`（@メンション読み取り）
3. 「Install to Workspace」→「許可する」
4. **Bot User OAuth Token** (`xoxb-...`) をコピー

### スクリプトプロパティに登録
1. Apps Script エディタで「プロジェクトの設定」（歯車アイコン）
2. 「スクリプト プロパティ」→「プロパティを追加」
3. 以下を追加：
   - キー: `SLACK_BOT_TOKEN` / 値: `xoxb-...（コピーしたトークン）`

---

## STEP 4: Web アプリとしてデプロイ

1. Apps Script エディタ右上「デプロイ」→「新しいデプロイ」
2. 種類「ウェブアプリ」を選択
3. 設定：
   - 実行ユーザー: **自分**
   - アクセスできるユーザー: **全員**
4. 「デプロイ」→ **ウェブアプリのURL** をコピー（`https://script.google.com/macros/s/...`）

---

## STEP 5: Slack Event Subscriptions の設定

1. Slack App の管理画面「Event Subscriptions」
2. Enable Events を **On** にする
3. Request URL に STEP 4 でコピーした **ウェブアプリのURL** を貼り付け
4. ✅ Verified と表示されればOK
5. 「Subscribe to bot events」→「Add Bot User Event」
   - `app_mention` を追加
6. 「Save Changes」
7. アプリを **ワークスペースに再インストール**（設定変更後は必要）

### Slackチャンネルにbotを招待
```
/invite @発注bot
```

---

## STEP 6: Google Form との連携（任意）

1. Google フォームを作成。質問例：
   - 「注文する商品名」（記述式）
   - 「個数」（記述式 or 数値）
   - 「依頼者名」（記述式）
2. フォームの回答スプレッドシートではなく、**マスターシートのGASから** フォームとリンク
   - Apps Script エディタ「トリガーを追加」（時計アイコン）
   - 関数: `onFormSubmit` / イベントソース: フォームから / イベントの種類: フォーム送信時

---

## STEP 7: 時間トリガーの設定

Apps Script エディタのコンソールで `setupTriggers` 関数を一度だけ実行：

1. 関数プルダウンで `setupTriggers` を選択
2. 「実行」ボタンを押す
3. 隔週月曜 9時に `generateOrderDrafts` が自動実行されます

手動で下書きを作りたい場合は `generateOrderDrafts` を直接実行してもOK。

---

## 使い方

### Slackから注文する
```
@発注bot スキャット20X-N 3個
@発注bot All-Trans-Retinal 2本
@発注bot イミダゾール
```
→ botが「✅ 注文を受け付けました」と返信

### 隔週月曜に自動で起こること
- 「未発注」ステータスの注文をまとめる
- 発注業者ごとにGmailの**下書き**を作成
- 下書きの件名例：`【発注依頼】理科研（2026年4月6日）`

### 下書き確認 → 送信
1. Gmail の下書きを開く
2. 宛先メールアドレスを入力
3. 内容を確認して送信

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| Slackで商品が見つからないと言われる | マスターシートの商品名を確認。部分一致で検索しています |
| 下書きが作成されない | 注文ログシートに「未発注」のデータがあるか確認 |
| Slack URL Verificationが通らない | デプロイのアクセス権限が「全員」になっているか確認 |
| トリガーが動かない | Apps Scriptのトリガー一覧（時計アイコン）で確認 |
