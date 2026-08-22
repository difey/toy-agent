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
    case "tool.call": return `${p.name} action=${p.action}`;
    case "tool.result": return `${p.name} ${(p.result || "").slice(0, 60)}`;
    case "tool.error": return `${p.name} ✗ ${(p.error || "").slice(0, 60)}`;
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

// 事件列表 → 展示行：把连续的 llm.stream_chunk 合并成一行（避免刷屏）
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
  return rows;
}

const rowKey = (r) => (r.kind === "stream" ? "s" + r.seq : "e" + r.event.seq);
const category = (t) => (t || "?").split(".")[0];
const rowType = (r) => (r.kind === "stream" ? r.type : r.event.type);
const rowTs = (r) => (r.kind === "stream" ? r.ts : r.event.ts) || "";

function Sidebar({ workspaces, activeSid, onSelect, openWs, toggleWs, onCollapseAll }) {
  return (
    <aside className="obs-side">
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

function EventList({ rows, selectedKey, onSelect, activeSid }) {
  return (
    <div className="obs-mid">
      <div className="obs-panel-head">事件时间线{activeSid ? ` · ${activeSid.slice(0, 6)}` : ""}</div>
      <div className="obs-mid-scroll">
        {rows.map((r) => {
          const key = rowKey(r);
          return (
            <div key={key} className={"obs-row" + (key === selectedKey ? " active" : "")} onClick={() => onSelect(key)}>
              <span className="obs-row-seq">{r.kind === "stream" ? `${r.seq}–${r.endSeq}` : r.event.seq}</span>
              <span className={"obs-row-type t-" + category(rowType(r))}>{rowType(r)}</span>
              <span className="obs-row-brief">
                {r.kind === "stream" ? `×${r.count} · ${r.text.slice(0, 50)}` : brief(r.event)}
              </span>
              <span className="obs-row-time">{rowTs(r).slice(11, 19)}</span>
            </div>
          );
        })}
        {!rows.length && <div className="obs-empty">{activeSid ? "该会话暂无事件" : "请先在左侧选择会话"}</div>}
      </div>
    </div>
  );
}

function Detail({ row }) {
  if (!row) return <div className="obs-detail"><div className="obs-detail-empty">← 点击中间列表的事件查看详情</div></div>;
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
    <div className="obs-detail">
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

  useEffect(() => { api.get("/api/workspaces").then(setWorkspaces); }, []);

  const selectSession = (sid) => {
    setActiveSid(sid);
    setSelectedKey(null);
    setViewedAt((m) => ({ ...m, [sid]: Date.now() })); // 查看即视为最近交互
    api.get(`/api/sessions/${sid}/events`).then((evs) => setEvents(evs || []));
  };

  const toggleWs = (id) => setOpenWs((prev) => ({ ...prev, [id]: !(prev[id] === true) }));
  const collapseAll = () => setOpenWs(() => { const n = {}; workspaces.forEach((w) => (n[w.id] = false)); return n; });

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
  const selectedRow = rows.find((r) => rowKey(r) === selectedKey) || null;

  return (
    <div className="obs">
      <Sidebar workspaces={sortedWorkspaces} activeSid={activeSid} onSelect={selectSession} openWs={openWs} toggleWs={toggleWs} onCollapseAll={collapseAll} />
      <EventList rows={rows} selectedKey={selectedKey} onSelect={setSelectedKey} activeSid={activeSid} />
      <Detail row={selectedRow} />
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Observe />);
