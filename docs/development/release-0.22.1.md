# SpecLock (workflow-core 0.22.1) — 修复未接入 `.git` 仓库的误拦截问题

- **修复未接入项目误触门禁**：`host_gate.project_root` 在遇到 `.git` 边界且不存在 `ai-workflow.yaml` 时，仅在当前会话存在活跃 `workflow_planning_cli` 规划登记时纳入本插件门禁；普通未接入 `.git` 仓库（含嵌套在已接入父目录下的独立 `.git` 子仓库）直接旁路放行。
- **全宿主门禁入口对齐**：`workflow_gate.handle` 与 `cursor_gate.handle` 统一按 `project_root(cwd, session_id)` 提前旁路未接入项目，不再注入 `ENGINE_TASK_UNBOUND`、拦截非任务工具写入或改写只读 Shell 输入。
- **回归测试补强**：在 `test_workflow_gate.py`、`test_cursor_gate.py`、`test_planning_gate.py` 补充无 `ai-workflow.yaml` 的 `.git` 仓库旁路与 `init` 规划自举期门禁边界回归测试。
