"""宿主共享同步门禁：流程防护栏，不是可信签署或系统写入沙箱。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import uuid
from contextvars import ContextVar

CURRENT_EVENT = ContextVar("workflow_gate_event", default={})

from baseline_config import resolve_baselines
from workflow_config import load

READ_TOOLS = {"Read", "ReadFile", "Glob", "Grep", "rg", "LS", "WebSearch", "WebFetch", "Skill", "AskUserQuestion", "ExitPlanMode"}
SHELL_TOOLS = {"Bash", "shell", "exec_command", "run_shell_command", "Shell"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
CONFIRM_HELP = ("ENGINE_CONFIRMATION_UNSUPPORTED：当前宿主回调没有可验证的用户确认 schema，不自动批准。"
                "请由用户运行 CLI confirm-tier；完整档另运行 approve-proposal --digest CONTROL_DIGEST。"
                "CLI 需要 --task、--version、--request、--actor；批准绑定当前任务/轮次/control_digest。"
                "这是人工流程防护栏，不是可信签署。")


def project_root(cwd):
    """最近配置为边界，禁止借用父项目状态。"""
    path = Path(cwd or ".").resolve()
    for folder in (path, *path.parents):
        if (folder / "ai-workflow.yaml").is_file():
            return folder
        if (folder / ".git").exists():
            break
    return None


def safe_shell_input(event):
    """Git 调查命令强制关闭外部 diff/textconv，回传宿主更新后的输入。"""
    data = event.get("tool_input") or {}
    command = shell_command(data)
    args = shell_tokens(command)
    if not args or args[0] != "git":
        return None
    index = 2 if len(args) > 1 and args[1] == "--no-pager" else 1
    if len(args) <= index or args[index] not in {"diff", "log", "show"}:
        return None
    if any(a.startswith(("--ext-diff", "--textconv", "--output")) for a in args):
        return None
    args[index + 1:index + 1] = ["--no-ext-diff", "--no-textconv"]
    changed = dict(data)
    key = "command" if "command" in data else "cmd"
    original = data.get(key)
    normalized = shlex.join(args)
    changed[key] = [*original[:2], normalized] if isinstance(original, list) else normalized
    return changed


def readonly_shell(command):
    """只放行有限调查命令，拒绝重定向、子命令、外部过滤器和隐式执行。"""
    args = shell_tokens(command)
    if not args:
        return False
    if not args:
        return False
    if args[0] == "git" and len(args) > 1 and args[1] == "--no-pager":
        args.pop(1)
    if args[0] == "git":
        return len(args) >= 2 and args[1] in {"status", "diff", "log", "show", "ls-files", "rev-parse"} and all(
            not a.startswith(("--output", "--ext-diff", "--textconv", "--exec", "--config", "--upload-pack", "--open-files-in-pager", "--paginate")) for a in args[2:])
    if args[0] in {"pwd", "ls", "cat", "head", "tail", "wc", "stat"}:
        return not any(a.startswith(("--files0-from", "--output")) for a in args[1:])
    if args[0] == "rg":
        return not any(a.startswith(("--pre", "--hostname-bin", "--search-zip", "--open-files-in-pager")) or a.startswith("-z") for a in args[1:])
    return False


def engine_command(command):
    """仅允许本插件固定 CLI 入口，不能用任意 Python 或 shell 包装绕过门禁。"""
    args = shell_tokens(command)
    if not args:
        return False
    if len(args) < 3 or args[0] not in {"python", "python3"}:
        return False
    script = Path(args[1])
    return script.is_absolute() and script.resolve() == Path(__file__).with_name("workflow_engine_cli.py").resolve()


def dashboard_command(command):
    args = shell_tokens(command)
    if not args or len(args) < 3 or args[0] not in {"python", "python3"}:
        return False
    if not Path(args[1]).is_absolute() or Path(args[1]).resolve() != Path(__file__).with_name("dashboard_server.py").resolve():
        return False
    remaining = args[2:]
    if remaining and remaining[0] == "status":
        remaining = remaining[1:]
    while remaining:
        if len(remaining) < 2 or remaining[0] not in {"--root", "--task"}:
            return False
        remaining = remaining[2:]
    return True


def pending_path(root, session):
    from workflow_engine_cli import default_db
    name = hashlib.sha256(str(session).encode()).hexdigest()
    return default_db(root).parent / ("confirmation-" + name + ".json")


def confirmation_markers(event):
    """普通澄清不进入授权链；出现协议前缀后必须完整匹配，不能用前缀子串批准。"""
    text = json.dumps(event.get("tool_input") or {}, ensure_ascii=False)
    return text, re.findall(r"workflow-confirm:[^\s\"<>]+", text)


def prepare_confirmation(event, root):
    """将待确认目标持久化；回执只消费相同工具调用及当前版本请求。"""
    text, markers = confirmation_markers(event)
    if "workflow-confirm:" not in text:
        return None
    if os.environ.get("WORKFLOW_HOST") == "codex":
        return None
    try:
        task = load_task(root)
        error = binding_error(event, task)
        if error:
            return error
        data = event.get("tool_input") or {}
        text = json.dumps(data, ensure_ascii=False)
        action = "approval" if event["tool_name"] == "ExitPlanMode" else "tier_confirmation"
        marker = "workflow-confirm:" + task["id"] + ":" + task["current_round"] + ":" + task["control_digest"] + ":" + action
        if markers != [marker] or text.count("workflow-confirm:") != 1 or not event.get("tool_use_id"):
            return "ENGINE_CONFIRMATION_REQUIRED：确认请求必须包含 " + marker + "，并提供宿主 tool_use_id。"
        path = pending_path(root, event.get("session_id"))
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        pending = {"task": task["id"], "round": task["current_round"], "digest": task["control_digest"], "version": task["version"], "tool": event["tool_name"], "call": event["tool_use_id"], "input": data, "action": action}
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(pending, handle, ensure_ascii=False)
        return None
    except Exception as exc:
        return "ENGINE_CONFIRMATION_REQUIRED：" + str(exc) + "；" + CONFIRM_HELP


def complete_confirmation(event):
    text, markers = confirmation_markers(event)
    if "workflow-confirm:" not in text:
        return None
    if os.environ.get("WORKFLOW_HOST") == "codex":
        return CONFIRM_HELP
    root = project_root(event.get("cwd"))
    path = pending_path(root, event.get("session_id"))
    if not path.is_file():
        return CONFIRM_HELP
    pending = json.loads(path.read_text(encoding="utf-8"))
    response = event.get("tool_response")
    expected_marker = "workflow-confirm:" + pending["task"] + ":" + pending["round"] + ":" + pending["digest"] + ":" + pending["action"]
    if markers != [expected_marker] or text.count("workflow-confirm:") != 1:
        return CONFIRM_HELP
    if (pending["call"] != event.get("tool_use_id") or pending["tool"] != event.get("tool_name") or pending["input"] != event.get("tool_input") or not isinstance(response, dict) or response.get("error") or response.get("is_error")):
        return CONFIRM_HELP
    if pending["tool"] == "AskUserQuestion":
        questions = pending["input"].get("questions", [])
        answers = response.get("answers")
        accepted = isinstance(answers, dict) and len(questions) == 1 and answers.get(questions[0].get("question")) == "确认"
    else:
        accepted = response.get("approved") is True
    task = load_task(root)
    if (not accepted or binding_error(event, task) or task["id"] != pending["task"] or task["current_round"] != pending["round"] or task["control_digest"] != pending["digest"] or task["version"] != pending["version"]):
        return "ENGINE_CONFIRMATION_REJECTED：回执未确认或任务/轮次/版本已经变化；" + CONFIRM_HELP
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db
    engine = Engine(root, default_db(root))
    if pending["action"] == "approval":
        engine.approve_proposal(task["id"], task["version"], str(uuid.uuid4()), "Claude 原生用户流程", task["control_digest"])
    else:
        engine.confirm_tier(task["id"], task["version"], str(uuid.uuid4()), "Claude 原生用户流程")
    path.unlink()
    return "ENGINE_CONFIRMATION_RECORDED：当前任务轮次用户流程确认已登记（非可信签署）。"


def shell_command(data):
    """兼容 Codex cmd 与 shell argv；argv 必须明确是 shell -c 结构。"""
    command = data.get("command", data.get("cmd", ""))
    if isinstance(command, list):
        if len(command) == 3 and command[0] in {"bash", "sh", "zsh", "/bin/bash", "/bin/sh", "/bin/zsh"} and command[1] in {"-c", "-lc"}:
            return command[2]
        return ""
    return command


def shell_tokens(command):
    """只在引号外拒绝 shell 语法；单引号 JSON 的美元符号是普通正文。"""
    if not isinstance(command, str):
        return None
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote != "'":
            escaped = True
            continue
        if char in {"'", '\"'}:
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
            continue
        if quote != "'" and char in "$`":
            return None
        if quote is None and char in ";&|<>\n\r\x00":
            return None
    try:
        return shlex.split(command) if quote is None else None
    except ValueError:
        return None


def load_task(root):
    """写入前和阶段边界才核对全量内容哈希，不给每次只读工具增加快照成本。"""
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db
    task_id = os.environ.get("WORKFLOW_TASK_ID")
    if not task_id:
        from session_binding import lookup
        task_id = lookup(root, CURRENT_EVENT.get().get("session_id"), default_db(root))
    return Engine(root, default_db(root)).status(task_id)


def targets(event, root):
    """从受支持编辑工具提取真实目标；不明确的写入按整个任务范围检查。"""
    data = event.get("tool_input") or {}
    values = []
    for key in ("file_path", "path", "notebook_path"):
        if data.get(key):
            values.append(data[key])
    if event.get("tool_name") == "apply_patch":
        text = data.get("command") or data.get("patch") or data.get("input") or ""
        values.extend(re.findall(r"^\*\*\* (?:Update File|Add File|Delete File|Move to): (.+)$", text, re.M))
    result = []
    for value in values:
        path = Path(value)
        path = path if path.is_absolute() else root / path
        result.append(path.resolve().relative_to(root).as_posix())
    return result


def binding_error(event, task):
    """会话和执行者必须同时匹配当前轮次，防止借用其他 Agent 的读取证据。"""
    active = next((r for r in task.get("rounds", []) if r.get("id") == task.get("current_round")), {})
    round_id = os.environ.get("WORKFLOW_ROUND_ID", task.get("current_round"))
    executor = os.environ.get("WORKFLOW_EXECUTOR", active.get("executor"))
    if (task.get("protocol_version") != 2 or task.get("id") != os.environ.get("WORKFLOW_TASK_ID", task.get("id")) or
            not round_id or round_id != task.get("current_round") or not executor or
            active.get("executor") != executor or not event.get("session_id") or
            active.get("session_id") != event.get("session_id")):
        return "ENGINE_BINDING_REQUIRED：任务/轮次/执行者/会话绑定不匹配；请先 CLI bind-executor。"
    return None


def configured_baselines(root, task, paths):
    """未知 shell/MCP 目标保守覆盖范围内文件，目录范围也要展开匹配 scoped 规则。"""
    config = load(root)
    selected = list(dict.fromkeys([*task.get("scope", []), *paths]))
    # 目录范围保守纳入可能相交的规则，不遍历整个仓库或依赖目录。
    for rule in config.get("baseline.scoped") or []:
        pattern = rule.split(" => ", 1)[0]
        prefix = re.split(r"[?*[]", pattern, maxsplit=1)[0].rstrip("/")
        if any(scope == "." or not prefix or prefix == scope or prefix.startswith(scope.rstrip("/") + "/") or scope.startswith(prefix + "/") for scope in task.get("scope", [])):
            selected.append(pattern)
    return resolve_baselines(root, selected, config)


def pre_tool(event):
    CURRENT_EVENT.set(event)
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    tool = event.get("tool_name")
    if tool in {"AskUserQuestion", "ExitPlanMode"}:
        return prepare_confirmation(event, root)
    if tool in READ_TOOLS or tool in set(filter(None, os.environ.get("WORKFLOW_READONLY_MCP_TOOLS", "").split(","))):
        return None
    data = event.get("tool_input") or {}
    if tool in SHELL_TOOLS and (readonly_shell(shell_command(data)) or engine_command(shell_command(data)) or dashboard_command(shell_command(data))):
        return None
    try:
        paths = targets(event, root)
        # 仅显式列出的 Markdown 方案文档可在实施前编辑，不允许扩展名或目录通配。
        plans = {p for p in os.environ.get("WORKFLOW_PLAN_PATHS", "").split(os.pathsep) if p}
        if tool in EDIT_TOOLS and paths and all(p in plans and p.endswith(".md") and p.startswith("docs/") for p in paths):
            return None
        task = load_task(root)
        error = binding_error(event, task)
        if error:
            return error
        required = configured_baselines(root, task, paths)
        absent = set(required) - set(task.get("baseline", []))
        if absent:
            return "ENGINE_BASELINE_REQUIRED：任务遗漏配置基线：" + ", ".join(sorted(absent))
        # status 的 missing 还含验证/评审终态缺项，实施阶段不能据此拒绝合法编码。
        readiness_missing = [item for item in task.get("missing", []) if item not in {"review", "checks"}]
        if readiness_missing:
            return "ENGINE_NOT_READY：" + ", ".join(readiness_missing)
        if task.get("state") != "implementing":
            return "ENGINE_STATE_DENIED：仅 implementing 允许实施写入；评审后请新轮次，失败/失效请 CLI repair。"
        if paths and any(not any(p == scope or p.startswith(scope.rstrip("/") + "/") or scope == "." for scope in task.get("scope", [])) for p in paths):
            return "ENGINE_SCOPE_DENIED：目标不在批准任务范围内。"
        return None
    except Exception as exc:
        return "ENGINE_GATE_ERROR：写入已拒绝：" + str(exc)


def post_tool(event):
    """不把普通工具结果或模型代答当人工确认，能力不足时展示 CLI 入口。"""
    CURRENT_EVENT.set(event)
    if event.get("tool_name") in {"AskUserQuestion", "ExitPlanMode"}:
        return complete_confirmation(event)
    if event.get("tool_name") not in {"Read", "ReadFile"}:
        return None
    root = project_root(event.get("cwd"))
    if root is None:
        return None
    paths = targets(event, root)
    if not paths:
        return None
    # 只处理配置基线；CLI read-baseline 自行输出正文并登记其他显式任务基线。
    config = load(root)
    patterns = [rule.split(" => ", 1)[0] for rule in config.get("baseline.scoped") or []]
    if paths[0] not in resolve_baselines(root, [*paths, *patterns], config):
        return None
    response = event.get("tool_response")
    if not isinstance(response, dict) or response.get("is_error") or response.get("error"):
        return "ENGINE_BASELINE_UNREAD：没有成功完整正文；请使用 CLI read-baseline。"
    file = response.get("file")
    if not isinstance(file, dict) or not isinstance(file.get("content"), str):
        return "ENGINE_BASELINE_UNREAD：宿主读取 schema 不受支持；请使用 CLI read-baseline。"
    with (root / paths[0]).open("rb") as handle:
        data = handle.read(1048577)
    if len(data) > 1048576:
        return "ENGINE_BASELINE_UNREAD：正文超过 1MiB；请使用 CLI read-baseline。"
    if (file.get("content").encode("utf-8") != data or file.get("startLine") != 1 or
            file.get("numLines") != file.get("totalLines") or not isinstance(file.get("totalLines"), int)):
        return "ENGINE_BASELINE_UNREAD：正文截断或版本不匹配；请使用 CLI read-baseline。"
    task = load_task(root)
    error = binding_error(event, task)
    if error:
        return error
    from workflow_engine.engine import Engine
    from workflow_engine_cli import default_db
    receipt = dict(path=paths[0], sha256=hashlib.sha256(data).hexdigest(), bytes_read=len(data), complete=True,
                   executor=next(r for r in task["rounds"] if r["id"] == task["current_round"])["executor"], session_id=event["session_id"], round_id=task["current_round"])
    Engine(root, default_db(root)).register_baseline(task["id"], task["version"], str(uuid.uuid4()), receipt)
    return "ENGINE_BASELINE_RECORDED：" + paths[0]


def context(event):
    """阶段边界汇总权威缺项，评审通过不等于人工验收。"""
    CURRENT_EVENT.set(event)
    if project_root(event.get("cwd")) is None:
        return None
    if event.get("hook_event_name") == "PostToolUse":
        return post_tool(event)
    try:
        task = load_task(project_root(event.get("cwd")))
        error = binding_error(event, task)
        if error:
            return error
        message = "ENGINE_STATE：" + json.dumps({k: task.get(k) for k in ("id", "current_round", "state", "missing")}, ensure_ascii=False)
        if task.get("state") == "review_passed":
            message += "；Agent 双轴评审通过，待人工验收（非可信签署）。"
        return message
    except Exception as exc:
        return str(exc) + "；请绑定 v2 任务、确认档位、完整档批准并 CLI read-baseline，再 start。"
