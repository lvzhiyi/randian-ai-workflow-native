# SpecLock (workflow-core 0.23.0) — 按需复杂 Bug 根因定位技能（`debug`）

- **新增按需 `debug` 技能**：新增 `skills/debug/SKILL.md`（`/workflow-core:debug` / `$workflow-core:debug`），针对多可能原因、横跨调用层/缓存/异步链路以及难稳定复现的故障提供最小根因排查协议（锁定预期与复现事实 → 假设矩阵与判据 → 跨层/缓存/异步边界二分采证 → 单变量验证与止损标准），日常非 Bug 流程零额外开销。
- **门禁与辅助技能衔接**：在 `tiering`、`implement` 与 `verify`（「原因待定位」「尝试无进展」）中补充按需调用 `debug` 的指引，继续遵守 `workflow` / `tiering` 门禁并兼容叠加 Superpowers `systematic-debugging`。
- **双语文档同步**：在 `README.md` 与 `README.zh-CN.md` 的日常技能速查表中补充 `debug` 入口。
