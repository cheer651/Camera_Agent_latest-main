# 采集与关键帧提取

这一组文件负责“视频从哪里来”和“如何从视频里提取候选关键帧”。

## 本地直连采集

- [camera_recorder.py](C:\Users\chens\Desktop\camera_project\camera_recorder.py)
  负责两件事：
  - `CameraService`
    用于网页实时预览，持续读取 RTSP 帧
  - `record_clip(...)`
    用 OpenCV 把一段 RTSP 视频录成 mp4

本地直连模式下，`monitoring_service.py` 会直接调用这里。

## 远程片段拉取

- [remote_capture_client.py](C:\Users\chens\Desktop\camera_project\remote_capture_client.py)
  远程模式专用。
  负责：
  - 通过 SSH 读取服务器的 `clips.jsonl`
  - 通过 SCP 下载新片段
  - 记录哪些片段已经处理过

远程模式下，不再本地直连 RTSP，而是先拿服务器录好的 mp4。

## 关键帧提取

- [smart_extractor.py](C:\Users\chens\Desktop\camera_project\smart_extractor.py)
  核心提取器。
  负责：
  - 从视频片段里抽帧
  - 运动检测
  - 滑动窗口
  - 合并相邻相似帧
  - 选代表帧

这部分是“先压缩视频信息量，再交给视觉模型”的关键。

## 主流程里对应的位置

- [monitoring_service.py](C:\Users\chens\Desktop\camera_project\monitoring_service.py)
  相关方法主要有：
  - `_prepare_frame_jobs_for_cameras`
  - `_prepare_frame_jobs`
  - `_extract_frame_jobs_from_clip`

含义：

- 本地版：先录制，再抽帧
- 远程版：先拉片，再抽帧

## 你最常改的参数

这些参数主要在配置文件的 `storage` 段里：

- `clip_duration_seconds`
- `frame_sample_rate`
- `similarity_threshold`
- `min_frame_gap_seconds`
- `motion_score_threshold`
- `event_merge_time_gap_seconds`
- `event_merge_similarity_threshold`
- `max_representative_frames`

如果你觉得“关键帧太多、太重复、没有人也被提出来”，优先看这里和 [smart_extractor.py](C:\Users\chens\Desktop\camera_project\smart_extractor.py)。
