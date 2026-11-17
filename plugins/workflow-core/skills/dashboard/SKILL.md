---
name: dashboard
description: 单项目任务级只读看板。显式调用时开关或查询服务，查看轮次、尝试与证据，不写流程状态。
disable-model-invocation: true
argument-hint: on | off | status [--root 项目根] [--task ID]
---

# 任务级只读看板

`${CLAUDE_PLUGIN_ROOT}` 指插件根；未替换时从 `SKILL.md` 向上三级定位，执行代入绝对路径。按当前宿主前置 `WORKFLOW_HOST=cursor` / `WORKFLOW_HOST=codex` / `WORKFLOW_HOST=claude`。服务管理无需绑定实施任务或确认档位，用户未指定任务时不带 `--task`。

## 执行

用户明确调用才使用；取 `on | off | status`，未给操作默认 `status`，不得自行开启。项目根取用户指定或调用前 cwd，不把插件根当项目根；用户给任务 ID 才带 `--task`，不猜测。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard_server.py" status --root "项目根"
```

需要时将 `status` 换成用户请求的 `on` / `off`，附实际支持的 `--task "ID"`。门禁只允许固定脚本的明确 `on` / `off` / `status` 及不重复的 `--root` / `--task` 键值；不通过门禁调用无 action、`serve` 或额外参数。只转述命令返回的服务状态与本机 URL，不自动打开浏览器。脚本缺失、端口/权限/沙盒失败明确报告，不自动安装依赖或重配权限；需要用户本机执行时提供同一命令。

## 展示与边界

以任务为单位展示档位、主状态、阶段说明、局部流程、todo 进度、任务内失败/阻塞/待确认、有效证据与下一步；不展示全局八步或独立阻塞区。详情读取当前轮次的批准版本、基线读取、验证清单、两轴评审与轮次/尝试历史。文档勾选不替代引擎证据，Agent 评审通过不替代人工验收/交付。

本技能仅开关本机服务和只读查询。定档及方案批准在 Agent 窗口处理，见 `workflow` 的「在 Agent 窗口定档」。看板按实际证据展示结果，并明确标注缺失数据。
