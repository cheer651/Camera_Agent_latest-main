# 前端页面与服务器录制端

## 前端页面

- `templates/index.html`：主页面结构，四个 Tag 页签都在这里
- `static/js/script.js`：前端接口请求、聊天流式输出、会话记录、关键帧渲染、日报渲染、页面交互
- `static/css/style.css`：页面样式、聊天气泡、卡片布局、动画效果

## 服务器录制端

- `server_capture_gateway/server_recorder.py`：服务器侧持续录制两路 RTSP，按片段写 mp4 和 manifest
- `server_capture_gateway/recorder_core.py`：单路摄像头片段录制核心逻辑
- `server_capture_gateway/server_config.example.json`：服务器端录制配置模板
- `server_capture_gateway/run_recorder.sh`：服务器端启动脚本
- `server_capture_gateway/README_server.md`：服务器录制端部署说明

## 重要限制

当前远程录制版网页不提供真正实时视频流预览，主要展示的是已拉回本地并分析后的结果。

## 建议后续归档目录

- `web/`
- `server_gateway/`

