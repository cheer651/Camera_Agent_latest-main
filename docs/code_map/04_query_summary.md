# 问答与日志总结

这一组文件负责“自然语言监控对话”和“全天日志 AI 总结”。

## 自然语言对话

- [monitoring_query.py](C:\Users\chens\Desktop\camera_project\monitoring_query.py)
  自然语言问答工作流。

主要步骤：

- 重写问题
- 解析时间、摄像头、风险等级、动作、衣着
- 加载候选事件
- 排序与筛选
- 生成基础答案
- 用本地 Qwen2.5 润色

你问的这类问题都走这里：

- “上周五发生了几起高危事件”
- “3 月 26 日发生了什么”
- “上周二有没有黑衣服的人”

## 全天总结

- [monitoring_summary.py](C:\Users\chens\Desktop\camera_project\monitoring_summary.py)
  总结工作流。

主要步骤：

- 加载某天事件
- 按时间段拆分
  - 凌晨
  - 早晨
  - 下午
  - 晚上
- 生成分段总结
- 生成全天总结
- 保存并可推送飞书

## 提示词

- [monitoring_prompts.py](C:\Users\chens\Desktop\camera_project\monitoring_prompts.py)
  这里放了：
  - 对话提示词
  - 回答润色提示词
  - 时间段总结提示词
  - 全天总结提示词

## Web 接口入口

- [app.py](C:\Users\chens\Desktop\camera_project\app.py)
  对应接口：
  - `/api/chat`
  - `/api/chat/stream`
  - `/api/summaries`
  - `/api/reports/daily`

## 文本模型

- [ollama_client.py](C:\Users\chens\Desktop\camera_project\ollama_client.py)
  本地文本模型客户端。

它负责：

- 自然语言回答生成
- 日报与总结润色

它不负责看图片。
