---
name: trace
description: 开关工作流执行轨迹：在本地网页实时查看正在调用的 Skill、MCP、验证命令和结果。仅在用户运行 /workflow-core:trace 时使用。
disable-model-invocation: true
argument-hint: on | off | status
---

# 执行轨迹

本技能只负责开关，默认关闭。参数是 `$ARGUMENTS`（`on`、`off`、`status`，为空按 `status`）。

运行下面的命令，把输出里的结果和页面地址告诉用户，不做其他事：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/trace_server.py" <参数>
```

- `on`：开启采集并启动只监听本机的页面。开启后所有项目的 Claude Code 会话都会记录，刚升级插件时需要重开会话才会加载钩子。
- `off`：停止采集并关闭页面；已有日志保留，7 天后在下次 `on` 时清理。
- `status`：查看当前状态。

日志在 `~/.claude/workflow-trace/`，只存本机、不进 git。写入前会按常见格式遮盖令牌和密码，但不保证覆盖所有敏感内容。
