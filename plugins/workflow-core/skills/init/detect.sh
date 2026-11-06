#!/usr/bin/env bash
# 只读扫描项目，输出可推断的工作流配置线索。用法：detect.sh [项目根目录]
# 输出格式：每行 "键: 值"，"-" 表示未识别。脚本不修改任何文件。
set -u
ROOT="${1:-.}"
cd "$ROOT" 2>/dev/null || { echo "error: 无法进入目录 $ROOT"; exit 1; }

say() { printf '%s: %s\n' "$1" "${2:--}"; }
has() { [ -e "$1" ]; }
join() { local IFS=', '; echo "$*"; }

say "project_root" "$(pwd)"
say "git_branch" "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

# ---- 技术栈 ----
stacks=()
if has pubspec.yaml; then
  if grep -qE '^\s*flutter:' pubspec.yaml; then stacks+=(flutter); else stacks+=(dart); fi
fi
if has package.json; then
  deps=$(sed -n '/"\(dev\)\{0,1\}[dD]ependencies"/,/}/p' package.json)
  echo "$deps" | grep -q '"next"' && stacks+=(next)
  echo "$deps" | grep -q '"react"' && stacks+=(react)
  echo "$deps" | grep -q '"vue"' && stacks+=(vue)
  echo "$deps" | grep -q '"@angular/core"' && stacks+=(angular)
  echo "$deps" | grep -q '"react-native"' && stacks+=(react-native)
  [ ${#stacks[@]} -eq 0 ] && stacks+=(node)
fi
has go.mod && stacks+=(go)
{ has pom.xml || has build.gradle || has build.gradle.kts; } && ! has pubspec.yaml && stacks+=(jvm)
{ has pyproject.toml || has requirements.txt; } && stacks+=(python)
say "stack" "$( [ ${#stacks[@]} -gt 0 ] && join "${stacks[@]}")"

if has package.json; then
  pm=npm
  has pnpm-lock.yaml && pm=pnpm
  has yarn.lock && pm=yarn
  has bun.lockb && pm=bun
  say "package_manager" "$pm"
  scripts=$(sed -n '/"scripts"/,/}/p' package.json | grep -oE '"[a-zA-Z0-9:_-]+"\s*:' | tr -d '":' | tr -d ' ' | grep -v '^scripts$' | tr '\n' ' ')
  say "package_scripts" "$scripts"
fi

if has pubspec.yaml; then
  plats=()
  for p in android ios web macos windows linux; do has "$p" && plats+=("$p"); done
  say "flutter_platforms" "$( [ ${#plats[@]} -gt 0 ] && join "${plats[@]}")"
  say "flutter_sdk_constraint" "$(grep -A3 '^environment:' pubspec.yaml | grep -E 'sdk|flutter' | tr -s ' ' | tr '\n' ' ')"
fi

# ---- 规格工具 ----
spec=-
has openspec && spec="openspec ($(ls openspec/changes 2>/dev/null | grep -vc '^archive$') 个进行中 change)"
say "spec_tool" "$spec"

# ---- 接口工具 ----
api=-
if has .apifox/settings.json; then
  pid=$(grep -oE '"[a-zA-Z]*[pP]roject[iI]d"\s*:\s*"?[0-9a-zA-Z-]+' .apifox/settings.json | head -1 | grep -oE '[0-9a-zA-Z-]+$')
  api="apifox (.apifox/settings.json, projectId=${pid:-未读出})"
fi
{ has openapi.yaml || has openapi.json || has swagger.json; } && api="${api/#-/}openapi 文件"
say "api_tool" "$api"

# ---- 设计工具（只取前 5 个不同链接） ----
links=$(grep -rhoE 'https://(pixso\.cn|www\.figma\.com|figma\.com|lanhuapp\.com|mastergo\.com)/[^ )>"`]+' \
  --include='*.md' --include='*.yaml' --include='*.json' . 2>/dev/null \
  | grep -v node_modules | sort | uniq -c | sort -rn | head -5 | awk '{print $2}')
tool=-
echo "$links" | grep -q pixso && tool=pixso
echo "$links" | grep -q figma && tool="${tool/#-/}${tool:+ }figma"
echo "$links" | grep -q lanhu && tool="${tool/#-/} lanhu"
echo "$links" | grep -q mastergo && tool="${tool/#-/} mastergo"
say "design_tool" "$tool"
[ -n "$links" ] && echo "$links" | sed 's/^/design_link: /'

# ---- 文档结构 ----
for d in docs/product docs/development docs/development/handoffs; do
  has "$d" && say "dir" "$d"
done
if has docs/product; then
  find docs/product -maxdepth 2 -name '*.md' 2>/dev/null | head -20 | sed 's/^/product_doc: /'
fi
if has docs/development; then
  find docs/development -maxdepth 1 -name '*.md' 2>/dev/null | sed 's/^/dev_doc: /'
fi

# ---- 检查与验证命令线索 ----
for f in scripts/check.py scripts/check.sh Makefile justfile melos.yaml Taskfile.yml; do
  has "$f" && say "check_entry" "$f"
done
if has Makefile; then
  say "make_targets" "$(grep -oE '^[a-zA-Z0-9_-]+:' Makefile | tr -d ':' | tr '\n' ' ')"
fi
ci=()
has .github/workflows && ci+=($(ls .github/workflows))
has .gitlab-ci.yml && ci+=(.gitlab-ci.yml)
say "ci" "$( [ ${#ci[@]} -gt 0 ] && join "${ci[@]}")"
has .git/hooks/pre-commit && say "git_hook" ".git/hooks/pre-commit"

# ---- Agent 入口与已有配置 ----
for f in AGENTS.md CLAUDE.md .claude/settings.json; do has "$f" && say "agent_file" "$f"; done
cfg=-
for f in AGENTS.md CLAUDE.md; do
  has "$f" && grep -q '工作流配置' "$f" && cfg="$f"
done
say "existing_workflow_config" "$cfg"
if has .claude/settings.json; then
  say "enabled_plugins" "$(grep -oE '"[a-z0-9-]+@[a-z0-9-]+"' .claude/settings.json | tr -d '"' | tr '\n' ' ')"
fi
exit 0
