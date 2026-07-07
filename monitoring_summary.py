from __future__ import annotations

import json
from collections import Counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from monitoring_prompts import PERIOD_SUMMARY_PROMPT_TEMPLATE, SUMMARY_PERIODS, SUMMARY_PROMPT_TEMPLATE
from monitoring_types import SummaryState


class MonitoringSummaryMixin:
    def generate_daily_summary(self, summary_date: str | None = None, send_to_feishu: bool = True) -> dict[str, Any]:
        target_date = summary_date or self._today()
        graph_result = self.summary_graph.invoke(
            {
                "summary_date": target_date,
                "send_to_feishu": bool(send_to_feishu),
            }
        )
        summary_record = {
            "summary_date": target_date,
            "title": graph_result.get("title", f"{target_date} 全天日志 AI 总结"),
            "overall_summary": graph_result.get("overall_summary", ""),
            "periods": graph_result.get("periods", []),
            "sent_to_feishu": bool(graph_result.get("sent_to_feishu", False)),
        }
        self.latest_summary = summary_record
        return summary_record

    def _build_summary_graph(self) -> Any:
        workflow = StateGraph(SummaryState)
        workflow.add_node("load_events", self._summary_node_load_events)
        workflow.add_node("split_periods", self._summary_node_split_periods)
        workflow.add_node("summarize_periods", self._summary_node_summarize_periods)
        workflow.add_node("summarize_overall", self._summary_node_summarize_overall)
        workflow.add_node("save_summary", self._summary_node_save_summary)
        workflow.add_node("send_summary", self._summary_node_send_summary)
        workflow.add_node("finalize", self._summary_node_finalize)

        workflow.add_edge(START, "load_events")
        workflow.add_edge("load_events", "split_periods")
        workflow.add_edge("split_periods", "summarize_periods")
        workflow.add_edge("summarize_periods", "summarize_overall")
        workflow.add_edge("summarize_overall", "save_summary")
        workflow.add_conditional_edges(
            "save_summary",
            self._route_summary_delivery,
            {
                "send_summary": "send_summary",
                "finalize": "finalize",
            },
        )
        workflow.add_edge("send_summary", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    def _summary_node_load_events(self, state: SummaryState) -> dict[str, Any]:
        summary_date = str(state.get("summary_date", self._today()))
        events = self.get_events_for_date(summary_date)
        self.add_log("总结", f"LangGraph 总结节点载入 {summary_date} 事件 {len(events)} 条。")
        return {"events": events}

    def _summary_node_split_periods(self, state: SummaryState) -> dict[str, Any]:
        events = list(state.get("events", []))
        buckets: list[dict[str, Any]] = []
        for spec in SUMMARY_PERIODS:
            bucket_events = [event for event in events if spec["start"] <= self._event_hour(event) < spec["end"]]
            buckets.append(
                {
                    "name": spec["name"],
                    "time_range": spec["time_range"],
                    "events": bucket_events,
                }
            )
        return {"period_buckets": buckets}

    def _summary_node_summarize_periods(self, state: SummaryState) -> dict[str, Any]:
        summary_date = str(state.get("summary_date", self._today()))
        periods: list[dict[str, Any]] = []
        for bucket in state.get("period_buckets", []):
            events = list(bucket.get("events", []))
            counter = Counter(event.get("risk_level", "Low") for event in events)
            llm_summary = self._generate_period_summary_with_llm(summary_date, str(bucket["name"]), events)
            summary_text = llm_summary or self._build_local_period_summary(str(bucket["name"]), events)
            periods.append(
                {
                    "name": bucket["name"],
                    "time_range": bucket["time_range"],
                    "event_count": len(events),
                    "summary": summary_text,
                    "high_count": counter["High"],
                    "medium_count": counter["Medium"],
                    "low_count": counter["Low"],
                    "highlights": self._select_period_highlights(events),
                }
            )
        return {"periods": periods}

    def _summary_node_summarize_overall(self, state: SummaryState) -> dict[str, Any]:
        summary_date = str(state.get("summary_date", self._today()))
        events = list(state.get("events", []))
        periods = list(state.get("periods", []))
        overall_summary = self._generate_overall_summary_with_llm(summary_date, events, periods)
        if not overall_summary:
            overall_summary = self._build_local_overall_summary(summary_date, events, periods)
        return {
            "title": f"{summary_date} 全天日志 AI 总结",
            "overall_summary": overall_summary,
        }

    def _summary_node_save_summary(self, state: SummaryState) -> dict[str, Any]:
        record = {
            "summary_date": state["summary_date"],
            "title": state["title"],
            "overall_summary": state["overall_summary"],
            "periods": state.get("periods", []),
            "sent_to_feishu": False,
        }
        body = json.dumps(record, ensure_ascii=False)
        self.store.save_summary(str(state["summary_date"]), str(state["title"]), body, False)
        self.latest_summary = record
        self.add_log("总结", f"LangGraph 总结节点已保存 {state['summary_date']} 的日报。")
        return {"body": body, "sent_to_feishu": False}

    def _route_summary_delivery(self, state: SummaryState) -> str:
        if bool(state.get("send_to_feishu", False)) and not self.feishu_agent.enabled:
            self.add_log("推送", "飞书未配置 app_id/app_secret/chat_id 或 webhook_url，无法推送日报。")
        should_send = bool(state.get("send_to_feishu", False) and self.feishu_agent.enabled)
        return "send_summary" if should_send else "finalize"

    def _summary_node_send_summary(self, state: SummaryState) -> dict[str, Any]:
        summary_text = self._format_summary_for_feishu(
            str(state["summary_date"]),
            str(state.get("overall_summary", "")),
            list(state.get("periods", [])),
        )
        sent = self.feishu_agent.send_daily_summary(str(state["summary_date"]), summary_text)
        record = {
            "summary_date": state["summary_date"],
            "title": state["title"],
            "overall_summary": state["overall_summary"],
            "periods": state.get("periods", []),
            "sent_to_feishu": sent,
        }
        body = json.dumps(record, ensure_ascii=False)
        self.store.save_summary(str(state["summary_date"]), str(state["title"]), body, sent)
        self.latest_summary = record
        if sent:
            self.add_log("推送", f"{state['summary_date']} 的日报已推送到飞书。")
        else:
            self.add_log("推送", f"{state['summary_date']} 的日报推送失败。")
        return {"body": body, "sent_to_feishu": sent}

    def _summary_node_finalize(self, state: SummaryState) -> dict[str, Any]:
        return {
            "summary_date": state.get("summary_date", self._today()),
            "title": state.get("title", ""),
            "overall_summary": state.get("overall_summary", ""),
            "periods": list(state.get("periods", [])),
            "sent_to_feishu": bool(state.get("sent_to_feishu", False)),
        }

    def _select_period_highlights(self, events: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
        ranked = sorted(
            events,
            key=lambda item: (
                self._risk_priority(str(item.get("risk_level", "Low"))),
                str(item.get("timestamp", item.get("event_time", ""))),
            ),
        )
        highlights: list[dict[str, Any]] = []
        for event in ranked[:limit]:
            highlights.append(
                {
                    "time_label": str(event.get("time_label", self._format_time_label(str(event.get("timestamp", ""))))),
                    "camera_name": str(event.get("camera_name", "")),
                    "description": str(event.get("description", "")),
                }
            )
        return highlights

    @staticmethod
    def _risk_priority(risk_level: str) -> int:
        if risk_level == "High":
            return 0
        if risk_level == "Medium":
            return 1
        return 2

    def _build_local_period_summary(self, period_name: str, events: list[dict[str, Any]]) -> str:
        if not events:
            return f"{period_name}时段未记录到明显异常，整体画面以常规活动为主。"

        counter = Counter(str(event.get("risk_level", "Low")) for event in events)
        anomaly_counter = Counter(
            str(event.get("anomaly_type", "normal"))
            for event in events
            if str(event.get("anomaly_type", "normal")) not in {"", "normal"}
        )
        camera_names = "、".join(sorted({str(event.get("camera_name", "")) for event in events if event.get("camera_name")}))
        top_types = "、".join(name for name, _ in anomaly_counter.most_common(3)) or "常规活动"
        return (
            f"{period_name}共记录 {len(events)} 条关键帧事件，高风险 {counter['High']} 条，"
            f"中风险 {counter['Medium']} 条，低风险 {counter['Low']} 条。"
            f"主要场景为 {top_types}，涉及摄像头 {camera_names}。"
        )

    def _build_local_overall_summary(
        self,
        summary_date: str,
        events: list[dict[str, Any]],
        periods: list[dict[str, Any]],
    ) -> str:
        if not events:
            return f"{summary_date} 未记录到需要关注的关键帧事件，全天运行状态平稳。"

        counter = Counter(str(event.get("risk_level", "Low")) for event in events)
        busiest_period = max(periods, key=lambda item: int(item.get("event_count", 0)), default=None)
        if busiest_period and int(busiest_period.get("event_count", 0)) > 0:
            busiest_text = f"事件最集中时段为 {busiest_period['name']}，共 {busiest_period['event_count']} 条。"
        else:
            busiest_text = "各时段事件分布较均衡。"
        return (
            f"{summary_date} 全天共记录 {len(events)} 条关键帧事件，高风险 {counter['High']} 条，"
            f"中风险 {counter['Medium']} 条，低风险 {counter['Low']} 条。{busiest_text}"
        )

    def _generate_period_summary_with_llm(
        self,
        summary_date: str,
        period_name: str,
        events: list[dict[str, Any]],
    ) -> str:
        if not events:
            return ""

        event_lines = self._build_event_digest_lines(events)
        prompt = PERIOD_SUMMARY_PROMPT_TEMPLATE.format(
            summary_date=summary_date,
            period_name=period_name,
            event_lines=event_lines,
        )
        response = self._run_text_llm(prompt, timeout=60)
        return response.strip() if response else ""

    def _generate_overall_summary_with_llm(
        self,
        summary_date: str,
        events: list[dict[str, Any]],
        periods: list[dict[str, Any]],
    ) -> str:
        if not events:
            return ""

        period_lines = []
        for period in periods:
            period_lines.append(
                f"- {period['name']}({period['time_range']})：{period['event_count']} 条，"
                f"高 {period['high_count']} / 中 {period['medium_count']} / 低 {period['low_count']}。"
            )
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            summary_date=summary_date,
            period_lines="\n".join(period_lines) or "无时段统计信息。",
            daily_logs=self._build_event_digest_lines(events, limit=max(12, min(len(events), 24))) or "无事件日志。",
        )
        response = self._run_text_llm(prompt, timeout=90)
        return response.strip() if response else ""

    def _build_event_digest_lines(self, events: list[dict[str, Any]], limit: int = 8) -> str:
        lines = []
        for event in events[:limit]:
            lines.append(
                f"- {event['time_label']} | {event['camera_name']} | {event['risk_level']} | "
                f"{event['anomaly_type']} | {event['description']}"
            )
        return "\n".join(lines)

    def _deserialize_summary_record(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None

        summary_date = str(row.get("summary_date", self._today()))
        title = str(row.get("title", f"{summary_date} 全天日志 AI 总结"))
        sent_to_feishu = bool(row.get("sent_to_feishu", 0))
        body = str(row.get("body", ""))

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if isinstance(payload, dict) and payload:
            return {
                "summary_date": summary_date,
                "title": str(payload.get("title", title)),
                "overall_summary": str(payload.get("overall_summary", body)),
                "periods": list(payload.get("periods", [])),
                "sent_to_feishu": bool(payload.get("sent_to_feishu", sent_to_feishu)),
            }

        return {
            "summary_date": summary_date,
            "title": title,
            "overall_summary": body,
            "periods": [],
            "sent_to_feishu": sent_to_feishu,
        }

    def _format_summary_for_feishu(
        self,
        summary_date: str,
        overall_summary: str,
        periods: list[dict[str, Any]],
    ) -> str:
        lines = [f"{summary_date} 全天日志 AI 总结", "", overall_summary]
        for period in periods:
            lines.extend(
                [
                    "",
                    f"{period['name']}（{period['time_range']}）",
                    f"事件数：{period['event_count']}，高 {period['high_count']} / 中 {period['medium_count']} / 低 {period['low_count']}",
                    str(period["summary"]),
                ]
            )
        return "\n".join(lines)

    def _event_hour(self, event: dict[str, Any]) -> int:
        timestamp = str(event.get("timestamp", event.get("event_time", "")))
        parsed = self._parse_datetime(timestamp)
        return parsed.hour if parsed else 0
