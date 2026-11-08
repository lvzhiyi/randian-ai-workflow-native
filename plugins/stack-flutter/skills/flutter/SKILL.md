---
name: flutter
description: Flutter/Dart 项目的技术栈惯例。在 Flutter 项目里写代码、查依赖版本、选 analyze/test/build 命令、做平台构建或设备验证、处理生成代码和 git 钩子里的 Flutter 问题时使用。项目自己的架构分层和默认验证平台以项目配置为准。
---

# Flutter 技术栈惯例

下文的 `${CLAUDE_PLUGIN_ROOT}` 指当前技能所在的插件根目录。如果它没有被替换成绝对路径（如在 Codex 中），从已加载的 `SKILL.md` 路径向上三级定位，执行命令时直接代入绝对路径。

只放**任何 Flutter 项目都成立**的做法。状态管理选型（Bloc/Riverpod/…）、目录分层、默认验证哪些平台属于项目约定，读项目的 `docs/` 和「工作流配置」。

## 与官方 Dart and Flutter 插件的分工

官方插件 `dart-flutter`（来自 `flutter/agent-plugins`，preset 已依赖）提供 Flutter/Dart 通用技能和 Dart MCP server。分工：

| 需要什么 | 用哪个 |
| --- | --- |
| Flutter/Dart API 用法、通用最佳实践、pub.dev 包查询、Dart MCP 的分析/格式/测试/运行工具 | 官方 `dart-flutter` |
| 版本核对口径、本团队的检查流程与交付证据、Stop 钩子兜底、常见坑 | 本技能 `stack-flutter` |
| 项目自己的架构分层、状态管理选型、目录约定 | 项目 `docs/` 与「工作流配置」 |

官方技能的建议与项目规范冲突时以项目规范为准（例如官方示例用 Riverpod，项目用 Bloc）。Dart MCP 工具跑出的分析或测试结果可以作为验证证据，但交付时仍要写明实际执行了什么。

## 版本核对（配合 `workflow-core:tech-docs`）

- 依赖：`pubspec.yaml` 看约束，`pubspec.lock` 看实际解析版本；Git 依赖核对 `ref` 与锁定的 `resolved-ref`。
- SDK：`flutter --version`，与 `pubspec.yaml` 的 `environment.sdk` / `flutter` 约束对照。
- 改依赖时同时检查 `pubspec.lock` 的变化；不为套用文档示例升级依赖。
- 查 pub 包文档时写明包名 + 锁定版本 + 平台。

## 默认检查脚本

项目「工作流配置」写了 `verify.*`（如 `python3 scripts/check.py full`）时用项目的；没有时用本插件自带的：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/flutter_check.py"                    # 改动文件格式 + analyze + 全部测试
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/flutter_check.py" test/x_test.dart   # 只跑指定测试
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/flutter_check.py" --all              # 格式检查 lib/ test/ 全部手写文件
```

- 格式检查只看相对 HEAD 改动和新增的手写 Dart 文件，自动排除 `.g.dart`、`.freezed.dart` 等生成文件。
- 输出 `status=PASS / CHECK_FAILED / BLOCKED / SKIPPED`；退出码 0 通过、1 未通过、2 执行受阻。`--no-test` 跳过测试时，交付必须说明原因。
- 已处理 git 钩子环境的 `GIT_DIR` 问题。

## Stop 钩子（自动兜底）

本插件启用后，AI 每次准备结束回合时，会对**相对 HEAD 改动的手写 Dart 文件**运行 `dart analyze`：

- 有 error 时，钩子把错误位置反馈给 AI，要求先修复再结束；第二轮仍有错误时只提示用户，不再阻止，避免死循环。
- 没改 Dart 文件、不是 Flutter 项目、分析器不可用或超时（90 秒）时直接放行。
- 它只兜底 error 级静态分析，**不替代** `workflow-core:verify` 要求的格式检查和测试；已经提交的改动不在检查范围内。

## 常用命令

按需单独执行：

| 目的 | 命令 |
| --- | --- |
| 格式检查 | `dart format --output=none --set-exit-if-changed <路径>` |
| 静态分析 | `flutter analyze`（依赖已解析时可加 `--no-pub` 加快） |
| 单个测试 | `flutter test test/<file>_test.dart`，用 `--name '<用例名>'` 只跑一条 |
| 全部测试 | `flutter test` |
| Android 构建 | `flutter build apk --debug --target-platform android-arm64` |
| iOS 构建（无签名） | `flutter build ios --no-codesign --debug`（需要 macOS + Xcode） |
| Web 构建 | `flutter build web` |

- 只跑项目配置的默认验证平台；其他平台写“按当前约定未执行”。
- 明确要求多平台构建时串行执行；磁盘不足先停并记录，不清理工作区外的缓存或用户数据。

## 验证口径

- Widget 测试 ≠ 已连接设备的端到端测试；单元/Widget 通过后仍需在交付中注明设备未覆盖。
- 有运行中的 `flutter run` 会话时，改完代码用热重载（`r`）或热重启（`R`）实际查看页面；没有会话时说明未覆盖。
- 修改公共主题或组件时，回归浅色、深色、窄屏、系统文字缩放、键盘弹出等场景。
- 测试直接调用真实 repository/controller；用 fake 替换外部依赖（网络、存储），不 mock 被测对象本身。

## 生成代码

- `build_runner`、`freezed`、`json_serializable`、资源常量等生成文件不手改：改生成源后重新生成并审查 diff。
- 生成前先看扫描范围；生成后只提交本次相关的生成结果。

## 评审清单（供 `workflow-core:review` 的 Standards 轴使用）

评审时排除生成文件：`*.g.dart`、`*.freezed.dart`、`*.gr.dart`、`*.config.dart`、`*.mocks.dart`，以及项目配置声明的生成目录。以下每条违反均按“应修”起报，标注“阻塞”的除外：

- **异步与生命周期**：`await` 之后使用 `BuildContext` 前检查 `mounted`（State 内用 `mounted`，其他位置用 `context.mounted`）；Bloc/Cubit 关闭后不再 `emit`；页面关闭后的异步返回不更新已释放的状态或登录态。
- **资源释放**：`TextEditingController`、`FocusNode`、`AnimationController`、`ScrollController`、`StreamSubscription`、`Timer` 由创建者在 `dispose` / `close` 中释放。
- **重复提交**：提交类按钮在请求进行中禁用或忽略重复触发。
- **分层**：视图（Widget）内不直接发请求、读写存储或实现鉴权逻辑。
- **敏感数据（阻塞）**：令牌、密码等不写入 SharedPreferences、日志、`print`、异常消息或测试 fixture；不硬编码生产地址或真实凭据。
- **生成代码（阻塞）**：生成文件只能由生成源重新生成，diff 中手改生成文件时报告。
- **依赖**：`pubspec.yaml` 依赖变化时 `pubspec.lock` 同步变化；不为套用示例升级无关依赖。
- **测试写法**：测试调用真实 repository/controller，只用 fake 替换外部依赖；不 mock 被测对象本身；不用 `sleep` / 固定延时等待异步结果（用 `pump` / `pumpAndSettle` 或 fake 时钟）。

## 常见坑

- **git 钩子里跑 Flutter 版本识别错误**：钩子环境带着 `GIT_DIR`，Flutter 会读到项目仓库的 git 元数据，SDK 版本显示成 `0.0.0-unknown`，导致 `pub get` 版本约束失败。在钩子脚本里先 `unset GIT_DIR GIT_INDEX_FILE` 再调用 `flutter`。
- 会格式化全仓库并 `git add .` 的 pre-commit 钩子会把无关文件卷进提交，不能拿来做验证；提交前看清暂存区。
- 页面关闭后的异步返回不得再更新已释放的控制器/状态；组件创建的 `TextEditingController`、`FocusNode`、订阅由创建者释放。
- 敏感数据（令牌等）用平台安全存储，不放 SharedPreferences 或日志。
