from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from monitoring_types import ChatState


class MonitoringQueryMixin:
    def _sanitize_rewritten_question(self, original: str, rewritten: str) -> str:
        original = str(original or "").strip()
        rewritten = str(rewritten or "").strip()
        if not rewritten:
            return original
        if len(rewritten) > 160:
            return original
        return rewritten

    @staticmethod
    def _normalize_query_text(text: str) -> str:
        normalized = str(text or "")
        if not normalized:
            return ""
        normalized = normalized.translate(
            str.maketrans(
                {
                    "０": "0",
                    "１": "1",
                    "２": "2",
                    "３": "3",
                    "４": "4",
                    "５": "5",
                    "６": "6",
                    "７": "7",
                    "８": "8",
                    "９": "9",
                    "／": "/",
                    "－": "-",
                    "，": ",",
                    "。": ".",
                    "？": "?",
                    "！": "!",
                    "：": ":",
                    "；": ";",
                    "（": "(",
                    "）": ")",
                }
            )
        )
        normalized = normalized.replace("星期", "周").replace("礼拜", "周")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _parse_chinese_number_token(self, token: str) -> int | None:
        token = self._normalize_query_text(token)
        if not token:
            return None
        if token.isdigit():
            return int(token)
        if token in {"几", "多"}:
            return 2

        digit_map = {
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
        }
        normalized = token.replace("两", "二")
        if "十" in normalized:
            if normalized == "十":
                return 10
            tens_part, ones_part = normalized.split("十", 1)
            tens = 1 if not tens_part else digit_map.get(tens_part)
            if tens is None:
                return None
            if not ones_part:
                return tens * 10
            ones = digit_map.get(ones_part)
            if ones is None:
                return None
            return tens * 10 + ones

        value = 0
        for char in normalized:
            digit = digit_map.get(char)
            if digit is None:
                return None
            value = value * 10 + digit
        return value

    def _extract_date_phrase(self, text: str) -> str:
        text = self._normalize_query_text(text)
        patterns = [
            r"\d{4}[/-]\d{1,2}[/-]\d{1,2}",
            r"\d{1,2}月\d{1,2}[日号]",
            r"[一二三四五六七八九十两〇零]+月[一二三四五六七八九十两〇零]+[日号]",
            r"(今天|昨日|昨天|前天|明天|后天)",
            r"(上周|这周|本周|下周)[一二三四五六日天]?",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0)
        return ""

    def _resolve_date_phrase(self, text: str, now: datetime | None = None) -> tuple[str | None, str | None]:
        now = now or datetime.now()
        text = self._normalize_query_text(text)
        if not text:
            return None, None

        absolute_match = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text)
        if absolute_match:
            year, month, day = [int(value) for value in absolute_match.groups()]
            return f"{year:04d}-{month:02d}-{day:02d}", absolute_match.group(0)

        numeric_cn_match = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
        if numeric_cn_match:
            month, day = [int(value) for value in numeric_cn_match.groups()]
            return f"{now.year:04d}-{month:02d}-{day:02d}", numeric_cn_match.group(0)

        chinese_cn_match = re.search(r"([一二三四五六七八九十两〇零]+)月([一二三四五六七八九十两〇零]+)[日号]", text)
        if chinese_cn_match:
            month = self._parse_chinese_number_token(chinese_cn_match.group(1))
            day = self._parse_chinese_number_token(chinese_cn_match.group(2))
            if month and day:
                return f"{now.year:04d}-{month:02d}-{day:02d}", chinese_cn_match.group(0)

        relative_map = {
            "今天": 0,
            "昨天": -1,
            "昨日": -1,
            "前天": -2,
            "明天": 1,
            "后天": 2,
        }
        for token, delta in relative_map.items():
            if token in text:
                resolved = (now + timedelta(days=delta)).date().strftime("%Y-%m-%d")
                return resolved, token
        return None, None

    def _resolve_date_scope(self, text: str, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now()
        text = self._normalize_query_text(text)

        scope = {
            "date": self._today(),
            "date_start": self._today(),
            "date_end": self._today(),
            "date_label": "今天",
            "days_back": None,
        }

        if any(token in text for token in ("最近七天", "近一周", "最近一周", "最近7天")):
            end_date = now.date()
            start_date = end_date - timedelta(days=6)
            scope.update(
                {
                    "date": None,
                    "date_start": start_date.strftime("%Y-%m-%d"),
                    "date_end": end_date.strftime("%Y-%m-%d"),
                    "date_label": "最近7天",
                    "days_back": 7,
                }
            )
            return scope

        week_prefix_map = {"上周": -7, "这周": 0, "本周": 0, "下周": 7}
        aggregate_week = re.search(r"(上周|这周|本周|下周)(?:一共|总共|总计|累计|整周|整个星期|整个礼拜|全周|这一周|那一周)", text)
        if aggregate_week:
            monday = now.date() - timedelta(days=now.weekday())
            start_date = monday + timedelta(days=week_prefix_map[aggregate_week.group(1)])
            end_date = start_date + timedelta(days=6)
            scope.update(
                {
                    "date": None,
                    "date_start": start_date.strftime("%Y-%m-%d"),
                    "date_end": end_date.strftime("%Y-%m-%d"),
                    "date_label": aggregate_week.group(1),
                    "days_back": None,
                }
            )
            return scope

        plain_week = re.search(r"(上周|这周|本周|下周)(?![一二三四五六日天])", text)
        if plain_week:
            monday = now.date() - timedelta(days=now.weekday())
            start_date = monday + timedelta(days=week_prefix_map[plain_week.group(1)])
            end_date = start_date + timedelta(days=6)
            scope.update(
                {
                    "date": None,
                    "date_start": start_date.strftime("%Y-%m-%d"),
                    "date_end": end_date.strftime("%Y-%m-%d"),
                    "date_label": plain_week.group(1),
                    "days_back": None,
                }
            )
            return scope

        relative_weekday = re.search(r"(上周|这周|本周|下周)([一二三四五六日天])(?![共])", text)
        if relative_weekday:
            weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
            monday = now.date() - timedelta(days=now.weekday())
            resolved_date = monday + timedelta(days=week_prefix_map[relative_weekday.group(1)] + weekday_map[relative_weekday.group(2)])
            scope.update(
                {
                    "date": resolved_date.strftime("%Y-%m-%d"),
                    "date_start": resolved_date.strftime("%Y-%m-%d"),
                    "date_end": resolved_date.strftime("%Y-%m-%d"),
                    "date_label": relative_weekday.group(0),
                    "days_back": None,
                }
            )
            return scope

        resolved_date, date_label = self._resolve_date_phrase(text, now=now)
        if resolved_date:
            scope.update(
                {
                    "date": resolved_date,
                    "date_start": resolved_date,
                    "date_end": resolved_date,
                    "date_label": date_label or resolved_date,
                    "days_back": None,
                }
            )
        return scope

    @staticmethod
    def _extract_risk_filter(question: str) -> tuple[str | None, str]:
        question = MonitoringQueryMixin._normalize_query_text(question)
        if any(token in question for token in ("高危", "高风险")):
            return "High", "高危"
        if any(token in question for token in ("中危", "中风险")):
            return "Medium", "中危"
        if any(token in question for token in ("低危", "低风险")):
            return "Low", "低危"
        lowered = question.lower()
        if "high risk" in lowered:
            return "High", "高危"
        if "medium risk" in lowered:
            return "Medium", "中危"
        if "low risk" in lowered:
            return "Low", "低危"
        return None, ""

    @staticmethod
    def _extract_action_filter(question: str) -> tuple[list[str], str]:
        question = MonitoringQueryMixin._normalize_query_text(question)
        action_groups = {
            "经过": ["路过", "经过", "走过", "通行", "行走", "通过", "走动", "走在", "移动"],
            "徘徊": ["徘徊", "来回走动", "反复走动", "游荡"],
            "停留": ["停留", "逗留", "驻足", "停着", "短暂停留"],
            "闯入": ["闯入", "入侵", "进入禁区", "强行进入"],
            "聚集": ["聚集", "扎堆", "围在一起"],
        }
        for label, keywords in action_groups.items():
            if any(keyword in question for keyword in keywords):
                return keywords, label
        return [], ""

    @staticmethod
    def _extract_clothing_filter(question: str) -> tuple[list[str], str]:
        question = MonitoringQueryMixin._normalize_query_text(question)
        color_groups = {
            "黑色": ["黑衣", "黑色衣服", "黑色上衣", "黑衣服", "黑色外套", "深色衣服", "深色上衣", "深色外套"],
            "白色": ["白衣", "白色衣服", "白色上衣", "白衣服", "浅色衣服", "浅色上衣"],
            "红色": ["红衣", "红色衣服", "红色上衣"],
            "蓝色": ["蓝衣", "蓝色衣服", "蓝色上衣"],
            "灰色": ["灰衣", "灰色衣服", "灰色上衣"],
        }
        for label, keywords in color_groups.items():
            if any(keyword in question for keyword in keywords):
                return keywords, label
        return [], ""

    @staticmethod
    def _classify_query_intent(question: str) -> str:
        normalized = MonitoringQueryMixin._normalize_query_text(question)
        normalized = re.sub(r"[?。!，,;:\s]+$", "", normalized)
        if re.fullmatch(r"(你好|您好|嗨|hello|hi)", normalized, flags=re.IGNORECASE):
            return "greeting"
        if re.search(r"(几个人|多少人|多少名人员|多少位人员|有几个人)", normalized):
            return "count_people"
        if re.search(r"(几起|多少起|多少条|多少次)", normalized) and any(
            token in normalized for token in ("事件", "异常", "告警", "高危", "高风险", "中危", "低危")
        ):
            return "count_events"
        if any(
            token in normalized
            for token in ("有没有", "是否有", "有无", "是否出现", "有没有出现", "有没有拍到", "是否发生", "有出现")
        ):
            return "existence"
        if re.search(r"(有.*吗|出现.*吗|拍到.*吗|发生.*吗|查到.*吗|看到了吗)$", normalized):
            return "existence"
        if any(token in normalized for token in ("发生了什么", "什么情况", "有什么记录", "有哪些记录", "查一下", "查一查")):
            return "list"
        return "list"

    @staticmethod
    def _extract_description_keywords(question: str) -> list[str]:
        question = MonitoringQueryMixin._normalize_query_text(question)
        keywords: list[str] = []
        for token in (
            "黑衣",
            "白衣",
            "红衣",
            "蓝衣",
            "灰衣",
            "黑色衣服",
            "白色衣服",
            "深色",
            "浅色",
            "人员",
            "人",
            "车辆",
            "车牌",
            "徘徊",
            "闯入",
            "停留",
            "经过",
            "路过",
            "聚集",
            "打火机",
            "点火",
            "明火",
            "跌倒",
            "滑倒",
        ):
            if token in question and token not in keywords:
                keywords.append(token)
        return keywords

    def _extract_question_context_parts(self, text: str) -> dict[str, str]:
        text = self._normalize_query_text(text)
        if not text:
            return {}

        date_phrase = self._extract_date_phrase(text)
        if not date_phrase:
            week_match = re.search(r"(上周|这周|本周|下周)(?:一共|总共|总计|累计|整周|整个星期|整个礼拜|全周|[一二三四五六日天])?", text)
            if week_match:
                date_phrase = week_match.group(0)

        period_phrase = ""
        for token in ("凌晨", "早晨", "上午", "中午", "下午", "傍晚", "晚上", "夜间", "晚间"):
            if token in text:
                period_phrase = token
                break

        camera_phrase = ""
        camera_match = re.search(r"([0-9一二三四五六七八九十两]+)号摄像头", text)
        if camera_match:
            camera_phrase = camera_match.group(0)

        appearance_phrase = ""
        appearance_tokens = (
            "黑衣", "白衣", "红衣", "蓝衣", "灰衣", "深色衣服", "浅色衣服", "黑色衣服", "白色衣服",
        )
        for token in appearance_tokens:
            if token in text:
                appearance_phrase = token
                break

        intent_phrase = ""
        intent_tokens = ("有没有", "是否有", "有无", "有几个人", "几个人", "多少人", "多少起", "几起", "发生了什么")
        for token in intent_tokens:
            if token in text:
                intent_phrase = token
                break

        return {
            "date": date_phrase,
            "period": period_phrase,
            "camera": camera_phrase,
            "appearance": appearance_phrase,
            "intent": intent_phrase,
        }

    def _rewrite_question_with_history(self, question: str, history: list[dict[str, str]]) -> str:
        question = str(question or "").strip()
        if not question:
            return question

        current_parts = self._extract_question_context_parts(question)
        if current_parts.get("date") and current_parts.get("camera"):
            return question

        history_texts = [str(item.get("text", "")).strip() for item in history if str(item.get("text", "")).strip()]
        if not history_texts:
            return question

        last_user = ""
        for item in reversed(history):
            if str(item.get("role", "")) == "user" and str(item.get("text", "")).strip():
                last_user = str(item.get("text", "")).strip()
                break

        previous_parts = self._extract_question_context_parts(last_user or history_texts[-1])
        rebuilt = question
        if not current_parts.get("date") and previous_parts.get("date"):
            rebuilt = f"{previous_parts['date']}{rebuilt}"
        if not current_parts.get("period") and previous_parts.get("period"):
            rebuilt = f"{previous_parts['period']}{rebuilt}"
        if not current_parts.get("camera") and previous_parts.get("camera"):
            rebuilt = f"{previous_parts['camera']}{rebuilt}"
        if not current_parts.get("appearance") and previous_parts.get("appearance"):
            rebuilt = f"{rebuilt} {previous_parts['appearance']}".strip()
        return self._sanitize_rewritten_question(question, rebuilt)

    def _should_use_fallback_answer(
        self,
        generated_answer: str,
        fallback_answer: str,
        matched_events: list[dict[str, Any]],
    ) -> bool:
        answer = str(generated_answer or "").strip()
        fallback = str(fallback_answer or "").strip()
        if not answer:
            return True
        if not matched_events:
            return False
        if answer == fallback:
            return False
        generic_patterns = (
            "建议进一步核查",
            "建议人工复核",
            "请结合现场情况判断",
            "可能存在",
        )
        return any(pattern in answer for pattern in generic_patterns) and len(answer) < len(fallback)

    @staticmethod
    def _has_structured_query_filters(constraints: dict[str, Any]) -> bool:
        return bool(
            constraints.get("risk_level")
            or constraints.get("action_keywords")
            or constraints.get("clothing_keywords")
            or constraints.get("person_related")
        )

    def _build_chat_graph(self) -> Any:
        workflow = StateGraph(ChatState)
        workflow.add_node("rewrite_question", self._chat_node_rewrite_question)
        workflow.add_node("extract_constraints", self._chat_node_extract_constraints)
        workflow.add_node("load_candidates", self._chat_node_load_candidates)
        workflow.add_node("rank_candidates", self._chat_node_rank_candidates)
        workflow.add_node("select_matches", self._chat_node_select_matches)
        workflow.add_node("build_answer", self._chat_node_build_answer)
        workflow.add_node("polish_answer", self._chat_node_polish_answer)

        workflow.add_edge(START, "rewrite_question")
        workflow.add_edge("rewrite_question", "extract_constraints")
        workflow.add_edge("extract_constraints", "load_candidates")
        workflow.add_edge("load_candidates", "rank_candidates")
        workflow.add_edge("rank_candidates", "select_matches")
        workflow.add_edge("select_matches", "build_answer")
        workflow.add_edge("build_answer", "polish_answer")
        workflow.add_edge("polish_answer", END)
        return workflow.compile()

    def _chat_node_rewrite_question(self, state: ChatState) -> dict[str, Any]:
        question = str(state.get("question", "")).strip()
        history = [
            {
                "role": str(item.get("role", "")),
                "text": str(item.get("text", "")).strip(),
            }
            for item in list(state.get("history", []))
            if str(item.get("text", "")).strip()
        ]
        standalone_question = self._rewrite_question_with_llm(question, history)
        return {"standalone_question": standalone_question, "history": history}

    def _chat_node_extract_constraints(self, state: ChatState) -> dict[str, Any]:
        question = str(state.get("standalone_question") or state.get("question", ""))
        constraints = self._extract_query_constraints(question)
        self.add_log("问答", f"LangGraph 问答节点已解析查询范围：{self._describe_query_scope(constraints)}")
        return {"constraints": constraints}

    def _chat_node_load_candidates(self, state: ChatState) -> dict[str, Any]:
        candidates = self._load_candidate_events(dict(state.get("constraints", {})))
        return {"candidate_events": candidates}

    def _chat_node_rank_candidates(self, state: ChatState) -> dict[str, Any]:
        constraints = dict(state.get("constraints", {}))
        ranked = self._rank_events(
            str(constraints.get("semantic_query", "")),
            list(state.get("candidate_events", [])),
            constraints=constraints,
        )
        return {"ranked_events": ranked}

    def _chat_node_select_matches(self, state: ChatState) -> dict[str, Any]:
        constraints = dict(state.get("constraints", {}))
        candidate_events = list(state.get("candidate_events", []))
        if self._has_structured_query_filters(constraints):
            matched_events = candidate_events[:4]
        else:
            matched_events = self._select_matched_events(list(state.get("ranked_events", [])), constraints)
        reference_source = matched_events or candidate_events
        references = [self._build_chat_reference(event) for event in reference_source[:4]]
        return {"matched_events": matched_events, "references": references}

    def _chat_node_build_answer(self, state: ChatState) -> dict[str, Any]:
        question = str(state.get("standalone_question") or state.get("question", ""))
        history = list(state.get("history", []))
        candidate_events = list(state.get("candidate_events", []))
        matched_events = list(state.get("matched_events", []))
        query_result = self._build_query_result(
            question,
            dict(state.get("constraints", {})),
            candidate_events,
            matched_events,
        )
        base_answer = str(query_result.get("answer", ""))
        llm_answer = self._generate_chat_answer_with_llm(
            question=question,
            constraints=dict(state.get("constraints", {})),
            query_result=query_result,
            matched_events=matched_events,
            history=history,
            fallback_answer=base_answer,
        )
        used_llm = bool(llm_answer and llm_answer.strip() and llm_answer.strip() != base_answer.strip())
        references = [
            self._build_chat_reference(event)
            for event in list(query_result.get("reference_events", []))[:4]
        ]
        return {
            "query_result": query_result,
            "base_answer": llm_answer or base_answer,
            "used_llm": used_llm,
            "references": references,
        }

    def _chat_node_polish_answer(self, state: ChatState) -> dict[str, Any]:
        base_answer = str(state.get("base_answer", ""))
        intent = str(dict(state.get("constraints", {})).get("query_intent", "list"))
        if intent in {"count_events", "count_people", "existence"}:
            return {"answer": base_answer, "used_llm": bool(state.get("used_llm", False))}
        final_answer = self._polish_answer_with_llm(base_answer)
        used_llm = bool(state.get("used_llm", False) or final_answer != base_answer)
        return {"answer": final_answer, "used_llm": used_llm}

    def _rewrite_question_with_llm(self, question: str, history: list[dict[str, str]]) -> str:
        if not question.strip() or not history:
            return question

        rewritten = self._rewrite_question_with_history(question, history)
        if rewritten and rewritten != question:
            self.add_log("问答", f"已基于上下文补全查询：{rewritten}")
            return rewritten
        return question

    def _extract_query_constraints(self, question: str) -> dict[str, Any]:
        question = self._normalize_query_text(question)
        now = datetime.now()
        time_scope = self._resolve_date_scope(question, now=now)
        risk_level, risk_label = self._extract_risk_filter(question)
        action_keywords, action_label = self._extract_action_filter(question)
        clothing_keywords, clothing_label = self._extract_clothing_filter(question)
        query_intent = self._classify_query_intent(question)
        description_keywords = self._extract_description_keywords(question)
        person_related = bool(
            action_keywords
            or clothing_keywords
            or any(token in question for token in ("人", "人员", "黑衣", "白衣", "红衣", "蓝衣", "灰衣", "深色", "浅色", "黑色", "白色"))
            or query_intent == "count_people"
        )

        camera_id = None
        camera_label = ""
        camera_match = re.search(r"([0-9一二三四五六七八九十两]+)号摄像头", question)
        if camera_match:
            camera_number = self._parse_chinese_number_token(camera_match.group(1))
            if camera_number is not None:
                camera_id = self._resolve_camera_id(camera_number)
                camera_label = camera_match.group(0)

        period_map = {
            "凌晨": (0, 6),
            "早晨": (6, 12),
            "上午": (6, 12),
            "中午": (11, 14),
            "下午": (12, 18),
            "傍晚": (17, 20),
            "晚上": (18, 24),
            "夜间": (18, 24),
            "晚间": (18, 24),
        }
        period_range = None
        period_name = ""
        for token, time_range in period_map.items():
            if token in question:
                period_name = token
                period_range = time_range
                break

        cleaned_question = re.sub(r"\d{4}[/-]\d{1,2}[/-]\d{1,2}", " ", question)
        cleaned_question = re.sub(r"\d{1,2}月\d{1,2}[日号]", " ", cleaned_question)
        cleaned_question = re.sub(r"[一二三四五六七八九十两〇零]+月[一二三四五六七八九十两〇零]+[日号]", " ", cleaned_question)
        cleaned_question = re.sub(r"(今天|昨日|昨天|前天|明天|后天)", " ", cleaned_question)
        cleaned_question = re.sub(r"(上周|这周|本周|下周)(?:一共|总共|总计|累计|整周|整个星期|整个礼拜|全周|这一周|那一周|[一二三四五六日天])?", " ", cleaned_question)
        cleaned_question = re.sub(r"([0-9一二三四五六七八九十两]+)号摄像头", " ", cleaned_question)
        cleaned_question = re.sub(r"(凌晨|早晨|上午|中午|下午|傍晚|晚上|夜间|晚间)", " ", cleaned_question)
        cleaned_question = re.sub(r"(几起|多少起|多少条|多少次|多少人|几个人|发生了什么)", " ", cleaned_question)
        semantic_query = " ".join(cleaned_question.split()).strip() or question.strip()

        constraints: dict[str, Any] = {
            "date": time_scope.get("date"),
            "date_start": time_scope.get("date_start"),
            "date_end": time_scope.get("date_end"),
            "date_label": time_scope.get("date_label", "今天"),
            "days_back": time_scope.get("days_back"),
            "camera_id": camera_id,
            "camera_label": camera_label,
            "period_range": period_range,
            "period_name": period_name,
            "semantic_query": semantic_query,
            "query_intent": query_intent,
            "risk_level": risk_level,
            "risk_label": risk_label,
            "action_keywords": action_keywords,
            "action_label": action_label,
            "clothing_keywords": clothing_keywords,
            "clothing_label": clothing_label,
            "description_keywords": description_keywords,
            "person_related": person_related,
        }
        return constraints

    def _resolve_camera_id(self, camera_number: int) -> str | None:
        candidates = list(self.camera_lookup.keys())
        if 1 <= camera_number <= len(candidates):
            return candidates[camera_number - 1]
        return None

    @staticmethod
    def _is_high_risk_like_event(row: dict[str, Any]) -> bool:
        anomaly_type = str(row.get("anomaly_type", "")).strip().lower()
        if anomaly_type in {"fire", "fall", "fight", "intrusion", "smoke", "weapon"}:
            return True
        text = f"{row.get('description', '')} {row.get('reason', '')}"
        keywords = ("打火机", "点火", "明火", "烟雾", "起火", "跌倒", "滑倒", "斗殴", "闯入", "入侵")
        return any(keyword in text for keyword in keywords)

    def _load_candidate_events(self, constraints: dict[str, Any]) -> list[dict[str, Any]]:
        start_date = str(constraints.get("date_start") or constraints.get("date") or self._today())
        end_date = str(constraints.get("date_end") or constraints.get("date") or start_date)
        action_keywords = list(constraints.get("action_keywords", []))
        clothing_keywords = list(constraints.get("clothing_keywords", []))
        description_keywords = list(constraints.get("description_keywords", []))
        rows = self.store.search_events(
            start_date=start_date,
            end_date=end_date,
            camera_id=str(constraints.get("camera_id") or "") or None,
            risk_level=str(constraints.get("risk_level") or "") or None,
            period_range=constraints.get("period_range"),
            person_present=None,
            action_keywords=action_keywords,
            clothing_keywords=clothing_keywords,
            description_keywords=description_keywords,
            order_desc=False,
        )
        if not rows and str(constraints.get("risk_level", "")).strip().lower() == "high":
            relaxed_rows = self.store.search_events(
                start_date=start_date,
                end_date=end_date,
                camera_id=str(constraints.get("camera_id") or "") or None,
                risk_level=None,
                period_range=constraints.get("period_range"),
                person_present=None,
                action_keywords=action_keywords,
                clothing_keywords=clothing_keywords,
                description_keywords=description_keywords,
                order_desc=False,
            )
            rows = [row for row in relaxed_rows if self._is_high_risk_like_event(row)]
            if rows:
                self.add_log("问答", f"高风险检索启用语义兜底：匹配到 {len(rows)} 条高危候选。")
        events = [self._build_report_item_from_row(row) for row in rows]
        return events

    def _build_qdrant_filter(self, constraints: dict[str, Any]) -> dict[str, Any] | None:
        must: list[dict[str, Any]] = []
        if constraints.get("date"):
            must.append({"key": "event_date", "match": {"value": str(constraints["date"])}})
        if constraints.get("camera_id"):
            must.append({"key": "camera_id", "match": {"value": str(constraints["camera_id"])}})
        period_range = constraints.get("period_range")
        if period_range:
            start_hour, end_hour = period_range
            must.append({"key": "event_hour", "range": {"gte": int(start_hour), "lt": int(end_hour)}})
        return {"must": must} if must else None

    def _rank_events_with_vector_store(
        self,
        semantic_query: str,
        events: list[dict[str, Any]],
        constraints: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        if not self.vector_search_enabled or not semantic_query or not events:
            return []

        query_vector = self.embedding_client.embed_text(semantic_query)
        candidate_index = {int(event.get("event_id", 0)): dict(event) for event in events}
        search_limit = max(limit * 3, self.config.vector_store.search_limit)
        if constraints.get("days_back"):
            search_limit = max(search_limit, min(len(candidate_index), 80))
        hits = self.vector_store.search(
            query_vector=query_vector,
            limit=search_limit,
            query_filter=self._build_qdrant_filter(constraints),
        )

        ranked: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.get("payload") or {}
            event_id = int(payload.get("event_id", hit.get("id", 0)))
            if event_id not in candidate_index:
                continue
            item = dict(candidate_index[event_id])
            item["score"] = float(hit.get("score", 0.0))
            ranked.append(item)

        ranked.sort(
            key=lambda item: (float(item.get("score", 0.0)), str(item.get("timestamp", item.get("event_time", "")))),
            reverse=True,
        )
        return ranked[:limit]

    def _rank_events(
        self,
        semantic_query: str,
        events: list[dict[str, Any]],
        constraints: dict[str, Any] | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        if not events:
            return []

        constraints = constraints or {}
        sorted_by_time = sorted(
            events,
            key=lambda item: (str(item.get("timestamp", item.get("event_time", ""))), int(item.get("event_id", 0))),
            reverse=True,
        )
        if not semantic_query:
            ranked_without_query = []
            for index, event in enumerate(sorted_by_time):
                item = dict(event)
                item["score"] = max(0.0, 1.0 - index * 0.01)
                ranked_without_query.append(item)
            return ranked_without_query[:limit]

        if self.vector_search_enabled:
            try:
                ranked_by_vector = self._rank_events_with_vector_store(semantic_query, events, constraints, limit)
                if ranked_by_vector:
                    return ranked_by_vector
            except Exception as exc:
                self.add_log("向量库", f"Qdrant 检索失败，已回退到 TF-IDF：{exc}")

        documents = [
            " ".join(
                [
                    str(event.get("camera_name", "")),
                    str(event.get("camera_id", "")),
                    str(event.get("anomaly_type", "")),
                    str(event.get("description", "")),
                    str(event.get("reason", "")),
                    str(event.get("timestamp", event.get("event_time", ""))),
                ]
            )
            for event in events
        ]
        try:
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
            matrix = vectorizer.fit_transform([semantic_query, *documents])
            scores = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
        except ValueError:
            scores = [0.0 for _ in documents]

        ranked = []
        for event, score in zip(events, scores):
            item = dict(event)
            item["score"] = float(score)
            ranked.append(item)

        ranked.sort(
            key=lambda item: (float(item.get("score", 0.0)), str(item.get("timestamp", item.get("event_time", "")))),
            reverse=True,
        )
        return ranked[:limit]

    def _select_matched_events(
        self,
        ranked_events: list[dict[str, Any]],
        constraints: dict[str, Any],
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        if not ranked_events:
            return []

        semantic_query = str(constraints.get("semantic_query", "")).strip()
        if not semantic_query:
            return ranked_events[:limit]

        top_score = float(ranked_events[0].get("score", 0.0))
        if top_score < 0.08:
            return []

        threshold = max(0.06, top_score * 0.45)
        matched = [event for event in ranked_events if float(event.get("score", 0.0)) >= threshold]
        return matched[:limit]

    def _describe_query_scope(self, constraints: dict[str, Any]) -> str:
        scope_parts: list[str] = []
        if constraints.get("date_label"):
            scope_parts.append(str(constraints["date_label"]))
        if constraints.get("period_name"):
            scope_parts.append(str(constraints["period_name"]))
        if constraints.get("camera_label"):
            scope_parts.append(str(constraints["camera_label"]))
        return " ".join(scope_parts) if scope_parts else "默认范围"

    @staticmethod
    def _count_people_from_events(events: list[dict[str, Any]]) -> int:
        total = 0
        for event in events:
            if bool(event.get("person_present", False)):
                total += max(1, int(event.get("person_count", 0) or 0))
        return total

    def _format_event_evidence(self, event: dict[str, Any]) -> str:
        details: list[str] = []
        if bool(event.get("person_present", False)):
            details.append(f"人数估计 {max(1, int(event.get('person_count', 0) or 0))} 人")
        if str(event.get("action_type", "")).strip():
            details.append(f"动作 {event['action_type']}")
        if str(event.get("upper_clothing_color", "")).strip():
            details.append(f"上衣 {event['upper_clothing_color']}")
        detail_suffix = f"；{'，'.join(details)}" if details else ""
        return (
            f"{event['time_label']}，{event['camera_name']}："
            f"{event['description']}（风险等级：{event['risk_level']}{detail_suffix}）。"
        )

    def _build_query_result(
        self,
        question: str,
        constraints: dict[str, Any],
        candidate_events: list[dict[str, Any]],
        matched_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scope = self._describe_query_scope(constraints)
        intent = str(constraints.get("query_intent", "list"))
        has_structured_filters = self._has_structured_query_filters(constraints)
        if intent in {"count_events", "count_people"}:
            filtered_events = list(candidate_events)
        elif has_structured_filters:
            filtered_events = list(candidate_events)
        else:
            filtered_events = matched_events or candidate_events
        reference_events = filtered_events[:4] if filtered_events else candidate_events[:4]
        risk_label = str(constraints.get("risk_label", "") or "")
        action_label = str(constraints.get("action_label", "") or "")
        clothing_label = str(constraints.get("clothing_label", "") or "")

        result: dict[str, Any] = {
            "scope": scope,
            "intent": intent,
            "filtered_events": filtered_events,
            "reference_events": reference_events,
            "count_value": 0,
            "people_count": 0,
            "exists": bool(filtered_events),
            "query_summary": "",
            "answer": "",
        }

        if intent == "count_events":
            count_value = len(filtered_events)
            event_label = f"{risk_label}事件" if risk_label else "事件"
            lines = [f"查询范围：{scope}。", f"共统计到 {count_value} 起{event_label}。"]
            if filtered_events:
                for event in filtered_events[:3]:
                    lines.append(self._format_event_evidence(event))
                if len(filtered_events) > 3:
                    lines.append(f"其余 {len(filtered_events) - 3} 条记录可在下方关键帧中查看。")
            result["count_value"] = count_value
            result["query_summary"] = (
                f"查询类型：统计事件数量\n"
                f"统计范围：{scope}\n"
                f"统计对象：{event_label}\n"
                f"结果数量：{count_value}\n"
            )
            result["answer"] = "\n".join(lines)
            return result

        if intent == "count_people":
            people_count = self._count_people_from_events(filtered_events)
            action_text = action_label or "出现"
            lines = [
                f"查询范围：{scope}。",
                f"按事件窗口累计估计，共有 {people_count} 人次与“{action_text}”相关。",
            ]
            if filtered_events:
                lines.append(f"共命中 {len(filtered_events)} 条相关事件记录。")
                for event in filtered_events[:3]:
                    lines.append(self._format_event_evidence(event))
                if len(filtered_events) > 3:
                    lines.append(f"其余 {len(filtered_events) - 3} 条记录可在下方关键帧中查看。")
            else:
                lines.append("当前范围内没有检索到满足条件的人员事件。")
            result["people_count"] = people_count
            result["query_summary"] = (
                f"查询类型：统计人数/人次\n"
                f"统计范围：{scope}\n"
                f"动作条件：{action_text or '未指定'}\n"
                f"累计人数：{people_count}\n"
            )
            result["answer"] = "\n".join(lines)
            return result

        if intent == "existence":
            if filtered_events:
                target_text = clothing_label or action_label or "相关目标"
                lines = [f"查询范围：{scope}。", f"发现 {len(filtered_events)} 条与“{target_text}”相关的记录。"]
                for event in filtered_events[:3]:
                    lines.append(self._format_event_evidence(event))
                if len(filtered_events) > 3:
                    lines.append(f"其余 {len(filtered_events) - 3} 条相关记录已附在下方参考中。")
            else:
                lines = [f"查询范围：{scope}。", "未在监控记录中发现相关异常。"]
            result["exists"] = bool(filtered_events)
            result["query_summary"] = (
                f"查询类型：存在性检索\n"
                f"查询范围：{scope}\n"
                f"衣着条件：{clothing_label or '未指定'}\n"
                f"动作条件：{action_label or '未指定'}\n"
                f"命中记录：{len(filtered_events)}\n"
            )
            result["answer"] = "\n".join(lines)
            return result

        if not filtered_events:
            result["query_summary"] = f"查询类型：列表/总结\n查询范围：{scope}\n命中记录：0\n"
            result["answer"] = (
                f"在 {scope} 范围内未找到符合条件的记录。"
                "当前检索基于关键帧分析结果，如果要查询衣着颜色、携带物等细节，需要模型描述中已经包含这些信息。"
            )
            return result

        lines = [f"查询范围：{scope}。", f"为您找到 {len(filtered_events)} 条记录。"]
        for event in filtered_events[:3]:
            lines.append(self._format_event_evidence(event))
        if len(filtered_events) > 3:
            lines.append(f"其余 {len(filtered_events) - 3} 条相关记录已附在下方关键帧参考中。")
        result["query_summary"] = (
            f"查询类型：列表/总结\n"
            f"查询范围：{scope}\n"
            f"命中记录：{len(filtered_events)}\n"
        )
        result["answer"] = "\n".join(lines)
        return result

    def _build_local_answer(
        self,
        question: str,
        constraints: dict[str, Any],
        matched_events: list[dict[str, Any]],
    ) -> str:
        return self._build_query_result(question, constraints, matched_events, matched_events).get("answer", "")

    def _build_chat_answer_prompt(
        self,
        question: str,
        constraints: dict[str, Any],
        query_result: dict[str, Any],
        evidence_text: str,
        fallback_answer: str,
    ) -> str:
        intent = str(constraints.get("query_intent", "list"))
        scope = str(query_result.get("scope", self._describe_query_scope(constraints)))
        intent_labels = {
            "count_events": "统计事件数量",
            "count_people": "统计人数/人次",
            "existence": "存在性检索",
            "list": "列表汇总",
        }
        return (
            "你是一个专业的安防监控 AI 智能体助理。\n"
            "请严格基于下面提供的结构化查询结果和监控检索日志作答，禁止编造事实。\n"
            "如果检索结果为空，必须明确说“未在监控记录中发现相关异常”。\n"
            "回答规则：\n"
            "1. 统计类问题第一句必须直接给出准确数字，不要模糊表述。\n"
            "2. 存在性问题第一句必须先回答“有”或“没有”。\n"
            "3. 如果衣着颜色、人数或动作只能近似判断，必须使用“疑似”“估计”“近似”等保守说法。\n"
            "4. 只允许使用结构化结果里已经给出的数字，不要自行重新推断数量。\n"
            "5. 输出使用简洁、专业的安防汇报口吻，优先给结论，再补充时间、摄像头、风险和描述。\n\n"
            f"[查询类型]\n{intent_labels.get(intent, '列表汇总')}\n\n"
            f"[查询范围]\n{scope}\n\n"
            f"[结构化查询结果]\n{str(query_result.get('query_summary', '')).strip() or '无'}\n\n"
            f"[监控检索日志]\n{evidence_text}\n\n"
            f"[用户提问]\n{question}\n\n"
            f"[建议草稿]\n{fallback_answer}\n"
        )

    @staticmethod
    def _build_answer_polish_prompt(answer: str) -> str:
        return (
            "你是安防值班汇报助手。\n"
            "请在不改变事实、不改变数字、不增加新信息的前提下，"
            "把下面的回答润色成更自然、更专业的中文汇报。\n"
            "要求：\n"
            "1. 保留原有结论、时间、摄像头和数量。\n"
            "2. 不要新增事实，不要删除关键数字。\n"
            "3. 控制在 3 到 6 句话内。\n\n"
            f"[原始回答]\n{answer}\n"
        )

    def _generate_chat_answer_with_llm(
        self,
        question: str,
        constraints: dict[str, Any],
        query_result: dict[str, Any],
        matched_events: list[dict[str, Any]],
        history: list[dict[str, str]],
        fallback_answer: str,
    ) -> str:
        if not self.text_llm_client.enabled:
            self.add_log("问答", "本地文本模型未启用，已回退到本地检索回答。")
            return fallback_answer

        evidence_events = matched_events or list(query_result.get("reference_events", []))
        query_intent = str(constraints.get("query_intent", ""))
        if not evidence_events:
            self.add_log("问答", "未命中有效事件，直接返回确定性检索回答。")
            return fallback_answer
        if query_intent == "existence" and not bool(query_result.get("exists", False)):
            self.add_log("问答", "存在性查询未命中结果，跳过文本模型。")
            return fallback_answer
        if query_intent == "count_events" and int(query_result.get("count_value", 0) or 0) == 0:
            self.add_log("问答", "事件统计结果为 0，跳过文本模型。")
            return fallback_answer
        if query_intent == "count_people" and int(query_result.get("people_count", 0) or 0) == 0:
            self.add_log("问答", "人数统计结果为 0，跳过文本模型。")
            return fallback_answer

        if evidence_events:
            evidence_lines = []
            for event in evidence_events[:6]:
                evidence_lines.append(
                    f"- 时间：{event['time_label']}；摄像头：{event['camera_name']}；"
                    f"风险：{event['risk_level']}；类型：{event['anomaly_type']}；"
                    f"描述：{event['description']}"
                )
            evidence_text = "\n".join(evidence_lines)
        else:
            evidence_text = "未检索到符合条件的事件记录。"

        _ = history
        prompt = self._build_chat_answer_prompt(
            question=question,
            constraints=constraints,
            query_result=query_result,
            evidence_text=evidence_text,
            fallback_answer=fallback_answer,
        )
        response = self._run_text_llm(prompt, timeout=45, temperature=0.1)
        if response and response.strip():
            normalized = response.strip()
            expected_numeric = (
                int(query_result.get("people_count", 0) or 0)
                if query_intent == "count_people"
                else int(query_result.get("count_value", 0) or 0)
            )
            if query_intent in {"count_events", "count_people"} and str(expected_numeric) not in normalized:
                self.add_log("问答", "文本大模型未明确保留统计结果数字，已回退到精确检索回答。")
                return fallback_answer
            if query_intent == "existence":
                exists_value = bool(query_result.get("exists", False))
                if exists_value and not any(token in normalized for token in ("有", "发现", "存在", "找到")):
                    self.add_log("问答", "文本大模型未明确回答是否存在，已回退到精确检索回答。")
                    return fallback_answer
                if not exists_value and not any(token in normalized for token in ("没有", "未", "未发现")):
                    self.add_log("问答", "文本大模型未明确回答未命中结果，已回退到精确检索回答。")
                    return fallback_answer
            if matched_events and "未在监控记录中发现相关异常" in normalized and (
                "为您找到" in normalized or "摄像头" in normalized or "时间" in normalized or "记录" in normalized
            ):
                self.add_log("问答", "文本大模型返回结果存在自相矛盾，已回退到本地检索回答。")
                return fallback_answer
            if self._should_use_fallback_answer(normalized, fallback_answer, matched_events):
                self.add_log("问答", "文本大模型回复过于泛化，已回退到更具体的检索回答。")
                return fallback_answer
            self.add_log("问答", "自然语言问答已调用文本大模型生成回复。")
            return normalized
        self.add_log("问答", "文本大模型未返回有效回复，已回退到本地检索回答。")
        return fallback_answer

    def _polish_answer_with_llm(self, base_answer: str) -> str:
        if not base_answer.strip():
            return base_answer
        prompt = self._build_answer_polish_prompt(base_answer)
        response = self._run_text_llm(prompt, timeout=45)
        return response.strip() if response else base_answer

    def _build_chat_reference(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": int(event.get("event_id", 0)),
            "camera_id": str(event.get("camera_id", "")),
            "camera_name": str(event.get("camera_name", "")),
            "risk_level": str(event.get("risk_level", "Low")),
            "event_time": str(event.get("timestamp", event.get("event_time", ""))),
            "description": str(event.get("description", "")),
            "image_url": str(event.get("image_url", "")),
        }
