---
name: trace
description: 开关工作流执行轨迹：在本地网页实时查看MCP、改动、验证命令和结果。仅在用户显式调用本技能时使用。
disable-model-invocation: true
argument-hint: on | off | status
---

# 执行轨迹

下文的 `${CLAUDE_PLUGIN_ROOT}` 指当前技能所在的插件根目录。如果它没有被替换成绝对路径（如在 Codex 中），从已加载的 `SKILL.md` 路径向上三级定位，执行命令时直接代入绝对路径。在 Codex 中运行下方命令时，在命令前加 `WORKFLOW_HOST=codex`，以使用 Codex 的本机数据目录。

本技能只负责开关，默认关闭。从用户请求取 `on`、`off` 或 `status`，为空按 `status`。

运行下面的命令，把输出里的结果和页面地址告诉用户，不做其他事：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/trace_server.py" <参数>
```

- `on`：开启采集并启动只监听本机的页面。开启后记录当前客户端上已启用本插件钩子的会话。
- `off`：停止采集并关闭页面；已有日志保留，7 天后在下次 `on` 时清理。
- `status`：查看当前状态。

Codex 的 `on` 和 `off` 需要写入本机数据目录并访问回环地址。若当前沙盒限制这些操作，在普通本地终端执行同一条命令，保留 `WORKFLOW_HOST=codex`。

Codex 日志默认位于 `~/.codex/workflow-trace/`（可随 `CODEX_HOME` 调整），Claude Code 日志位于 `~/.claude/workflow-trace/`。日志只存本机。写入前会按常见格式遮盖令牌和密码，但不保证覆盖所有敏感内容。
