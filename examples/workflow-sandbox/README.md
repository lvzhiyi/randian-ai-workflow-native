# 工作流模拟项目

本项目用于从原始 PRD 演练 ai-dev-workflow；所有数据均应为合成数据。

- 需求来源：[PRD v1.0](PRD.md)
- 拆解入口：[项目首页](docs/product/项目首页.md)
- 流程场景：[scenarios.json](scenarios.json)
- 实际证据与限制：[基线记录](runs/baseline.md)

## 使用

Python 3.9+，运行期只依赖标准库。从本目录运行：

```bash
python3 src/task_cli.py --file /tmp/sandbox-tasks.json add "演练待办"
python3 src/task_cli.py --file /tmp/sandbox-tasks.json list --status pending
python3 src/task_cli.py --file /tmp/sandbox-tasks.json complete 1
python3 src/task_cli.py --file /tmp/sandbox-tasks.json undo 1
```

必须显式指定文件，父目录必须存在；缺失文件的查询不创建文件。只支持单写进程，不提供多进程锁或合并。原子替换保障可见性，不承诺断电耐久性。损坏文件拒绝覆盖，修复后可重试；符号链接不受支持。
成功退出 0，业务输入错误退出 1，文件或数据错误退出 2；错误写 stderr，结果为 JSON。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check.py tests
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check.py docs
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check.py format
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check.py static
PYTHONDONTWRITEBYTECODE=1 python3 scripts/check.py all
PYTHONDONTWRITEBYTECODE=1 python3 scripts/protocol_baseline.py
```

检查退出 0 表示通过，1 表示失败，2 表示必要工具缺失而 BLOCKED。检查器拒绝零测试，不自动安装工具。格式与静态分析拟使用 Ruff，目前未安装，尚无已确认锁定版本；不能用语法检查或 IDE 无诊断代替。
文档检查复用父仓库检查器，仅以本目录为根。Git 属于父仓库，不初始化嵌套仓库。
协议探针在临时副本注入失败和改动，只发送合成钩子输入，不启动真实 Codex 会话，不提供真实审批证据；结束后清理临时数据。
