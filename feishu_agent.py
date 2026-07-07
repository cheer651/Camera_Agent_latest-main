from __future__ import annotations

import json
import os
from typing import Any

import requests


class FeishuAgent:
    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        chat_id: str = "",
        webhook_url: str = "",
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.webhook_url = webhook_url
        self.tenant_access_token = ""

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url or (self.app_id and self.app_secret and self.chat_id))

    def _get_tenant_access_token(self) -> bool:
        if not (self.app_id and self.app_secret):
            return False

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=15).json()
        except requests.RequestException:
            return False

        if response.get("code") == 0:
            self.tenant_access_token = response.get("tenant_access_token", "")
            return bool(self.tenant_access_token)
        return False

    def _upload_image(self, image_path: str) -> str | None:
        if not self.tenant_access_token or not os.path.exists(image_path):
            return None

        url = "https://open.feishu.cn/open-apis/im/v1/images"
        headers = {"Authorization": f"Bearer {self.tenant_access_token}"}

        try:
            with open(image_path, "rb") as image_file:
                files = {
                    "image_type": (None, "message"),
                    "image": (os.path.basename(image_path), image_file.read(), "image/jpeg"),
                }
                response = requests.post(url, headers=headers, files=files, timeout=30).json()
        except (OSError, requests.RequestException):
            return None

        if response.get("code") == 0:
            data = response.get("data", {})
            return data.get("image_key")
        return None

    def _send_webhook_text(self, title: str, body: str) -> bool:
        if not self.webhook_url:
            return False

        payload = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n{body}",
            },
        }
        try:
            response = requests.post(self.webhook_url, json=payload, timeout=20)
            return response.ok
        except requests.RequestException:
            return False

    def _send_chat_message(self, msg_type: str, content: dict[str, Any] | str) -> bool:
        if not self.chat_id:
            return False
        if not self.tenant_access_token and not self._get_tenant_access_token():
            return False

        url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        headers = {
            "Authorization": f"Bearer {self.tenant_access_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {
            "receive_id": self.chat_id,
            "msg_type": msg_type,
            "content": json.dumps(content) if isinstance(content, dict) else content,
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=20).json()
        except requests.RequestException:
            return False
        return response.get("code") == 0

    def send_text_message(self, title: str, body: str) -> bool:
        if self.webhook_url:
            return self._send_webhook_text(title, body)
        return self._send_chat_message("text", {"text": f"{title}\n{body}"})

    def send_daily_summary(self, summary_date: str, summary_text: str) -> bool:
        title = f"安防每日日志总结 | {summary_date}"
        return self.send_text_message(title, summary_text)

    def send_alert_card(self, camera_id: str, ai_result: dict[str, Any], image_path: str = "") -> bool:
        risk_level = str(ai_result.get("risk_level", "High"))
        anomaly_type = str(ai_result.get("anomaly_type", "unknown"))
        description = str(ai_result.get("description", ""))
        reason = str(ai_result.get("reason", ""))
        risk_text = self._risk_label(risk_level)

        if self.webhook_url:
            body = (
                f"摄像头：{camera_id}\n"
                f"风险等级：{risk_text}\n"
                f"异常类型：{anomaly_type}\n"
                f"画面描述：{description}\n"
                f"判定依据：{reason}"
            )
            return self._send_webhook_text("高风险安防告警", body)

        if not self._get_tenant_access_token():
            return False

        image_key = self._upload_image(image_path) if image_path else None
        card_color = "red" if risk_level == "High" else "orange"
        elements: list[dict[str, Any]] = [
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**摄像头**\n{camera_id}"},
                    },
                    {
                        "is_short": True,
                        "text": {"tag": "lark_md", "content": f"**风险等级**\n{risk_text}"},
                    },
                ],
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**异常类型**\n{anomaly_type}\n\n**画面描述**\n{description}\n\n**判定依据**\n{reason}",
                },
            },
        ]

        if image_key:
            elements.extend(
                [
                    {"tag": "hr"},
                    {
                        "tag": "img",
                        "img_key": image_key,
                        "alt": {"tag": "plain_text", "content": "告警截图"},
                    },
                ]
            )

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"安防告警 | {camera_id}"},
                "template": card_color,
            },
            "elements": elements,
        }

        return self._send_chat_message("interactive", card)

    @staticmethod
    def _risk_label(risk_level: str) -> str:
        mapping = {
            "High": "高风险",
            "Medium": "中风险",
            "Low": "低风险",
            "高风险": "高风险",
            "中风险": "中风险",
            "低风险": "低风险",
        }
        return mapping.get(risk_level, risk_level)
