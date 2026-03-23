"""
Slack APIクライアント
Slack SDK を使ってメッセージを取得する
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class SlackClient:
    """Slack APIクライアント"""

    def __init__(self, token: str | None = None):
        self.token = token or os.environ.get("SLACK_BOT_TOKEN")
        if not self.token:
            raise ValueError("SLACK_BOT_TOKEN が設定されていません")
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from slack_sdk import WebClient
            self._client = WebClient(token=self.token)
        return self._client

    def get_unread_messages(self, hours_ago: int = 24) -> list[dict[str, Any]]:
        """未読・最近のメッセージを取得する"""
        oldest = (datetime.now() - timedelta(hours=hours_ago)).timestamp()
        messages = []

        # DMチャンネルを取得
        try:
            dms = self.client.conversations_list(types="im", limit=20)
            for channel in dms.get("channels", []):
                channel_messages = self._get_channel_messages(channel["id"], oldest, is_dm=True)
                messages.extend(channel_messages)
        except Exception as e:
            logger.warning(f"DM取得エラー: {e}")

        # メンションされたメッセージを取得
        try:
            mentions = self.client.search_messages(
                query="to:me",
                sort="timestamp",
                count=20,
            )
            for msg in mentions.get("messages", {}).get("matches", []):
                if float(msg.get("ts", 0)) >= oldest:
                    messages.append({
                        "channel": msg.get("channel", {}).get("name", "unknown"),
                        "user": msg.get("username", "unknown"),
                        "text": msg.get("text", ""),
                        "timestamp": msg.get("ts", ""),
                        "type": "mention",
                    })
        except Exception as e:
            logger.warning(f"メンション取得エラー: {e}")

        return messages

    def _get_channel_messages(
        self, channel_id: str, oldest: float, is_dm: bool = False
    ) -> list[dict[str, Any]]:
        """チャンネルのメッセージを取得する"""
        try:
            response = self.client.conversations_history(
                channel=channel_id,
                oldest=str(oldest),
                limit=50,
            )
            messages = []
            for msg in response.get("messages", []):
                messages.append({
                    "channel_id": channel_id,
                    "user": msg.get("user", "unknown"),
                    "text": msg.get("text", ""),
                    "timestamp": msg.get("ts", ""),
                    "type": "dm" if is_dm else "channel",
                })
            return messages
        except Exception as e:
            logger.warning(f"チャンネルメッセージ取得エラー ({channel_id}): {e}")
            return []

    def get_channel_list(self) -> list[dict[str, Any]]:
        """参加しているチャンネル一覧を取得する"""
        try:
            response = self.client.conversations_list(
                types="public_channel,private_channel",
                limit=100,
            )
            return [
                {
                    "id": ch["id"],
                    "name": ch["name"],
                    "is_member": ch.get("is_member", False),
                }
                for ch in response.get("channels", [])
                if ch.get("is_member", False)
            ]
        except Exception as e:
            logger.error(f"チャンネル一覧取得エラー: {e}")
            return []
