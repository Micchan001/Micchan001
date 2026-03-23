"""
AI秘書スクリプト
Claude APIとGmail/Google Calendar APIを使ってメッセージ確認・タスク管理を行う
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Any

import anthropic
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]
ALL_SCOPES = GMAIL_SCOPES + CALENDAR_SCOPES

# ツール定義
TOOLS = [
    {
        "name": "gmail_search",
        "description": "Gmailでメールを検索する",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail検索クエリ (例: 'is:unread newer_than:1d')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "取得する最大件数",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_get_message",
        "description": "特定のメールの詳細を取得する",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "メールID",
                },
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "gmail_create_draft",
        "description": "メールの返信ドラフトを作成する",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "宛先メールアドレス"},
                "subject": {"type": "string", "description": "件名"},
                "body": {"type": "string", "description": "本文"},
                "thread_id": {
                    "type": "string",
                    "description": "返信するスレッドID（オプション）",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "calendar_list_events",
        "description": "Google Calendarのイベント一覧を取得する",
        "input_schema": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "今から何日先までのイベントを取得するか",
                    "default": 7,
                },
            },
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Google Calendarにイベントを作成する",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "イベントのタイトル"},
                "description": {
                    "type": "string",
                    "description": "イベントの詳細説明",
                },
                "start_datetime": {
                    "type": "string",
                    "description": "開始日時 (ISO 8601形式: 2024-01-15T10:00:00 または終日の場合 2024-01-15)",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "終了日時 (ISO 8601形式)",
                },
                "is_all_day": {
                    "type": "boolean",
                    "description": "終日イベントかどうか",
                    "default": False,
                },
            },
            "required": ["summary", "start_datetime", "end_datetime"],
        },
    },
]


class GoogleAuthClient:
    """Google API認証クライアント"""

    def __init__(self, credentials_file: str = "credentials.json", token_file: str = "token.json"):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.creds = None

    def get_credentials(self) -> Credentials:
        if os.path.exists(self.token_file):
            self.creds = Credentials.from_authorized_user_file(self.token_file, ALL_SCOPES)

        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, ALL_SCOPES)
                self.creds = flow.run_local_server(port=0)

            with open(self.token_file, "w") as token:
                token.write(self.creds.to_json())

        return self.creds


class GmailClient:
    """Gmail APIクライアント"""

    def __init__(self, credentials: Credentials):
        self.service = build("gmail", "v1", credentials=credentials)

    def search_messages(self, query: str, max_results: int = 20) -> list[dict]:
        results = self.service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        return messages

    def get_message(self, message_id: str) -> dict[str, Any]:
        message = self.service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in message["payload"].get("headers", [])}

        body = ""
        payload = message["payload"]
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    import base64
                    body = base64.urlsafe_b64decode(part["body"].get("data", "")).decode("utf-8", errors="replace")
                    break
        elif payload.get("body", {}).get("data"):
            import base64
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        return {
            "id": message_id,
            "thread_id": message.get("threadId"),
            "subject": headers.get("Subject", "(件名なし)"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "body": body[:2000],  # 長すぎる場合は切り詰め
        }

    def create_draft(self, to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(body, "plain", "utf-8")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        draft_body: dict[str, Any] = {"message": {"raw": raw}}
        if thread_id:
            draft_body["message"]["threadId"] = thread_id

        draft = self.service.users().drafts().create(userId="me", body=draft_body).execute()
        return draft


class CalendarClient:
    """Google Calendar APIクライアント"""

    def __init__(self, credentials: Credentials):
        self.service = build("calendar", "v3", credentials=credentials)

    def list_events(self, days_ahead: int = 7) -> list[dict]:
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        events_result = self.service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = events_result.get("items", [])
        return [
            {
                "id": e["id"],
                "summary": e.get("summary", "(タイトルなし)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
                "description": e.get("description", ""),
            }
            for e in events
        ]

    def create_event(
        self,
        summary: str,
        start_datetime: str,
        end_datetime: str,
        description: str = "",
        is_all_day: bool = False,
    ) -> dict:
        if is_all_day:
            event = {
                "summary": summary,
                "description": description,
                "start": {"date": start_datetime},
                "end": {"date": end_datetime},
            }
        else:
            event = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_datetime, "timeZone": "Asia/Tokyo"},
                "end": {"dateTime": end_datetime, "timeZone": "Asia/Tokyo"},
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 24 * 60},
                        {"method": "popup", "minutes": 30},
                    ],
                },
            }

        created = self.service.events().insert(calendarId="primary", body=event).execute()
        return created


class SecretaryAgent:
    """AI秘書エージェント"""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        auth = GoogleAuthClient(
            credentials_file=os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
            token_file=os.environ.get("GOOGLE_TOKEN_FILE", "token.json"),
        )
        creds = auth.get_credentials()
        self.gmail = GmailClient(creds)
        self.calendar = CalendarClient(creds)

    def process_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """ツール呼び出しを処理する"""
        try:
            if tool_name == "gmail_search":
                messages = self.gmail.search_messages(
                    tool_input["query"],
                    tool_input.get("max_results", 20),
                )
                return json.dumps(messages, ensure_ascii=False)

            elif tool_name == "gmail_get_message":
                message = self.gmail.get_message(tool_input["message_id"])
                return json.dumps(message, ensure_ascii=False)

            elif tool_name == "gmail_create_draft":
                draft = self.gmail.create_draft(
                    to=tool_input["to"],
                    subject=tool_input["subject"],
                    body=tool_input["body"],
                    thread_id=tool_input.get("thread_id"),
                )
                return json.dumps({"success": True, "draft_id": draft.get("id")}, ensure_ascii=False)

            elif tool_name == "calendar_list_events":
                events = self.calendar.list_events(tool_input.get("days_ahead", 7))
                return json.dumps(events, ensure_ascii=False)

            elif tool_name == "calendar_create_event":
                event = self.calendar.create_event(
                    summary=tool_input["summary"],
                    start_datetime=tool_input["start_datetime"],
                    end_datetime=tool_input["end_datetime"],
                    description=tool_input.get("description", ""),
                    is_all_day=tool_input.get("is_all_day", False),
                )
                return json.dumps(
                    {"success": True, "event_id": event.get("id"), "html_link": event.get("htmlLink")},
                    ensure_ascii=False,
                )

            return json.dumps({"error": f"不明なツール: {tool_name}"})

        except Exception as e:
            logger.error(f"ツール実行エラー ({tool_name}): {e}")
            return json.dumps({"error": str(e)})

    def run(self) -> str:
        """秘書エージェントを実行する"""
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        logger.info(f"AI秘書を開始します: {now}")

        system_prompt = f"""あなたはAI秘書です。現在時刻は {now} です。

以下の手順でメッセージ確認とタスク管理を行ってください：

1. **Gmailの未読メール確認**: 過去24時間の未読メールを検索し、重要なものは内容を確認する
2. **タスク・締め切りの抽出**: 各メールから期限・依頼事項・返信が必要なものを抽出
3. **カレンダー確認**: 今後1週間の予定を確認
4. **カレンダー登録**: 抽出したタスク・締め切りをカレンダーに登録（重複は避ける）
5. **返信ドラフト作成**: 返信が必要なメールの返信文を作成してドラフト保存
6. **レポート作成**: 実行結果をまとめたレポートを日本語で出力

注意事項：
- 返信ドラフトは必ずユーザーが確認してから送信すること
- カレンダー登録前に既存のイベントと重複がないか確認すること
- タスクの優先度を明確に示すこと（🔴緊急、🟡重要、🟢通常）
"""

        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": "メッセージを確認して、タスク管理と秘書業務を実行してください。",
            }
        ]

        # エージェントループ
        while True:
            response = self.client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            logger.info(f"Claude応答: stop_reason={response.stop_reason}")

            # アシスタントの返答をメッセージ履歴に追加
            messages.append({"role": "assistant", "content": response.content})

            # ツール使用がない場合は終了
            if response.stop_reason != "tool_use":
                break

            # ツール呼び出しを処理
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"ツール呼び出し: {block.name} - 入力: {block.input}")
                    result = self.process_tool_call(block.name, block.input)
                    logger.info(f"ツール結果: {result[:200]}...")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})

        # 最終テキスト応答を返す
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        return final_text


def main():
    agent = SecretaryAgent()
    report = agent.run()
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)


if __name__ == "__main__":
    main()
