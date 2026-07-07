from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import re
from typing import Any

from xiaoan_prompts import (
    XIAOAN_GREETING_TEXT,
    XIAOAN_WAKE_ACK_TEXT,
    XIAOAN_POLISH_PROMPT_TEMPLATE,
    XIAOAN_WAKE_PHRASE,
)


RISK_META = {
    "High": {"label": "高危", "color": "#ff6b81"},
    "Medium": {"label": "中危", "color": "#ffb454"},
    "Low": {"label": "低危", "color": "#29d3ff"},
}

ANOMALY_META = {
    "fire": {"label": "烟火", "color": "#ff6b81"},
    "fall": {"label": "倒地", "color": "#ff8f5a"},
    "fight": {"label": "冲突", "color": "#ff4d6d"},
    "intrusion": {"label": "闯入", "color": "#7d7aff"},
    "crowd": {"label": "聚集", "color": "#4dd8a7"},
    "normal": {"label": "常规活动", "color": "#29d3ff"},
    "unknown": {"label": "未知", "color": "#8a94ad"},
    "model_unavailable": {"label": "模型未加载", "color": "#8a94ad"},
    "llm_unavailable": {"label": "模型未加载", "color": "#8a94ad"},
}


class MonitoringDashboardMixin:
    def get_dashboard_payload(self) -> dict[str, Any]:
        today = self._today()
        yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
        cameras = self.get_cameras_overview()
        task = self.get_task_status()
        logs = list(self.get_logs())
        today_events = list(self.get_events_for_date(today))
        yesterday_events = list(self.get_events_for_date(yesterday))

        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=6)
        weekly_rows = self.store.list_events_between(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )
        weekly_events = [self._build_report_item_from_row(row) for row in weekly_rows]
        ranked_recent_events = sorted(
            weekly_events,
            key=self._dashboard_event_sort_key,
            reverse=True,
        )

        recent_alerts = [
            self._build_dashboard_event_card(event)
            for event in ranked_recent_events
            if str(event.get("risk_level", "Low")) in {"High", "Medium"}
        ][:6]
        latest_events = [self._build_dashboard_event_card(event) for event in ranked_recent_events[:10]]
        featured_event = recent_alerts[0] if recent_alerts else (latest_events[0] if latest_events else None)

        return {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "assistant": {
                "greeting": XIAOAN_GREETING_TEXT,
                "wake_phrase": XIAOAN_WAKE_PHRASE,
                "wake_ack": XIAOAN_WAKE_ACK_TEXT,
                "placeholder": "例如：昨天有没有出现一个黑色衣服的人？",
            },
            "overview": self._build_dashboard_overview(today_events, yesterday_events, cameras, task),
            "trends": self._build_dashboard_trends(today_events, weekly_events),
            "structure": self._build_dashboard_structure(weekly_events or today_events),
            "cameras": cameras,
            "task": task,
            "recent_alerts": recent_alerts,
            "latest_events": latest_events,
            "featured_event": featured_event,
            "logs": list(reversed(logs[-8:])),
            "summary": self._build_dashboard_summary_card(),
            "capture_mode": str(self.capture_mode),
        }

    def answer_xiaoan_question(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        result = self.answer_question(question, history=history)
        base_answer = str(result.get("answer", "")).strip()
        if not base_answer:
            result["answer"] = "未发现相关异常记录。"
            result["used_llm"] = False
            result["speech_text"] = "未发现相关异常记录。"
            return result

        if not self.text_llm_ready:
            result["answer"] = base_answer
            result["speech_text"] = self._build_xiaoan_speech_text(question, result)
            return result

        prompt = XIAOAN_POLISH_PROMPT_TEMPLATE.format(
            question=str(question or "").strip(),
            answer=base_answer,
        )
        polished = self._run_text_llm(prompt, timeout=45, temperature=0.15)
        polished_text = str(polished or "").strip()
        if polished_text:
            result["answer"] = polished_text
            result["used_llm"] = True
        else:
            result["answer"] = base_answer
        result["speech_text"] = self._build_xiaoan_speech_text(question, result)
        return result

    @staticmethod
    def _extract_first_number(text: str) -> int | None:
        match = re.search(r"(\d+)", str(text or ""))
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _clean_speech_description(text: str, limit: int = 36) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"该事件窗口合并了\s*\d+\s*张候选关键帧。?", "", cleaned)
        cleaned = re.sub(r"本次事件.*", "", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        cleaned = cleaned.replace("风险等级", "")
        if len(cleaned) > limit:
            cleaned = cleaned[:limit].rstrip("，。；、 ") + "。"
        return cleaned.rstrip("，；、 ")

    def _build_reference_speech_text(self, reference: dict[str, Any]) -> str:
        if not reference:
            return ""

        event_time = str(reference.get("event_time", "")).strip()
        time_label = self._format_time_label(event_time) if event_time else ""
        camera_name = str(reference.get("camera_name", "相关摄像头")).strip() or "相关摄像头"
        risk_level = str(reference.get("risk_level", "")).strip()
        risk_label = RISK_META.get(risk_level, {}).get("label", risk_level)
        description = self._clean_speech_description(reference.get("description", ""))

        sentence = ""
        if time_label:
            sentence += f"{time_label}，"
        sentence += camera_name
        if description:
            if description.startswith(("出现", "发现", "记录到", "拍到")):
                sentence += description
            else:
                sentence += f"记录到{description}"
        if risk_label:
            sentence += f"，风险等级为{risk_label}"
        return sentence.strip("，。 ") + "。"

    def _build_xiaoan_speech_text(self, question: str, result: dict[str, Any]) -> str:
        answer = str(result.get("answer", "")).strip()
        references = list(result.get("references", []))
        intent = self._classify_query_intent(str(question or "").strip())
        scope = self._resolve_date_scope(str(question or "").strip())
        date_label = str(scope.get("date_label") or "当前查询范围")
        _, risk_label = self._extract_risk_filter(str(question or ""))

        if not answer:
            return "未发现相关异常记录。"

        negative_tokens = ("未发现相关异常记录", "未在监控记录中发现相关异常", "未找到符合条件的记录")
        if any(token in answer for token in negative_tokens):
            return "未发现相关异常记录。"

        if intent == "count_events":
            count_value = self._extract_first_number(answer)
            if not count_value:
                return "未发现相关异常记录。"
            event_label = f"{risk_label}事件" if risk_label else "相关事件"
            lead = f"{date_label}共发现{count_value}起{event_label}。"
            if references:
                return f"{lead}{self._build_reference_speech_text(references[0])}"
            return lead

        if intent == "count_people":
            people_count = self._extract_first_number(answer)
            if people_count is None:
                people_count = 0
            if people_count <= 0:
                return "未发现相关异常记录。"
            lead = f"{date_label}共发现{people_count}人次相关活动。"
            if references:
                return f"{lead}{self._build_reference_speech_text(references[0])}"
            return lead

        if intent == "existence":
            if not references:
                return "未发现相关异常记录。"
            if len(references) == 1:
                return self._build_reference_speech_text(references[0])
            return f"共找到{len(references)}条相关记录。{self._build_reference_speech_text(references[0])}"

        if references:
            lead = f"共找到{len(references)}条相关记录。"
            return f"{lead}{self._build_reference_speech_text(references[0])}"

        cleaned_answer = self._clean_speech_description(answer, limit=48)
        return cleaned_answer or "未发现相关异常记录。"

    def _build_dashboard_overview(
        self,
        today_events: list[dict[str, Any]],
        yesterday_events: list[dict[str, Any]],
        cameras: list[dict[str, Any]],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        risk_counter = Counter(str(event.get("risk_level", "Low")) for event in today_events)
        yesterday_risk_counter = Counter(str(event.get("risk_level", "Low")) for event in yesterday_events)
        alerts_sent = sum(1 for event in today_events if bool(event.get("alert_sent", False)))
        yesterday_alerts_sent = sum(1 for event in yesterday_events if bool(event.get("alert_sent", False)))
        online_cameras = sum(1 for camera in cameras if bool(camera.get("available", False)))
        return {
            "today_event_count": len(today_events),
            "high_risk_count": risk_counter["High"],
            "medium_risk_count": risk_counter["Medium"],
            "low_risk_count": risk_counter["Low"],
            "alerts_sent_count": alerts_sent,
            "yesterday_event_count": len(yesterday_events),
            "yesterday_high_risk_count": yesterday_risk_counter["High"],
            "yesterday_medium_risk_count": yesterday_risk_counter["Medium"],
            "yesterday_low_risk_count": yesterday_risk_counter["Low"],
            "yesterday_alerts_sent_count": yesterday_alerts_sent,
            "today_event_delta": self._build_day_delta(len(today_events), len(yesterday_events)),
            "high_risk_delta": self._build_day_delta(risk_counter["High"], yesterday_risk_counter["High"]),
            "medium_risk_delta": self._build_day_delta(risk_counter["Medium"], yesterday_risk_counter["Medium"]),
            "alerts_sent_delta": self._build_day_delta(alerts_sent, yesterday_alerts_sent),
            "online_cameras": online_cameras,
            "total_cameras": len(cameras),
            "task_status": str(task.get("status", "idle")),
            "task_label": self._task_status_label(str(task.get("status", "idle"))),
            "task_message": str(task.get("message", "")),
            "last_task_id": str(task.get("task_id", "")),
        }

    @staticmethod
    def _build_day_delta(current: int, previous: int) -> dict[str, Any]:
        current_count = int(current or 0)
        previous_count = int(previous or 0)
        diff = current_count - previous_count
        if diff > 0:
            direction = "up"
        elif diff < 0:
            direction = "down"
        else:
            direction = "flat"

        if previous_count == 0:
            percent = 0.0 if current_count == 0 else None
            display = "0.0%" if current_count == 0 else "新增"
        else:
            percent = round(abs(diff) * 100 / previous_count, 1)
            display = f"{percent:.1f}%"

        return {
            "current": current_count,
            "previous": previous_count,
            "diff": diff,
            "percent": percent,
            "display": display,
            "direction": direction,
        }

    def _build_dashboard_trends(
        self,
        today_events: list[dict[str, Any]],
        weekly_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "hourly": self._build_hourly_trend(today_events),
            "weekly": self._build_weekly_trend(weekly_events),
            "heatmap": self._build_period_heatmap(weekly_events),
        }

    def _build_dashboard_structure(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        risk_counter = Counter(str(event.get("risk_level", "Low")) for event in events)
        total_events = max(len(events), 1)
        risk_distribution = []
        for key in ("High", "Medium", "Low"):
            count = risk_counter[key]
            meta = RISK_META[key]
            risk_distribution.append(
                {
                    "key": key,
                    "label": meta["label"],
                    "count": count,
                    "ratio": round(count * 100 / total_events, 1),
                    "color": meta["color"],
                }
            )

        anomaly_counter = Counter(
            str(event.get("anomaly_type", "normal") or "normal")
            for event in events
        )
        anomaly_total = max(sum(anomaly_counter.values()), 1)
        anomaly_distribution = []
        for key, count in anomaly_counter.most_common(5):
            meta = ANOMALY_META.get(key, {"label": key or "未知", "color": "#8a94ad"})
            anomaly_distribution.append(
                {
                    "key": key,
                    "label": meta["label"],
                    "count": count,
                    "ratio": round(count * 100 / anomaly_total, 1),
                    "color": meta["color"],
                }
            )

        return {
            "total_events": len(events),
            "risk_distribution": risk_distribution,
            "anomaly_distribution": anomaly_distribution,
        }

    def _build_hourly_trend(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        buckets = [0 for _ in range(24)]
        for event in events:
            parsed = self._parse_datetime(str(event.get("timestamp", event.get("event_time", ""))))
            if parsed:
                buckets[parsed.hour] += 1
        return [
            {
                "hour": hour,
                "label": f"{hour:02d}",
                "count": buckets[hour],
            }
            for hour in range(24)
        ]

    def _build_weekly_trend(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        today = datetime.now().date()
        days = [(today - timedelta(days=offset)) for offset in range(6, -1, -1)]
        counters: dict[str, Counter[str]] = {
            day.strftime("%Y-%m-%d"): Counter({"High": 0, "Medium": 0, "Low": 0}) for day in days
        }
        for event in events:
            timestamp = str(event.get("timestamp", event.get("event_time", "")))
            event_date = timestamp[:10]
            if event_date in counters:
                counters[event_date][str(event.get("risk_level", "Low"))] += 1

        weekly = []
        for day in days:
            day_key = day.strftime("%Y-%m-%d")
            day_counter = counters[day_key]
            total = sum(day_counter.values())
            weekly.append(
                {
                    "date": day_key,
                    "label": day.strftime("%m/%d"),
                    "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day.weekday()],
                    "total": total,
                    "high": day_counter["High"],
                    "medium": day_counter["Medium"],
                    "low": day_counter["Low"],
                }
            )
        return weekly

    def _build_period_heatmap(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        period_specs = [
            {"key": "morning", "label": "早晨", "start": 6, "end": 12, "color": "#b8e6ff"},
            {"key": "afternoon", "label": "下午", "start": 12, "end": 18, "color": "#ff6b81"},
            {"key": "evening", "label": "晚上", "start": 18, "end": 24, "color": "#ffb454"},
            {"key": "night", "label": "凌晨", "start": 0, "end": 6, "color": "#29d3ff"},
        ]
        bucket_map: dict[str, int] = defaultdict(int)
        for event in events:
            parsed = self._parse_datetime(str(event.get("timestamp", event.get("event_time", ""))))
            if parsed is None:
                continue
            for spec in period_specs:
                if spec["start"] <= parsed.hour < spec["end"]:
                    bucket_map[spec["key"]] += 1
                    break
        max_value = max(bucket_map.values(), default=1)
        return [
            {
                "key": spec["key"],
                "label": spec["label"],
                "value": bucket_map[spec["key"]],
                "intensity": round(bucket_map[spec["key"]] / max_value, 3) if max_value else 0,
                "color": spec["color"],
            }
            for spec in period_specs
        ]

    def _build_dashboard_summary_card(self) -> dict[str, Any]:
        latest_summary = self.get_latest_summary() or {}
        overall = str(latest_summary.get("overall_summary", "")).strip()
        if not overall:
            overall = "当前尚未生成新的全天总结，大屏将优先展示实时事件统计和最新预警。"
        return {
            "title": str(latest_summary.get("title", "今日安防态势播报")).strip() or "今日安防态势播报",
            "overall_summary": overall,
            "summary_date": str(latest_summary.get("summary_date", self._today())),
        }

    def _build_dashboard_event_card(self, event: dict[str, Any]) -> dict[str, Any]:
        risk_level = str(event.get("risk_level", "Low"))
        anomaly_type = str(event.get("anomaly_type", "normal") or "normal")
        return {
            "event_id": int(event.get("event_id", 0)),
            "camera_id": str(event.get("camera_id", "")),
            "camera_name": str(event.get("camera_name", "")),
            "timestamp": str(event.get("timestamp", event.get("event_time", ""))),
            "time_label": str(event.get("time_label", self._format_time_label(str(event.get("timestamp", ""))))),
            "risk_level": risk_level,
            "risk_label": RISK_META.get(risk_level, RISK_META["Low"])["label"],
            "risk_color": RISK_META.get(risk_level, RISK_META["Low"])["color"],
            "anomaly_type": anomaly_type,
            "anomaly_label": ANOMALY_META.get(anomaly_type, {"label": anomaly_type or "未知"})["label"],
            "description": str(event.get("description", "")),
            "reason": str(event.get("reason", "")),
            "image_url": str(event.get("image_url", "")),
            "clip_url": str(event.get("clip_url", "")),
            "alert_sent": bool(event.get("alert_sent", False)),
            "person_count": int(event.get("person_count", 0) or 0),
        }

    @staticmethod
    def _dashboard_event_sort_key(event: dict[str, Any]) -> tuple[str, int]:
        timestamp = str(event.get("timestamp", event.get("event_time", "")))
        return (timestamp, int(event.get("event_id", 0)))

    @staticmethod
    def _task_status_label(status: str) -> str:
        mapping = {
            "idle": "空闲",
            "running": "进行中",
            "completed": "已完成",
            "partial_failed": "部分失败",
            "failed": "失败",
            "success": "已启动",
        }
        return mapping.get(status, status or "未知")
