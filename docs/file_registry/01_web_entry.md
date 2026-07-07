# 入口、配置、启动脚本

## 入口文件

- `app.py`：Flask Web 服务入口，负责前端页面、接口路由、启动 `MonitoringOrchestrator`
- `main.py`：命令行方式运行一次任务或生成一次日报总结

## 配置文件

- `camera_config.json`：默认配置
- `camera_config.local.json`：研究院内网直连摄像头版本
- `camera_config.remote.json`：远程录制、本地分析版本
- `schemas.py`：所有配置和数据结构的 Pydantic 定义
- `prompt.txt`：关键帧分析提示词

## 启动脚本

- `run_local.ps1`：本地直连版启动
- `run_remote.ps1`：远程录制版启动

## 建议后续归档目录

如果你后面想进一步整理根目录，可以考虑把这些文件收进：

- `configs/`
- `scripts/`
- `app_entry/`

