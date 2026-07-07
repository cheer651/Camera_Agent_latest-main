# 代码导航

这组文档按职责拆开介绍项目代码，不再把所有文件说明塞进一个 README。

建议阅读顺序：

1. [01_entry_config.md](C:\Users\chens\Desktop\camera_project\docs\code_map\01_entry_config.md)
2. [02_capture_extract.md](C:\Users\chens\Desktop\camera_project\docs\code_map\02_capture_extract.md)
3. [03_analysis_workflow.md](C:\Users\chens\Desktop\camera_project\docs\code_map\03_analysis_workflow.md)
4. [04_query_summary.md](C:\Users\chens\Desktop\camera_project\docs\code_map\04_query_summary.md)
5. [05_models_storage_alerts.md](C:\Users\chens\Desktop\camera_project\docs\code_map\05_models_storage_alerts.md)
6. [06_frontend_server_gateway.md](C:\Users\chens\Desktop\camera_project\docs\code_map\06_frontend_server_gateway.md)

这些文档覆盖的都是主代码。

下面这些不是核心业务代码：

- `test.jpg`
- `test_alert.py`
- `tmpeu58u2nx/`
- `_tmp_*`
- `tmp_*`
- `__pycache__/`

如果你只想快速知道“启动后会经过哪些文件”，优先看：

- [app.py](C:\Users\chens\Desktop\camera_project\app.py)
- [monitoring_service.py](C:\Users\chens\Desktop\camera_project\monitoring_service.py)
- [monitoring_analysis.py](C:\Users\chens\Desktop\camera_project\monitoring_analysis.py)
- [event_store.py](C:\Users\chens\Desktop\camera_project\event_store.py)
