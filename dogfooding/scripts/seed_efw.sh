#!/usr/bin/env bash
# EFW dogfooding 数据录入（只写 new/efw/.pjt，不改 EFW 源码）
set -euo pipefail
EFW=/mnt/d/framework/new/efw
PT=/mnt/d/ProjectTool
EVID=$PT/dogfooding/evidence
P="uv run --project $PT pjt"
PY="uv run --project $PT python"
LOG=$EVID/seed-output.txt
: > "$LOG"
cd "$EFW"

jget() { $PY -c "import sys,json;print(json.load(sys.stdin)['result']['$1'])"; }
note() { echo "$@" | tee -a "$LOG"; }

note "== member =="
M=$($P --json member add jichao --name "计超" --role maintainer --git-name jichao | jget id)
note "member jichao = $M"
$P member use jichao | tee -a "$LOG"

note "== goal =="
GOAL=$($P --json goal add "完成可实际使用的 EFW Studio" \
  --criterion "核心模型可稳定表达应用" \
  --criterion "代码生成稳定" \
  --criterion "虚拟调试可用" \
  --criterion "真机调试链路可用" \
  --criterion "Studio UI 可完成完整工作流" \
  --criterion "打包与发布链路完整" | jget id)
note "goal = $GOAL"

note "== milestones =="
M1=$($P --json milestone add "页面内模型编辑" --goal $GOAL --status active | jget id)
M2=$($P --json milestone add "真机调试链路" --goal $GOAL | jget id)
M3=$($P --json milestone add "桌面壳与打包" --goal $GOAL | jget id)
M4=$($P --json milestone add "工程卫生" --goal $GOAL | jget id)
note "M1 页面内模型编辑 = $M1"
note "M2 真机调试链路 = $M2"
note "M3 桌面壳与打包 = $M3"
note "M4 工程卫生 = $M4"

note "== tasks =="
task() { # title milestone priority weight owner labels... 
  local title="$1"; shift
  $P --json task add "$title" "$@" | jget id
}
T1=$(task "store.updateModel 保存通路（revision + 诊断）" --milestone $M1 --owner jichao --priority high --weight 3 --label ui --label core)
T2=$(task "通信页行内编辑（信号/事件/队列增删改）" --milestone $M1 --owner jichao --weight 3 --label ui)
T3=$(task "数据流页句子行内编辑与拖动排序" --milestone $M1 --weight 2 --label ui)
T4=$(task "状态机页编辑（加状态/转换/条件）" --milestone $M1 --weight 3 --label ui)
T5=$(task "删除对象前的引用检查（信号/数据流/事件）" --milestone $M1 --weight 2 --label ui --label core)
T6=$(task "serial/tcp 回环集成测试（socat/pty）" --milestone $M2 --owner jichao --priority high --weight 2 --label debug --label test)
T7=$(task "真机 hash 不一致提示与 observe_port 模板实机验证" --milestone $M2 --priority low --weight 2 --label debug)
T8=$(task "重建 desktop 主进程与 preload 白名单桥" --milestone $M3 --owner jichao --priority high --weight 5 --label desktop)
T9=$(task "修复 package.json 脚本与 electron-builder 资源路径" --milestone $M3 --weight 2 --label packaging)
T10=$(task "PyInstaller 后端打包脚本与 backend-bin 产物" --milestone $M3 --owner jichao --weight 3 --label packaging)
T11=$(task "打包发布 smoke test（安装包启动完整链路）" --milestone $M3 --weight 2 --label packaging --label test)
T12=$(task "ProcTransport.close 资源泄漏与测试 ResourceWarning" --milestone $M4 --priority low --weight 1 --label test)
T13=$(task "efw.h 聚合 msgq.h / efw_all.c 收录 msgq.c" --milestone $M4 --priority low --weight 1 --label runtime)
T14=$(task "源码草稿持久化（崩溃恢复）" --milestone $M4 --priority low --weight 2 --label ui)
T15=$($P --json task add "完成 ProjectTool dogfooding 第一轮记录与报告" --owner jichao --status ready --weight 1 --label process | jget id)
note "T1 = $T1"; note "T2 = $T2"; note "T3 = $T3"; note "T4 = $T4"; note "T5 = $T5"
note "T6 = $T6"; note "T7 = $T7"; note "T8 = $T8"; note "T9 = $T9"; note "T10 = $T10"
note "T11 = $T11"; note "T12 = $T12"; note "T13 = $T13"; note "T14 = $T14"; note "T15 = $T15"

note "== dependencies =="
$P task depend $T2 $T1 | tee -a "$LOG"
$P task depend $T3 $T1 | tee -a "$LOG"
$P task depend $T11 $T8 | tee -a "$LOG"
$P task depend $T11 $T10 | tee -a "$LOG"
$P task depend $T7 $T6 | tee -a "$LOG"

note "== updates =="
$P update add --task $T6 --milestone $M2 \
  --blocker "没有真实硬件与伪终端环境时无法端到端验证" \
  --next "用 socat 建 pty 对补回环集成测试" \
  "已确认 serial/tcp 传输只有实现没有集成测试；回环方案可行。" | tee -a "$LOG"
$P update add --task $T1 --task $T2 --milestone $M1 \
  "store 目前只有 open/refresh/create，模型编辑缺少统一保存通路；通信页编辑依赖该通路。" | tee -a "$LOG"
$P update add --task $T8 --milestone $M3 \
  --blocker "desktop/ 目录不存在，package.json 的 start/main 指向缺失文件" \
  "确认 desktop/ 与 scripts/ 为空，打包链路未闭合；先重建主进程桥。" | tee -a "$LOG"

note "== decisions =="
$P decision add --title "ProjectTool 只嵌入 new/efw，不初始化整个 framework 仓库" \
  --context "framework 根包含与本工作无关的历史改动（136 项未提交），Git root 与 EFW 项目根不一致" \
  --decision "只在 new/efw/.pjt 初始化 ProjectTool，不触碰 framework 根" \
  --rationale "保持 Studio 模块边界；避免把无关历史纳入项目状态" \
  --alternative "framework 根初始化::会把旧版 Studio 与无关内容混入同一项目" \
  --consequence "未来跨模块工作需要 Project Link" \
  --status accepted | tee -a "$LOG"
$P decision add --title "Studio CLI 与 GUI 继续共享同一个 Service/Core" \
  --context "cli.py 与 server.py 都通过 studio_core/service.py 调度表分发方法" \
  --decision "保持单一 service 调度表作为唯一事实来源，不另写 CLI 专用实现" \
  --rationale "模型分析与 codegen 的单事实来源约定；测试可以同时覆盖两条入口" \
  --alternative "CLI 独立实现::会与 GUI 行为漂移" \
  --consequence "服务方法变更需同步 docs/04 与 ui/types.ts" \
  --status accepted | tee -a "$LOG"
$P decision add --title "Electron 主进程以 stdio 启动 studio_core.server，而不是内嵌 HTTP" \
  --context "desktop/ 目录缺失需要重建；现有服务协议是 JSON Lines over stdio" \
  --decision "主进程 spawn python -m studio_core.server（或 PyInstaller 产物），经 preload 白名单转发 RPC" \
  --rationale "复用既有协议与安全边界；无需新引入本地端口与鉴权" \
  --alternative "本地 HTTP/WebSocket::需要额外端口管理与安全策略" \
  --consequence "需要管理子进程生命周期与白名单方法表" \
  --status draft | tee -a "$LOG"

note "== ids saved =="
cat > "$EVID/efw-ids.env" <<EOF
PRJ_PROJECT_ROOT=$EFW
EFW_GOAL=$GOAL
EFW_M1=$M1
EFW_M2=$M2
EFW_M3=$M3
EFW_M4=$M4
EFW_T1=$T1
EFW_T2=$T2
EFW_T3=$T3
EFW_T4=$T4
EFW_T5=$T5
EFW_T6=$T6
EFW_T7=$T7
EFW_T8=$T8
EFW_T9=$T9
EFW_T10=$T10
EFW_T11=$T11
EFW_T12=$T12
EFW_T13=$T13
EFW_T14=$T14
EFW_T15=$T15
EOF
echo "seed done"
