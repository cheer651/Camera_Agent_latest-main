# 前端与服务器录制端

这一组文件负责“网页长什么样”和“服务器端怎么持续录视频”。

## 前端页面

- [templates/index.html](C:\Users\chens\Desktop\camera_project\templates\index.html)
  页面结构模板。

- [static/js/script.js](C:\Users\chens\Desktop\camera_project\static\js\script.js)
  前端行为逻辑。
  负责：
  - 标签页切换
  - 实时画面请求
  - 关键帧日期筛选
  - 对话会话管理
  - 聊天流式输出
  - 日报刷新

- [static/css/style.css](C:\Users\chens\Desktop\camera_project\static\css\style.css)
  页面样式。

## 服务器录制端

服务器端代码都在：

- [server_capture_gateway](C:\Users\chens\Desktop\camera_project\server_capture_gateway)

具体文件：

- [server_capture_gateway/server_recorder.py](C:\Users\chens\Desktop\camera_project\server_capture_gateway\server_recorder.py)
  服务器录制入口。

- [server_capture_gateway/recorder_core.py](C:\Users\chens\Desktop\camera_project\server_capture_gateway\recorder_core.py)
  录制核心逻辑。

- [server_capture_gateway/server_config.example.json](C:\Users\chens\Desktop\camera_project\server_capture_gateway\server_config.example.json)
  服务器录制配置模板。

- [server_capture_gateway/run_recorder.sh](C:\Users\chens\Desktop\camera_project\server_capture_gateway\run_recorder.sh)
  Linux 服务器启动脚本。

- [server_capture_gateway/README_server.md](C:\Users\chens\Desktop\camera_project\server_capture_gateway\README_server.md)
  服务器端单独说明。

## 服务器录制端的职责

这部分只负责：

- 连接研究院内网摄像头
- 按固定时长录制 mp4
- 写 `clips.jsonl`
- 清理过期原始视频

它不负责：

- 关键帧分析
- 自然语言问答
- SQLite/Qdrant
- 前端展示

## 当前前端与远程模式的关系

当前项目里：

- 本地直连模式：支持网页实时画面
- 远程录制模式：当前不支持真正的实时视频流，只看分析结果

如果后面要补远程预览，优先会改：

- [server_capture_gateway](C:\Users\chens\Desktop\camera_project\server_capture_gateway)
- [camera_recorder.py](C:\Users\chens\Desktop\camera_project\camera_recorder.py)
- [app.py](C:\Users\chens\Desktop\camera_project\app.py)
