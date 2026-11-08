---
name: metrics
description: 生成流程度量报告：工作流技能触发率、评审阻塞、Stop 钩子拦截、待验证比例、规则命中表和删除候选。仅在用户显式调用本技能时使用。
disable-model-invocation: true
argument-hint: [--days N] [--all] [--min-reviews N]
---

# 流程度量报告

下文的 `${CLAUDE_PLUGIN_ROOT}` 指当前技能所在的插件根目录。如果它没有被替换成绝对路径（如在 Codex 中），从已加载的 `SKILL.md` 路径向上三级定位，执行命令时直接代入绝对路径。在 Codex 中运行下方命令时，在命令前加 `WORKFLOW_HOST=codex`，以使用 Codex 的本机数据目录。

运行下面的命令，把报告原样展示给用户，再用一两句话指出最值得关注的一点。不修改任何规则：报告只产出候选，去留由用户决定。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/metrics_report.py" --project "${CLAUDE_PROJECT_DIR}" $ARGUMENTS
```

- 默认统计当前项目最近 90 天，`--all` 统计本机所有项目。Codex 中在项目根目录执行，`${CLAUDE_PROJECT_DIR}` 和 `$ARGUMENTS` 不会被替换，按用户请求追加 `--days N`、`--all` 或 `--min-reviews N`。
- Codex 汇总结构化度量记录。技能触发率和依赖该比例的规则删除候选仅在 Claude Code 中提供。
- 触发率为低时，“零命中”可能只是规则没被检查，不要据此建议删除。
- 样本不足时只说明趋势，不下结论。
