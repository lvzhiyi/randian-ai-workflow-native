---
name: flutter
description: Flutter/Dart 项目的技术栈惯例。在 Flutter 项目里写代码、查依赖版本、选 analyze/test/build 命令、做平台构建或设备验证、处理生成代码和 git 钩子里的 Flutter 问题时使用。项目自己的架构分层和默认验证平台以项目配置为准。
---

# Flutter 技术栈惯例

只放**任何 Flutter 项目都成立**的做法。状态管理选型（Bloc/Riverpod/…）、目录分层、默认验证哪些平台属于项目约定，读项目的 `docs/` 和「工作流配置」。

## 版本核对（配合 `workflow-core:tech-docs`）

- 依赖：`pubspec.yaml` 看约束，`pubspec.lock` 看实际解析版本；Git 依赖核对 `ref` 与锁定的 `resolved-ref`。
- SDK：`flutter --version`，与 `pubspec.yaml` 的 `environment.sdk` / `flutter` 约束对照。
- 改依赖时同时检查 `pubspec.lock` 的变化；不为套用文档示例升级依赖。
- 查 pub 包文档时写明包名 + 锁定版本 + 平台。

## 常用检查命令

项目配置里有封装好的检查脚本时优先用脚本；否则按需组合：

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

## 常见坑

- **git 钩子里跑 Flutter 版本识别错误**：钩子环境带着 `GIT_DIR`，Flutter 会读到项目仓库的 git 元数据，SDK 版本显示成 `0.0.0-unknown`，导致 `pub get` 版本约束失败。在钩子脚本里先 `unset GIT_DIR GIT_INDEX_FILE` 再调用 `flutter`。
- 会格式化全仓库并 `git add .` 的 pre-commit 钩子会把无关文件卷进提交，不能拿来做验证；提交前看清暂存区。
- 页面关闭后的异步返回不得再更新已释放的控制器/状态；组件创建的 `TextEditingController`、`FocusNode`、订阅由创建者释放。
- 敏感数据（令牌等）用平台安全存储，不放 SharedPreferences 或日志。
