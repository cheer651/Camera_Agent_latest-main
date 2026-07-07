from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any

from xiaoan_prompts import XIAOAN_GREETING_TEXT


XIAOAN_NO_RESULT_TEXT = "未发现相关异常记录。"

RISK_LABELS = {
    "High": "高风险",
    "Medium": "中风险",
    "Low": "低风险",
}

RISK_QUERY_ALIASES = {
    "high": "High",
    "高风险": "High",
    "高危": "High",
    "high risk": "High",
    "medium": "Medium",
    "中风险": "Medium",
    "中危": "Medium",
    "medium risk": "Medium",
    "low": "Low",
    "低风险": "Low",
    "低危": "Low",
    "low risk": "Low",
}

PERIOD_RANGES = {
    "凌晨": (0, 6),
    "早晨": (6, 12),
    "早上": (6, 12),
    "上午": (6, 12),
    "中午": (11, 14),
    "下午": (12, 18),
    "傍晚": (17, 20),
    "晚上": (18, 24),
    "夜间": (18, 24),
}

ACTION_KEYWORD_MAP = {
    "打火机": ["打火机", "点燃", "明火", "点火", "火源"],
    "点火": ["打火机", "点燃", "明火", "点火", "火源"],
    "明火": ["打火机", "点燃", "明火", "点火", "火源"],
    "摔倒": ["摔倒", "倒地", "跌倒"],
    "倒地": ["摔倒", "倒地", "跌倒"],
    "跌倒": ["摔倒", "倒地", "跌倒"],
    "路过": ["经过", "路过"],
    "经过": ["经过", "路过"],
    "徘徊": ["徘徊"],
    "闯入": ["闯入", "入侵"],
}

CLOTHING_KEYWORD_MAP = {
    "白色": ["白色", "浅色", "白衣", "白色上衣"],
    "黑色": ["黑色", "黑衣", "黑色上衣"],
    "深色": ["深色", "黑色", "灰色", "蓝色", "深色上衣"],
    "浅色": ["浅色", "白色", "浅色上衣"],
    "红色": ["红色", "红衣", "红色上衣"],
    "蓝色": ["蓝色", "蓝衣", "蓝色上衣"],
    "灰色": ["灰色", "灰衣", "灰色上衣"],
}

WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}

CN_NUMBER_MAP = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class XiaoAnAssistantMixin:
    def answer_xiaoan_question(
        self,
        question: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        cleaned_question = str(question or "").strip()
        if not cleaned_question:
            return self._build_xiaoan_response("请输入你要查询的问题。", [], cleaned_question)

        if self._is_xiaoan_greeting(cleaned_question):
            return self._build_xiaoan_response(XIAOAN_GREETING_TEXT, [], cleaned_question)

        query = self._build_xiaoan_query(cleaned_question, list(history or []))
        self.add_log("小安", f"小安专用检索已解析：{self._describe_xiaoan_query(query)}")

        matched_events = self._search_xiaoan_events(query)
        answer = self._build_xiaoan_answer(query, matched_events)
        self.add_log("小安", f"小安专用检索命中 {len(matched_events)} 条事件。")

        # XiaoAn on the dashboard is a voice/text assistant; keyframe cards stay in
        # the dedicated keyframe analysis page to keep the voice panel lightweight.
        return self._build_xiaoan_response(answer, [], cleaned_question)

    def _build_xiaoan_response(
        self,
        answer: str,
        references: list[dict[str, Any]],
        question: str,
    ) -> dict[str, Any]:
        clean_answer = str(answer or "").strip() or XIAOAN_NO_RESULT_TEXT
        return {
            "answer": clean_answer,
            "references": references,
            "used_llm": False,
            "standalone_question": question,
            "speech_text": clean_answer,
        }

    @staticmethod
    def _build_xiaoan_speech_text(answer: str) -> str:
        text = re.sub(r"\s+", " ", str(answer or "").strip())
        if not text:
            return XIAOAN_NO_RESULT_TEXT
        if text == XIAOAN_NO_RESULT_TEXT or "未发现相关异常记录" in text:
            return XIAOAN_NO_RESULT_TEXT

        short = XiaoAnAssistantMixin._try_build_short_speech_text(text)
        if short:
            return short

        text = text.replace("相关记录", "记录")
        text = text.replace("风险等级为", "")
        text = text.replace("共发现", "发现")
        text = text.replace("共检索到", "发现")
        text = re.sub(r"(\d{1,2}):(\d{2})", r"\1点\2分", text)
        text = XiaoAnAssistantMixin._compact_xiaoan_speech_fragment(text)
        if len(text) > 42:
            text = text[:42].rstrip("，。；;、 ") + "。"
        return text

    @staticmethod
    def _try_build_short_speech_text(answer: str) -> str:
        lead_match = re.search(r"(.+?日)发现(\d+)条(.+?)相关?记录", answer)
        if not lead_match:
            return ""

        date_label = lead_match.group(1)
        count = lead_match.group(2)
        subject = XiaoAnAssistantMixin._build_speech_subject_label(lead_match.group(3))
        risk_match = re.search(r"风险等级为(高风险|中风险|低风险)", answer)
        risk_suffix = f"{risk_match.group(1)}" if risk_match else ""
        if risk_suffix and risk_suffix in subject:
            risk_suffix = ""

        detail_match = re.search(r"最典型的是(\d{1,2}):(\d{2})，([^，。]+)", answer)
        if detail_match:
            detail = XiaoAnAssistantMixin._compact_xiaoan_speech_fragment(detail_match.group(3))
            camera_match = re.search(r"([一二三四五六七八九十\d]+号摄像头)", detail)
            camera = camera_match.group(1) if camera_match else ""
            action = ""
            if "打火机" in detail:
                action = "有人持打火机"
            elif "倒地" in detail or "跌倒" in detail:
                action = "有人倒地"
            elif subject not in {"白衣", "黑衣", "深色衣服"}:
                action = detail.replace(camera, "")[:8]
            suffix = risk_suffix or action
            return f"{date_label}有{count}条{subject}记录，{camera}{suffix}。"

        suffix = f"，{risk_suffix}" if risk_suffix else ""
        return f"{date_label}有{count}条{subject}记录{suffix}。"

    @staticmethod
    def _build_speech_subject_label(text: str) -> str:
        compact = XiaoAnAssistantMixin._compact_xiaoan_speech_fragment(text)
        if "白衣" in compact:
            return "白衣"
        if "黑衣" in compact or "黑色" in compact:
            return "黑衣"
        if "深色" in compact:
            return "深色衣服"
        if "高风险" in compact:
            return "高风险"
        if "中风险" in compact:
            return "中风险"
        if "低风险" in compact:
            return "低风险"
        return compact[:8] or "相关"

    @staticmethod
    def _compact_xiaoan_speech_fragment(text: str) -> str:
        compact = str(text or "").strip(" ，。；;、 ")
        replacements = {
            "白色衣着人员经过": "白衣人员经过",
            "白色衣着人员": "白衣人员",
            "白色衣服的人": "白衣人员",
            "白色衣服人员": "白衣人员",
            "高风险相关": "高风险",
            "中风险相关": "中风险",
            "低风险相关": "低风险",
            "2号摄像头拍到人员持打火机": "2号摄像头有人持打火机",
            "1号摄像头拍到人员持打火机": "1号摄像头有人持打火机",
            "拍到人员持打火机": "有人持打火机",
            "拍到": "",
        }
        for old, new in replacements.items():
            compact = compact.replace(old, new)
        return compact.strip(" ，。；;、 ")

    @staticmethod
    def _is_xiaoan_greeting(question: str) -> bool:
        normalized = str(question or "").strip().lower()
        return normalized in {"你好", "您好", "嗨", "hello", "hi", "小安", "你好小安", "您好小安"}

    def _build_xiaoan_query(
        self,
        question: str,
        history: list[dict[str, str]],
        use_history: bool = True,
    ) -> dict[str, Any]:
        normalized = self._normalize_xiaoan_text(question)
        query = {
            "question": question,
            "normalized_question": normalized,
            "intent": self._parse_xiaoan_intent(normalized),
            "start_date": "",
            "end_date": "",
            "date_label": "",
            "period_range": None,
            "period_label": "",
            "camera_id": "",
            "camera_name": "",
            "risk_level": "",
            "risk_label": "",
            "clothing_keywords": [],
            "clothing_label": "",
            "action_keywords": [],
            "action_label": "",
            "description_keywords": [],
            "person_present": None,
            "explicit_date": False,
            "explicit_camera": False,
            "explicit_risk": False,
            "explicit_clothing": False,
            "explicit_action": False,
        }

        query.update(self._parse_xiaoan_date_scope(normalized))
        period_range, period_label = self._parse_xiaoan_period(normalized)
        query["period_range"] = period_range
        query["period_label"] = period_label
        camera_id, camera_name = self._parse_xiaoan_camera(normalized)
        query["camera_id"] = camera_id
        query["camera_name"] = camera_name
        query["explicit_camera"] = bool(camera_id)

        risk_level = self._parse_xiaoan_risk(normalized)
        query["risk_level"] = risk_level
        query["risk_label"] = RISK_LABELS.get(risk_level, "")
        query["explicit_risk"] = bool(risk_level)

        clothing_keywords, clothing_label = self._parse_xiaoan_clothing(normalized)
        query["clothing_keywords"] = clothing_keywords
        query["clothing_label"] = clothing_label
        query["explicit_clothing"] = bool(clothing_keywords)

        action_keywords, action_label = self._parse_xiaoan_action(normalized)
        query["action_keywords"] = action_keywords
        query["action_label"] = action_label
        query["explicit_action"] = bool(action_keywords)

        query["description_keywords"] = self._parse_xiaoan_description_keywords(normalized)
        query["person_present"] = self._infer_xiaoan_person_present(normalized, query)

        if use_history and self._should_merge_xiaoan_history(query, normalized):
            self._merge_xiaoan_history(query, history)

        if not query["start_date"]:
            today = self._today()
            query["start_date"] = today
            query["end_date"] = today
            query["date_label"] = "今天"

        return query

    @staticmethod
    def _should_merge_xiaoan_history(query: dict[str, Any], normalized: str) -> bool:
        if any(
            bool(query.get(flag))
            for flag in (
                "explicit_date",
                "explicit_camera",
                "explicit_risk",
                "explicit_clothing",
                "explicit_action",
            )
        ):
            return False
        followup_tokens = (
            "那天",
            "当天",
            "同一天",
            "刚才",
            "上一条",
            "上一个",
            "这些",
            "这个人",
            "那个人",
            "这个摄像头",
            "那个摄像头",
            "继续",
            "还有",
        )
        return any(token in normalized for token in followup_tokens)

    def _merge_xiaoan_history(self, query: dict[str, Any], history: list[dict[str, str]]) -> None:
        if not history:
            return
        for item in reversed(history):
            if str(item.get("role", "")).strip() != "user":
                continue
            previous_question = str(item.get("text", "")).strip()
            if not previous_question:
                continue
            previous_query = self._build_xiaoan_query(previous_question, [], use_history=False)
            if not query["explicit_date"] and previous_query["start_date"]:
                query["start_date"] = previous_query["start_date"]
                query["end_date"] = previous_query["end_date"]
                query["date_label"] = previous_query["date_label"]
            if not query["explicit_camera"] and previous_query["camera_id"]:
                query["camera_id"] = previous_query["camera_id"]
                query["camera_name"] = previous_query["camera_name"]
            if not query["explicit_risk"] and previous_query["risk_level"]:
                query["risk_level"] = previous_query["risk_level"]
                query["risk_label"] = previous_query["risk_label"]
            if not query["explicit_clothing"] and previous_query["clothing_keywords"]:
                query["clothing_keywords"] = list(previous_query["clothing_keywords"])
                query["clothing_label"] = previous_query["clothing_label"]
            if not query["explicit_action"] and previous_query["action_keywords"]:
                query["action_keywords"] = list(previous_query["action_keywords"])
                query["action_label"] = previous_query["action_label"]
            if query.get("person_present") is None and previous_query.get("person_present") is not None:
                query["person_present"] = previous_query["person_present"]
            break

    @staticmethod
    def _normalize_xiaoan_text(text: str) -> str:
        translation = str.maketrans("０１２３４５６７８９", "0123456789")
        normalized = str(text or "").translate(translation)
        normalized = normalized.replace("礼拜", "星期").replace("週", "周")
        normalized = re.sub(r"\s+", "", normalized)
        return normalized

    def _parse_xiaoan_intent(self, normalized: str) -> str:
        if any(token in normalized for token in ("几个人", "多少人", "多少名", "几名")):
            return "count_people"
        if any(token in normalized for token in ("几起", "多少起", "多少条", "几条", "几次", "多少次")):
            return "count_events"
        if any(token in normalized for token in ("有没有", "有无", "是否有", "是否出现", "出现了吗", "有没有出现", "有出现")):
            return "existence"
        if normalized.endswith("吗") and "出现" in normalized:
            return "existence"
        if any(token in normalized for token in ("发生了什么", "有哪些", "列出", "总结", "汇总", "情况")):
            return "summary"
        return "summary"

    def _parse_xiaoan_date_scope(self, normalized: str) -> dict[str, Any]:
        today = datetime.now().date()

        if "今天" in normalized:
            return self._build_xiaoan_date_payload(today, today, "今天", explicit=True)
        if "昨天" in normalized:
            target = today - timedelta(days=1)
            return self._build_xiaoan_date_payload(target, target, "昨天", explicit=True)
        if "前天" in normalized:
            target = today - timedelta(days=2)
            return self._build_xiaoan_date_payload(target, target, "前天", explicit=True)
        if any(token in normalized for token in ("最近几天", "近几天")):
            start = today - timedelta(days=2)
            return self._build_xiaoan_date_payload(start, today, "最近三天", explicit=True)

        range_payload = self._parse_xiaoan_explicit_date_range(normalized, today=today)
        if range_payload["explicit_date"]:
            return range_payload

        weekday_match = re.search(r"上周([一二三四五六日天])", normalized)
        if weekday_match:
            weekday = WEEKDAY_MAP.get(weekday_match.group(1))
            if weekday is not None:
                current_week_start = today - timedelta(days=today.weekday())
                last_week_start = current_week_start - timedelta(days=7)
                target = last_week_start + timedelta(days=weekday)
                return self._build_xiaoan_date_payload(target, target, f"上周{weekday_match.group(1)}", explicit=True)

        if any(token in normalized for token in ("上周", "上星期")):
            current_week_start = today - timedelta(days=today.weekday())
            last_week_start = current_week_start - timedelta(days=7)
            last_week_end = last_week_start + timedelta(days=6)
            return self._build_xiaoan_date_payload(last_week_start, last_week_end, "上周", explicit=True)

        full_date_match = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})[日号]?", normalized)
        if full_date_match:
            year = int(full_date_match.group(1))
            month = int(full_date_match.group(2))
            day = int(full_date_match.group(3))
            target = date(year, month, day)
            return self._build_xiaoan_date_payload(target, target, f"{month}月{day}日", explicit=True)

        month_day_match = re.search(r"([零〇一二两三四五六七八九十\d]{1,3})月([零〇一二两三四五六七八九十\d]{1,3})[日号]?", normalized)
        if month_day_match:
            month = self._parse_xiaoan_number(month_day_match.group(1))
            day = self._parse_xiaoan_number(month_day_match.group(2))
            if month and day:
                target = date(today.year, month, day)
                return self._build_xiaoan_date_payload(target, target, f"{month}月{day}日", explicit=True)

        return self._build_xiaoan_date_payload(None, None, "", explicit=False)

    def _parse_xiaoan_explicit_date_range(self, normalized: str, today: date) -> dict[str, Any]:
        connector = r"(?:到|至|—|-|~|～)"
        number_token = r"[零〇一二两三四五六七八九十\d]{1,3}"

        full_range = re.search(
            rf"(?:(\d{{4}})[年/-])?({number_token})月({number_token})[日号]?"
            rf"{connector}"
            rf"(?:(\d{{4}})[年/-])?(?:({number_token})月)?({number_token})[日号]?",
            normalized,
        )
        if full_range:
            start_year = int(full_range.group(1) or today.year)
            start_month = self._parse_xiaoan_number(full_range.group(2))
            start_day = self._parse_xiaoan_number(full_range.group(3))
            end_year = int(full_range.group(4) or start_year)
            end_month = self._parse_xiaoan_number(full_range.group(5)) if full_range.group(5) else start_month
            end_day = self._parse_xiaoan_number(full_range.group(6))
            if start_month and start_day and end_month and end_day:
                start = date(start_year, start_month, start_day)
                end = date(end_year, end_month, end_day)
                if end < start:
                    start, end = end, start
                label = self._format_xiaoan_date_range_label(start, end)
                return self._build_xiaoan_date_payload(start, end, label, explicit=True)

        numeric_range = re.search(
            rf"(\d{{4}})[/-](\d{{1,2}})[/-](\d{{1,2}}){connector}(\d{{4}})[/-](\d{{1,2}})[/-](\d{{1,2}})",
            normalized,
        )
        if numeric_range:
            start = date(int(numeric_range.group(1)), int(numeric_range.group(2)), int(numeric_range.group(3)))
            end = date(int(numeric_range.group(4)), int(numeric_range.group(5)), int(numeric_range.group(6)))
            if end < start:
                start, end = end, start
            label = self._format_xiaoan_date_range_label(start, end)
            return self._build_xiaoan_date_payload(start, end, label, explicit=True)

        return self._build_xiaoan_date_payload(None, None, "", explicit=False)

    @staticmethod
    def _format_xiaoan_date_range_label(start: date, end: date) -> str:
        if start == end:
            return f"{start.month}月{start.day}日"
        if start.year == end.year:
            return f"{start.month}月{start.day}日到{end.month}月{end.day}日"
        return f"{start.year}年{start.month}月{start.day}日到{end.year}年{end.month}月{end.day}日"

    @staticmethod
    def _build_xiaoan_date_payload(
        start: date | None,
        end: date | None,
        label: str,
        explicit: bool,
    ) -> dict[str, Any]:
        return {
            "start_date": start.strftime("%Y-%m-%d") if start else "",
            "end_date": end.strftime("%Y-%m-%d") if end else "",
            "date_label": label,
            "explicit_date": explicit,
        }

    @staticmethod
    def _parse_xiaoan_number(token: str) -> int | None:
        raw = str(token or "").strip()
        if not raw:
            return None
        if raw.isdigit():
            return int(raw)
        if raw == "十":
            return 10
        if "十" in raw:
            left, right = raw.split("十", 1)
            tens = 1 if not left else CN_NUMBER_MAP.get(left)
            ones = 0 if not right else CN_NUMBER_MAP.get(right)
            if tens is None or ones is None:
                return None
            return tens * 10 + ones
        if len(raw) == 1:
            return CN_NUMBER_MAP.get(raw)
        value = 0
        for char in raw:
            digit = CN_NUMBER_MAP.get(char)
            if digit is None:
                return None
            value = value * 10 + digit
        return value

    def _parse_xiaoan_period(self, normalized: str) -> tuple[tuple[int, int] | None, str]:
        for label, hour_range in PERIOD_RANGES.items():
            if label in normalized:
                return hour_range, label
        return None, ""

    def _parse_xiaoan_camera(self, normalized: str) -> tuple[str, str]:
        patterns = [
            re.search(r"([一二两三四五六七八九十\d]+)号摄像头", normalized),
            re.search(r"摄像头([一二两三四五六七八九十\d]+)", normalized),
            re.search(r"cam0*(\d+)", normalized, flags=re.IGNORECASE),
        ]
        camera_number: int | None = None
        for match in patterns:
            if not match:
                continue
            camera_number = self._parse_xiaoan_number(match.group(1))
            if camera_number:
                break
        if not camera_number:
            return "", ""
        camera_id = f"cam{camera_number:02d}"
        camera_name = getattr(self.camera_lookup.get(camera_id), "camera_name", "") or f"{camera_number}号摄像头"
        return camera_id, camera_name

    @staticmethod
    def _parse_xiaoan_risk(normalized: str) -> str:
        for alias, canonical in RISK_QUERY_ALIASES.items():
            if alias in normalized:
                return canonical
        return ""

    def _parse_xiaoan_clothing(self, normalized: str) -> tuple[list[str], str]:
        for canonical, keywords in CLOTHING_KEYWORD_MAP.items():
            if any(keyword in normalized for keyword in keywords):
                return list(dict.fromkeys(keywords)), canonical
        return [], ""

    def _parse_xiaoan_action(self, normalized: str) -> tuple[list[str], str]:
        for label, keywords in ACTION_KEYWORD_MAP.items():
            if any(keyword in normalized for keyword in keywords):
                return list(dict.fromkeys(keywords)), label
        return [], ""

    @staticmethod
    def _parse_xiaoan_description_keywords(normalized: str) -> list[str]:
        keywords: list[str] = []
        if "白色" in normalized:
            keywords.append("白色")
        if "黑色" in normalized:
            keywords.append("黑色")
        if "深色" in normalized:
            keywords.append("深色")
        if "浅色" in normalized:
            keywords.append("浅色")
        if "打火机" in normalized or "点火" in normalized or "明火" in normalized:
            keywords.extend(["打火机", "点火", "明火"])
        if "摔倒" in normalized or "倒地" in normalized:
            keywords.extend(["摔倒", "倒地"])
        return list(dict.fromkeys(keywords))

    @staticmethod
    def _infer_xiaoan_person_present(normalized: str, query: dict[str, Any]) -> bool | None:
        if query["clothing_keywords"]:
            return True
        if any(token in normalized for token in ("人", "人员", "有人", "几个人", "多少人", "路过", "经过")):
            return True
        return None

    def _describe_xiaoan_query(self, query: dict[str, Any]) -> str:
        parts = [f"范围={query['date_label'] or '今天'}"]
        if query["period_label"]:
            parts.append(f"时段={query['period_label']}")
        if query["camera_name"]:
            parts.append(f"摄像头={query['camera_name']}")
        if query["risk_label"]:
            parts.append(f"风险={query['risk_label']}")
        if query["clothing_label"]:
            parts.append(f"衣着={query['clothing_label']}")
        if query["action_label"]:
            parts.append(f"动作={query['action_label']}")
        parts.append(f"意图={query['intent']}")
        return "，".join(parts)

    def _search_xiaoan_events(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.store.search_events(
            start_date=query["start_date"] or None,
            end_date=query["end_date"] or None,
            camera_id=query["camera_id"] or None,
            risk_level=query["risk_level"] or None,
            period_range=query["period_range"],
            person_present=query["person_present"],
            action_keywords=query["action_keywords"] or None,
            clothing_keywords=query["clothing_keywords"] or None,
            description_keywords=query["description_keywords"] or None,
            limit=200,
            order_desc=False,
        )
        events = []
        for row in rows:
            event = self._build_report_item_from_row(row)
            event["task_id"] = str(row.get("task_id", ""))
            events.append(event)
        return self._merge_xiaoan_events(events)

    @staticmethod
    def _merge_xiaoan_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for event in events:
            group_id = str(event.get("event_group_id", "")).strip()
            task_id = str(event.get("task_id", "")).strip()
            camera_id = str(event.get("camera_id", "")).strip()
            key = f"{task_id}|{camera_id}|{group_id}" if group_id else str(event.get("event_id"))
            if key not in merged:
                merged[key] = event
                continue
            existing = merged[key]
            if float(event.get("confidence", 0.0) or 0.0) > float(existing.get("confidence", 0.0) or 0.0):
                merged[key] = event
        return sorted(
            merged.values(),
            key=lambda item: (str(item.get("event_time", "")), int(item.get("event_id", 0))),
        )

    def _build_xiaoan_answer(self, query: dict[str, Any], events: list[dict[str, Any]]) -> str:
        if not events:
            return XIAOAN_NO_RESULT_TEXT

        intent = str(query.get("intent", "summary"))
        if intent == "count_people":
            return self._build_xiaoan_people_count_answer(query, events)
        if intent == "count_events":
            return self._build_xiaoan_count_answer(query, events)
        if intent == "existence":
            return self._build_xiaoan_existence_answer(query, events)
        return self._build_xiaoan_summary_answer(query, events)

    def _build_xiaoan_count_answer(self, query: dict[str, Any], events: list[dict[str, Any]]) -> str:
        count = len(events)
        label = self._build_xiaoan_subject_label(query)
        lead = f"{query['date_label']}共发生{count}起{label}事件。"
        return self._build_xiaoan_brief_answer(lead, query, events)

    def _build_xiaoan_people_count_answer(self, query: dict[str, Any], events: list[dict[str, Any]]) -> str:
        total_people = sum(self._estimate_xiaoan_people_count(event) for event in events)
        if total_people <= 0:
            return XIAOAN_NO_RESULT_TEXT
        label = query["camera_name"] or "监控范围内"
        lead = f"{query['date_label']}{label}累计记录到{total_people}人次相关活动。"
        return self._build_xiaoan_brief_answer(lead, query, events)

    def _build_xiaoan_existence_answer(self, query: dict[str, Any], events: list[dict[str, Any]]) -> str:
        label = self._build_xiaoan_subject_label(query)
        lead = f"{query['date_label']}发现{len(events)}条{label}相关记录。"
        return self._build_xiaoan_brief_answer(lead, query, events)

    def _build_xiaoan_summary_answer(self, query: dict[str, Any], events: list[dict[str, Any]]) -> str:
        label = self._build_xiaoan_subject_label(query)
        lead = f"{query['date_label']}共检索到{len(events)}条{label}。"
        return self._build_xiaoan_brief_answer(lead, query, events)

    def _build_xiaoan_brief_answer(
        self,
        lead: str,
        query: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> str:
        key_events = self._select_xiaoan_key_events(query, events, limit=1)
        if not key_events:
            return lead
        clause = self._build_xiaoan_event_sentence(
            key_events[0],
            query=query,
            include_risk=not bool(query.get("explicit_risk")),
        )
        if not clause:
            return lead
        return f"{lead} 其中最典型的是{clause}。"

    def _build_xiaoan_subject_label(self, query: dict[str, Any]) -> str:
        if query["risk_label"]:
            return query["risk_label"]
        if query["clothing_label"]:
            return f"{query['clothing_label']}衣着人员"
        if query["action_label"]:
            return f"{query['action_label']}相关事件"
        return "相关事件"

    def _select_xiaoan_key_events(
        self,
        query: dict[str, Any],
        events: list[dict[str, Any]],
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        def query_match_weight(event: dict[str, Any]) -> int:
            score = 0
            if query.get("explicit_risk") and str(event.get("risk_level", "")) == str(query.get("risk_level", "")):
                score += 6
            if query.get("explicit_camera") and str(event.get("camera_id", "")) == str(query.get("camera_id", "")):
                score += 4
            if query.get("explicit_clothing") and self._event_matches_xiaoan_clothing(event, str(query.get("clothing_label", ""))):
                score += 10
            if query.get("explicit_action") and self._event_matches_xiaoan_action(event, str(query.get("action_label", ""))):
                score += 10
            return score

        def risk_weight(event: dict[str, Any]) -> int:
            risk_level = str(event.get("risk_level", "Low"))
            return {"High": 3, "Medium": 2, "Low": 1}.get(risk_level, 0)

        def action_weight(event: dict[str, Any]) -> int:
            anomaly_type = str(event.get("anomaly_type", "")).lower()
            description = f"{event.get('description', '')} {event.get('reason', '')}"
            if anomaly_type == "fire" or any(token in description for token in ("打火机", "点燃", "点火", "明火")):
                return 3
            if anomaly_type == "fall" or any(token in description for token in ("摔倒", "跌倒", "倒地")):
                return 2
            return 1

        ranked = sorted(
            events,
            key=lambda event: (
                query_match_weight(event),
                risk_weight(event),
                action_weight(event),
                str(event.get("event_time", "")),
                int(event.get("event_id", 0)),
            ),
            reverse=True,
        )
        return ranked[:limit]

    @staticmethod
    def _event_matches_xiaoan_clothing(event: dict[str, Any], clothing_label: str) -> bool:
        label = str(clothing_label or "").strip()
        if not label:
            return False
        haystack = " ".join(
            [
                str(event.get("upper_clothing_color", "")),
                str(event.get("lower_clothing_color", "")),
                str(event.get("description", "")),
                str(event.get("reason", "")),
            ]
        )
        aliases = CLOTHING_KEYWORD_MAP.get(label, [label])
        return any(alias in haystack for alias in aliases)

    @staticmethod
    def _event_matches_xiaoan_action(event: dict[str, Any], action_label: str) -> bool:
        label = str(action_label or "").strip()
        if not label:
            return False
        haystack = " ".join(
            [
                str(event.get("action_type", "")),
                str(event.get("anomaly_type", "")),
                str(event.get("description", "")),
                str(event.get("reason", "")),
            ]
        )
        aliases = ACTION_KEYWORD_MAP.get(label, [label])
        return any(alias in haystack for alias in aliases)

    def _build_xiaoan_event_sentence(
        self,
        event: dict[str, Any],
        query: dict[str, Any] | None = None,
        include_risk: bool = True,
    ) -> str:
        time_label = self._format_time_label(str(event.get("event_time", event.get("timestamp", ""))))[:5]
        camera_name = str(event.get("camera_name", "")).strip() or str(event.get("camera_id", "")).strip() or "相关摄像头"
        detail = self._summarize_xiaoan_event_detail(event, query=query)
        if not detail:
            detail = "拍到相关活动"
        sentence = f"{time_label}，{camera_name}{detail}"
        if include_risk:
            risk_label = RISK_LABELS.get(str(event.get("risk_level", "")), "")
            if risk_label:
                sentence += f"，风险等级为{risk_label}"
        return sentence

    def _summarize_xiaoan_event_detail(self, event: dict[str, Any], query: dict[str, Any] | None = None) -> str:
        anomaly_type = str(event.get("anomaly_type", "")).lower()
        action_type = str(event.get("action_type", "")).strip()
        upper_color = str(event.get("upper_clothing_color", "")).strip()
        reason = f"{event.get('description', '')} {event.get('reason', '')}"
        clothing_label = str((query or {}).get("clothing_label", "")).strip()

        if clothing_label:
            clothing_text = f"{clothing_label}衣着人员"
            if action_type == "经过":
                return f"拍到{clothing_text}经过"
            if action_type == "办公":
                return f"拍到{clothing_text}活动"
            return f"拍到{clothing_text}"

        if anomaly_type == "fire" or any(token in reason for token in ("打火机", "点火", "点燃", "明火")):
            return "拍到人员持打火机"
        if anomaly_type == "fall" or any(token in reason for token in ("摔倒", "跌倒", "倒地")):
            return "拍到人员疑似跌倒"
        if action_type == "经过":
            if upper_color and upper_color != "未知":
                return f"拍到{upper_color}衣着人员经过"
            return "拍到人员经过"
        if action_type == "办公":
            if upper_color and upper_color != "未知":
                return f"拍到{upper_color}衣着人员活动"
            return "拍到人员活动"

        description = self._clean_xiaoan_description(str(event.get("description", "")))
        if not description:
            return ""
        description = re.sub(r"^[0-9一二两三四五六七八九十]+名", "", description)
        description = description[:18].rstrip("，。；")
        if description.startswith(("发现", "出现", "拍到")):
            return description
        return f"拍到{description}"

    @staticmethod
    def _clean_xiaoan_description(text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"该事件窗口合并了.*?$", "", cleaned)
        cleaned = re.sub(r"综合参考了.*?$", "", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        cleaned = cleaned.rstrip("。；，")
        return cleaned

    @staticmethod
    def _estimate_xiaoan_people_count(event: dict[str, Any]) -> int:
        person_count = int(event.get("person_count", 0) or 0)
        if person_count > 0:
            return person_count
        if bool(event.get("person_present", False)):
            return 1
        description = str(event.get("description", ""))
        return 1 if "人" in description else 0
