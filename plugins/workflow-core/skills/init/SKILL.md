---
name: init
description: 为项目生成或更新「工作流配置」`ai-workflow.yaml`，并按需生成文档骨架（项目首页、需求说明、任务总览、设计索引、术语表、工程规范）。项目第一次接入 ai-dev-workflow 插件、项目根还没有 ai-workflow.yaml、配置仍是 AGENTS.md/CLAUDE.md 里的旧格式 Markdown 小节需要迁移、用户说“初始化工作流 / 接入插件 / 生成工作流配置”，或项目的技术栈、设计工具、接口工具、验证命令发生变化需要刷新配置时使用。
---

# 初始化项目工作流配置与文档骨架

目标：自动识别项目情况，**只问识别不了的**，生成项目根目录的「工作流配置」`ai-workflow.yaml`，在 Agent 入口文件留一行指针，并补齐流程需要的文档骨架。配置和文档按项目写一次、提交进 git，团队共用。

流程说明（三档、拆解、交接、交付等）由插件技能承载，**不**在项目里生成 `ai-workflow.md` 一类的流程文档；项目里只放项目事实。

## 1. 探测（只读）

运行探测脚本，它只读文件、不做修改：

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/init/detect.sh" .
```

输出每行 `键: 值`，`-` 表示未识别。然后**只补读需要确认的文件**，不全库扫描：

| 配置项 | 依据 | 需要时补读 |
| --- | --- | --- |
| 技术栈 | `stack`、`flutter_platforms`、`package_manager` | — |
| 规格工具 | `spec_tool` | `openspec/project.md` 首段 |
| 接口工具 | `api_tool` | 开发规范里的接口文档，取项目名称 |
| 设计工具与权威文件 | `design_tool`、`design_link` | 设计索引或 UI 规范中写明“权威/当前”的那个文件 |
| 产品文档、交接目录 | `dir`、`product_doc`、`dev_doc` | 项目首页 / 总览文件名；已有文档的实际位置 |
| 是否有界面 / 后端接口 | `stack`、`flutter_platforms`、`api_tool` | 有前端或移动端视为有界面；有接口工具或网络层目录视为有后端接口 |
| 评审基线分支 | 功能分支实际合入的分支（`git log --merges --format=%s origin/<候选> -10` 看合并目标），参考远端默认分支 `git symbolic-ref --short refs/remotes/origin/HEAD` | 两者不一致或都取不到时列为待问项 |
| 验证命令 | `check_entry`、`make_targets`、`package_scripts`、`ci` | 测试/验证规范、`scripts/` 说明、CI 文件中的实际命令 |
| 默认验证平台 | 测试/验证规范中的约定 | — |
| 代码产物要求 | 代码规范中的注释、生成代码规则 | — |
| 已有配置 | `existing_workflow_config` | `ai-workflow.yaml` 全文（进入更新模式），或旧格式 Markdown 小节全文（进入迁移模式） |

**取值规则**：

- 命令只写项目里**真实存在**的脚本或 CI 中实际执行的命令，不编造。
- 项目没有任何代码检查入口时，轻量/标准档验证命令写技术栈插件的默认检查（Flutter 为 `stack-flutter` 的 `flutter_check.py`），并注明来自插件。
- 文档验证命令默认写 workflow-core 自带的 `check_docs.py`；项目原有文档检查若已覆盖同样的链接和任务卡规则，在第 6 步的迁移建议里提出改用插件脚本，避免两份实现。
- 有多个设计链接时，以文档中明确写着“权威 / 当前 / 确认”的那个为准；判断不了就作为待问项，不按出现次数或顺序猜。
- 每个值都要能说出依据（文件 + 位置），依据只在第 3 步的展示表里给出，不写进最终配置。

## 2. 只问识别不了的

把仍然未知或有歧义的项集中一次提问（有提问工具就用选项形式，每项给推荐值），常见待问项：

- 默认验证平台（例如只有 `android/ ios/ web/` 目录，没有写明默认验证哪个）
- 同一文件里有多个候选的权威设计文件
- 交接目录（项目还没有约定时，推荐有规格变更放变更目录、否则 `docs/development/handoffs/`）
- 标准档、完整档分别跑哪条命令（只找到一条检查命令时可以都用它）

能从仓库确认的不要问。用户没回答的项写“待确认”，不填示例值。

## 3. 展示草稿，确认后写入

1. 按 `${CLAUDE_PLUGIN_ROOT}/templates/ai-workflow.yaml` 的结构生成配置：保留模板头部的格式说明注释，删掉示例值，不适用的写“无”，未确认的写“待确认”。只写脚本和技能能直接取用的事实；规则类说明（如“iOS 仅在明确要求时验证”的理由）留在项目 `docs/`，不写进配置。
2. 先展示「配置项 | 值 | 依据」表和将要写入的文件全文，等用户确认。
3. 写入项目根目录 `ai-workflow.yaml`，然后在 Agent 入口文件加一行指针（如“工作流配置：根目录 `ai-workflow.yaml`”）：
   - 已有 `AGENTS.md` 写 `AGENTS.md`；只有 `CLAUDE.md` 写 `CLAUDE.md`；`CLAUDE.md` 只是 `@AGENTS.md` 引用时写 `AGENTS.md`。
   - 两者都没有：新建 `AGENTS.md`，并询问是否同时新建只含 `@AGENTS.md` 的 `CLAUDE.md`。
   - 写入前用 `git check-ignore -v <文件>` 检查 `ai-workflow.yaml`、入口文件和 `docs/` 是否被忽略；被忽略时团队拿不到配置，先告诉用户命中的规则，由用户决定改 `.gitignore` 还是换位置，不擅自修改。
4. 写完运行 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_docs.py" --root . --check-config`：解析错误（退出码 2）或路径不存在必须修正后再交付。
5. **更新模式**（已有 `ai-workflow.yaml`）：逐项对比，只展示有变化的键；保留用户手写的 `notes` 和注释，不整份覆盖。
6. **迁移模式**（只有旧格式 Markdown 小节）：把小节里的每一项映射到对应键，展示「旧条目 | 新键 | 值」；规则类文字（不是路径、命令、名称的部分）留在原文档或移到 `docs/` 对应规范，不塞进 `notes`。确认后写入 `ai-workflow.yaml`，删除入口文件里的旧小节并换成一行指针。

## 4. 文档骨架（只补缺失的）

模板在 `${CLAUDE_PLUGIN_ROOT}/templates/docs/`，生成规则见其中的 `README.md`。默认结构：

```
docs/product/项目首页.md                 init
docs/product/需求/需求说明.md            init
docs/product/任务/版本任务总览.md        init
docs/product/设计/设计索引.md            init，有设计工具时
docs/product/术语表.md                  init，只建骨架，不预填词条
docs/development/coding.md              init
docs/development/architecture.md        init
docs/development/testing.md             init
docs/development/ui.md                  init，有界面时
docs/development/api-integration.md     init，有后端接口时
docs/product/任务/<模块>.md              prd-breakdown 首次拆出该模块时
docs/development/handoffs/<task-id>.md  handoff 首次跨会话交接时
```

1. **先映射已有文档**：项目已有承担同一角色的文档（如 `doc/测试说明.md`、`wiki/架构.md`），不新建，把它的路径写进 `ai-workflow.yaml` 对应键；文件名不同但职责相同也算已有。
2. **列清单再写**：展示「文档 | 状态（新建 / 已有·映射到 X / 不适用及原因）」，确认后再创建。只创建缺失的文件，**已有文件一律不覆盖、不改写**。
3. **填事实，不留空壳**：用第 1 步探测到的事实替换 `{{...}}` 占位符——
   - `testing.md`：真实存在的检查命令、CI 命令、默认验证平台，与配置一致；
   - `architecture.md`：按现有顶层目录推断分层职责，每行标「待确认」请用户核对；
   - `coding.md`：格式化/分析配置文件、生成代码命令；
   - `设计索引.md`、`api-integration.md`：设计工具与权威文件、接口工具与项目；
   - `项目首页.md`：项目名、一句话说明，并**只保留已生成或已映射文档的链接**。
   确实不知道的写「待确认」；删除模板里的 `<!-- 说明 -->` 注释。
4. 术语表只建骨架：可以从 PRD、任务卡、规格和代码中提取候选词列给用户，**只有用户确认了定义的词才写入**，不替业务方编造定义。
5. 生成后运行 `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/check_docs.py" --root . --check-config`，链接和配置路径必须全部通过。
6. `ai-workflow.yaml` 里的文档路径与实际生成/映射的位置保持一致（默认设计索引为 `docs/product/设计/设计索引.md`）。

## 5. 插件建议（可选）

根据识别结果给出建议的插件组合，例如 `flutter + pixso + apifox` → `preset-flutter-pixso-apifox`；没有对应 preset 时列出 `workflow-core` + 对应维度插件，并说明哪些维度暂时没有插件。

用户同意后，再在 `.claude/settings.json` 写入 `extraKnownMarketplaces` 和 `enabledPlugins`，让团队成员打开项目时收到安装提示：已有文件时合并，不覆盖其他设置。

`extraKnownMarketplaces` 除了 `ai-dev-workflow`，还要列出所选插件依赖的**其他 marketplace**：依赖解析不会自动添加 marketplace，缺了依赖就装不上。例如 Flutter preset 依赖官方 `dart-flutter`，需要加 `"dart-flutter": {"source": {"source": "github", "repo": "flutter/agent-plugins"}}`（`claude-plugins-official` 是内置的，不用加）。

## 6. 收尾

- 不提交、不推送；告诉用户改了哪些文件，并建议提交，这样团队共用同一份配置和文档。
- 提示下一步：有 PRD 时运行 `/workflow-core:prd-breakdown` 拆解，它会生成模块卡。
- 发现项目文档里还保留着和插件重复的流程正文（三档、交接、交付格式等）时，列出位置并建议迁移：插件里已有的段落改成“见 `workflow-core:<技能>`”，只保留项目特有内容。是否迁移由用户决定，本技能不自动删改。
- 按 `deliver` 的五项格式汇报。
