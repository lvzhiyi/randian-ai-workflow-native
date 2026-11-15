---
name: trace
description: 旧执行轨迹入口迁移提示。用户调用旧 trace 技能时说明 Trace 已整合至任务级 dashboard，不再推荐或执行独立 trace on。
disable-model-invocation: true
---

# 执行轨迹入口迁移

本技能仅保留迁移提示，不运行旧 `trace_server.py`，不再提供或推荐独立 `trace on`。

请改用 `workflow-core:dashboard`（Codex 用 `$workflow-core:dashboard`，Claude Code 用 `/workflow-core:dashboard`），按其实际 `on | off | status` 参数查询或开启任务级只读观测。没有明确开启请求时只说明迁移，不代为启动服务。

Trace 作为任务观测详情，关联项目、任务、会话和轮次；未归属事件不得改变任务状态。旧日志只作历史线索，不自动升级为 v2 有效证据。集成或原生回调缺失时如实说明限制，不编造采集状态、活动、URL 或门禁能力。
