from __future__ import annotations

import json
import queue
import re
import threading
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
from langgraph.graph import END, START, StateGraph

from monitoring_prompts import RISK_PRIORITY
from monitoring_types import AnalysisState, FrameJob
from schemas import FrameAnalysis, ValidationError


class MonitoringAnalysisMixin:
    def _build_analysis_graph(self) -> Any:
        workflow = StateGraph(AnalysisState)
        workflow.add_node("analyze_frames", self._analysis_node_analyze_frames)
        workflow.add_node("persist_events", self._analysis_node_persist_events)
        workflow.add_node("decide_alerts", self._analysis_node_decide_alerts)
        workflow.add_node("send_alerts", self._analysis_node_send_alerts)
        workflow.add_node("finalize", self._analysis_node_finalize)

        workflow.add_edge(START, "analyze_frames")
        workflow.add_edge("analyze_frames", "persist_events")
        workflow.add_edge("persist_events", "decide_alerts")
        workflow.add_conditional_edges(
            "decide_alerts",
            self._route_analysis_alerts,
            {
                "send_alerts": "send_alerts",
                "finalize": "finalize",
            },
        )
        workflow.add_edge("send_alerts", "finalize")
        workflow.add_edge("finalize", END)
        return workflow.compile()

    def _interleave_frame_jobs(self, frame_jobs: list[FrameJob]) -> list[FrameJob]:
        if not frame_jobs:
            return []

        per_camera: dict[str, list[tuple[datetime, FrameJob]]] = {}
        for raw_job in frame_jobs:
            job = dict(raw_job)
            camera_id = str(job.get("camera_id", ""))
            started_at = self._parse_datetime(str(job.get("clip_started_at", ""))) or datetime.min
            event_at = started_at + timedelta(seconds=float(job.get("frame_second", 0.0)))
            per_camera.setdefault(camera_id, []).append((event_at, job))

        for camera_id in per_camera:
            per_camera[camera_id].sort(
                key=lambda pair: (
                    pair[0],
                    float(pair[1].get("event_start_second", pair[1].get("frame_second", 0.0))),
                    int(pair[1].get("representative_rank", 1)),
                )
            )

        ordered_jobs: list[FrameJob] = []
        order_index = 0
        last_camera = ""
        alternation_window_seconds = 1.2

        while True:
            heads: list[tuple[datetime, str, FrameJob]] = []
            for camera_id, items in per_camera.items():
                if not items:
                    continue
                event_at, job = items[0]
                heads.append((event_at, camera_id, job))

            if not heads:
                break

            heads.sort(key=lambda item: (item[0], item[1]))
            selected_event_at, selected_camera, _ = heads[0]
            if len(heads) > 1 and selected_camera == last_camera:
                second_event_at, second_camera, _ = heads[1]
                delta = (second_event_at - selected_event_at).total_seconds()
                if second_camera != last_camera and delta <= alternation_window_seconds:
                    selected_event_at, selected_camera, _ = heads[1]

            _, selected_job = per_camera[selected_camera].pop(0)
            selected_job["analysis_order"] = order_index
            ordered_jobs.append(selected_job)
            order_index += 1
            last_camera = selected_camera

        return ordered_jobs

    def _analysis_node_analyze_frames(self, state: AnalysisState) -> dict[str, Any]:
        frame_jobs = self._interleave_frame_jobs(list(state.get("frame_jobs", [])))
        if not frame_jobs:
            self.add_log("分析", "未提取到可分析关键帧，LangGraph 分析节点直接结束。")
            return {"analyses": []}

        analyses: list[dict[str, Any]] = []
        input_queue: queue.Queue[FrameJob | None] = queue.Queue()
        result_lock = threading.Lock()
        worker_count = 1

        def worker() -> None:
            while True:
                job = input_queue.get()
                if job is None:
                    input_queue.task_done()
                    return
                try:
                    prompt_text = self._build_frame_prompt_v2(job)
                    raw_payload = self.llm_client.analyze_frame(job["frame_path"], prompt_text)
                    analysis, normalized_raw = self._parse_analysis_result(raw_payload, job)
                    item = {
                        "camera_name": job["camera_name"],
                        "analysis": analysis,
                        "raw_payload": normalized_raw,
                        "job": job,
                    }
                    with result_lock:
                        analyses.append(item)
                finally:
                    input_queue.task_done()

        workers = [threading.Thread(target=worker, daemon=True, name=f"analysis-worker-{index}") for index in range(worker_count)]
        for thread in workers:
            thread.start()

        for job in frame_jobs:
            input_queue.put(job)
        for _ in workers:
            input_queue.put(None)

        input_queue.join()
        for thread in workers:
            thread.join()

        analyses.sort(
            key=lambda item: (
                int(item.get("job", {}).get("analysis_order", 0)),
                float(item["analysis"].frame_second),
            )
        )

        risk_counter = Counter(item["analysis"].risk_level for item in analyses)
        self.add_log(
            "分析",
            (
                f"LangGraph 分析节点完成，共处理 {len(analyses)} 张关键帧，"
                f"高风险 {risk_counter['High']} 条，中风险 {risk_counter['Medium']} 条。"
            ),
        )
        return {"analyses": analyses}

    def _analysis_node_persist_events(self, state: AnalysisState) -> dict[str, Any]:
        report_items: list[dict[str, Any]] = []
        grouped_items: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in state.get("analyses", []):
            analysis: FrameAnalysis = item["analysis"]
            group_key = (
                analysis.camera_id,
                analysis.event_group_id or f"frame_{analysis.frame_second:.2f}",
            )
            grouped_items.setdefault(group_key, []).append(item)

        for group_items in grouped_items.values():
            analysis, raw_payload = self._merge_event_window(group_items)
            if self._should_skip_generic_event(analysis, group_items):
                self.add_log(
                    "过滤",
                    f"{analysis.camera_id} {analysis.event_group_id or 'unknown'} 被判定为无意义空事件，已跳过入库。",
                )
                continue
            camera_name = str(group_items[0].get("camera_name", analysis.camera_id))
            event_id = self.store.add_event(
                task_id=str(state.get("task_id", "")),
                camera_name=camera_name,
                analysis=analysis,
                raw_payload=raw_payload,
            )
            report_items.append(self._build_report_item(event_id, camera_name, analysis))

        report_items.sort(key=lambda item: (item["timestamp"], item["event_id"]))
        if report_items:
            try:
                self._index_report_items(report_items, source="analysis")
            except Exception as exc:
                self.add_log("向量库", f"关键帧事件写入 Qdrant 失败：{exc}")
        self.add_log("存储", f"LangGraph 持久化节点完成，共写入 {len(report_items)} 条事件。")
        return {"report_items": report_items}

    def _analysis_node_decide_alerts(self, state: AnalysisState) -> dict[str, Any]:
        alerts = [item for item in state.get("report_items", []) if item.get("risk_level") == "High"]
        if alerts:
            self.add_log("告警", f"LangGraph 决策节点识别到 {len(alerts)} 条高风险事件。")
        else:
            self.add_log("告警", "LangGraph 决策节点未发现需要推送的高风险事件。")
        return {"alerts": alerts}

    def _route_analysis_alerts(self, state: AnalysisState) -> str:
        return "send_alerts" if state.get("alerts") else "finalize"

    def _analysis_node_send_alerts(self, state: AnalysisState) -> dict[str, Any]:
        report_items = [dict(item) for item in state.get("report_items", [])]
        report_index = {int(item["event_id"]): item for item in report_items}
        sent_count = 0

        for alert in state.get("alerts", []):
            event_id = int(alert["event_id"])
            if self.feishu_agent.enabled:
                sent = self.feishu_agent.send_alert_card(
                    camera_id=str(alert["camera_id"]),
                    ai_result={
                        "risk_level": alert.get("risk_level", "High"),
                        "anomaly_type": alert.get("anomaly_type", "unknown"),
                        "description": alert.get("description", ""),
                        "reason": alert.get("reason", ""),
                    },
                    image_path=str(alert.get("image_path", "")),
                )
            else:
                sent = False

            self.store.mark_alert_sent(event_id, sent)
            if event_id in report_index:
                report_index[event_id]["alert_sent"] = sent
            if sent:
                sent_count += 1

        if state.get("alerts"):
            if self.feishu_agent.enabled:
                self.add_log(
                    "告警",
                    f"LangGraph 告警节点完成，高风险 {len(state['alerts'])} 条，飞书已发送 {sent_count} 条。",
                )
            else:
                self.add_log("告警", "飞书未配置，高风险事件已写入数据库但未推送。")

        normalized_items = sorted(report_index.values(), key=lambda item: (item["timestamp"], item["event_id"]))
        return {"report_items": normalized_items}

    def _analysis_node_finalize(self, state: AnalysisState) -> dict[str, Any]:
        return {"report_items": list(state.get("report_items", []))}

    def _build_frame_prompt_v2(self, job: FrameJob) -> str:
        return (
            f"{self.prompt_template}\n\n"
            "补充上下文：\n"
            f"- 摄像头编号：{job['camera_id']}\n"
            f"- 摄像头名称：{job['camera_name']}\n"
            f"- 片段开始时间：{job['clip_started_at']}\n"
            f"- 当前关键帧位于片段第 {job['frame_second']:.2f} 秒\n"
            f"- 事件窗口编号：{job.get('event_group_id', '')}\n"
            f"- 当前事件窗口候选关键帧数：{job.get('event_frame_count', 1)}\n"
            f"- 当前帧在事件窗口中的代表序号：{job.get('representative_rank', 1)}/{job.get('representative_count', 1)}\n"
            f"- 事件窗口时间范围：{job.get('event_start_second', job['frame_second']):.2f} 秒 - {job.get('event_end_second', job['frame_second']):.2f} 秒\n"
            f"- 本地人体检测提示：人数候选 {job.get('person_count_hint', 0)}，置信参考 {job.get('person_score_hint', 0.0):.2f}\n\n"
            f"- 本地低姿态提示：{('疑似倒地/低姿态目标' if int(job.get('low_pose_hint', 0)) > 0 else '未触发')}，前景面积参考 {job.get('foreground_area_ratio_hint', 0.0):.4f}\n\n"
            "你必须继续只返回合法 JSON，并额外补齐以下字段：\n"
            "{\n"
            '  "person_present": true,\n'
            '  "person_count": 1,\n'
            '  "action_type": "经过/徘徊/停留/闯入/聚集/倒地/持火源/办公/未知",\n'
            '  "upper_clothing_color": "黑色/白色/红色/蓝色/灰色/深色/浅色/未知",\n'
            '  "lower_clothing_color": "黑色/白色/红色/蓝色/灰色/深色/浅色/未知",\n'
            '  "confidence": 0.0\n'
            "}\n"
            "要求：\n"
            "1. person_count 必须是整数，没有人时填 0。\n"
            "2. action_type 优先描述人物动作，没有人物时可留空。\n"
            "3. 衣着颜色无法确认时使用“深色”“浅色”或空字符串，不要编造。\n"
            "4. confidence 用 0 到 1 的小数表示你对结构化判断的把握程度。\n"
            "5. description 仍然要尽量写清人数、衣着和动作。"
        )

    def _parse_analysis_result(self, raw_payload: str | None, job: FrameJob) -> tuple[FrameAnalysis, str]:
        started_at = self._parse_datetime(job["clip_started_at"]) or datetime.now()
        event_time = started_at + timedelta(seconds=float(job["frame_second"]))
        base_payload = {
            "timestamp": event_time.isoformat(timespec="seconds"),
            "camera_id": job["camera_id"],
            "frame_second": float(job["frame_second"]),
            "frame_path": job["frame_path"],
            "clip_path": job["clip_path"],
            "event_group_id": str(job.get("event_group_id", "")),
            "event_frame_count": int(job.get("event_frame_count", 1)),
            "representative_count": int(job.get("representative_count", 1)),
            "event_start_second": float(job.get("event_start_second", job["frame_second"])),
            "event_end_second": float(job.get("event_end_second", job["frame_second"])),
            "event_duration_seconds": float(job.get("event_duration_seconds", 0.0)),
            "person_present": False,
            "person_count": 0,
            "action_type": "",
            "upper_clothing_color": "",
            "lower_clothing_color": "",
            "confidence": 0.0,
        }
        default_payload = {
            **base_payload,
            "anomaly_detected": False,
            "anomaly_type": "normal",
            "risk_level": "Low",
            "description": "画面未发现明显异常。",
            "reason": "未检测到需要重点处置的风险。",
        }

        normalized_raw = (raw_payload or "").strip()
        if not normalized_raw:
            fallback = self._build_visual_fallback_payload(job, "远端视觉模型未返回内容。", default_payload)
            return FrameAnalysis.model_validate(fallback), normalized_raw

        if normalized_raw.startswith("__ERROR__:"):
            fallback = self._build_visual_fallback_payload(
                job,
                normalized_raw.replace("__ERROR__:", "").strip(),
                default_payload,
            )
            return FrameAnalysis.model_validate(fallback), normalized_raw

        candidate_text = normalized_raw
        json_match = re.search(r"\{.*\}", normalized_raw, flags=re.S)
        if json_match:
            candidate_text = json_match.group(0)

        parsed_payload: dict[str, Any] = {}
        try:
            loaded = json.loads(candidate_text)
            if isinstance(loaded, dict):
                parsed_payload = loaded
        except json.JSONDecodeError:
            parsed_payload = {}

        if not parsed_payload:
            fallback = self._build_visual_fallback_payload(job, normalized_raw[:180], default_payload)
            return FrameAnalysis.model_validate(fallback), normalized_raw

        merged_payload = {**parsed_payload, **base_payload}
        if not str(merged_payload.get("description", "")).strip():
            merged_payload["description"] = "画面存在待人工复核内容。"
        if not str(merged_payload.get("reason", "")).strip():
            merged_payload["reason"] = "根据场景语义和风险规则综合判断。"
        merged_payload = self._enrich_analysis_payload(job, merged_payload, normalized_raw)

        try:
            analysis = FrameAnalysis.model_validate(merged_payload)
        except ValidationError:
            fallback = dict(default_payload)
            fallback["description"] = str(parsed_payload.get("description", fallback["description"]))
            fallback["reason"] = str(parsed_payload.get("reason", fallback["reason"]))
            fallback = self._enrich_analysis_payload(job, fallback, normalized_raw)
            analysis = FrameAnalysis.model_validate(fallback)

        if not analysis.anomaly_detected:
            if analysis.anomaly_type != "模型未加载成功":
                analysis.risk_level = "Low"
                analysis.anomaly_type = "normal"
                if not analysis.description.strip():
                    analysis.description = "画面未发现明显异常。"
            else:
                analysis.risk_level = "Low"
                analysis.description = "模型未加载成功"
                analysis.reason = "模型未加载成功"

        return analysis, normalized_raw

    def _build_visual_fallback_payload(
        self,
        job: FrameJob,
        reason_hint: str,
        default_payload: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(default_payload)
        payload["anomaly_detected"] = False
        payload["anomaly_type"] = "模型未加载成功"
        payload["risk_level"] = "Low"
        payload["description"] = "模型未加载成功"
        payload["reason"] = "模型未加载成功"
        return self._enrich_analysis_payload(job, payload, reason_hint)

    def _detect_people_from_image(self, image_path: str) -> tuple[int, tuple[int, int, int, int] | None]:
        image = cv2.imread(image_path)
        if image is None:
            return 0, None

        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        rects, weights = hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.05)
        height, width = image.shape[:2]

        valid_boxes: list[tuple[tuple[int, int, int, int], float]] = []
        for rect, weight in zip(rects, weights):
            x, y, box_width, box_height = [int(value) for value in rect]
            top_ratio = y / max(height, 1)
            bottom_ratio = (y + box_height) / max(height, 1)
            height_ratio = box_height / max(height, 1)
            area_ratio = (box_width * box_height) / max(height * width, 1)
            confidence = float(weight)
            if confidence < 0.65 or top_ratio < 0.08 or bottom_ratio < 0.55 or height_ratio < 0.30 or area_ratio < 0.03:
                continue
            valid_boxes.append(((x, y, box_width, box_height), confidence))

        if not valid_boxes:
            return 0, None

        valid_boxes.sort(key=lambda item: item[1], reverse=True)
        return len(valid_boxes), valid_boxes[0][0]

    def _estimate_upper_clothing_color(self, image_path: str, box: tuple[int, int, int, int]) -> str:
        image = cv2.imread(image_path)
        if image is None:
            return "浅色"

        x, y, width, height = box
        torso_top = y + int(height * 0.18)
        torso_bottom = y + int(height * 0.58)
        torso_left = x + int(width * 0.20)
        torso_right = x + int(width * 0.80)

        roi = image[max(0, torso_top):max(0, torso_bottom), max(0, torso_left):max(0, torso_right)]
        if roi.size == 0:
            return "浅色"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue = float(hsv[:, :, 0].mean())
        saturation = float(hsv[:, :, 1].mean())
        value = float(hsv[:, :, 2].mean())

        if value >= 195 and saturation <= 40:
            return "白色"
        if value >= 155 and saturation <= 70:
            return "浅色"
        if value <= 75:
            return "黑色"
        if saturation < 55 and value < 150:
            return "深色"
        if 90 <= hue <= 135:
            return "蓝色"
        if 0 <= hue <= 12 or hue >= 170:
            return "红色"
        if saturation <= 60 and 70 <= value <= 180:
            return "灰色"
        return "深色"

    @staticmethod
    def _normalize_action_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        action_map = {
            "经过": ("经过", "路过", "走过", "通行", "行走", "通过", "走动", "走在", "移动"),
            "徘徊": ("徘徊", "来回走动", "反复走动", "游荡"),
            "停留": ("停留", "逗留", "驻足", "短暂停留"),
            "闯入": ("闯入", "入侵", "进入禁区", "强行进入"),
            "聚集": ("聚集", "扎堆", "围在一起"),
            "倒地": ("倒地", "跌倒", "摔倒", "倒下", "躺倒", "躺在地上", "倒在地上"),
            "持火源": ("持火源", "打火机", "持打火机", "拿打火机", "火机", "明火", "点火", "火源"),
            "办公": ("办公", "工作", "值守"),
            "未知": ("未知",),
        }
        for canonical, keywords in action_map.items():
            if any(keyword in text for keyword in keywords):
                return canonical
        return ""

    @staticmethod
    def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
        normalized = str(text or "").strip()
        return any(keyword in normalized for keyword in keywords)

    def _apply_high_risk_override(self, payload: dict[str, Any], text: str) -> dict[str, Any]:
        normalized = str(text or "").strip()
        if not normalized:
            return payload

        overridden = dict(payload)
        fire_tokens = (
            "打火机",
            "持打火机",
            "拿打火机",
            "火机",
            "明火",
            "火焰",
            "火苗",
            "点火",
            "引燃",
            "火源",
        )
        fall_tokens = (
            "倒地",
            "跌倒",
            "摔倒",
            "倒下",
            "躺倒",
            "躺在地上",
            "倒在地上",
        )

        def has_positive_keyword(keywords: tuple[str, ...], negations: tuple[str, ...]) -> bool:
            for keyword in keywords:
                start = normalized.find(keyword)
                while start >= 0:
                    window = normalized[max(0, start - 8): start + len(keyword) + 4]
                    if not any(negation in window for negation in negations):
                        return True
                    start = normalized.find(keyword, start + len(keyword))
            return False

        fire_negations = ("无", "未", "没有", "未见", "未发现", "未出现", "无人持有")
        fall_negations = ("无", "未", "没有", "未见", "未发现", "未出现", "无人倒地", "未倒地")

        if has_positive_keyword(fire_tokens, fire_negations):
            overridden["anomaly_detected"] = True
            overridden["anomaly_type"] = "fire"
            overridden["risk_level"] = "High"
            if not str(overridden.get("action_type", "")).strip():
                overridden["action_type"] = "持火源"
            reason = str(overridden.get("reason", "")).strip()
            if "打火机" not in reason and "火源" not in reason and "明火" not in reason:
                overridden["reason"] = (reason + " " if reason else "") + "画面中出现打火机或明火迹象，按高风险事件处理。"

        if has_positive_keyword(fall_tokens, fall_negations):
            overridden["anomaly_detected"] = True
            overridden["anomaly_type"] = "fall"
            overridden["risk_level"] = "High"
            overridden["action_type"] = "倒地"
            reason = str(overridden.get("reason", "")).strip()
            if "倒地" not in reason and "跌倒" not in reason and "摔倒" not in reason:
                overridden["reason"] = (reason + " " if reason else "") + "画面中出现人员倒地或跌倒迹象，按高风险事件处理。"

        return overridden

    @staticmethod
    def _normalize_color_value(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        color_map = {
            "黑色": ("黑色", "黑衣", "黑色上衣", "深黑"),
            "白色": ("白色", "白衣", "白色上衣"),
            "红色": ("红色", "红衣"),
            "蓝色": ("蓝色", "蓝衣"),
            "灰色": ("灰色", "灰衣"),
            "深色": ("深色", "深色衣服", "深色上衣", "深色外套"),
            "浅色": ("浅色", "浅色衣服", "浅色上衣"),
            "未知": ("未知",),
        }
        for canonical, keywords in color_map.items():
            if any(keyword in text for keyword in keywords):
                return canonical
        return ""

    def _infer_person_count_from_text(self, text: str) -> int:
        normalized = str(text or "").strip()
        if not normalized:
            return 0
        numeric_match = re.search(r"(\d+)\s*(?:名|位|个)?(?:人员|人)", normalized)
        if numeric_match:
            return max(0, int(numeric_match.group(1)))
        chinese_match = re.search(r"([零〇一二两三四五六七八九十百几多]+)\s*(?:名|位|个)?(?:人员|人)", normalized)
        if chinese_match:
            parsed = self._parse_chinese_number_token(chinese_match.group(1))
            if parsed is not None:
                return max(0, parsed)
        if any(token in normalized for token in ("多人", "数人", "多名人员")):
            return 2
        if any(token in normalized for token in ("一人", "1人", "1名", "1位")):
            return 1
        return 0

    def _infer_person_presence_from_text(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        if "无人" in normalized:
            return False
        if self._infer_person_count_from_text(normalized) > 0:
            return True
        person_tokens = ("人员", "有人", "人影", "男子", "女子", "行人", "巡逻", "保洁", "访客", "员工", "有人在")
        return any(token in normalized for token in person_tokens)

    def _infer_action_type_from_text(self, text: str) -> str:
        normalized = str(text or "").strip()
        return self._normalize_action_value(normalized)

    def _infer_clothing_color_from_text(self, text: str) -> str:
        normalized = str(text or "").strip()
        return self._normalize_color_value(normalized)

    def _enrich_analysis_payload(
        self,
        job: FrameJob,
        payload: dict[str, Any],
        raw_payload: str = "",
    ) -> dict[str, Any]:
        enriched = dict(payload)
        combined_text = " ".join(
            [
                str(enriched.get("anomaly_type", "")),
                str(enriched.get("description", "")),
                str(enriched.get("reason", "")),
                str(raw_payload or ""),
            ]
        )
        local_person_count, person_box = self._detect_people_from_image(job["frame_path"])
        inferred_person_count = self._infer_person_count_from_text(combined_text)
        person_count = int(enriched.get("person_count", 0) or 0)
        person_count = max(person_count, inferred_person_count, int(job.get("person_count_hint", 0) or 0), local_person_count)

        person_present = bool(enriched.get("person_present", False))
        if not person_present:
            person_present = (
                person_count > 0
                or self._infer_person_presence_from_text(combined_text)
                or float(job.get("person_score_hint", 0.0) or 0.0) >= 0.65
            )

        action_type = self._normalize_action_value(str(enriched.get("action_type", "")))
        if not action_type:
            action_type = self._infer_action_type_from_text(combined_text)
        if not action_type and person_present and float(job.get("event_duration_seconds", 0.0) or 0.0) <= 4.0:
            action_type = "经过"

        upper_clothing_color = self._normalize_color_value(str(enriched.get("upper_clothing_color", "")))
        if not upper_clothing_color and person_box is not None:
            upper_clothing_color = self._estimate_upper_clothing_color(job["frame_path"], person_box)
        if not upper_clothing_color:
            upper_clothing_color = self._infer_clothing_color_from_text(combined_text)

        lower_clothing_color = self._normalize_color_value(str(enriched.get("lower_clothing_color", "")))
        confidence = float(enriched.get("confidence", 0.0) or 0.0)
        if confidence <= 0 and person_present:
            confidence = 0.55
        if confidence <= 0 and enriched.get("anomaly_detected"):
            confidence = 0.65

        enriched.update(
            {
                "person_present": bool(person_present),
                "person_count": int(max(0, person_count if person_present else 0)),
                "action_type": action_type,
                "upper_clothing_color": upper_clothing_color,
                "lower_clothing_color": lower_clothing_color,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
        return self._apply_high_risk_override(enriched, combined_text)

    def _hydrate_event_attributes(self, event: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(event)
        combined_text = " ".join(
            [
                str(hydrated.get("anomaly_type", "")),
                str(hydrated.get("description", "")),
                str(hydrated.get("reason", "")),
            ]
        )
        person_present = bool(hydrated.get("person_present", False))
        person_count = int(hydrated.get("person_count", 0) or 0)
        if not person_count:
            person_count = self._infer_person_count_from_text(combined_text)
        if not person_present:
            person_present = person_count > 0 or self._infer_person_presence_from_text(combined_text)
        if person_present and person_count <= 0:
            person_count = 1

        action_type = self._normalize_action_value(str(hydrated.get("action_type", "")))
        if not action_type:
            action_type = self._infer_action_type_from_text(combined_text)

        upper_clothing_color = self._normalize_color_value(str(hydrated.get("upper_clothing_color", "")))
        if not upper_clothing_color:
            upper_clothing_color = self._infer_clothing_color_from_text(combined_text)

        lower_clothing_color = self._normalize_color_value(str(hydrated.get("lower_clothing_color", "")))
        confidence = float(hydrated.get("confidence", 0.0) or 0.0)
        if confidence <= 0 and person_present:
            confidence = 0.55

        hydrated.update(
            {
                "person_present": person_present,
                "person_count": person_count,
                "action_type": action_type,
                "upper_clothing_color": upper_clothing_color,
                "lower_clothing_color": lower_clothing_color,
                "confidence": max(0.0, min(1.0, confidence)),
            }
        )
        return self._apply_high_risk_override(hydrated, combined_text)

    def _merge_event_window(self, items: list[dict[str, Any]]) -> tuple[FrameAnalysis, str]:
        analyses = [item["analysis"] for item in items]
        if not analyses:
            raise ValueError("No analyses to merge")

        primary = max(
            analyses,
            key=lambda analysis: (
                -RISK_PRIORITY.get(analysis.risk_level, 9),
                int(analysis.anomaly_detected),
                int(analysis.event_frame_count),
                -abs(
                    float(analysis.frame_second)
                    - ((float(analysis.event_start_second) + float(analysis.event_end_second)) / 2.0)
                ),
            ),
        )

        anomaly_detected = any(analysis.anomaly_detected for analysis in analyses)
        risk_level = min(
            (analysis.risk_level for analysis in analyses),
            key=lambda level: RISK_PRIORITY.get(level, 9),
        )
        anomaly_counter = Counter(
            analysis.anomaly_type
            for analysis in analyses
            if analysis.anomaly_type not in {"", "normal"}
        )
        anomaly_type = anomaly_counter.most_common(1)[0][0] if anomaly_counter else primary.anomaly_type

        unique_descriptions = [analysis.description.strip() for analysis in analyses if analysis.description.strip()]
        unique_reasons = [analysis.reason.strip() for analysis in analyses if analysis.reason.strip()]
        description = self._select_preferred_event_description(analyses, primary)
        reason = primary.reason.strip() or "根据代表帧分析结果综合判断。"
        if len(unique_descriptions) > 1 and not description.endswith("。"):
            description += "。"
        if len(unique_descriptions) > 1:
            description += f" 该事件窗口合并了 {primary.event_frame_count} 张候选关键帧。"
        if len(unique_reasons) > 1 and not reason.endswith("。"):
            reason += "。"
        if len(unique_reasons) > 1:
            reason += " 综合参考了同一事件窗口内多张代表帧。"

        person_present = any(analysis.person_present or analysis.person_count > 0 for analysis in analyses)
        person_count = max((int(analysis.person_count) for analysis in analyses), default=0)
        if person_present and person_count <= 0:
            person_count = 1

        action_counter = Counter(
            self._normalize_action_value(analysis.action_type)
            for analysis in analyses
            if self._normalize_action_value(analysis.action_type)
        )
        action_type = action_counter.most_common(1)[0][0] if action_counter else ""

        upper_color_counter = Counter(
            self._normalize_color_value(analysis.upper_clothing_color)
            for analysis in analyses
            if self._normalize_color_value(analysis.upper_clothing_color)
        )
        lower_color_counter = Counter(
            self._normalize_color_value(analysis.lower_clothing_color)
            for analysis in analyses
            if self._normalize_color_value(analysis.lower_clothing_color)
        )
        upper_clothing_color = upper_color_counter.most_common(1)[0][0] if upper_color_counter else ""
        lower_clothing_color = lower_color_counter.most_common(1)[0][0] if lower_color_counter else ""
        confidence = max((float(analysis.confidence) for analysis in analyses), default=0.0)

        merged_payload = {
            "timestamp": primary.timestamp,
            "camera_id": primary.camera_id,
            "risk_level": risk_level,
            "anomaly_detected": anomaly_detected,
            "anomaly_type": anomaly_type,
            "description": description,
            "reason": reason,
            "frame_second": primary.frame_second,
            "frame_path": primary.frame_path,
            "clip_path": primary.clip_path,
            "event_group_id": primary.event_group_id,
            "event_frame_count": max(1, max(analysis.event_frame_count for analysis in analyses)),
            "representative_count": max(1, len(analyses)),
            "event_start_second": min(analysis.event_start_second for analysis in analyses),
            "event_end_second": max(analysis.event_end_second for analysis in analyses),
            "event_duration_seconds": max(analysis.event_end_second for analysis in analyses)
            - min(analysis.event_start_second for analysis in analyses),
            "person_present": person_present,
            "person_count": person_count,
            "action_type": action_type,
            "upper_clothing_color": upper_clothing_color,
            "lower_clothing_color": lower_clothing_color,
            "confidence": max(0.0, min(1.0, confidence)),
        }
        raw_payload = "\n---\n".join(str(item.get("raw_payload", "")) for item in items if str(item.get("raw_payload", "")).strip())
        return FrameAnalysis.model_validate(merged_payload), raw_payload

    @staticmethod
    def _is_generic_event_description(text: str) -> bool:
        normalized = text.strip().lower()
        if not normalized:
            return True
        generic_markers = (
            "画面未发现明显异常",
            "未发现明显异常",
            "模型未返回有效json",
            "待人工复核",
            "低风险结果写入",
        )
        return any(marker in normalized for marker in generic_markers)

    def _select_preferred_event_description(self, analyses: list[FrameAnalysis], primary: FrameAnalysis) -> str:
        informative_keywords = (
            "人员",
            "人",
            "车辆",
            "动物",
            "经过",
            "进入",
            "离开",
            "停留",
            "徘徊",
            "白色",
            "黑色",
            "浅色",
            "深色",
            "上衣",
            "外套",
            "裤子",
        )
        candidates: list[tuple[int, int, int, int, float, str]] = []
        for analysis in analyses:
            text = analysis.description.strip()
            if not text:
                continue
            keyword_score = sum(1 for keyword in informative_keywords if keyword in text)
            generic_penalty = 1 if self._is_generic_event_description(text) else 0
            center_distance = abs(
                float(analysis.frame_second)
                - ((float(analysis.event_start_second) + float(analysis.event_end_second)) / 2.0)
            )
            candidates.append(
                (
                    generic_penalty,
                    -keyword_score,
                    -len(text),
                    RISK_PRIORITY.get(analysis.risk_level, 9),
                    center_distance,
                    text,
                )
            )

        if candidates:
            return sorted(candidates)[0][-1]
        return primary.description.strip() or "画面未发现明显异常。"

    def _should_skip_generic_event(self, analysis: FrameAnalysis, items: list[dict[str, Any]]) -> bool:
        if analysis.anomaly_type == "模型未加载成功":
            return False
        if analysis.anomaly_detected or analysis.risk_level != "Low":
            return False
        if analysis.person_present or analysis.person_count > 0:
            return False
        if not self._is_generic_event_description(analysis.description):
            return False

        max_person_score = max(float(item.get("job", {}).get("person_score_hint", 0.0)) for item in items)
        max_person_count = max(int(item.get("job", {}).get("person_count_hint", 0)) for item in items)
        if max_person_count > 0 or max_person_score >= 0.65:
            return False

        if analysis.event_frame_count <= 1:
            return True
        if analysis.event_frame_count <= 2 and analysis.event_duration_seconds <= 2.5:
            return True
        return False

    def _build_report_item(self, event_id: int, camera_name: str, analysis: FrameAnalysis) -> dict[str, Any]:
        event = {
            "event_id": event_id,
            "camera_id": analysis.camera_id,
            "camera_name": camera_name,
            "timestamp": analysis.timestamp,
            "event_time": analysis.timestamp,
            "time_label": self._format_time_label(analysis.timestamp),
            "risk_level": analysis.risk_level,
            "anomaly_detected": bool(analysis.anomaly_detected),
            "anomaly_type": analysis.anomaly_type,
            "description": analysis.description,
            "reason": analysis.reason,
            "frame_second": round(float(analysis.frame_second), 2),
            "event_group_id": analysis.event_group_id,
            "event_frame_count": int(analysis.event_frame_count),
            "representative_count": int(analysis.representative_count),
            "event_start_second": round(float(analysis.event_start_second), 2),
            "event_end_second": round(float(analysis.event_end_second), 2),
            "event_duration_seconds": round(float(analysis.event_duration_seconds), 2),
            "person_present": bool(analysis.person_present),
            "person_count": int(analysis.person_count),
            "action_type": analysis.action_type,
            "upper_clothing_color": analysis.upper_clothing_color,
            "lower_clothing_color": analysis.lower_clothing_color,
            "confidence": round(float(analysis.confidence), 3),
            "alert_sent": False,
            "image_path": analysis.frame_path,
            "clip_path": analysis.clip_path,
            "image_url": self._to_session_url(analysis.frame_path),
            "clip_url": self._to_session_url(analysis.clip_path),
        }
        return self._hydrate_event_attributes(event)

    def _build_report_item_from_row(self, row: dict[str, Any]) -> dict[str, Any]:
        timestamp = str(row.get("event_time", ""))
        frame_path = str(row.get("frame_path", ""))
        clip_path = str(row.get("clip_path", ""))
        event = {
            "event_id": int(row.get("event_id", 0)),
            "camera_id": str(row.get("camera_id", "")),
            "camera_name": str(row.get("camera_name", "")),
            "timestamp": timestamp,
            "event_time": timestamp,
            "time_label": self._format_time_label(timestamp),
            "risk_level": str(row.get("risk_level", "Low")),
            "anomaly_detected": bool(row.get("anomaly_detected", 0)),
            "anomaly_type": str(row.get("anomaly_type", "normal")),
            "description": str(row.get("description", "")),
            "reason": str(row.get("reason", "")),
            "frame_second": round(float(row.get("frame_second", 0.0)), 2),
            "event_group_id": str(row.get("event_group_id", "")),
            "event_frame_count": int(row.get("event_frame_count", 1)),
            "representative_count": int(row.get("representative_count", 1)),
            "event_start_second": round(float(row.get("event_start_second", row.get("frame_second", 0.0))), 2),
            "event_end_second": round(float(row.get("event_end_second", row.get("frame_second", 0.0))), 2),
            "event_duration_seconds": round(float(row.get("event_duration_seconds", 0.0)), 2),
            "person_present": bool(row.get("person_present", 0)),
            "person_count": int(row.get("person_count", 0) or 0),
            "action_type": str(row.get("action_type", "")),
            "upper_clothing_color": str(row.get("upper_clothing_color", "")),
            "lower_clothing_color": str(row.get("lower_clothing_color", "")),
            "confidence": round(float(row.get("confidence", 0.0) or 0.0), 3),
            "alert_sent": bool(row.get("alert_sent", 0)),
            "image_path": frame_path,
            "clip_path": clip_path,
            "image_url": self._to_session_url(frame_path),
            "clip_url": self._to_session_url(clip_path),
        }
        return self._hydrate_event_attributes(event)

    def _build_embedding_text(self, event: dict[str, Any]) -> str:
        return "；".join(
            [
                str(event.get("timestamp", event.get("event_time", ""))),
                str(event.get("camera_name", "")),
                str(event.get("camera_id", "")),
                str(event.get("risk_level", "")),
                str(event.get("anomaly_type", "")),
                str(event.get("description", "")),
                str(event.get("reason", "")),
                f"person_present={int(bool(event.get('person_present', False)))}",
                f"person_count={int(event.get('person_count', 0) or 0)}",
                f"action_type={event.get('action_type', '')}",
                f"upper_clothing_color={event.get('upper_clothing_color', '')}",
                f"event_frames={event.get('event_frame_count', 1)}",
            ]
        )

    def _build_qdrant_payload(self, event: dict[str, Any]) -> dict[str, Any]:
        timestamp = str(event.get("timestamp", event.get("event_time", "")))
        parsed = self._parse_datetime(timestamp)
        period_name = ""
        event_hour = 0
        if parsed:
            event_hour = parsed.hour
            for spec in self.summary_periods:
                if spec["start"] <= event_hour < spec["end"]:
                    period_name = str(spec["name"])
                    break

        return {
            "event_id": int(event.get("event_id", 0)),
            "camera_id": str(event.get("camera_id", "")),
            "camera_name": str(event.get("camera_name", "")),
            "event_date": timestamp[:10],
            "event_time": timestamp,
            "event_hour": event_hour,
            "period_name": period_name,
            "risk_level": str(event.get("risk_level", "Low")),
            "anomaly_type": str(event.get("anomaly_type", "normal")),
            "event_group_id": str(event.get("event_group_id", "")),
            "event_frame_count": int(event.get("event_frame_count", 1)),
            "representative_count": int(event.get("representative_count", 1)),
            "person_present": bool(event.get("person_present", False)),
            "person_count": int(event.get("person_count", 0) or 0),
            "action_type": str(event.get("action_type", "")),
            "upper_clothing_color": str(event.get("upper_clothing_color", "")),
            "lower_clothing_color": str(event.get("lower_clothing_color", "")),
            "confidence": float(event.get("confidence", 0.0) or 0.0),
            "description": str(event.get("description", "")),
            "reason": str(event.get("reason", "")),
            "image_url": str(event.get("image_url", "")),
            "clip_url": str(event.get("clip_url", "")),
            "semantic_text": self._build_embedding_text(event),
        }

    def _index_report_items(
        self,
        report_items: list[dict[str, Any]],
        source: str = "analysis",
        force: bool = False,
    ) -> None:
        if (not force and not getattr(self, "vector_search_enabled", False)) or not report_items:
            return

        texts = [self._build_embedding_text(item) for item in report_items]
        embeddings = self.embedding_client.embed_texts(texts)
        points = []
        for item, vector in zip(report_items, embeddings):
            points.append(
                {
                    "id": int(item["event_id"]),
                    "vector": vector,
                    "payload": self._build_qdrant_payload(item),
                }
            )
        self.vector_store.upsert_points(points)
        self.add_log("向量库", f"{source} 事件已写入 Qdrant：{len(points)} 条。")

    def _to_session_url(self, file_path: str) -> str:
        if not file_path:
            return ""
        try:
            absolute_path = Path(file_path).resolve()
            relative_path = absolute_path.relative_to(self.base_dir.resolve())
        except ValueError:
            return ""
        return f"/session_data/{relative_path.as_posix()}"
