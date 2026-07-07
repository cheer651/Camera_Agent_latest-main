# 模型、存储与告警

这一组文件负责“结果存哪里、向量怎么检索、告警怎么发”。

## 结构化数据库

- [event_store.py](C:\Users\chens\Desktop\camera_project\event_store.py)
  SQLite 存储层。

主要表：

- `tasks`
- `camera_runs`
- `events`
- `summaries`

这个文件是全项目最重要的数据落库位置。

## Embedding 服务

- [api_server.py](C:\Users\chens\Desktop\camera_project\api_server.py)
  本地 embedding HTTP 服务。

负责：

- 加载 Qwen3-Embedding 模型
- 暴露 `/embed`
- 提供 `/health`

- [embedding_client.py](C:\Users\chens\Desktop\camera_project\embedding_client.py)
  对应的客户端。

## 向量库

- [vector_store.py](C:\Users\chens\Desktop\camera_project\vector_store.py)
  Qdrant 客户端。

负责：

- 建 collection
- 建 payload index
- upsert 向量
- 语义搜索

## 飞书

- [feishu_agent.py](C:\Users\chens\Desktop\camera_project\feishu_agent.py)
  飞书告警与日报推送。

负责：

- 发送高危告警
- 发送每日总结

## 图像模型与文本模型客户端

- [llm_client.py](C:\Users\chens\Desktop\camera_project\llm_client.py)
  图像模型客户端，当前主要服务关键帧分析。

- [ollama_client.py](C:\Users\chens\Desktop\camera_project\ollama_client.py)
  文本模型客户端，当前主要服务问答和总结。

## 这组文件的关系

流程上通常是：

1. `llm_client.py` 产出结构化分析结果
2. `event_store.py` 写入 SQLite
3. `embedding_client.py` 生成向量
4. `vector_store.py` 写入 Qdrant
5. `feishu_agent.py` 在需要时发送告警
