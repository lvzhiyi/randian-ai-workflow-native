---
name: metrics
description: 生成流程度量报告：工作流技能触发率、评审阻塞、Stop 钩子拦截、待验证比例、规则命中表和删除候选。仅在用户运行 /workflow-core:metrics 时使用。
disable-model-invocation: true
argument-hint: [--days N] [--all] [--min-reviews N]
---

# 流程度量报告

运行下面的命令，把报告原样展示给用户，再用一两句话指出最值得关注的一点。不修改任何规则：报告只产出候选，去留由用户决定。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/metrics_report.py" --project "${CLAUDE_PROJECT_DIR}" $ARGUMENTS
```

- 默认统计当前项目最近 90 天，`--all` 统计本机所有项目。
- 触发率为低时，“零命中”可能只是规则没被检查，不要据此建议删除。
- 样本不足时只说明趋势，不下结论。
