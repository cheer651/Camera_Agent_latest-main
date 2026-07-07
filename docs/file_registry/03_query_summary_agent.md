# 自然语言问答、RAG、日报总结

## 自然语言监控对话

- `monitoring_query.py`：问句改写、时间/摄像头/风险/人物条件解析、候选事件检索、排序、答案生成
- `ollama_client.py`：调用本地 Qwen2.5 文本模型，用于问答结果润色和总结生成

## 日报总结

- `monitoring_summary.py`：按早晨/下午/晚上/凌晨四个时段组织每日总结，再生成全天综合总结

## 提示词管理

- `monitoring_prompts.py`：集中管理自然语言问答、答案润色、日报总结等提示词模板

## 总编排入口

- `monitoring_service.py`：对外提供 `answer_question()`、`stream_answer_question()`、`generate_daily_summary()` 等方法

## 建议后续归档目录

- `agent/`
- `query/`
- `summary/`
- `prompts/`

