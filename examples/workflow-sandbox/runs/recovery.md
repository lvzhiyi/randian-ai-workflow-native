# 模拟项目磁盘恢复记录

日期：2026-11-14。真实磁盘初始确认 examples 与 workflow-sandbox 均不存在，未使用 Glob 旧列表作为文件证据。

从此前会话创建内容恢复领域、CLI、检查器与相关测试；按完整读取上下文恢复存储及 12 项测试，重建 PRD、提案、任务卡、配置和索引。仅写 examples/workflow-sandbox，不改引擎和父目录已有文件。

## 本次实际验证

从真实绝对路径执行 `PYTHONDONTWRITEBYTECODE=1 python3 /Users/lv/work/randian/ai-dev-workflow/examples/workflow-sandbox/scripts/check.py all`：实际运行 27 项测试，全部通过（存储 12、领域 5、CLI 5、检查器 5）；文档配置、5 个文件链接和任务卡均 0 错误。格式与静态分析因 Ruff 缺失均 BLOCKED，整体真实退出 2。

实际重新执行 `scripts/protocol_baseline.py`，退出 0：S05 注入失败测试真实退出 1且失败文件保留；S06 改动前测试退出 0、改动后未重测；S04/S05/S06 返回提醒；S04 第二次 Stop 无输出；S07 仅加载 deliver 后 Stop 无输出。仅为合成协议观察，真实 Codex 会话仍未验收。

本次恢复沿用此前代码与测试，不宣称重新经历开发红绿流程。源文件与新测试由旧会话创建内容精确恢复（包括最后退出码分类修复）；存储从完整读取上下文重建，PRD/索引/任务卡/提案部分重建而非字节级备份。未查明目录消失原因。没有新增批准，没有安装、提交或发布。
