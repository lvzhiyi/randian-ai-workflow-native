---
name: review
description: 所有档位的 Agent Spec + Standards 双轴评审。验证通过后核对需求忠实度和项目规范，记录版本绑定报告；只评审不改代码，评审通过不等于人工验收或交付。
---

# Agent 双轴评审

三档均需两轴：**Spec** 对照已确认目标、范围、验收与来源；**Standards** 对照适用项目规范、术语、技术栈清单及 [prompts.md](prompts.md) 的坏味道基线。轻量可简报但不跳轴；文档任务同样检查需求与规范。本技能只报告不改代码，原范围修复由实施阶段继续，不为每个问题重复审批。

## 执行步骤

1. 查询当前任务/轮次、批准范围和验证证据。规定检查必须全部通过且未失效；缺项、失败或执行异常先回 `verify`，不能靠评审覆盖。
2. 固定评审 diff：用户指定范围优先；否则使用 `review.base_branch` 的 merge-base 加工作区改动。确认对比点存在，记录 HEAD、工作区快照与本任务文件范围，排除无关并行修改。未跟踪且属本任务的文件也纳入。对比点无效先报告，不猜测。纯调查没有改动时核对交付物与验收，而非编造代码 diff。
3. Spec 来源优先用户指令/任务卡/Issue、关联提案或产品规格、交接记录；完整档核对提案、技术设计与引擎内的已批准方案，同时对照关联任务卡的验收。来源冲突明确报告。轻量档使用已确认的用户预期。目标或验收不明先回任务就绪检查。
4. Standards 读取项目入口、配置适用基线、工程规范、术语表、维度插件清单及文档最小化规则。只报有依据的问题，不重复工具已经验证的格式项；关注性能、可维护性与资源边界。
5. 有授权且工具支持时两轴可用独立干净上下文评审；无子 Agent 能力或未授权委派时在当前上下文分开检查，注明“两轴未隔离”，不因此伪造独立评审。复核问题引用与位置。
6. 两轴各自输出 pass/fail 和 findings。每项有稳定 ID、出处、位置、严重度与修复要求；阻塞/应修均为必修，未解决不得通过；建议独列。重试同轴同 ID 显式标 `resolved=true`，不能删报告逃避未解决项。
7. 使用实际 CLI `review --file` 提交结构化报告，必含 `round_id`、`control_digest`、验证 `snapshot`、`executor` 与 `axes.spec/standards`。参数与通用入口见 `workflow`，没有 mark-pass 命令。报告绑定当前轮次及输入；变化后受影响验证/评审失效，修复后先复验再重审。

报告示例字段（替换占位值，不把模板当证据）：

```json
{"round_id":"当前轮次","control_digest":"控制摘要","snapshot":"验证快照","executor":"实际执行者","axes":{"spec":{"conclusion":"pass","findings":[]},"standards":{"conclusion":"pass","findings":[]}}}
```

提交评审报告后，无论成功或失败，都按 `workflow` 调用只读 `progress --task` 并同步宿主清单与真实阶段。review_failed 显示暂停/待修复，不把实施项虚标运行中；原范围 repair 后重读当前轮次新增 todo，成功 finish-step 后再同步完成。评审是独立阶段，不因实施清单全 completed 提前宣称通过。工具不可用则给简短聊天清单，不从 UI 回写引擎。

原生清单遵守 `workflow` 的“安全同步与聊天降级”：按真实 schema 核实数量、必填参数和已有列表可见性；单项、空清单、不能安全清理旧项或工具拒绝时使用简短聊天清单，不凑假 todo、不覆盖未知列表、不声称已原生同步。CLI 只是投影，由 Agent 显式调用宿主工具，不提供自动 UI bridge。

## 结论与交接

两轴分开报告来源、结论、必修/建议、证据与未覆盖项，不跨轴合并掩盖失败。规定验证通过、证据有效且两轴通过后引擎得到 `review_passed`，这是 Agent 终态，不证明无缺陷，不代表人工验收、上线或产品完成。缺任何轴、必修未关闭或证据过期，只能报告当前缺口。

报告原位引用任务记录与引擎证据，不另建重复评审文档；历史度量是辅助统计，不能替代 v2 报告或降低通过条件。接 `deliver` 做 Agent 总结与人工交接。

## 辅助度量（不替代证据）

插件根按 `workflow` 定位。保留实际支持的历史评审统计命令；Codex 前置 `WORKFLOW_HOST=codex`，只有宿主提供真实会话 ID 时运行，不猜 ID。仅填写实际结果，记录失败报告限制，不改变评审结论。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_metric.py" record review --session "${CLAUDE_SESSION_ID}" <<'JSON'
{"task":"实际任务ID","tier":"轻量|标准|完整","files":0,"sources":[],"skipped_axes":[],"findings":[]}
JSON
```

将示例任务、档位、文件数、来源与 findings 替换为实际值；findings 按现有 schema 写 axis、severity、rule，不写代码或规格原文。
