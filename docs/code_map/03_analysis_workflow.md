# 关键帧分析工作流

这一组文件负责把关键帧送给视觉模型，产出结构化事件。

## 工作流核心

- [monitoring_analysis.py](C:\Users\chens\Desktop\camera_project\monitoring_analysis.py)
  这是关键帧分析的 LangGraph 工作流实现。

主要节点：

- `analyze_frames`
  调视觉模型逐帧分析
- `persist_events`
  把结果写入数据库
- `decide_alerts`
  判断哪些事件需要飞书告警
- `send_alerts`
  发送告警
- `finalize`
  生成最终报告项

## 输入数据结构

- [monitoring_types.py](C:\Users\chens\Desktop\camera_project\monitoring_types.py)
  这里定义了：
  - `FrameJob`
  - `AnalysisState`
  - `ChatState`
  - `SummaryState`

其中 `FrameJob` 是关键帧分析流里最重要的中间结构。

## 模型调用

- [llm_client.py](C:\Users\chens\Desktop\camera_project\llm_client.py)
  图像模型客户端。
  当前已经支持：
  - 老式表单上传接口
  - OpenAI 兼容接口

你现在项目实际走的是：

- `provider = openai_compatible`
- `Qwen2.5-VL`

## 分析输出

关键帧分析产出的不是纯文本，而是结构化结果，最后会补全到：

- 风险等级
- 异常类型
- 描述
- 原因
- 人数
- 动作类型
- 上衣颜色
- 下衣颜色
- 置信度

这些字段最终对应 [schemas.py](C:\Users\chens\Desktop\camera_project\schemas.py) 里的 `FrameAnalysis`。

## 你最常改的地方

如果你要改“关键帧分析质量”，最常改的是：

- [prompt.txt](C:\Users\chens\Desktop\camera_project\prompt.txt)
- [monitoring_prompts.py](C:\Users\chens\Desktop\camera_project\monitoring_prompts.py)
- [monitoring_analysis.py](C:\Users\chens\Desktop\camera_project\monitoring_analysis.py)

尤其是：

- 事件合并规则
- 人数判断
- 服装颜色补全
- 模型失败后的兜底逻辑
