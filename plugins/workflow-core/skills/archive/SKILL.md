---
name: archive
description: 归档已交付或已合入主干的变更目录（如 docs/development/changes/<task-id>/ 或历史 openspec/changes/<change-id>/），并在归档后自动检测文档断链。用户说“归档变更 / 归档提案 / archive change / 清理已完成变更目录”时使用。
---

# 归档已完成变更目录

`${CLAUDE_PLUGIN_ROOT}` 指当前插件根目录；未替换时从本 `SKILL.md` 向上三级定位并代入绝对路径。

目标：将已人工交付或已合入主干的完整档变更目录移入 `archive/YYYY-MM-<id>/`，避免变更目录长期堆积，同时确保仓库内文档链接零断链。无需为归档创建假实施任务。

## 1. 盘点与只读预览（必做）

1. 读取项目根 `ai-workflow.yaml`，确定变更根目录：默认 `<docs.dev_docs>/changes`（无配置时为 `docs/development/changes`）；用户明确归档旧 OpenSpec 目录时传 `--changes-dir openspec/changes`。
2. 列出变更根目录下除 `archive/` 外的候选子目录，结合任务卡或引擎状态区分**已完成/已合入**与**仍在进行中/待联调**的变更。
3. 对拟归档项先运行只读预览（Cursor / Codex 可前置 `WORKFLOW_HOST=cursor` / `WORKFLOW_HOST=codex`）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive_change.py" --root "项目绝对根" --task "<task-id>" --dry-run
```

4. 向用户展示待归档清单与目标路径，**等用户确认后再移动**；绝不静默归档仍在实施或待联调的变更。

## 2. 执行归档与断链校验

用户确认后执行真实归档（批量归档可重复 `--task`；归档旧目录加 `--changes-dir openspec/changes`）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/archive_change.py" --root "项目绝对根" --task "<task-id>"
```

脚本会原子校验全部目标（拒绝路径穿越、符号链接及目标冲突），移动至 `archive/YYYY-MM-<id>/`，并自动调用 `check_docs.py` 检查全库文档链接。

## 3. 断链修复与收尾

- **退出码 0（无断链）**：报告归档前后路径与检查结果。
- **退出码 1（存在指向旧路径的断链）**：列出所有报错文件与旧链接；若为模块卡或设计索引等规划文档，按 `workflow` / `prd-breakdown` 做会话级规划登记后修正为新归档路径，再运行项目 `verify.docs`（或自包含 `python3 scripts/check_docs.py --root .`）确认 0 错误。
- **权限边界**：不自动 `git commit`、不推送、不删除变更内容。
