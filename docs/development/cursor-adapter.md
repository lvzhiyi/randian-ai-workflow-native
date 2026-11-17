# Cursor 适配（0.18.0）

本仓库仅为 `workflow-core` 提供 Cursor 原生插件清单。根 `.cursor-plugin/marketplace.json` 只列该插件，其他维度插件、组合包和外部依赖不承诺可在 Cursor 安装。本版本提供远程仓库发布内容；安装与启用需通过 Cursor 支持的插件入口完成，不直接修改用户全局配置。

## 安装与检查

需要支持插件和 hooks 的 Cursor 版本、Python 3、Git。通过 Cursor 插件安装入口从本仓库添加 marketplace，再选择 `workflow-core`；本地开发可将 `plugins/workflow-core` 作为插件目录加载。具体入口以当前 Cursor 版本为准，本适配未验证真实客户端安装，不提供臆测的 CLI 安装命令。重启会话后检查技能可发现、sessionStart 返回宿主环境以及 preToolUse 是否执行；未实际执行的钩子不能算覆盖。

清单使用 `hooks: "./hooks/cursor.json"`、`skills: "./skills/"`。Cursor hooks 为扁平事件数组，每项运行 `python3 "${CURSOR_PLUGIN_ROOT}/scripts/cursor_gate.py"`，`failClosed: true`、`timeout: 30`，不是 Claude 的嵌套 hooks 格式。

官方协议来源：
- https://cursor.com/docs/reference/plugins.md
- https://cursor.com/docs/hooks.md

## 任务与 CLI

`CURSOR_PLUGIN_ROOT` 是插件根，不是项目根。适配器使用 `CURSOR_PROJECT_DIR` 或 `workspace_roots`，Shell 的 `tool_input.working_directory` 保留实际执行目录，并从该目录查找最近的 `ai-workflow.yaml`，不折叠为工作区根；`CURSOR_PROJECT_DIR` 只是默认目录，合法子目录可覆盖，兄弟目录等真正冲突仍拒绝；不采用可能指向插件的 cwd。多根缺少明确选择、目录不一致或格式无效时 preToolUse 拒绝。只有明确找到 `ai-workflow.yaml` 才启用门禁；未接入项目旁路允许，便于初始化。已接入项目的配置、任务或输入错误不降级为旁路。

`conversation_id` 原样映射引擎 `session_id`，执行者通过 CLI `bind-executor --session <conversation_id>` 绑定。每轮会话唯一任务 lookup 沿用共享逻辑，歧义不猜测。读取基线仍由 CLI `read-baseline` 输出完整正文并登记；Cursor Read 输出没有已验证的完整读取回执契约，不会自动登记。

在 Cursor 中每次运行引擎 CLI 前明确设置 `WORKFLOW_HOST=cursor`，不要假定 hooks 子进程能修改之后 Shell 的父环境。使用插件脚本绝对路径和显式 `--root`，先查询 `--help`：

```bash
WORKFLOW_HOST=cursor python3 "/绝对路径/plugins/workflow-core/scripts/workflow_engine_cli.py" --root "/项目根" status --task "T1"
```

共享门禁只为固定引擎脚本允许这个精确环境前缀，不允许任意环境包装或 shell 拼接。引擎默认数据库仍沿用共享 `$CODEX_HOME/workflow-engine`（默认 `~/.codex/workflow-engine`），并未实现宿主隔离；如用 `WORKFLOW_ENGINE_HOME` 或 `--db`，必须确保门禁、CLI 和看板读取同一库，不能只对某次 CLI 使用另一个库后期待自动关联。

Agent 用 `request-confirmation` 登记当前任务版本和 `conversation_id`，随后展示档位。用户在聊天中单独回复 `选轻量档`、`选标准档` 或 `选完整档`，由 `beforeSubmitPrompt` 登记。完整档方案就绪后，另登记 `--kind approval`，让用户回复 `批准方案`。Agent 用 `status` 核实登记结果。`AskQuestion` 的普通工具结果继续只用于问答，因为 Cursor 尚未文档化可用于定档的选择回执。

## 支持边界

- preToolUse 显式输出 allow/deny，绝不输出 ask；Git 调查的 updated_input 保留原字段并禁用外部 diff/textconv。
- Read/Glob/Grep/rg 与 AskQuestion 允许调查；未知 MCP、Shell 写命令、Task 仍须通过共享引擎就绪检查，explore 名称不构成只读证明。Write/Delete/Edit 只接受非空字符串目标 `file_path`、`path`、`target_file`，未知 schema 拒绝；目标范围、会话和基线由共享门禁验证。
- Task 仅在父任务已绑定且当前轮次授权就绪时允许委派；子 Agent 不因此取得独立授权，必须使用其实际会话重新绑定、读取基线。subagentStart 仅返回合法的 permission/user_message，提醒不等于全部子工具路径已覆盖；Cursor 未回调的写入路径不在保证内。插件不是系统沙箱。
- sessionStart 返回 env 与 additional_context；postToolUse 返回适用的 additional_context。
- 看板 CLI 使用 `WORKFLOW_HOST=cursor` 将服务运行信息存放在 `~/.cursor/workflow-dashboard`，任务数据来自共享引擎数据库。

## 验证口径

`test_cursor_gate.py` 使用官方输入形状模拟进程回调，并连接真实 Engine/CLI 验证绑定、read-baseline、start 和跨会话拒绝；还验证清单、格式故障拒绝、字符串工具结果、以及多个项目根。`python3 scripts/check.py` 覆盖根 Cursor marketplace JSON。上述是协议模拟与本机引擎集成，不是实际 Cursor E2E；真实安装、工具 schema、子 Agent 传播和用户终端交互仍需人工验收。
