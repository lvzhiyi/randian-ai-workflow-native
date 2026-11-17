# 任务级工作流引擎协议 v2

本文是后续宿主、dashboard 适配契约。引擎强制流程判据，普通插件不提供抗恶意、身份认证或防程序代答保证。人工确认记录 `human_process=true` 只表示流程属性；TTY 和 actor 字符串都不是安全签名。同一系统用户可以修改数据库、检查程序及运行环境。

## 权威与兼容

权威层级为任务 → `rounds[]` 执行轮次 → `attempts[]` 阶段尝试 → `evidence[]` 证据。`current_round` 选择活动轮次，当前仅允许一个活动轮次。顶层 `state/phase/results/snapshot/missing` 是兼容投影，不应作为单独可写状态接口。SQLite 任务、事件、请求幂等响应原子提交；所有修改需要整数 CAS `version` 和全局唯一 request。相同 request 不同参数拒绝；v2 重放返回当前只读投影，不返回旧轮次成功。事件 history 保留原时点快照。

CLI `create --details` 必填且必须为 JSON 对象（包括拒绝 null）；CLI 不存在旧协议创建回退。所有旧任务变更执行 CLI（包括 run/start/cancel/confirm-plan）均拒绝并要求先 adopt-protocol；status/snapshot/history 仍可只读查询旧任务。Python `create(..., details=...)` 创建 v2。旧 `create(id,tier,acceptance,plan,request)` 保留首期 API 语义用于兼容既有调用，不作为新任务工作流入口；旧任务可调用 `adopt_protocol(..., details)` 显式升级，旧事件保留、旧证据不继承。标准/完整档必须升级或直接创建 v2，才能使用新增的真实批准和评审闭环，不再要求不存在的可信签署通道。

## 任务外的规划与服务管理

`workflow_planning_cli.py open|status|close --root PROJECT --session SESSION` 是固定绝对脚本入口，不要求 `--task`。用户选择 init / prd-breakdown 后由技能显式 open：附 `--operation init|prd-breakdown`、重复 `--path` 精确目标及可选 `--ttl`（默认 1800 秒、最多 3600 秒）。配置文档角色来自 `docs.*`；模块卡只限 cards_dir 直接 Markdown 文件；README 只有明确登记才开放。init 可通过 `--config-json` 内联已确认的配置草稿自举有限配置与骨架目标，不因缺配置文件死锁。

状态和开闭 JSONL 审计保存在项目外引擎目录，以项目、真实宿主 session、操作、精确路径及有效期约束。原生 Write / Edit / apply_patch 的全部目标命中才放行；路径穿越、符号链接、伪扩展、Shell 文件写入、MCP 混写及模板/产品代码不在例外内。结束、取消和交接前 close，过期或关闭后恢复原实施门槛。旧 WORKFLOW_PLAN_PATHS 环境例外不再生效。技能调用不是可靠身份认证，宿主也不能自动观察 Skill 后声称用户已批准实施。

看板固定脚本只接受明确 on / off / status 与不重复的 --root / --task 键值，不需要实施任务；三宿主固定 WORKFLOW_HOST 前缀均支持。动作可放在白名单键值之前或之后，标量选项重复仍拒绝。无 action、serve、其他参数、任意脚本和 shell 拼接不属于免任务命令。init 的固定 detect.sh、git check-ignore -v 与固定 check_docs.py --root PROJECT --check-config 独立只读放行，不要求实施任务。macOS 只规范化 /var、/tmp、/etc 的已知 /private 系统祖先别名，项目内部符号链接仍逐级拒绝；配置与草稿均不可将插件 scripts/skills/templates 源码映射成规划文档。只读调查保持原有独立放行逻辑。

## 小接口

所有修改方法前缀均为 `(task_id, expected_version, request_id, ...)`：

- `create(task_id,tier,acceptance,plan,request_id,details=...)`：登记任务，不偷偷补齐目标和来源。任务字段 `goal/scope/acceptance/source/dependencies` 缺失呈现 missing；依赖是 `{id,status:"done"}` 列表，空列表表示无依赖，未完成依赖阻止开始。
- `confirm_tier(..., actor, selected_tier=None)`：确认当前档位，或在待定档轮次内原子地记录用户选中的档位。选中档位需要不同的步骤、方案或验证计划时，保留选择并报告待补项。
- `request-confirmation`：由 Agent 为当前任务、轮次、版本及绑定会话准备聊天确认。命令仅登记请求。宿主通过用户消息钩子处理档位回复或完整档的单独方案批准。
- `approve_proposal(..., actor, control_digest)`：完整档专用批准。方案必需 goal、scope、impact、risk、rollback、acceptance，以及任务结构化 steps；批准绑定当前轮次和控制摘要。标准档 3–5 步短计划无需方案审批，轻量至少一项必要实施记录。
- `register_baseline(..., receipt)`：供可信读取组件登记成功完整读取回执。receipt 为 `{path,sha256,bytes_read,complete:true,executor,session_id,round_id}`，必须匹配当前 executor/session，登记时引擎附加 binding_version；readiness 只使用当前绑定代次的基线。路径必须在声明 baseline 内、为根目录内普通非链接文件；当前内容哈希和字节数必须一致。缺失、截断、错误轮次不可用。此接口验证回执一致性，不证明阅读理解或组件身份。
- `bind_executor(...,executor,session_id)`：显式绑定轮次主执行者与会话；切换任一字段递增 binding_version，旧读取与 TDD 记录不能借用，即使切回旧身份仍须重新读取。人工档位确认和方案批准保持有效，当前验证/评审成功失效。宿主可检查 rounds[-1].executor/session_id/binding_version 和 missing 中 executor_binding/baseline。绑定是流程属性，不是身份认证。
- `start(...)`：全部就绪门禁通过后进入 implementing。
- `record_tdd(...,{adopted:boolean,reason?:string,alternative_validation?:string,step_id?:string})`：TDD 优先非强制；adopted=false 必须同时提供非空 reason 与 alternative_validation，不能替代真实验证。有 step_id 时只覆盖该有效未完成步骤；无 step_id 为任务级、覆盖当前轮次（含同轮修复）。记录绑定当前 executor/session/binding_version，换执行者需重新决策。
- `finish_step(...,step_id,summary)`：只能完成首个未完成 todo，先有 TDD 决策。
- `finish_implementation(...)`：所有步骤完成且就绪证据有效后进入 pending_verification，不是任务成功；同轮 repair attempt 同时记 passed。
- `repair(...,steps,reason)`：仅 failed/review_failed/stale 可用；steps 是非空 `{id,title}` 数组，ID 必须与本轮已有 todo 不重复。原范围授权内追加修复 todo 与 repair attempt，进入 implementing；不改变 scope/control_digest，不重新批准。当前绑定的基线失效时须先重读。完成修复步骤 → finish_implementation → run → review，不能跳过新验证。扩大范围仍须 update_task 并重新授权。
- `run(...)`：沿用真实 runner、检查计划和快照；执行前后内容一致且每项真实退出零，才得到 passed。失败、超时、异常分别进入 attempt 明细；同范围重跑追加新 attempt。执行期间不持数据库写锁。
- `review(...,report)`：验证通过且证据仍有效后，双轴结构化评审；通过得到 review_passed，是 Agent 终态，不再要求人工交付。必修未解决不能通过，也不能在重试报告中删除后逃逸；同轴同 ID 显式 resolved=true 才关闭。
- `update_task(...,changes)`：只接受明确允许的任务字段。goal/scope/tier/acceptance/plan/source/dependencies/baseline/steps/proposal 改变控制摘要，撤销当前批准及相关证据、重置 todos，旧记录保留。选档后首次补齐当前缺失的步骤、方案或验证计划，可以沿用同一档位选择。纯展示措辞使用 note。方案批准绑定 proposal 的 JSON 语义内容。
- `resume(...)`：同轮继续，只登记活动，不跳门禁、不推测阻塞。`return_task(...,reason,actor)`：人工退回新轮次，旧轮保留、新轮无证据。cancel 后只能人工退回，start/run/resume 均不能自动复活。
- `cancel(...)`：取消并保持历史；running 期间拒绝取消，避免误报子进程已经停止。`recover(...)` 只恢复已死亡所有者的孤立 running，记 error attempt，不能把异常当成功。
- `status(task_id)` / `snapshot(task_id)`：只读快照查询，核对当前文件和基线，返回 stale/invalidated 投影但不写任务、事件或版本。`history(task_id)`：只读历史事件。观察失效在下一次成功修改时落库，查询版本仍可用于 CAS。活动缺失不等于阻塞；activity 是明确事件，不根据静默时长造 blocked。

## JSON 输出 schema

CLI 成功为 `{ok:true,task:Task}`；history 为 `{ok:true,history:[{seq,action,task:Task}]}`。检查或评审实际失败返回退出码 1 与 `ok:false`，拒绝/参数错误返回退出码 2 与 `{ok:false,code,message}`。检查通过或正常修改返回 0。

Task 的核心结构（新增字段应允许向前兼容）：

```json
{
  "protocol_version": 2,
  "id": "T1", "version": 12, "root": "/project",
  "tier": "standard", "goal": "目标", "scope": ["src"],
  "source": "需求来源", "dependencies": [], "acceptance": ["A1"],
  "baseline": ["docs/standards.md"],
  "steps": [{"id":"s1","title":"步骤"}],
  "plan": {"version":1,"checks":[]},
  "plan_digest": "sha256", "control_digest": "sha256",
  "current_round": "uuid", "state":"review_passed", "phase":"done",
  "snapshot":"sha256", "results":[], "missing":[],
  "activity":{"action":"review","at":0,"round_id":"uuid","state":"review_passed"},
  "rounds":[{
    "id":"uuid","state":"review_passed","phase":"done","control_digest":"sha256",
    "executor":"cli-reader","session_id":"session-1","binding_version":1,
    "todos":[{"id":"s1","title":"步骤","status":"done","summary":"记录"}],
    "attempts":[{"id":"uuid","stage":"review","status":"passed","round_id":"uuid","control_digest":"sha256","snapshot":"sha256","evidence_id":"uuid"}],
    "evidence":[{"id":"uuid","kind":"review","round_id":"uuid","control_digest":"sha256","valid":true,"data":{}}]
  }]
}
```

状态：created、implementing、pending_verification、running、passed、failed、stale、review_failed、review_passed、cancelled。阶段：planning、implementation、verification、review、done。attempt 状态含 running/passed/failed/error/invalidated；未完成 todo 为 pending。review report 的 findings 保留在证据 data 内，required_findings 是轮次必修状态投影。各 attempt 的 snapshot 是对应尝试输入，并带 executor/session_id/binding_version，不可拿最新任务字段反推历史。

`report` 必需字段：

```json
{
  "round_id":"当前轮次", "control_digest":"当前控制摘要", "snapshot":"验证快照",
  "executor":"review-agent",
  "axes":{
    "spec":{"conclusion":"pass","findings":[]},
    "standards":{"conclusion":"fail","findings":[{"id":"F1","required":true,"resolved":false,"message":"修复说明"}]}
  }
}
```

## CLI 示例

以下 `we` 代表 `python3 plugins/workflow-core/scripts/workflow_engine_cli.py --root /project --db /outside/state.sqlite`；每次修改用上次输出 version，request 使用新唯一值。没有 mark-pass 命令。

```sh
we create --task T1 --tier 标准 --acceptance A1 --plan checks.json --details details.json --request create-T1
we confirm-tier --task T1 --version 1 --actor 用户 --request tier-T1
# 完整档才需要；摘要取当前 control_digest，命令会要求人工终端确认。
we approve-proposal --task T1 --version 2 --actor 用户 --digest CONTROL_DIGEST --request approve-T1
we bind-executor --task T1 --version 3 --executor cli-reader --session session-1 --request bind-T1
we read-baseline --task T1 --version 4 --path docs/standards.md --executor cli-reader --session session-1 --max-bytes 65536 --request baseline-T1
we start --task T1 --version 5 --request start-T1
we record-tdd --task T1 --version 6 --file tdd.json --request tdd-T1
we finish-step --task T1 --version 7 --step s1 --summary 完成当前步 --request step-T1
# 按顺序完成剩余步骤后：
we finish-implementation --task T1 --version 10 --request implementation-T1
we run --task T1 --version 11 --request verify-T1
we review --task T1 --version 13 --file report.json --request review-T1
we status --task T1
we snapshot --task T1
we history --task T1
we resume --task T1 --version 14 --request resume-T1
we return-task --task T1 --version 15 --actor 用户 --reason 需求退回 --request return-T1
we update-task --task T1 --version 16 --file changes.json --request update-T1
we adopt-protocol --task OLD --version 4 --file details.json --request adopt-OLD
# 验证/评审失败或失效时，同轮原授权范围内修复（VERSION 取当前值）：
we repair --task T1 --version VERSION --file repair-steps.json --reason 原范围内修复 --request repair-T1
```

`tdd.json` 示例：`{"adopted":false,"reason":"文档变更","alternative_validation":"运行真实检查计划"}`。`repair-steps.json` 示例：`[{"id":"fix-1","title":"修复原范围内问题"}]`。

`details.json` 示例（标准档三步）：

```json
{"goal":"实现需求","scope":["src"],"source":"用户需求链接","dependencies":[],"baseline":["docs/standards.md"],"steps":[{"id":"s1","title":"测试"},{"id":"s2","title":"实施"},{"id":"s3","title":"整理"}]}
```

`read-baseline --executor ID --session SESSION [--max-bytes N]` 在 JSON 顶层返回 `document:{path,content,truncated,bytes_read}`，正文实际交给 Agent。默认 65536 字节，上限可设 1–1048576；最多读取 N+1 字节检测超限。正文须为完整 UTF-8 文本，非法编码拒绝且不登记。未截断才登记完整回执；超限退出 2、code=BASELINE_TRUNCATED，返回有界正文且不写证据、不增加版本。宿主组件可用 `register-baseline --file receipt.json` 登记相同协议。登记不是 Agent 对文档的理解证明。

## 检查计划与资源边界

检查计划保持 v1 严格 schema：顶层 version=1/checks；每项 id/argv/cwd/timeout/covers/acceptance。argv 数组、不执行 shell 字符串；covers 合计必须 format/analyze/test，acceptance 完整覆盖。项目需选择真正检查这些目标的命令，退出零不证明测试质量；包装器应拒绝空测试。每项结果保存 exit_code/reason/stdout/stderr/truncated；selectors 同时排空双管道，stdout/stderr 各保留最多 4096 字节，超限继续排空并标记 truncated，不使用无界 communicate。常见 token/password/secret/API key 与 Authorization 值尽力脱敏；脱敏不等于任意敏感数据检测，检查程序仍不得输出秘密。超时及父进程退出均清理进程组，避免遗留子进程持有管道造成死锁。

数据库必须放在 root 外部，私有权限，拒绝符号链接。源码内容快照使用 Git 纳管文件与未忽略文件内容哈希，拒绝敏感文件、链接、子模块。基线另按声明文件完整核对；修改基线不能复用阅读证据。status 不改数据库，CLI 实例初始化已有数据库也不更新 schema 版本。旧协议 status 同样只读。

## 最终集成接口补充

### 无落盘 JSON 输入

CLI 创建的 `--plan PATH` / `--plan-json JSON` 二选一，`--details PATH` / `--details-json JSON` 二选一且必填；接受报告/变更/步骤输入的命令使用 `--file PATH` / `--file-json JSON` 二选一。可在尚未获得实施授权前完成计划登记，不必先向项目写配置文件。文件与内联同传时输出 ARGUMENT。

```sh
we create --task T1 --tier 轻量 --acceptance A1 --plan-json '{"version":1,"checks":[{"id":"all","argv":["python3","-m","unittest"],"cwd":".","timeout":120,"covers":["format","analyze","test"],"acceptance":["A1"]}]}' --details-json '{"goal":"需求","scope":["src"],"source":"用户","dependencies":[],"baseline":["docs/standards.md"],"steps":[{"id":"s1","title":"实施"}]}' --request inline-create
we record-tdd --task T1 --version VERSION --file-json '{"adopted":true}' --request inline-tdd
```

CLI status/snapshot/history 在数据库不存在时直接返回 NOT_FOUND，不创建数据库或父目录。

### 档位配置强制验证

若 `ai-workflow.yaml` 存在 verify 段，当前档位 `verify.light/standard/full` 必须有非空命令或命令列表。配置了 `verify.docs` 时，其命令也必须逐项纳入执行。`platforms.*` 只声明平台范围，不包含可执行命令；默认平台构建必须由项目写入对应档位 verify 清单，不由技术栈无关引擎猜测构建命令。无 verify 段保留 Python 旧 API 兼容，不凭空补命令；有 verify 配置不允许静默回退。

create/adopt/update/run 强制计划包含该档位的全部命令（重复配置也需相应数量），以 `cwd="."` 的 argv 精确匹配。使用标准库 shlex 分词而非 shell；含 `&&`、管道、重定向、命令替换等无法直接安全执行的形式返回 VERIFY_CONFIG，缺失命令返回 VERIFY_REQUIRED。复杂组合应拆成列表项或项目内检查包装器。covers 仍保留覆盖 schema 校验，但绝不是配置命令已运行的证据。

任务输出新增 `verify_config_digest`（当前档命令 argv 列表摘要）。配置变化使成功验证/评审失效，missing 含 verify_config；须 update-task 使计划重新满足配置后执行。run 前及执行后均检查配置，配置在执行中变化不能继续报通过；实际结果仍来自 runner。

### 原范围 todo 细化

`refine_steps(task_id,version,request,steps,reason)` / `refine-steps --file[-json] ... --reason ...` 只允许追加 `{id,title,parent_id}`，parent_id 必须引用本轮已有 todo，新 id 唯一且不得与已有 ID 重复。不接受 scope/acceptance/proposal 等控制字段；原 todo（含已完成记录）和 attempts 保留。新增 todo 必须完成才能 finish-implementation → run。

细化不改变原授权 `steps`、control_digest 或人工批准；新增执行细节权威在当前轮次 todos，追加 steps_refined 审计证据（含原范围/验收与原因）。不能用它扩展任务范围；实质改变范围/验收/方案仍使用 update-task 并重授权。

### 宿主只读会话解析

`Engine.task_for_session(session_id, executor=None)` 不依赖环境变量。只读扫描当前 root 的 v2 当前轮绑定，返回唯一活动任务的当前失效投影；无匹配返回 None，多匹配抛 SESSION_AMBIGUOUS，宿主须显式消歧。cancelled 和仍有效的 review_passed 不算活动；已失效 review_passed 会返回 stale 供修复。结果带 current_round 以及 rounds[-1].executor/session_id/binding_version。旧事件中绑定不参与匹配，不把上一轮会话误认成当前轮。

### 资源硬上限

`_baseline_bytes`、register_baseline 和 status 刷新验证均最多读取 1MiB+1 哨兵字节，超过 1MiB 拒绝 BASELINE_LIMIT；不能借回执接口绕开 CLI 上限。公开 read_baseline_bytes 的显式 limit 同样最多读 1MiB+1，供宿主有界展示，宿主不得把截断正文登记为完整。

runner 的 deadline 涵盖进程执行和管道排空。父进程已退出但逃逸 setsid 子进程仍持有管道时，到期关闭本地管道、标 timeout/truncated 并退出；仅尽力清理原进程组，不承诺终止逃逸到其他会话的所有进程。

## 当前限制与后续适配

不修改 dashboard/hooks/config/skills；这些消费者需要按 protocol_version 选择适配，并读取 current_round 下明细。旧 Python API 为兼容桥，不自动获得 v2 就绪门禁；CLI 强制 details，旧任务只允许查询或显式 adopt-protocol 后执行。步骤创建、升级、更新与修复共用非空字符串 id/title 和唯一 ID 校验。

尚无任务图自动调度、跨宿主身份认证、流式文档读取证明、主动文件监控或后台自动恢复。依赖由调用方登记完成事实，不主动查询其他任务。语义措辞与实质方案变化无法通用自动判别：note 明确为非控制展示文字，其余方案字段保守撤销授权。事件保存完整快照，目前历史增长和 status 全量内容哈希适合本地中小项目；后续可做归档和内容寻址优化，但不能用 mtime 替代内容一致性。
