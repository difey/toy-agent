/* Mira Code 遥测观测页（/observe）—— 独立于主页面（无互相跳转）。
   布局：左=工作区会话列表，中=所选会话的事件列表（可滚动），右=点击事件的详情。 */

const { useState, useEffect, useMemo } = React;

const api = { get: (p) => fetch(p).then((r) => r.json()) };

// 事件 → 一行摘要
function brief(ev) {
  const p = ev.payload || {};
  switch (ev.type) {
    case "session.created": return `会话 ${p.session_id} · ${p.agent} · ${p.model}`;
    case "session.status": return `状态 → ${p.status}`;
    case "session.titled": return `标题: ${p.title}`;
    case "user.message": return (p.content || "").slice(0, 80);
    case "agent.message": return (p.content || "").slice(0, 80);
    case "llm.request": return `model=${p.model} step=${p.step ?? "-"} tools=${(p.tools || []).length}${p.task ? ` task=${p.task}` : ""}`;
    case "llm.response": {
      const tc = p.tool_calls || [];
      const c = (p.content || "").slice(0, 50);
      return `content=${c || "''"}` + (tc.length ? ` tool_calls=${tc.map((t) => (t.id || "").slice(0, 8)).join(",")}` : "");
    }
    case "llm.stream_chunk": return (p.text || "").slice(0, 60);
    case "tool.call": { const c = p.call_id ? ` #${p.call_id.slice(-8)}` : ""; return `${p.name} action=${p.action}${c}`; }
    case "tool.result": { const c = p.call_id ? ` #${p.call_id.slice(-8)}` : ""; return `${p.name} ${(p.result || "").slice(0, 60)}${c}`; }
    case "tool.error": { const c = p.call_id ? ` #${p.call_id.slice(-8)}` : ""; return `${p.name} ✗ ${(p.error || "").slice(0, 60)}${c}`; }
    case "approval.requested": return `审批: ${p.tool}`;
    case "approval.resolved": return `审批: ${p.tool} → ${p.decision}${p.auto ? " (auto)" : ""}`;
    case "error.raised": return (p.message || "").slice(0, 90);
    case "agent.loop.start": return `agent=${p.agent} model=${p.model}`;
    case "agent.loop.end": return `agent=${p.agent} steps=${p.steps}`;
    case "agent.spawn": return `agent=${p.agent_id} task=${p.task_id}`;
    case "agent.join": return `agent=${p.agent_id}`;
    case "task.dispatch": return `→ ${p.target_agent}: ${(p.goal || "").slice(0, 50)}`;
    case "task.start": return `task=${p.task_id} ${p.target_agent}`;
    case "task.complete": return `task=${p.task_id} ✓`;
    case "task.failed": return `task=${p.task_id} ✗`;
    case "metric.snapshot": return JSON.stringify(p).slice(0, 80);
    default: return JSON.stringify(p).slice(0, 80);
  }
}

// 识别子 agent 子树（agent.spawn 起的所有事件）的 seq 范围；嵌套 spawn 只保留最外层
// 注意：sp_llm_N / sp_tool_N 等 span 名在主/子 run 间可能同名，不能 bySpan.get(其它 span) 收行，
//       只能从 spawn span 的共享行出发，沿 children（parent 链）逐层展开真正属于该子树的行。
function collectSpawnRanges(events) {
  const bySpan = new Map();
  const children = new Map();
  for (const ev of events) {
    const sp = ev.span_id || "";
    const par = ev.parent_span_id || "";
    if (sp) {
      if (!bySpan.has(sp)) bySpan.set(sp, []);
      bySpan.get(sp).push(ev);
      if (!children.has(par)) children.set(par, []);
      children.get(par).push(ev);
    }
  }
  const ranges = [];
  for (const ev of events) {
    if (ev.type !== "agent.spawn" || !ev.span_id) continue;
    const sp = ev.span_id;
    const spawnSeq = ev.seq;
    const seqs = [];
    // 根：spawn span 的共享行（agent.spawn / task.start / task.failed / agent.join）
    for (const e of bySpan.get(sp) || []) seqs.push(e.seq);
    // 子树硬上限：该 spawn 的 agent.join（与 spawn 共享 span）。
    // 跨 run 同名 span（sp_llm_N / sp_tool_N）会使 children.get(同名) 把之后其它 run
    // （第二个子 run、主 agent join 后再次调工具）的事件误连进来，仅靠 seq>=spawnSeq 挡不住；
    // 必须以 join 为界，否则 min/max 被错误扩大、折叠时把主 agent 事件也折进子 agent 组。
    const joins = (bySpan.get(sp) || []).filter((e) => e.type === "agent.join").map((e) => e.seq);
    const upper = joins.length ? Math.max(...joins) : Infinity;
    // BFS：仅沿 parent 链展开（children.get(span) = parent_span_id === span 的子事件）
    // 子树事件必然在 spawn 之后、join 之前；跨 run 同名 span（如 sp_tool_1）会把 spawn 前后的
    // 其它 run 事件误连，须用 [spawnSeq, joinSeq] 双边界过滤
    const stack = [sp];
    const seen = new Set();
    while (stack.length) {
      const s = stack.pop();
      if (seen.has(s)) continue;
      seen.add(s);
      for (const c of children.get(s) || []) {
        if (c.seq < spawnSeq || c.seq > upper) continue;
        seqs.push(c.seq);
        if (c.span_id) stack.push(c.span_id);
      }
    }
    if (!seqs.length) continue;
    ranges.push({
      span: sp,
      agent: (ev.payload || {}).agent_id || "sub",
      min: Math.min(...seqs),
      max: Math.max(...seqs),
    });
  }
  // 去嵌套：被更大子树包含的 spawn 不单独折叠（作为外层 children 的一部分）
  return ranges.filter((r) => !ranges.some((o) => o !== r && o.min <= r.min && r.max <= o.max));
}

// 事件列表 → 展示行：合并 stream、折叠子 agent 子树、折叠 one_shot 请求/回复 成 group 行
function buildRows(events) {
  const rows = [];
  for (const ev of events) {
    if (ev.type === "llm.stream_chunk") {
      const last = rows[rows.length - 1];
      if (last && last.kind === "stream") {
        last.count += 1;
        last.endSeq = ev.seq;
        last.ts = ev.ts;
        last.text += (ev.payload && ev.payload.text) || "";
      } else {
        rows.push({ kind: "stream", type: ev.type, seq: ev.seq, endSeq: ev.seq, ts: ev.ts, count: 1, text: (ev.payload && ev.payload.text) || "" });
      }
    } else {
      rows.push({ kind: "event", event: ev });
    }
  }
  // 折叠子 agent 子树（按 seq 范围；子树在事件流中连续，主 agent 阻塞等待）
  const ranges = collectSpawnRanges(events);
  let cur = null;
  const folded = [];
  for (const r of rows) {
    const rs = r.kind === "stream" ? r.seq : r.event.seq;
    const g = ranges.find((rg) => rs >= rg.min && rs <= rg.max);
    if (g) {
      if (!cur || cur.groupId !== g.span) {
        cur = { kind: "group", groupId: g.span, label: "子 agent · " + g.agent, agentId: g.agent, seqStart: g.min, seqEnd: g.max, children: [] };
        folded.push(cur);
      }
      cur.children.push(r);
    } else {
      cur = null;
      folded.push(r);
    }
  }
  // 折叠 one_shot 请求/回复（llm.request task=one_shot + 同 span 的 llm.response，相邻成对）
  const out = [];
  let i = 0;
  while (i < folded.length) {
    const r = folded[i];
    if (r.kind === "event" && r.event.type === "llm.request" && (r.event.payload || {}).task === "one_shot") {
      const span = r.event.span_id || "";
      const children = [r];
      let j = i + 1;
      if (j < folded.length) {
        const c = folded[j];
        if (c.kind === "event" && c.event.type === "llm.response" && (c.event.payload || {}).task === "one_shot" && (c.event.span_id || "") === span) {
          children.push(c);
          j++;
        }
      }
      out.push({ kind: "group", groupId: "os_" + (span || r.event.seq), label: "one_shot", children, oneShot: true });
      i = j;
    } else {
      out.push(r);
      i++;
    }
  }
  return out;
}

const rowKey = (r) => (r.kind === "stream" ? "s" + r.seq : "e" + r.event.seq);
const category = (t) => (t || "?").split(".")[0];
const rowType = (r) => (r.kind === "stream" ? r.type : r.event.type);
const rowTs = (r) => (r.kind === "stream" ? r.ts : r.event.ts) || "";

/* ── 关联高亮：策略责任链 ─────────────────────────────────
   每条规则输入 (rows, target, idx)，返回与 target 关联的行 key 集合；
   多条规则依次执行并把结果合并（叠加）。后续新增规则只需 push 进 CORRELATION_RULES。 */

// 预建索引：toolPairs（(parent|span) 工具配对兜底）、callIds（call_id→行，精确配对）；遍历展开子 agent group 的 children
function buildRowIndex(rows) {
  const toolPairs = new Map();
  const callIds = new Map();
  const visit = (r) => {
    if (r.kind !== "event") return;
    const ev = r.event;
    const sp = ev.span_id || "";
    const par = ev.parent_span_id || "";
    if (sp.startsWith("sp_tool_")) {
      const key = par + "|" + sp; // 兜底：同一次工具调用的 call/result 共享 (parent, span)
      if (!toolPairs.has(key)) toolPairs.set(key, []);
      toolPairs.get(key).push(r);
      const cid = (ev.payload || {}).call_id;
      if (cid) {
        if (!callIds.has(cid)) callIds.set(cid, []);
        callIds.get(cid).push(r);
      }
    }
  };
  for (const r of rows) {
    if (r.kind === "group") {
      for (const c of r.children) visit(c);
    } else {
      visit(r);
    }
  }
  return { toolPairs, callIds };
}

const TOOL_RESULT_TYPES = { "tool.result": 1, "tool.error": 1 };

// 规则①：工具调用配对 —— hover/选中 tool.call ↔ tool.result/tool.error 联动
// 注意：approval.requested/resolved 也共享 sp_tool_N span，收集时必须按类型过滤；
//       新数据优先用 call_id 精确配对；旧数据无 call_id 时回退 (parent|span) 并按 seq 就近配对
//       （同 run 多步工具的 sp_tool_N 会重名，若返回同 key 全部行会误亮多个调用）。
function toolCallPairRule({ rows, target, idx }) {
  const out = new Set();
  if (target.kind !== "event") return out;
  const ev = target.event;
  const sp = ev.span_id || "";
  if (!sp.startsWith("sp_tool_")) return out;
  if (ev.type !== "tool.call" && !TOOL_RESULT_TYPES[ev.type]) return out;
  out.add(rowKey(target)); // 自身
  const cid = (ev.payload || {}).call_id;
  const key = (ev.parent_span_id || "") + "|" + sp;
  const candidates = (cid ? idx.callIds.get(cid) : null) || idx.toolPairs.get(key) || [];
  let best = null;
  let bestDist = Infinity;
  for (const r of candidates) {
    const t = r.event.type;
    if (t !== "tool.call" && !TOOL_RESULT_TYPES[t]) continue;
    if (rowKey(r) === rowKey(target)) continue;
    const d = Math.abs(r.event.seq - ev.seq);
    if (d < bestDist) { bestDist = d; best = r; }
  }
  if (best) out.add(rowKey(best));
  return out;
}

// 规则链（叠加执行，结果合并）；子 agent 整组标记规则已移除（改为折叠分组）
const CORRELATION_RULES = [toolCallPairRule];

// 在 rows 中按 key 找行（展开子 agent group 的 children）
function findRow(rows, key) {
  if (!key) return null;
  for (const r of rows) {
    if (r.kind === "group") {
      for (const c of r.children) if (rowKey(c) === key) return c;
    } else if (rowKey(r) === key) {
      return r;
    }
  }
  return null;
}

function correlatedKeys(rows, key, idx) {
  const out = new Set();
  if (!key) return out;
  const target = findRow(rows, key);
  if (!target) return out;
  for (const rule of CORRELATION_RULES) {
    for (const k of rule({ rows, target, idx })) out.add(k);
  }
  return out;
}

// 事件 → 主 agent 完整上下文（system prompt + 对话 + 工具调用/结果，按角色分块）
// 只展示主 agent 的上下文：子 agent 子树（agent.spawn → agent.join 之间）与
// 辅助 one_shot 调用（approver 决策 / 标题生成）都不进入视图。
function buildContext(events) {
  const parts = [];
  let inSub = false; // 子 agent 子树期间跳过（spawn 进入 / join 退出）
  for (const ev of events) {
    const p = ev.payload || {};
    if (ev.type === "agent.spawn") { inSub = true; continue; }
    if (ev.type === "agent.join") { inSub = false; continue; }
    if (inSub) continue; // 子 agent 内部事件不进入主 agent 上下文
    switch (ev.type) {
      case "session.system_prompt":
        parts.push({ role: "system", title: "SYSTEM PROMPT", text: p.prompt || "" });
        break;
      case "user.message":
        parts.push({ role: "user", title: "USER", text: p.content || "" });
        break;
      case "llm.response":
        if (p.task === "one_shot") continue; // 辅助调用（approver/标题）不属对话上下文
        {
          let text = "";
          if (p.reasoning_content) text += `[推理] ${p.reasoning_content}\n\n`;
          text += p.content || "";
          const tc = p.tool_calls || [];
          if (tc.length) {
            text += "\n→ tool_calls: " + tc.map((t) => `${(t.function && t.function.name) || "?"}(${String((t.function && t.function.arguments) || "")})`).join(" | ");
          }
          parts.push({ role: "assistant", title: `ASSISTANT (step ${p.step ?? "-"})`, text });
        }
        break;
      case "tool.call":
        parts.push({ role: "tool", title: `TOOL CALL · ${p.name}`, text: JSON.stringify(p.arguments || {}, null, 2) });
        break;
      case "tool.result":
        parts.push({ role: "tool", title: `TOOL RESULT · ${p.name}`, text: p.result || "" });
        break;
      case "tool.error":
        parts.push({ role: "tool", title: `TOOL ERROR · ${p.name}`, text: p.error || "" });
        break;
      case "agent.message":
        parts.push({ role: "assistant", title: "ASSISTANT（最终）", text: p.content || "" });
        break;
      default:
        break;
    }
  }
  // system prompt 恒为上下文首条（语义顺序：SYSTEM → USER → 对话/工具）
  const sys = parts.filter((p) => p.role === "system");
  const rest = parts.filter((p) => p.role !== "system");
  return [...sys, ...rest];
}

function Sidebar({ workspaces, activeSid, onSelect, openWs, toggleWs, onCollapseAll, width }) {
  return (
    <aside className="obs-side" style={width ? { width: width + "px", flex: "none" } : undefined}>
      <div className="obs-panel-head"><span>遥测 · 会话</span><button className="obs-collapse-all icon-btn" onClick={onCollapseAll} title="折叠全部工作区"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg></button></div>
      <div className="obs-side-scroll">
        {(workspaces || []).map((w) => {
          const open = openWs[w.id] === true; // 默认折叠（未点击过 → 折叠），与主页面一致
          return (
            <div key={w.id} className="obs-ws">
              <div className="obs-ws-name" onClick={() => toggleWs(w.id)}>
                <span className={"obs-ws-ico" + (open ? " open" : "")}>▸</span>
                {w.id.split("_")[0]}
                <span className="obs-ws-cnt">{w.sessions.length}</span>
              </div>
              {open && (
                <div className="obs-ws-sessions">
                  {w.sessions.map((s) => (
                    <div key={s.id} className={"obs-sess" + (s.id === activeSid ? " active" : "")} onClick={() => onSelect(s.id)} title={s.id}>
                      <span className="obs-sess-t">{s.title || s.id}</span>
                      <span className="obs-sess-id">{s.id.slice(0, 6)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {(!workspaces || !workspaces.length) && <div className="obs-empty">暂无工作区</div>}
      </div>
    </aside>
  );
}

function Row({ r, selectedKey, hoveredKey, activeRels, hoverRels, onSelect, onHover, onLeave, indent }) {
  const key = rowKey(r);
  const cls = "obs-row"
    + (key === selectedKey ? " active" : "")
    + (key === hoveredKey ? " hover" : "")
    + (activeRels.has(key) ? " is-rel-active" : "")
    + (hoverRels.has(key) ? " is-rel-hover" : "")
    + (indent ? " obs-row-indent" : "");
  return (
    <div className={cls} onClick={(e) => { e.stopPropagation(); onSelect(key); }} onMouseEnter={() => onHover(key)} onMouseLeave={() => onLeave(key)}>
      <span className="obs-row-seq">{r.kind === "stream" ? `${r.seq}–${r.endSeq}` : r.event.seq}</span>
      <span className={"obs-row-type t-" + category(rowType(r))}>{rowType(r)}</span>
      {r.kind === "stream" ? <span className="obs-row-cnt">×{r.count}</span> : null}
      <span className="obs-row-brief">{r.kind === "stream" ? r.text.slice(0, 50) : brief(r.event)}</span>
      <span className="obs-row-time">{rowTs(r).slice(11, 19)}</span>
    </div>
  );
}

function EventList({ rows, selectedKey, onSelect, activeSid, openGroups, toggleGroup, onShowContext }) {
  const [hoveredKey, setHoveredKey] = useState(null);
  const idx = useMemo(() => buildRowIndex(rows), [rows]);
  const activeRels = useMemo(() => correlatedKeys(rows, selectedKey, idx), [rows, selectedKey, idx]);
  const hoverRels = useMemo(() => correlatedKeys(rows, hoveredKey, idx), [rows, hoveredKey, idx]);
  const onHover = (k) => setHoveredKey(k);
  const onLeave = (k) => setHoveredKey((p) => (p === k ? null : p));
  const rowProps = { selectedKey, hoveredKey, activeRels, hoverRels, onSelect, onHover, onLeave };
  return (
    <div className="obs-mid">
      <div className="obs-panel-head">
        <span>事件时间线{activeSid ? ` · ${activeSid.slice(0, 6)}` : ""}</span>
        <button className="obs-ctx-btn" onClick={onShowContext} disabled={!activeSid} title="把该会话的完整上下文展示在右侧面板">完整上下文</button>
      </div>
      <div className="obs-mid-scroll">
        {rows.map((r) => {
          if (r.kind === "group") {
            const open = openGroups.has(r.groupId);
            return (
              <div key={"g" + r.groupId} className={"obs-group" + (open ? " open" : "")} onClick={() => toggleGroup(r.groupId)}>
                <span className="obs-group-caret">▸</span>
                <span className="obs-group-label">{r.label}</span>
                <span className="obs-group-cnt">{r.children.length} 条</span>
                {open && (
                  <div className="obs-group-children">
                    {r.children.map((c) => <Row key={rowKey(c)} r={c} {...rowProps} indent />)}
                  </div>
                )}
              </div>
            );
          }
          return <Row key={rowKey(r)} r={r} {...rowProps} />;
        })}
        {!rows.length && <div className="obs-empty">{activeSid ? "该会话暂无事件" : "请先在左侧选择会话"}</div>}
      </div>
    </div>
  );
}

function Detail({ row, width, ctx }) {
  const wstyle = width ? { width: width + "px", flex: "none" } : undefined;
  // 完整上下文视图：点中间面板头部的「完整上下文」按钮进入（ctx 非空）
  if (ctx && ctx.length) {
    return (
      <div className="obs-detail" style={wstyle}>
        <div className="obs-panel-head"><span>完整上下文</span><span className="obs-ctx-cnt">{ctx.length} 条</span></div>
        <div className="obs-ctx-scroll">
          {ctx.map((c, i) => (
            <div key={i} className={"obs-ctx-block " + c.role}>
              <div className="obs-ctx-title">{c.title}</div>
              {c.text ? <pre className="obs-ctx-text">{c.text}</pre> : null}
            </div>
          ))}
        </div>
      </div>
    );
  }
  if (!row) return <div className="obs-detail" style={wstyle}><div className="obs-detail-empty">← 点击中间列表的事件查看详情</div></div>;
  const isStream = row.kind === "stream";
  const meta = isStream
    ? [["type", "llm.stream_chunk"], ["seq", `${row.seq}–${row.endSeq}`], ["chunks", String(row.count)], ["ts", row.ts]]
    : [
        ["type", row.event.type],
        ["seq", String(row.event.seq)],
        ["event_id", row.event.event_id],
        ["ts", row.event.ts],
        ["span_id", row.event.span_id || "-"],
        ["parent", row.event.parent_span_id || "-"],
      ];
  const body = isStream ? row.text : JSON.stringify(row.event.payload, null, 2);
  return (
    <div className="obs-detail" style={wstyle}>
      <div className="obs-panel-head">事件详情</div>
      <div className="obs-detail-meta">
        {meta.map(([k, v]) => (
          <div key={k}><span>{k}</span>{v}</div>
        ))}
      </div>
      <pre className="obs-detail-body">{body}</pre>
    </div>
  );
}

function Observe() {
  const [workspaces, setWorkspaces] = useState([]);
  const [activeSid, setActiveSid] = useState(null);
  const [events, setEvents] = useState([]);
  const [selectedKey, setSelectedKey] = useState(null);
  const [viewedAt, setViewedAt] = useState({}); // 客户端「查看」时间戳（sid→ms）：会话列表按最近交互倒序
  const [openWs, setOpenWs] = useState({}); // 工作区折叠状态（默认折叠，与主页面一致）
  const [openGroups, setOpenGroups] = useState(new Set()); // 子 agent 折叠分组（默认折叠成一个条目）
  const [sideWidth, setSideWidth] = useState(250); // 左面板宽度（可拖拽）
  const [detailWidth, setDetailWidth] = useState(340); // 右面板宽度（可拖拽）
  const [showCtx, setShowCtx] = useState(false); // 中间面板头部「完整上下文」按钮 → 右侧展示完整上下文

  // 与主页面一致的宽度调整器：拖拽更新面板宽度，拖动中禁用文本选择
  const startResize = (which) => (e) => {
    e.preventDefault();
    const move = (ev) => {
      if (which === "side") {
        setSideWidth(Math.min(Math.max(ev.clientX - 8, 180), 420));
      } else {
        setDetailWidth(Math.min(Math.max((window.innerWidth - 8) - ev.clientX, 240), 680));
      }
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.classList.remove("dragging");
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
    document.body.classList.add("dragging");
  };

  useEffect(() => { api.get("/api/workspaces").then(setWorkspaces); }, []);

  const selectSession = (sid) => {
    setActiveSid(sid);
    setSelectedKey(null);
    setShowCtx(false);
    setViewedAt((m) => ({ ...m, [sid]: Date.now() })); // 查看即视为最近交互
    api.get(`/api/sessions/${sid}/events`).then((evs) => setEvents(evs || []));
  };

  const toggleWs = (id) => setOpenWs((prev) => ({ ...prev, [id]: !(prev[id] === true) }));
  const collapseAll = () => setOpenWs(() => { const n = {}; workspaces.forEach((w) => (n[w.id] = false)); return n; });
  const toggleGroup = (id) => setOpenGroups((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  // 会话列表按「最近交互」倒序：新对话（updated_at）与查看（viewedAt）取较新者（与主页面一致）
  const sortedWorkspaces = useMemo(() => {
    const ts = (s) => {
      const v = viewedAt[s.id] || 0;
      const u = s.updated_at ? Date.parse(s.updated_at) : NaN;
      return Math.max(v, Number.isFinite(u) ? u : 0);
    };
    return (workspaces || []).map((w) => ({
      ...w,
      sessions: [...(w.sessions || [])].sort((a, b) => ts(b) - ts(a)),
    }));
  }, [workspaces, viewedAt]);

  const rows = useMemo(() => buildRows(events), [events]);
  const selectedRow = findRow(rows, selectedKey);
  // 「完整上下文」视图：由事件流重建的对话上下文（含 system prompt / 对话 / 工具调用）
  const ctx = useMemo(() => (showCtx ? buildContext(events) : null), [showCtx, events]);
  const selectEvent = (k) => { setSelectedKey(k); setShowCtx(false); }; // 点击事件行回到事件详情

  return (
    <div className="obs">
      <Sidebar workspaces={sortedWorkspaces} activeSid={activeSid} onSelect={selectSession} openWs={openWs} toggleWs={toggleWs} onCollapseAll={collapseAll} width={sideWidth} />
      <div className="obs-resizer" onMouseDown={startResize("side")} title="拖动调整面板宽度"><div className="grip"><span></span><span></span><span></span></div></div>
      <EventList rows={rows} selectedKey={selectedKey} onSelect={selectEvent} activeSid={activeSid} openGroups={openGroups} toggleGroup={toggleGroup} onShowContext={() => setShowCtx(true)} />
      <div className="obs-resizer" onMouseDown={startResize("detail")} title="拖动调整面板宽度"><div className="grip"><span></span><span></span><span></span></div></div>
      <Detail row={selectedRow} width={detailWidth} ctx={ctx} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Observe />);
