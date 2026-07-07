# 根目录文件管理索引

这组小文件用于把当前项目里较杂的代码文件按职责分桶，方便你快速定位。

建议阅读顺序：

1. `01_web_entry.md`：项目入口、配置文件、启动脚本
2. `02_capture_and_analysis.md`：摄像头录制、远程片段同步、关键帧抽取、关键帧分析
3. `03_query_summary_agent.md`：自然语言问答、日志总结、LangGraph 智能体工作流
4. `04_models_storage_alerts.md`：图像模型、文本模型、Embedding、SQLite、Qdrant、飞书告警
5. `05_frontend_and_server_gateway.md`：前端页面与服务器录制端
6. `06_test_and_temp_files.md`：测试脚本、临时目录、建议清理规则

当前主线代码入口优先看这几个：

- `app.py`
- `monitoring_service.py`
- `monitoring_analysis.py`
- `monitoring_query.py`
- `monitoring_summary.py`
- `event_store.py`

