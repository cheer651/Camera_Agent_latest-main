from __future__ import annotations

from typing import Any, TypedDict


class FrameJob(TypedDict):
    task_id: str
    camera_id: str
    camera_name: str
    clip_path: str
    clip_started_at: str
    frame_path: str
    frame_second: float
    event_group_id: str
    event_frame_count: int
    representative_count: int
    event_start_second: float
    event_end_second: float
    event_duration_seconds: float
    representative_rank: int
    is_primary: int
    person_count_hint: int
    person_score_hint: float
    low_pose_hint: int
    foreground_area_ratio_hint: float
    analysis_order: int


class AnalysisState(TypedDict, total=False):
    task_id: str
    frame_jobs: list[FrameJob]
    analyses: list[dict[str, Any]]
    report_items: list[dict[str, Any]]
    alerts: list[dict[str, Any]]


class SummaryState(TypedDict, total=False):
    summary_date: str
    send_to_feishu: bool
    events: list[dict[str, Any]]
    period_buckets: list[dict[str, Any]]
    periods: list[dict[str, Any]]
    overall_summary: str
    title: str
    body: str
    sent_to_feishu: bool


class ChatState(TypedDict, total=False):
    question: str
    standalone_question: str
    history: list[dict[str, str]]
    constraints: dict[str, Any]
    candidate_events: list[dict[str, Any]]
    ranked_events: list[dict[str, Any]]
    matched_events: list[dict[str, Any]]
    query_result: dict[str, Any]
    base_answer: str
    used_llm: bool
    answer: str
    references: list[dict[str, Any]]
