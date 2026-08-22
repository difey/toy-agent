/* Mira Code Web 前端（React SPA，无构建，经 Babel standalone 在浏览器编译 JSX）。
   消费与 CLI 同构的 EventStream：REST + WebSocket（last_seq 增量 + 断线重连）。 */
const { useState, useEffect, useRef, useMemo } = React;

const api = {
  get: (p) => fetch(p).then((r) => r.json()),
  post: (p, body) =>
    fetch(p, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  put: (p, body) =>
    fetch(p, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
};

// Markdown 渲染：markdown-it + DOMPurify（消毒）+ highlight.js（代码高亮）+ KaTeX（数学）
const renderMarkdown = (() => {
  if (typeof window.markdownit !== "function") return (t) => t;
  const md = window.markdownit({
    html: false,
    linkify: true,
    breaks: true,
    highlight: (str, lang) => {
      if (lang && window.hljs && window.hljs.getLanguage(lang)) {
        try {
          return (
            '<pre><code class="hljs language-' + lang + '">' +
            window.hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
            "</code></pre>"
          );
        } catch (e) { /* 语言不支持则退回纯文本 */ }
      }
      return '<pre><code class="hljs">' + md.utils.escapeHtml(str) + "</code></pre>";
    },
  });
  // 数学公式（$...$ / $$...$$），KaTeX 渲染
  if (window.texmath && window.katex) {
    try {
      md.use(window.texmath, { engine: window.katex, delimiters: "dollars", katexOptions: { throwOnError: false } });
    } catch (e) { /* 数学渲染不可用则跳过 */ }
  }
  return (text) => {
    try {
      const html = md.render(text || "");
      return window.DOMPurify ? window.DOMPurify.sanitize(html) : html;
    } catch (e) {
      return String(text || "");
    }
  };
})();

const STATUS_DOT = { running: "running", waiting: "waiting", idle: "", failed: "failed" };

const THINK_LEVELS = [
  { value: "off", label: "关" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "max", label: "Max" },
];
// models.dev 未提供枚举时 reasoning 模型的默认 effort 阶梯
const DEFAULT_EFFORTS = ["low", "medium", "high"];
const effortLabel = (v) => { const t = THINK_LEVELS.find((x) => x.value === v); return t ? t.label : v; };

const APPROVAL_MODES = [
  { value: "auto", label: "自动审批", glyph: "A" },
  { value: "ask", label: "逐条询问", glyph: "?" },
  { value: "allow_all", label: "全部通过", glyph: "!" },
];
const approvalGlyph = (v) => { const m = APPROVAL_MODES.find((x) => x.value === v); return m ? m.glyph : "A"; };

function ModelPopup({ models, model, setModel, effort, setEffort, modelInfo }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!e.target.closest(".model-popup-wrap")) setOpen(false); };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);
  const info = modelInfo ? modelInfo[model] : undefined;
  const supportsThinking = info === undefined ? true : !!info.supports_thinking;
  // 该模型支持的 effort 枚举（来自 models.dev，经 /api/config/models）；未知模型用默认阶梯
  const efforts = info && Array.isArray(info.thinking_efforts) && info.thinking_efforts.length
    ? info.thinking_efforts
    : (supportsThinking ? DEFAULT_EFFORTS : []);
  const effortOptions = [{ value: "off", label: "关" }].concat(
    efforts.map((v) => ({ value: v, label: effortLabel(v) }))
  );
  const pickModel = (m) => {
    const mi = modelInfo ? modelInfo[m] : undefined;
    const st = mi === undefined ? true : !!mi.supports_thinking;
    const allowed = mi && Array.isArray(mi.thinking_efforts) && mi.thinking_efforts.length
      ? mi.thinking_efforts
      : (st ? DEFAULT_EFFORTS : []);
    setModel(m);
    if (!st) { if (effort !== "off") setEffort("off"); }
    else if (allowed.indexOf(effort) === -1) setEffort(allowed[0]);
  };
  // 模型串 {provider}/{model}：按 provider 分组展示
  const groups = {};
  (models.length ? models : ["mock/mock-model"]).forEach((spec) => {
    const p = spec.includes("/") ? spec.split("/")[0] : "?";
    (groups[p] = groups[p] || []).push(spec);
  });
  const modelName = (spec) => (spec.includes("/") ? spec.split("/").slice(1).join("/") : spec);
  return (
    <span className="model-popup-wrap push">
      <span className="pill model" onClick={(e) => { e.stopPropagation(); setOpen(!open); }} title="模型 / 思考程度">
        <span className="mp-summary">{model}{supportsThinking ? ` · ${effortLabel(effort)}` : ""}</span>
      </span>
      {open && (
        <div className="model-popup" onClick={(e) => e.stopPropagation()}>
          <div className="mp-title">模型</div>
          <div className="mp-list">
            {Object.keys(groups).map((p) => (
              <div key={p}>
                <div style={{ fontSize: 10.5, color: "var(--text-dim)", padding: "7px 10px 2px", textTransform: "uppercase", letterSpacing: 0.4 }}>{p}</div>
                {groups[p].map((m) => (
                  <div key={m} className={"mp-item" + (m === model ? " on" : "")} onClick={() => pickModel(m)}>
                    <span className="mp-check">{m === model ? "✓" : ""}</span>
                    <span className="mp-name">{modelName(m)}</span>
                    {modelInfo && modelInfo[m] && !modelInfo[m].supports_thinking && <span className="mp-tag">无思考</span>}
                  </div>
                ))}
              </div>
            ))}
            <div className="mp-more">更多模型…</div>
          </div>
          <div className={"mp-think" + (supportsThinking ? "" : " off")}>
            <span className="mp-think-label">思考</span>
            <span className="seg">
              {effortOptions.map((lv) => (
                <button key={lv.value} className={"opt" + (effort === lv.value ? " on" : "")} onClick={() => setEffort(lv.value)} disabled={!supportsThinking}>{lv.label}</button>
              ))}
            </span>
          </div>
          {!supportsThinking && <div className="mp-hint">当前模型不支持 thinking effort，思考程度已自动设为「关」。</div>}
          <div className="mp-hint">提示：切换模型或思考程度会使已有提示词缓存失效。建议新建会话，避免额外的 token 消耗。</div>
          <div className="mp-foot">{model}{supportsThinking ? ` · ${effortLabel(effort)}` : " · 不支持思考"}</div>
        </div>
      )}
    </span>
  );
}

/* 配置中心 agent 的模型下拉选择（分组 popup，风格与聊天框一致；支持自定义输入） */
function ModelSelect({ models, model, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!e.target.closest(".model-select-wrap")) setOpen(false); };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);
  const groups = {};
  (Array.isArray(models) ? models : []).forEach((spec) => {
    const p = spec.includes("/") ? spec.split("/")[0] : "?";
    (groups[p] = groups[p] || []).push(spec);
  });
  const modelName = (spec) => (spec.includes("/") ? spec.split("/").slice(1).join("/") : spec);
  const useCustom = () => { const t = custom.trim(); if (t) { onChange(t); setCustom(""); setOpen(false); } };
  return (
    <span className="model-select-wrap">
      <button type="button" className="model-pick" onClick={(e) => { e.stopPropagation(); setOpen(!open); }} title="选择模型">
        <span className="mp-summary">{model || placeholder || "选择模型…"}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      {open && (
        <div className="model-popup" onClick={(e) => e.stopPropagation()}>
          <div className="mp-title">模型</div>
          <div className="mp-list">
            {Object.keys(groups).map((p) => (
              <div key={p}>
                <div style={{ fontSize: 10.5, color: "var(--text-dim)", padding: "7px 10px 2px", textTransform: "uppercase", letterSpacing: 0.4 }}>{p}</div>
                {groups[p].map((m) => (
                  <div key={m} className={"mp-item" + (m === model ? " on" : "")} onClick={() => { onChange(m); setOpen(false); }}>
                    <span className="mp-check">{m === model ? "✓" : ""}</span>
                    <span className="mp-name">{modelName(m)}</span>
                  </div>
                ))}
              </div>
            ))}
            {!Object.keys(groups).length && <div className="mp-empty">暂无模型（请先在 Providers 页配置）</div>}
          </div>
          <div className="mp-custom">
            <input type="text" value={custom} onChange={(e) => setCustom(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") useCustom(); }} placeholder="或输入自定义模型…" spellCheck={false} />
            <button type="button" className="btn sm" onClick={useCustom}>使用</button>
          </div>
        </div>
      )}
    </span>
  );
}

/* 事件流 → 渲染块 */
function groupEvents(events) {
  const blocks = [];
  for (const ev of events) {
    const t = ev.type, p = ev.payload;
    if (t === "user.message") blocks.push({ kind: "user", text: p.content });
    else if (t === "agent.message") {
      // 回合结束时的完整消息：若末尾已有本回合的流式块（llm.stream_chunk），
      // 直接用完整内容替换它，避免同一回复重复显示两遍。
      const last = blocks[blocks.length - 1];
      if (last && last.kind === "stream") {
        last.kind = "agent";
        last.text = p.content;
      } else {
        blocks.push({ kind: "agent", text: p.content });
      }
    }
    else if (t === "llm.stream_chunk") {
      const last = blocks[blocks.length - 1];
      if (last && last.kind === "stream") last.text += p.text;
      else blocks.push({ kind: "stream", text: p.text });
    } else if (t === "tool.call") blocks.push({ kind: "tool", name: p.name, args: p.arguments, status: "running" });
    else if (t === "tool.result" || t === "tool.error") {
      for (let i = blocks.length - 1; i >= 0; i--) {
        if (blocks[i].kind === "tool" && blocks[i].name === p.name) {
          blocks[i].status = t === "tool.result" ? "done" : "err";
          blocks[i].result = p.result || p.error || "";
          blocks[i].dur = p.duration_ms;
          break;
        }
      }
    } else if (t === "approval.requested") blocks.push({ kind: "approval", name: p.tool, args: p.arguments });
    else if (t === "error.raised") blocks.push({ kind: "error", message: p.message });
  }
  return blocks;
}

function ToolCard({ b }) {
  const [open, setOpen] = useState(false);
  const detail = JSON.stringify(b.args, null, 1) + (b.result ? "\n\n" + b.result : "");
  const summary = (b.result || "").trim().split("\n").find((line) => line.trim()) || "";
  return (
    <div className={"card tool-card" + (open ? " open" : "")}>
      <button className="head" onClick={() => setOpen((v) => !v)} title={open ? "收起工具详情" : "展开工具详情"}>
        <span className={"caret" + (open ? " open" : "")}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
        </span>
        <span className="name">{b.name}</span>
        {b.dur != null && <span>{b.dur}ms</span>}
        <span className={"stat" + (b.status === "err" ? " err" : "")}>
          {b.status === "done" ? "✓" : b.status === "err" ? "✗" : "…"}
        </span>
      </button>
      {!open && summary && <div className="summary">{summary}</div>}
      {open && <div className="body">{detail}</div>}
    </div>
  );
}

function Block({ b }) {
  if (b.kind === "user") return <div className="msg user">{b.text}</div>;
  if (b.kind === "agent" || b.kind === "stream") {
    return (
      <div className="msg agent">
        <div className="who">main</div>
        <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(b.text) }} />
      </div>
    );
  }
  if (b.kind === "tool") return <ToolCard b={b} />;
  if (b.kind === "approval") {
    let detail = "";
    try {
      if (b.args && typeof b.args === "object") {
        detail = Object.entries(b.args)
          .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
          .join(" ");
        if (detail.length > 160) detail = detail.slice(0, 160) + "…";
      }
    } catch (e) { detail = ""; }
    return <div className="approval-line">⏸ 审批请求：{b.name}{detail ? ` · ${detail}` : ""}</div>;
  }
  if (b.kind === "error") return <div className="error-line">错误: {b.message}</div>;
  return null;
}

function Sidebar({ workspaces, sessions, activeSid, onSelect, onNew, onNewInWs, view, onView,
                   onCollapse, onCollapseAll, width, openWs, toggleWs, moreOpen, setMoreOpen, onRenameWs, onDeleteWs, onArchive, archived, titles }) {
  const live = {};
  sessions.forEach((s) => (live[s.id] = s.status));
  const statusOf = (sid) => live[sid] || "idle";
  const visible = (w) => (w.sessions || []).filter((s) => !archived.has(s.id));
  return (
    <aside className="sidebar" style={{ width: width + "px" }}>
      <div className="logo">
        <span className="mark">M</span>
        <span className="name">Mira Code</span>
        <button className="new-btn" onClick={onNew} title="新建会话">＋</button>
        <button className="collapse-btn icon-btn" onClick={onCollapse} title="收起侧边栏">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
      </div>
      <div className="side-scroll">
        <div className="grp"><span>工作区</span><button className="collapse-all icon-btn" onClick={onCollapseAll} title="折叠全部工作区"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/></svg></button></div>
        {workspaces.map((w) => {
          const open = openWs[w.id] === true;  // 默认折叠（未点击过 → 折叠）
          const sids = visible(w);
          return (
            <div key={w.id}>
              <div className="ws" onClick={() => toggleWs(w.id)}>
                <span className={"caret" + (open ? " open" : "")}>
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
                </span>
                <span className="f">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                </span>
                <span className="nm">{w.id.split("_")[0]}</span>
                <span className="cnt">{sids.length}</span>
                <span className="ws-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="act icon-btn" onClick={() => onNewInWs(w)} title="在工作区创建新会话">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                  </button>
                  <span className={"act more" + (moreOpen === w.id ? " open" : "")} onClick={() => setMoreOpen(moreOpen === w.id ? null : w.id)} title="更多操作">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>
                    <span className="menu">
                      <span className="mi" onClick={() => onRenameWs(w)}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>重命名
                      </span>
                      <span className="mi danger" onClick={() => onDeleteWs(w)}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>删除工作区
                      </span>
                    </span>
                  </span>
                </span>
              </div>
              {open && (
                <div className="ws-sessions">
                  {sids.map((s) => (
                    <div key={s.id} className={"sess" + (s.id === activeSid ? " active" : "")} onClick={() => onSelect(s.id)}>
                      <span className={"dot " + STATUS_DOT[statusOf(s.id)]} />
                      <span className="t" title={s.id}>{titles[s.id] || s.id}</span>
                      <button className="archive icon-btn" onClick={(e) => { e.stopPropagation(); onArchive(s.id); }} title="归档会话">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {workspaces.length === 0 && <div className="status-line">暂无工作区</div>}
      </div>
      <div className="side-foot">
        <button className={"fbtn" + (view === "work" ? " active" : "")} onClick={() => onView("work")}>会话工作区</button>
        <button className={"fbtn" + (view === "settings" ? " active" : "")} onClick={() => { onView("settings"); onCollapse(); }}>配置中心</button>
      </div>
    </aside>
  );
}

function InputTools({ agents, agent, setAgent, approvalMode, setApprovalMode, models, model, setModel, effort, setEffort, onSend, modelInfo, running, onStop, input, insertMode, onInsert, onToggleMode, onPickFiles }) {
  return (
    <div className="input-tools">
      <button className="attach icon-btn" title="引用文件" onClick={onPickFiles}>
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
      </button>
      <span className="pill mode">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><text x="12" y="15.5" textAnchor="middle" fontSize="11" fontWeight="700" fill="currentColor" stroke="none">{approvalGlyph(approvalMode)}</text></svg>
        <select value={approvalMode} onChange={(e) => setApprovalMode(e.target.value)} title="审批层次">
          {APPROVAL_MODES.map((m) => (<option key={m.value} value={m.value}>{m.label}</option>))}
        </select>
      </span>
      <span className="pill agent">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="8" width="16" height="11" rx="2.5"/><line x1="12" y1="8" x2="12" y2="4.5"/><circle cx="12" cy="3.5" r="1.3"/><circle cx="9" cy="13" r="1.2" fill="currentColor" stroke="none"/><circle cx="15" cy="13" r="1.2" fill="currentColor" stroke="none"/></svg>
        <select value={agent} onChange={(e) => setAgent(e.target.value)} title="选择 Agent">
          {(agents.length ? agents : [{ id: "main", name: "main" }]).map((a) => (<option key={a.id} value={a.id}>{a.id}</option>))}
        </select>
      </span>
      <ModelPopup models={models} model={model} setModel={setModel} effort={effort} setEffort={setEffort} modelInfo={modelInfo} />
      <button className={"send" + (running ? " stop" : "")} onClick={running ? onStop : onSend} title={running ? "停止生成" : "发送"}>
        {running ? (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/></svg>
        ) : (
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
        )}
      </button>
      {running && onInsert && input && (
        <>
          <button className="insert" onClick={onInsert} title={insertMode === "interrupt" ? "插入（停止当前回复后优先处理）" : "排队（当前回复结束后处理）"}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>
          </button>
          <button className="insert-mode" onClick={onToggleMode} title="插入方式：插入 / 排队">
            {insertMode === "interrupt" ? "插入" : "排队"}
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </>
      )}
    </div>
  );
}

function FilePicker({ workspace, onPick, onClose }) {
  const [path, setPath] = useState("");
  const [pathInput, setPathInput] = useState(""); // 路径输入框当前值（绝对路径）
  const [entries, setEntries] = useState([]);
  const [parent, setParent] = useState(null);
  const [sel, setSel] = useState({}); // abs path -> { name, path(绝对路径) }
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = (p) => {
    setLoading(true);
    setErr("");
    api.get(`/api/fs/list?path=${encodeURIComponent(p || "")}`)
      .then((d) => {
        // api.get 对非 2xx 不 reject（返回 {detail}）：失败时保持下方文件框位置不变
        if (d && d.detail) {
          setErr("加载失败：" + d.detail);
          return;
        }
        setPath(d.path || "");
        setPathInput(d.path || "");
        setParent(d.parent ?? null);
        setEntries(d.entries || []);
      })
      .catch((e) => setErr("加载失败：" + (e && e.detail ? e.detail : e)))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    setSel({});
    load(workspace || "/"); // 起点为工作区；无则从根开始（不限制工作区）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace]);

  // 输入目录跳转：绝对路径直接跳转；相对路径相对当前目录；无效时保持下方文件框位置不变
  const go = (target) => {
    const t = (target || "").trim();
    if (!t) return;
    load(t.startsWith("/") ? t : (path ? path + "/" + t : t));
  };

  const enter = (ent) => { if (ent.type === "dir") load(ent.path); };
  const toggle = (ent) => {
    if (ent.type !== "file") return;
    const abs = ent.path; // 后端返回绝对路径
    setSel((s) => {
      const n = { ...s };
      if (n[ent.path]) delete n[ent.path];
      else n[ent.path] = { name: ent.name, path: abs };
      return n;
    });
  };
  const confirm = () => {
    const picked = Object.values(sel);
    if (picked.length) onPick(picked);
    onClose();
  };
  const selCount = Object.keys(sel).length;

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal fp" onClick={(e) => e.stopPropagation()}>
        <h3>引用文件</h3>
        <div className="fp-path">
          {parent != null && <button className="fp-up" onClick={() => load(parent)} title="返回上级">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>
            上级
          </button>}
          <input
            className="fp-crumb"
            value={pathInput}
            onChange={(e) => setPathInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") go(pathInput); }}
            placeholder="输入目录路径，如 /Users/… 或子目录名"
            spellCheck={false}
          />
          <button className="fp-go" onClick={() => go(pathInput)} title="跳转到输入的目录">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>
          </button>
        </div>
        <div className="fp-body">
          {err && <div className="fp-err">{err}</div>}
          {loading && <div className="fp-loading">加载中…</div>}
          {!loading && entries.map((ent) => (
            <div key={ent.path} className={"fp-item " + ent.type + (sel[ent.path] ? " on" : "")} onClick={() => (ent.type === "dir" ? enter(ent) : toggle(ent))}>
              <span className="fp-ico">
                {ent.type === "dir" ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                )}
              </span>
              <span className="fp-name">{ent.name}</span>
              {ent.type === "file" && sel[ent.path] && <span className="fp-check">✓</span>}
            </div>
          ))}
          {!loading && !err && !entries.length && <div className="fp-empty">（空目录）</div>}
        </div>
        <div className="fp-foot">
          <span className="fp-count">已选 {selCount} 个</span>
          <button className="btn" onClick={onClose}>取消</button>
          <button className="btn primary" onClick={confirm} disabled={!selCount}>确定</button>
        </div>
      </div>
    </div>
  );
}

function AttachChips({ attachments, onRemove }) {
  if (!attachments || !attachments.length) return null;
  return (
    <div className="chips">
      {attachments.map((a) => (
        <span key={a.path} className="chip" title={a.path}>
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
          <span className="chip-name">{a.name}</span>
          <button className="chip-x" onClick={() => onRemove(a.path)} title="移除" aria-label="移除">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </span>
      ))}
    </div>
  );
}

function ChatView({ session, title, live, events, input, setInput, send, sendKey, running, onStop, insertMode, onInsert, onToggleMode, collapsed, onExpand, agents, agent, setAgent, models, model, setModel, effort, setEffort, approvalMode, setApprovalMode, modelInfo, attachments, onRemoveAttachment, onOpenFiles }) {
  const blocks = useMemo(() => groupEvents(events), [events]);
  const msgsRef = useRef(null);
  const stickRef = useRef(true); // 贴底（自动滚动）标志：用户上滚后置 false

  // 切换会话：重置为贴底
  useEffect(() => { stickRef.current = true; }, [session && session.id]);

  // 新消息时若仍贴底则自动滚到底部
  useEffect(() => {
    const el = msgsRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [blocks]);

  const onMessagesScroll = () => {
    const el = msgsRef.current;
    if (!el) return;
    // 距底部 < 40px 视为贴底（恢复自动滚动），否则停止自动滚动
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  return (
    <>
      <div className="chat-title">
        {collapsed && <button className="expand-btn icon-btn" onClick={onExpand} title="展开侧边栏"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg></button>}
        <span>{title}</span>
      </div>
      <div className="messages" ref={msgsRef} onScroll={onMessagesScroll}>
        {blocks.map((b, i) => <Block key={i} b={b} />)}
      </div>
      <div className="input-wrap">
        <AttachChips attachments={attachments} onRemove={onRemoveAttachment} />
        <div className="inputbox">
          <textarea
            placeholder="输入消息…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (sendKey === "ctrl_enter") {
                if (e.metaKey || e.ctrlKey) { e.preventDefault(); send(); }
                else if (e.shiftKey) { /* Shift+Enter 换行 */ }
                else { e.preventDefault(); } // Enter 单独：不发送、不换行
              } else if (e.shiftKey) {
                /* Shift+Enter 换行 */
              } else {
                e.preventDefault(); send();
              }
            }}
            rows={2}
          />
          <InputTools agents={agents} agent={agent} setAgent={setAgent}
            models={models} model={model} setModel={setModel} effort={effort} setEffort={setEffort}
            approvalMode={approvalMode} setApprovalMode={setApprovalMode} onSend={send} modelInfo={modelInfo} running={running} onStop={onStop}
            input={input} insertMode={insertMode} onInsert={onInsert} onToggleMode={onToggleMode} onPickFiles={onOpenFiles} />
        </div>
        <div className="hint">{sendKey === "ctrl_enter" ? "Ctrl/Cmd+Enter 发送 · Shift+Enter 换行" : "Enter 发送 · Shift+Enter 换行"}</div>
      </div>
    </>
  );
}

function WsPicker({ workspaces, workspace, setWorkspace }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState("");
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!e.target.closest(".ns-ws-wrap")) setOpen(false); };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);
  const name = workspace ? (workspace.replace(/\/+$/, "").split("/").pop() || workspace) : "";
  const wsVal = (w) => w.path || w.id.split("_")[0];
  const pick = (w) => { setWorkspace(wsVal(w)); setOpen(false); };
  const useCustom = () => { const t = custom.trim(); if (t) { setWorkspace(t); setOpen(false); setCustom(""); } };
  return (
    <span className="ns-ws-wrap">
      <span className={"ns-ws" + (open ? " open" : "")} onClick={() => setOpen(!open)} title="选择工作区">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        <span className="ns-name">{name || "选择工作区…"}</span>
      </span>
      {open && (
        <div className="ns-ws-pop" onClick={(e) => e.stopPropagation()}>
          <div className="ns-ws-list">
            {(workspaces || []).map((w) => (
              <div key={w.id} className={"ns-ws-item" + (workspace === wsVal(w) ? " on" : "")} onClick={() => pick(w)}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <span className="ns-ws-name">{w.id.split("_")[0]}</span>
                <span className="ns-ws-path">{w.path || ""}</span>
              </div>
            ))}
            {(!workspaces || !workspaces.length) && <div className="ns-ws-empty">暂无工作区，可输入路径新建</div>}
          </div>
          <div className="ns-ws-custom">
            <input value={custom} onChange={(e) => setCustom(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") useCustom(); }} placeholder="或输入工作区路径…" />
            <button onClick={useCustom}>使用</button>
          </div>
        </div>
      )}
    </span>
  );
}

function NewSessionView({ workspaces, input, setInput, workspace, setWorkspace, sendKey, running, onStop, agents, agent, setAgent, models, model, setModel, effort, setEffort, approvalMode, setApprovalMode, collapsed, onExpand, onSubmit, modelInfo, attachments, onRemoveAttachment, onOpenFiles }) {
  return (
    <div className="new-session">
      <div className="ns-inner">
        {collapsed && <button className="expand-btn icon-btn" onClick={onExpand} title="展开侧边栏"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg></button>}
        <div className="ns-logo">M</div>
        <AttachChips attachments={attachments} onRemove={onRemoveAttachment} />
        <div className="inputbox">
          <textarea
            placeholder="输入消息…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (sendKey === "ctrl_enter") {
                if (e.metaKey || e.ctrlKey) { e.preventDefault(); onSubmit(); }
                else if (e.shiftKey) { /* Shift+Enter 换行 */ }
                else { e.preventDefault(); } // Enter 单独：不发送、不换行
              } else if (e.shiftKey) {
                /* Shift+Enter 换行 */
              } else {
                e.preventDefault(); onSubmit();
              }
            }}
            rows={2}
          />
          <InputTools agents={agents} agent={agent} setAgent={setAgent}
            models={models} model={model} setModel={setModel} effort={effort} setEffort={setEffort}
            approvalMode={approvalMode} setApprovalMode={setApprovalMode} onSend={onSubmit} modelInfo={modelInfo} running={running} onStop={onStop} onPickFiles={onOpenFiles} />
        </div>
        <div className="hint">{sendKey === "ctrl_enter" ? "Ctrl/Cmd+Enter 发送 · Shift+Enter 换行" : "Enter 发送 · Shift+Enter 换行"}</div>
        <div className="ns-extras">
          <WsPicker workspaces={workspaces} workspace={workspace} setWorkspace={setWorkspace} />
        </div>
      </div>
    </div>
  );
}

function ApprovalDialog({ req, onResolve }) {
  return (
    <div className="modal-mask">
      <div className="modal">
        <h3>工具执行需要确认</h3>
        <div className="mt">
          工具: {req.tool}
          {"\n" + JSON.stringify(req.arguments, null, 2)}
        </div>
        <div className="acts">
          <button className="btn" onClick={() => onResolve("deny")}>拒绝</button>
          <button className="btn" onClick={() => onResolve("always")}>总是允许</button>
          <button className="btn primary" onClick={() => onResolve("allow")}>允许</button>
        </div>
      </div>
    </div>
  );
}

/* ── 配置中心（决策 #10：可视化编辑 → pydantic 校验 → 写回 TOML → 热重载）── */

const Ic = ({ children, w = 14 }) => (
  <svg width={w} height={w} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
const IcoGrid = <Ic><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></Ic>;
const IcoDb = <Ic><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></Ic>;
const IcoUser = <Ic><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></Ic>;
const IcoZap = <Ic><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></Ic>;
const IcoBook = <Ic><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></Ic>;
const IcoSearch = <Ic><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.3-4.3"/></Ic>;
const IcoDiamond = <Ic><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></Ic>;
const IcoFile = <Ic><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></Ic>;

function Field({ fn, fd, children }) {
  return (
    <div className="field">
      <div className="fl"><div className="fn">{fn}</div><div className="fd">{fd}</div></div>
      <div className="fc">{children}</div>
    </div>
  );
}

function Row({ label, hint, children }) {
  return (
    <div className="row"><label>{label}</label><div className="ctrl">{children}{hint ? <div className="hint">{hint}</div> : null}</div></div>
  );
}

function Seg({ value, options, onChange }) {
  return (
    <span className="seg">
      {options.map((o) => (
        <span key={o.v} className={"opt" + (value === o.v ? " on" : "")} onClick={() => onChange(o.v)}>{o.l}</span>
      ))}
    </span>
  );
}

function Chips({ candidates, value, onChange }) {
  const toggle = (c) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <span className="chips">
      {candidates.map((c) => (
        <span key={c} className={"sel-chip" + (value.includes(c) ? " on" : "")} onClick={() => toggle(c)}>{c}</span>
      ))}
    </span>
  );
}

function RuleChips({ value, onChange }) {
  const add = () => {
    const v = window.prompt("需审批规则（tool glob），例：shell_* 或 file_write");
    if (v && v.trim() && !value.includes(v.trim())) onChange([...value, v.trim()]);
  };
  return (
    <span className="rulelist">
      {value.map((r) => (
        <span key={r} className="chip">{r}<span className="x" onClick={() => onChange(value.filter((x) => x !== r))}>×</span></span>
      ))}
      <span className="chip add" onClick={add}>+ 添加规则</span>
    </span>
  );
}

function RuleList({ value, onChange }) {
  const add = () => {
    const v = window.prompt("规则：tool → action（如 shell_* → ask）");
    if (!v) return;
    const m = v.match(/^\s*([^\s→]+)\s*→\s*(\w+)\s*$/);
    if (!m) return;
    onChange([...value, { tool: m[1], path: "**", action: m[2] }]);
  };
  const remove = (i) => onChange(value.filter((_, x) => x !== i));
  return (
    <span className="rulelist">
      {value.map((r, i) => (
        <span key={i} className="chip">{r.tool} → {r.action}<span className="x" onClick={() => remove(i)}>×</span></span>
      ))}
      <span className="chip add" onClick={add}>+ 添加规则</span>
    </span>
  );
}

function ConfigList({ items, renderRow, renderDetail, addLabel, onAdd, save }) {
  // 展开态按索引维护：编辑 ID 等可编辑字段时 key 不变 → 不会折叠 / 失焦
  const [open, setOpen] = useState({});
  const upd = (i, patch) => {
    // 由上层通过 renderDetail 的 upd 回调驱动（这里只负责展开态）
  };
  return (
    <>
      <div className="cfg-toolbar"><span className="mono cfg-tip">配置即注册：新增 / 编辑无需改代码</span><button className="btn sm primary" onClick={onAdd}>＋ {addLabel}</button></div>
      {items.map((it, i) => {
        const isOpen = !!open[i];
        return (
          <div key={i} className={"list-item" + (isOpen ? " open" : "")}>
            <div className="li-row" onClick={() => setOpen((o) => ({ ...o, [i]: !o[i] }))}>
              {renderRow(it)}
              <span className="li-caret"><Ic w={13}><polyline points="9 18 15 12 9 6"/></Ic></span>
            </div>
            {isOpen && <div className="li-detail">{renderDetail(it, (patch) => upd(i, patch), () => save())}</div>}
          </div>
        );
      })}
    </>
  );
}

function GeneralPane({ data, agents, models, onChange }) {
  const s = data.session || {};
  const ap = data.approval || {};
  const tel = data.telemetry || {};
  const agentIds = agents.map((a) => a.id);
  const set = (g, k, v) => onChange({ ...data, [g]: { ...(data[g] || {}), [k]: v } });
  return (
    <>
      <div className="src-row">来源 <span className="file">configs/mira.toml</span><span className="src-state">● 已同步</span></div>
      <div className="fgroup">
        <div className="fg-head">会话默认 <span className="fg-src">[session]</span></div>
        <div className="fg-body">
          <Field fn="默认 Agent" fd="新建会话默认使用的主 agent（配置即注册）">
            <select value={s.default_agent} onChange={(e) => set("session", "default_agent", e.target.value)}>
              {(agentIds.length ? agentIds : ["main"]).map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </Field>
          <Field fn="默认模型" fd="新建会话默认使用的模型（格式 {provider}/{model}，含 thinking 能力标注）">
            <select value={s.default_model || ""} onChange={(e) => set("session", "default_model", e.target.value)}>
              <option value="">（空）</option>
              {(models.length ? models : []).map((m) => (
                <option key={m.spec} value={m.spec}>{m.spec}{m.supports_thinking ? " · 思考" : ""}</option>
              ))}
            </select>
          </Field>
          <Field fn="最大并发会话" fd="全局并发上限，超出排队 / 拒绝（§4.2.1）">
            <input type="number" className="code" value={s.max_concurrent_sessions ?? 4} min={1} max={16} onChange={(e) => set("session", "max_concurrent_sessions", Number(e.target.value))} />
          </Field>
          <Field fn="超限排队" fd="queue_on_quota：true 排队 / false 拒绝">
            <label className="switch"><input type="checkbox" checked={!!s.queue_on_quota} onChange={(e) => set("session", "queue_on_quota", e.target.checked)} /><span className="tk" /></label>
          </Field>
          <Field fn="发送快捷键" fd="Enter 直接发送；或 Ctrl/Cmd+Enter 发送、Enter 换行">
            <Seg value={s.send_key || "enter"} options={[{ v: "enter", l: "Enter 发送" }, { v: "ctrl_enter", l: "Ctrl/Cmd+Enter" }]} onChange={(v) => set("session", "send_key", v)} />
          </Field>
        </div>
      </div>
      <div className="fgroup">
        <div className="fg-head">审批策略 <span className="fg-src">[approval]</span></div>
        <div className="fg-body">
          <Field fn="审批模式" fd="auto 自动审批 · ask 询问 · allow_all 全部通过（与输入栏盾牌联动）">
            <Seg value={ap.mode || "ask"} options={[{ v: "auto", l: "自动审批" }, { v: "ask", l: "询问" }, { v: "allow_all", l: "全部通过" }]} onChange={(v) => set("approval", "mode", v)} />
          </Field>
          <Field fn="需审批规则" fd="匹配的工具调用进入审批流（glob 匹配 tool + path）">
            <RuleChips value={ap.ask_include || []} onChange={(v) => set("approval", "ask_include", v)} />
          </Field>
        </div>
      </div>
      <div className="fgroup">
        <div className="fg-head">遥测 <span className="fg-src">[telemetry]</span></div>
        <div className="fg-body">
          <Field fn="启用遥测" fd="事件 JSONL 记录 + SQLite 索引，支撑回放与观测">
            <label className="switch"><input type="checkbox" checked={!!tel.enabled} onChange={(e) => set("telemetry", "enabled", e.target.checked)} /><span className="tk" /></label>
          </Field>
          <Field fn="指标采集间隔" fd="metric_interval_s（秒）">
            <input type="number" className="code" value={tel.metric_interval_s ?? 5} min={1} onChange={(e) => set("telemetry", "metric_interval_s", Number(e.target.value))} />
          </Field>
        </div>
      </div>
    </>
  );
}

function ProviderDetailForm({ p, setItem, del, onSave }) {
  const [pmodels, setPmodels] = useState(null);
  const [catProviders, setCatProviders] = useState([]);  // models.dev 可选供应商（经 /api/config/models）
  const [refreshing, setRefreshing] = useState(false);
  const refresh = async () => {
    setRefreshing(true);
    try {
      // 按 type 查 models.dev 目录（新供应商未保存也能显示）；type 变化自动刷新
      const r = await api.get(`/api/config/models?type=${encodeURIComponent(p.type || "openai")}`);
      setPmodels(r.models || []);
      if (r.providers) setCatProviders(r.providers);
    } finally {
      setRefreshing(false);
    }
  };
  useEffect(() => { refresh(); }, [p.type]);
  // 决策 #25 / models.dev：切换供应商时自动带出 base_url，用户只需填 api_key（已取消 env 引用设计）
  // id 即 type：切换供应商时同步更新 id 与 type，并带出 base_url（models.dev 有 api 才覆盖）
  const applyProviderMeta = (type) => {
    const pr = catProviders.find((x) => x.id === type);
    const patch = { id: type, type };
    if (pr && pr.base_url) patch.base_url = pr.base_url;
    setItem(patch);
  };
  return (
    <div className="ef">
      <Row label="provider" hint="id 即 type；每种 provider 只允许一个配置（聊天框按 {provider}/{model} 选模型）">
        <select value={p.type || "openai"} onChange={(e) => applyProviderMeta(e.target.value)}>
          <option value="mock">mock（本地可测）</option>
          {(catProviders.length ? catProviders : [{ id: "openai", name: "openai" }]).map((pr) => (
            <option key={pr.id} value={pr.id}>{pr.id}（{pr.name}）</option>
          ))}
        </select>
      </Row>
      <Row label="base_url"><input type="text" className="code" value={p.base_url || ""} onChange={(e) => setItem({ base_url: e.target.value })} placeholder="（留空 = litellm 默认端点）" /></Row>
      <Row label="api_key">
        <input type="password" className="code" value={p.api_key || ""} onChange={(e) => setItem({ api_key: e.target.value })} placeholder="（粘贴 API Key）" />
      </Row>
      <Row label="可用模型">
        <span className="mono" style={{ fontSize: 12, color: "var(--text-dim)", lineHeight: 1.7 }}>
          {(pmodels && pmodels.length)
            ? pmodels.map((m) => m.id).join(" · ")
            : "（暂无，切换供应商后自动刷新）"}
        </span>
      </Row>
      <Row label="timeout / retries">
        <input type="number" className="code" value={p.timeout_s ?? 120} min={1} onChange={(e) => setItem({ timeout_s: Number(e.target.value) })} />
        <span className="mono" style={{ fontSize: 12, color: "var(--text-dim)" }}>s</span>
        <input type="number" className="code" value={p.max_retries ?? 3} min={0} style={{ width: 60 }} onChange={(e) => setItem({ max_retries: Number(e.target.value) })} />
        <span className="mono" style={{ fontSize: 12, color: "var(--text-dim)" }}>次重试</span>
      </Row>
      <div className="ef-foot"><button className="btn sm danger" onClick={del}>删除</button><button className="btn sm primary" onClick={onSave}>保存修改</button></div>
    </div>
  );
}

function ProvidersPane({ data, onChange, save }) {
  const items = data.providers || [];
  const setItem = (i, patch) => { const arr = [...items]; arr[i] = { ...arr[i], ...patch }; onChange({ ...data, providers: arr }); };
  const addItem = () => onChange({ ...data, providers: [...items, { id: "openai", type: "openai", base_url: "", api_key: "" }] });
  const delItem = (i) => onChange({ ...data, providers: items.filter((_, x) => x !== i) });
  return (
    <>
      <div className="src-row">来源 <span className="file">configs/providers.toml</span><span className="src-state">● 已同步</span></div>
      <ConfigList items={items} addLabel="新增供应商" onAdd={addItem} save={save}
        renderRow={(p) => (
          <>
            <div className="li-ico provider">{IcoDb}</div>
            <div className="li-main">
              <div className="li-title">{p.id} {p.type === "mock" && <span className="badge meta">mock</span>}</div>
              <div className="li-sub mono">base_url: {p.base_url || "—"} · api_key: {p.api_key ? "已配置" : "未配置"}</div>
            </div>
          </>
        )}
        renderDetail={(p, upd, onSave) => (
          <ProviderDetailForm p={p} setItem={(patch) => setItem(items.indexOf(p), patch)} del={() => delItem(items.indexOf(p))} onSave={onSave} />
        )}
      />
    </>
  );
}

const TOOL_CANDIDATES = ["dispatch_task", "shell", "file_read", "file_write", "file_edit", "search_grep", "glob", "apply_patch", "todowrite", "project_memory", "web_fetch", "web_search", "git_log", "git_show", "git_status"];

function AgentsPane({ data, skills, mcpServers, onChange, save, models }) {
  const items = data.agents || [];
  const skillIds = skills.map((s) => s.id);
  const mcpIds = mcpServers.map((s) => s.id);
  const setItem = (i, patch) => { const arr = [...items]; arr[i] = { ...arr[i], ...patch }; onChange({ ...data, agents: arr }); };
  const addItem = () => onChange({ ...data, agents: [...items, { id: `agent-${Date.now().toString(36)}`, role: "sub", name: "", description: "", system_prompt: "", model: "", dispatch: "off", tools: { enabled: [] }, skills: { enabled: [] }, mcp: { enabled: [] }, permission: { rules: [] } }] });
  const delItem = (i) => onChange({ ...data, agents: items.filter((_, x) => x !== i) });
  const sub = (a) => [
    a.model || "默认模型",
    `分派:${a.dispatch || "off"}`,
    `tools: ${(a.tools?.enabled || []).join(", ") || "—"}`,
    `skills: ${(a.skills?.enabled || []).join(", ") || "—"}`,
    `mcp: ${(a.mcp?.enabled || []).join(", ") || "—"}`,
    a.report_schema ? `汇报: ${a.report_schema}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <>
      <div className="src-row">来源 <span className="file">configs/agents/*.toml</span><span className="src-state">● 已同步</span></div>
      <ConfigList items={items} addLabel="新增 Agent" onAdd={addItem} save={save}
        renderRow={(a) => (
          <>
            <div className={"li-ico " + (a.role === "main" ? "agent-main" : "agent-sub")}>{a.role === "main" ? IcoUser : IcoSearch}</div>
            <div className="li-main">
              <div className="li-title">{a.id} · {a.name || "未命名"} <span className={"badge " + (a.role === "main" ? "role-main" : "role-sub")}>{a.role === "main" ? "主" : "子"}</span></div>
              <div className="li-sub">{sub(a)}</div>
            </div>
          </>
        )}
        renderDetail={(a, upd, onSave) => (
          <div className="ef">
            <Row label="id / role">
              <input type="text" className="code" value={a.id} readOnly style={{ flex: 1 }} />
              <Seg value={a.role || "sub"} options={[{ v: "main", l: "主" }, { v: "sub", l: "子" }]} onChange={(v) => setItem(items.indexOf(a), { role: v })} />
            </Row>
            <Row label="名称"><input type="text" value={a.name || ""} onChange={(e) => setItem(items.indexOf(a), { name: e.target.value })} /></Row>
            <Row label="描述"><input type="text" value={a.description || ""} onChange={(e) => setItem(items.indexOf(a), { description: e.target.value })} /></Row>
            <Row label="system_prompt"><textarea value={a.system_prompt || ""} onChange={(e) => setItem(items.indexOf(a), { system_prompt: e.target.value })} /></Row>
            <Row label="model"><ModelSelect models={models} model={a.model || ""} onChange={(v) => setItem(items.indexOf(a), { model: v })} placeholder="默认模型" /></Row>
            <Row label="tools"><Chips candidates={TOOL_CANDIDATES} value={a.tools?.enabled || []} onChange={(v) => setItem(items.indexOf(a), { tools: { ...(a.tools || {}), enabled: v } })} /></Row>
            <Row label="skills"><Chips candidates={skillIds} value={a.skills?.enabled || []} onChange={(v) => setItem(items.indexOf(a), { skills: { ...(a.skills || {}), enabled: v } })} /></Row>
            <Row label="mcp"><Chips candidates={mcpIds} value={a.mcp?.enabled || []} onChange={(v) => setItem(items.indexOf(a), { mcp: { ...(a.mcp || {}), enabled: v } })} /></Row>
            <Row label="权限规则" hint="tool glob + path + action(allow / ask / deny)，与审批流联动。">
              <RuleList value={a.permission?.rules || []} onChange={(v) => setItem(items.indexOf(a), { permission: { ...(a.permission || {}), rules: v } })} />
            </Row>
            <div className="ef-foot"><button className="btn sm danger" onClick={() => delItem(items.indexOf(a))}>删除 agent</button><button className="btn sm primary" onClick={onSave}>保存修改</button></div>
          </div>
        )}
      />
    </>
  );
}

function McpPane({ data, onChange, save }) {
  const servers = data.mcp?.servers || [];
  const setItem = (i, patch) => { const arr = [...servers]; arr[i] = { ...arr[i], ...patch }; onChange({ ...data, mcp: { ...(data.mcp || {}), servers: arr } }); };
  const addItem = () => onChange({ ...data, mcp: { ...(data.mcp || {}), servers: [...servers, { id: `server-${Date.now().toString(36)}`, transport: "stdio", command: [], url: "" }] } });
  const delItem = (i) => onChange({ ...data, mcp: { ...(data.mcp || {}), servers: servers.filter((_, x) => x !== i) } });
  return (
    <>
      <div className="src-row">来源 <span className="file">configs/mcp.toml</span><span className="src-state">● 已同步</span></div>
      <ConfigList items={servers} addLabel="新增服务" onAdd={addItem} save={save}
        renderRow={(s) => (
          <>
            <div className="li-ico mcp">{s.transport === "http" ? IcoZap : IcoFile}</div>
            <div className="li-main">
              <div className="li-title">{s.id} <span className={"badge " + (s.transport === "http" ? "t-http" : "t-stdio")}>{s.transport}</span></div>
              <div className="li-sub mono">{s.transport === "http" ? (s.url || "—") : ((s.command || []).join(" ") || "—")}{s.auth ? ` · auth: ${s.auth}` : ""}</div>
            </div>
          </>
        )}
        renderDetail={(s, upd, onSave) => (
          <div className="ef">
            <Row label="ID"><input type="text" className="code" value={s.id} readOnly /></Row>
            <Row label="transport">
              <Seg value={s.transport || "stdio"} options={[{ v: "stdio", l: "stdio" }, { v: "http", l: "http" }]} onChange={(v) => setItem(servers.indexOf(s), { transport: v })} />
            </Row>
            {(s.transport || "stdio") === "stdio" ? (
              <Row label="command" hint="空格分隔的可执行命令（含参数）。"><input type="text" className="code" value={(s.command || []).join(" ")} onChange={(e) => setItem(servers.indexOf(s), { command: e.target.value.split(/\s+/).filter(Boolean) })} /></Row>
            ) : (
              <Row label="url"><input type="text" className="code" value={s.url || ""} onChange={(e) => setItem(servers.indexOf(s), { url: e.target.value })} /></Row>
            )}
            <Row label="auth" hint="env 引用或明文（决策 #8a）。"><input type="text" className="code" value={s.auth || ""} onChange={(e) => setItem(servers.indexOf(s), { auth: e.target.value })} /></Row>
            <div className="ef-foot"><button className="btn sm danger" onClick={() => delItem(servers.indexOf(s))}>移除服务</button><button className="btn sm primary" onClick={onSave}>保存修改</button></div>
          </div>
        )}
      />
    </>
  );
}

function SkillsPane({ data, agents, onChange, save }) {
  const items = data.skills || [];
  const setItem = (i, patch) => { const arr = [...items]; arr[i] = { ...arr[i], ...patch }; onChange({ ...data, skills: arr }); };
  const addItem = () => onChange({ ...data, skills: [...items, { id: `skill-${Date.now().toString(36)}`, name: "", description: "", prompt: "", tools: [] }] });
  const delItem = (i) => onChange({ ...data, skills: items.filter((_, x) => x !== i) });
  const usedBy = (id) => agents.filter((a) => (a.skills?.enabled || []).includes(id)).map((a) => a.id).join(", ") || "—";
  return (
    <>
      <div className="src-row">来源 <span className="file">configs/skills.toml</span><span className="src-state">● 已同步</span></div>
      <ConfigList items={items} addLabel="新增 Skill" onAdd={addItem} save={save}
        renderRow={(s) => (
          <>
            <div className="li-ico skill">{IcoBook}</div>
            <div className="li-main">
              <div className="li-title">{s.id} · {s.name || "未命名"} <span className="badge meta">{s.id}</span></div>
              <div className="li-sub">{s.description || ""} · 被启用: {usedBy(s.id)}</div>
            </div>
          </>
        )}
        renderDetail={(s, upd, onSave) => (
          <div className="ef">
            <Row label="id"><input type="text" className="code" value={s.id} readOnly /></Row>
            <Row label="名称"><input type="text" value={s.name || ""} onChange={(e) => setItem(items.indexOf(s), { name: e.target.value })} /></Row>
            <Row label="描述"><input type="text" value={s.description || ""} onChange={(e) => setItem(items.indexOf(s), { description: e.target.value })} /></Row>
            <Row label="prompt 模板"><textarea value={s.prompt || ""} onChange={(e) => setItem(items.indexOf(s), { prompt: e.target.value })} /></Row>
            <Row label="tools"><Chips candidates={TOOL_CANDIDATES} value={s.tools || []} onChange={(v) => setItem(items.indexOf(s), { tools: v })} /></Row>
            <Row label="被启用" hint="由各 agent 配置的 [agents.skills].enabled 决定。"><span className="chips"><span className="sel-chip on" style={{ cursor: "default" }}>{usedBy(s.id)}</span></span></Row>
            <div className="ef-foot"><button className="btn sm danger" onClick={() => delItem(items.indexOf(s))}>删除 skill</button><button className="btn sm primary" onClick={onSave}>保存修改</button></div>
          </div>
        )}
      />
    </>
  );
}

function SettingsView({ collapsed, onBack, onSaved }) {
  const [cfg, setCfg] = useState(null);
  const [tab, setTab] = useState("general");
  const [dirty, setDirty] = useState({});
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState(null);
  const [allModels, setAllModels] = useState([]);

  const load = () => api.get("/api/config").then(setCfg);
  useEffect(() => {
    load();
    api.get("/api/config/models").then((r) => setAllModels((r.models || []).map((x) => x.spec).filter(Boolean)));
  }, []);

  const showToast = (msg, kind = "ok") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 2200);
  };
  const mutate = (section, data) => { setCfg((c) => ({ ...c, [section]: { ...c[section], data } })); setDirty((d) => ({ ...d, [section]: true })); };

  const saveSections = async (sections) => {
    setSaving(true);
    try {
      for (const s of sections) {
        const updated = await api.put("/api/config", { section: s, data: cfg[s].data });
        if (updated && updated[s]) setCfg((c) => ({ ...c, [s]: updated[s] }));
      }
      setDirty((d) => { const n = { ...d }; sections.forEach((s) => delete n[s]); return n; });
      if (onSaved) onSaved();
      showToast("配置已保存并生效");
    } catch (e) {
      showToast("保存失败：校验未通过或写回错误", "err");
    } finally {
      setSaving(false);
    }
  };
  const dirtySections = Object.keys(dirty).filter((s) => dirty[s]);
  const dirtyCount = dirtySections.length;
  const discardAll = () => { load(); setDirty({}); };

  const tabs = [
    { id: "general", label: "General", icon: IcoGrid },
    { id: "providers", label: "Providers", icon: IcoDb },
    { id: "agents", label: "Agents", icon: IcoUser, badge: () => (cfg ? cfg.agents.data.agents.length : 0) },
    { id: "mcp", label: "MCP", icon: IcoZap },
    { id: "skills", label: "Skills", icon: IcoBook, badge: () => (cfg ? cfg.skills.data.skills.length : 0) },
  ];

  if (!cfg) return <div className="settings"><div className="set-body"><div className="set-content">加载配置…</div></div></div>;

  return (
    <div className="settings">
      <div className="set-head">
        <div className="ht">
          <h1>
            {collapsed && <button className="expand-btn icon-btn" onClick={onBack} title="返回会话面板"><Ic w={14}><polyline points="9 18 15 12 9 6"/></Ic></button>}
            配置中心
          </h1>
        </div>
        <div className="head-actions">
          <span className="reload">{dirtyCount ? `● ${dirtyCount} 项待保存` : "● 配置已加载"}</span>
          <button className="btn primary" disabled={!dirtyCount || saving} onClick={() => saveSections(dirtySections)}>{saving ? "保存中…" : "保存"}</button>
        </div>
      </div>
      <div className="set-body">
        <nav className="set-tabs">
          {tabs.map((t) => (
            <button key={t.id} className={"tab" + (tab === t.id ? " active" : "")} onClick={() => setTab(t.id)}>
              {t.icon}{t.label}
              {t.badge ? <span className="badge">{t.badge()}</span> : null}
            </button>
          ))}
        </nav>
        <div className="set-content">
          {tab === "general" && <GeneralPane data={cfg.general.data} agents={cfg.agents.data.agents} models={allModels} onChange={(d) => mutate("general", d)} />}
          {tab === "providers" && <ProvidersPane data={cfg.providers.data} onChange={(d) => mutate("providers", d)} save={() => saveSections(["providers"])} />}
          {tab === "agents" && <AgentsPane data={cfg.agents.data} skills={cfg.skills.data.skills} mcpServers={cfg.mcp.data.mcp.servers} models={allModels} onChange={(d) => mutate("agents", d)} save={() => saveSections(["agents"])} />}
          {tab === "mcp" && <McpPane data={cfg.mcp.data} onChange={(d) => mutate("mcp", d)} save={() => saveSections(["mcp"])} />}
          {tab === "skills" && <SkillsPane data={cfg.skills.data} agents={cfg.agents.data.agents} onChange={(d) => mutate("skills", d)} save={() => saveSections(["skills"])} />}
        </div>
      </div>
      {dirtyCount > 0 && (
        <div className="dirty-bar show">
          <span className="db-msg">{dirtyCount} 项未保存修改</span>
          <button className="btn" onClick={discardAll}>放弃修改</button>
          <button className="btn primary" onClick={() => saveSections(dirtySections)} disabled={saving}>校验并写回</button>
        </div>
      )}
      {toast && <div className={"toast show " + toast.kind}>{toast.msg}</div>}
    </div>
  );
}

function App() {
  const [meta, setMeta] = useState({ agents: [], providers: [] });
  const [workspaces, setWorkspaces] = useState([]);
  const [viewedAt, setViewedAt] = useState({}); // 客户端「查看」时间戳（sid→ms）：会话列表按最近交互倒序
  const [sessions, setSessions] = useState([]);
  const [activeSid, setActiveSid] = useState(null);
  const [events, setEvents] = useState([]);
  const [input, setInput] = useState("");
  const [view, setView] = useState("work");
  const [isNew, setIsNew] = useState(false);
  const [pendingApproval, setPendingApproval] = useState(null);
  const [agent, setAgent] = useState("main");
  const [workspace, setWorkspace] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(268);
  const [approvalMode, setApprovalMode] = useState("auto");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("high");
  const [models, setModels] = useState([]);
  const [modelInfo, setModelInfo] = useState({});
  const [archived, setArchived] = useState(() => new Set());
  const [openWs, setOpenWs] = useState({});
  const [moreOpen, setMoreOpen] = useState(null);
  const [sendKey, setSendKey] = useState("enter");
  const [attachments, setAttachments] = useState([]); // [{ name, path(绝对路径) }]
  const [filePick, setFilePick] = useState(false);

  const activeSidRef = useRef(null);
  const lastSeqRef = useRef(0);
  const wsRef = useRef(null);
  useEffect(() => { activeSidRef.current = activeSid; }, [activeSid]);
  const isLive = sessions.some((s) => s.id === activeSid);
  const isLiveRef = useRef(isLive);
  isLiveRef.current = isLive;

  const refreshWorkspaces = () => api.get("/api/workspaces").then(setWorkspaces);
  const refreshSessions = () => api.get("/api/sessions").then(setSessions);
  const generalRef = useRef(null); // 最近一次 /api/config 的 general.data（聊天框改审批模式时据此写回）
  const applyGeneral = (c) => {
    const g = c.general?.data || {};
    generalRef.current = g;
    setSendKey(g.session?.send_key || "enter");
    const m = g.approval?.mode || "auto";
    setApprovalMode(APPROVAL_MODES.some((x) => x.value === m) ? m : "auto");
  };
  const loadGeneral = () => api.get("/api/config").then(applyGeneral);
  // 聊天框审批盾牌 → 同步到配置中心（后端 [approval].mode），保持两处联动
  const changeApprovalMode = (v) => {
    setApprovalMode(v);
    api.get("/api/config").then((c) => {
      const g = JSON.parse(JSON.stringify(c.general?.data || { session: {}, approval: {}, telemetry: {} }));
      g.approval = { ...(g.approval || {}), mode: v };
      generalRef.current = g;
      api.put("/api/config", { section: "general", data: g });
    });
  };

  useEffect(() => {
    api.get("/api/meta").then((m) => { setMeta(m); });
    // 可用模型（模型串 {provider}/{model}），供模型弹窗 / 配置中心使用
    Promise.all([api.get("/api/config/models"), api.get("/api/config")]).then(([modelData, config]) => {
      const entries = modelData.models || [];
      const list = entries.map((x) => x.spec).filter(Boolean);
      setModels(list.length ? list : ["mock/mock-model"]);
      const map = {};
      entries.forEach((x) => (x.spec ? (map[x.spec] = x) : null));
      setModelInfo(map);
      const sessionCfg = config.general?.data?.session || {};
      const configured = sessionCfg.default_model;
      setModel((prev) => (prev ? prev : configured || list[0] || "mock/mock-model"));
      applyGeneral(config); // sendKey + 审批模式 + generalRef（与配置中心联动）
    });
    refreshWorkspaces();
    refreshSessions();
  }, []);

  useEffect(() => {
    if (!activeSid && sessions.length) {
      setActiveSid(sessions[0].id);
      setIsNew(false);
    } else if (!sessions.length && !isNew) {
      setIsNew(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.length]);

  const selectSession = (sid) => {
    activeSidRef.current = sid;
    setActiveSid(sid);
    setViewedAt((m) => ({ ...m, [sid]: Date.now() })); // 查看即视为最近交互
    setIsNew(false);
    setEvents([]);
    lastSeqRef.current = 0;
    api.get(`/api/sessions/${sid}/events`).then((evs) => {
      setEvents((prev) => {
        const bySeq = new Map(prev.map((event) => [event.seq, event]));
        evs.forEach((event) => bySeq.set(event.seq, event));
        return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
      });
      lastSeqRef.current = Math.max(
        lastSeqRef.current,
        evs.length ? evs[evs.length - 1].seq : 0
      );
    });
  };

  useEffect(() => {
    if (!activeSid) return;
    let closed = false, retries = 0;
    const connect = () => {
      if (closed) return;
      if (!isLiveRef.current) { closed = true; return; } // 历史会话只读，不订阅
      const ws = new WebSocket(`ws://${location.host}/api/ws/sessions/${activeSid}`);
      wsRef.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ last_seq: lastSeqRef.current }));
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data);
        lastSeqRef.current = Math.max(lastSeqRef.current, ev.seq);
        setEvents((prev) => [...prev, ev]);
        // 新消息/回复/工具结果等实时交互 → 该会话视为最近交互（置顶）
        if (["user.message", "agent.message", "tool.result", "tool.error", "session.status", "session.titled"].indexOf(ev.type) !== -1) {
          setViewedAt((m) => ({ ...m, [activeSid]: Date.now() }));
        }
        if (ev.type === "approval.requested") setPendingApproval(ev.payload);
        if (ev.type === "approval.resolved") setPendingApproval(null);
        if (ev.type === "session.status" || ev.type === "session.titled") { refreshSessions(); refreshWorkspaces(); }
      };
      ws.onclose = () => {
        if (!closed && retries < 5 && activeSidRef.current === activeSid) {
          retries += 1;
          setTimeout(connect, 1000);
        }
      };
    };
    connect();
    return () => { closed = true; if (wsRef.current) wsRef.current.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSid, isLive]);

  const attPaths = () => attachments.map((a) => a.path);
  const openFilePicker = () => setFilePick(true);
  const onPickFiles = (picked) => {
    setAttachments((prev) => {
      const exist = new Set(prev.map((a) => a.path));
      const merged = [...prev];
      picked.forEach((a) => { if (!exist.has(a.path)) { merged.push(a); exist.add(a.path); } });
      return merged;
    });
  };
  const removeAttachment = (path) => setAttachments((prev) => prev.filter((a) => a.path !== path));

  const send = () => {
    const text = input.trim();
    if (!text || !activeSid) return;
    const atts = attPaths();
    api.post(`/api/sessions/${activeSid}/messages`, { content: text, effort, model, attachments: atts }).then(() => {
      refreshSessions();
      refreshWorkspaces();
    });
    setInput("");
    if (atts.length) setAttachments([]);
  };
  const running = !!activeSid && sessions.some((s) => s.id === activeSid && (s.status === "running" || s.status === "waiting"));
  const stop = () => { if (!activeSid) return; api.post(`/api/sessions/${activeSid}/stop`); };
  const [insertMode, setInsertMode] = useState("interrupt");
  const onInsert = () => {
    const text = input.trim();
    if (!text || !activeSid) return;
    const atts = attPaths();
    api.post(`/api/sessions/${activeSid}/insert`, { content: text, effort, model, interrupt: insertMode === "interrupt", attachments: atts }).then(() => { refreshSessions(); refreshWorkspaces(); });
    setInput("");
    if (atts.length) setAttachments([]);
  };
  const onToggleMode = () => setInsertMode((m) => (m === "interrupt" ? "queue" : "interrupt"));

  const createAndSend = () => {
    const wsPath = workspace.trim();
    if (!wsPath) return;
    const atts = attPaths();
    api.post("/api/sessions", { workspace: wsPath, agent_type: agent, model }).then((s) => {
      if (!s.id) return;
      setIsNew(false);
      refreshWorkspaces();
      refreshSessions();
      setActiveSid(s.id);
      api.get(`/api/sessions/${s.id}/events`).then((evs) => { setEvents(evs); lastSeqRef.current = evs.length ? evs[evs.length - 1].seq : 0; });
      if (input.trim()) {
        api.post(`/api/sessions/${s.id}/messages`, { content: input, effort, model, attachments: atts });
        setInput("");
        if (atts.length) setAttachments([]);
      }
    });
  };

  const openNewForWs = (w) => {
    if (w.path) setWorkspace(w.path);
    setIsNew(true);
  };

  const startResize = (e) => {
    e.preventDefault();
    const move = (ev) => setSidebarWidth(Math.min(Math.max(ev.clientX - 8, 180), 420));
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
      document.body.classList.remove("dragging");
    };
    document.body.classList.add("dragging");
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const onArchive = (sid) => setArchived((prev) => { const n = new Set(prev); n.add(sid); return n; });
  const toggleWs = (id) => setOpenWs((prev) => ({ ...prev, [id]: !(prev[id] === true) }));
  const collapseAll = () => setOpenWs(() => { const n = {}; workspaces.forEach((w) => (n[w.id] = false)); return n; });
  const onRenameWs = (w) => {
    setMoreOpen(null);
    const name = window.prompt("重命名工作区", w.id.split("_")[0]);
    if (name && name.trim()) api.post(`/api/workspaces/${w.id}/rename`, { name: name.trim() }).then(refreshWorkspaces);
  };
  const onDeleteWs = (w) => {
    setMoreOpen(null);
    if (window.confirm(`删除工作区 ${w.id}？其下所有 session 数据将被移除。`)) {
      fetch(`/api/workspaces/${w.id}`, { method: "DELETE" }).then(refreshWorkspaces);
    }
  };
  const expand = () => setCollapsed(false);
  // 从配置中心返回会话工作区：展开侧边栏并切换右面板为会话面板
  const backToSessions = () => { setCollapsed(false); setView("work"); };

  // 三点菜单：点击空白处自动关闭
  useEffect(() => {
    if (!moreOpen) return;
    const close = (e) => { if (!e.target.closest(".act.more")) setMoreOpen(null); };
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [moreOpen]);

  const resolveApproval = (decision) => {
    if (!pendingApproval || !activeSid) return;
    api.post(`/api/sessions/${activeSid}/approvals/${pendingApproval.request_id}`, { decision });
    setPendingApproval(null);
  };

  const activeSession = useMemo(() => {
    if (!activeSid) return null;
    const live = sessions.find((s) => s.id === activeSid);
    if (live) return live;
    // 历史会话：从 session.created 事件推导显示信息（只读）
    const sc = events.find((e) => e.type === "session.created");
    return {
      id: activeSid,
      workspace: (sc && sc.payload.workspace) || "",
      agent_type: (sc && sc.payload.agent) || "?",
      model: (sc && sc.payload.model) || "?",
      status: "history",
    };
  }, [activeSid, sessions, events]);

  const titles = useMemo(() => {
    const m = {};
    workspaces.forEach((w) => (w.sessions || []).forEach((s) => { m[s.id] = s.title || ""; }));
    return m;
  }, [workspaces]);
  // 会话列表按「最近交互」倒序：新对话（updated_at）与查看（viewedAt）取较新者
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
  const activeTitle = activeSession ? (activeSession.title || titles[activeSid] || activeSid) : "";
  // 文件选择器起点：解析当前会话的真实工作区路径（历史会话事件里存的是 workspace id，需映射回 path）
  const pickWs = (() => {
    if (!activeSession) return workspace;
    const raw = activeSession.workspace || "";
    if (raw.includes("/")) return raw; // 已是绝对路径
    const hit = (workspaces || []).find((w) => w.id === raw);
    return (hit && hit.path) || raw;
  })();

  return (
    <div className="app">
      {!collapsed && (
        <>
          <Sidebar
            workspaces={sortedWorkspaces} sessions={sessions} activeSid={activeSid}
            onSelect={selectSession} onNew={() => setIsNew(true)} onNewInWs={openNewForWs}
            view={view} onView={setView} onCollapse={() => setCollapsed(true)} onCollapseAll={collapseAll} width={sidebarWidth}
            openWs={openWs} toggleWs={toggleWs} moreOpen={moreOpen} setMoreOpen={setMoreOpen}
            onRenameWs={onRenameWs} onDeleteWs={onDeleteWs} onArchive={onArchive} archived={archived} titles={titles}
          />
          <div className="resizer" style={{ left: `${sidebarWidth + 2}px` }} onMouseDown={startResize} title="拖动调整面板宽度">
            <span className="grip"><span /><span /><span /></span>
          </div>
        </>
      )}
      <main className="main">
        {view === "settings" ? (
          <SettingsView collapsed={collapsed} onBack={backToSessions} onSaved={loadGeneral} />
        ) : isNew || !activeSession ? (
          <NewSessionView
            workspaces={workspaces} input={input} setInput={setInput} workspace={workspace} setWorkspace={setWorkspace} sendKey={sendKey} running={running} onStop={stop}
            agents={meta.agents} agent={agent} setAgent={setAgent}
            models={models} model={model} setModel={setModel} effort={effort} setEffort={setEffort}
            approvalMode={approvalMode} setApprovalMode={changeApprovalMode} modelInfo={modelInfo}
            collapsed={collapsed} onExpand={expand} onSubmit={createAndSend}
            attachments={attachments} onRemoveAttachment={removeAttachment} onOpenFiles={openFilePicker}
          />
        ) : (
          <ChatView
            session={activeSession} title={activeTitle} live={isLive} events={events} input={input} setInput={setInput} send={send} sendKey={sendKey} running={running} onStop={stop}
            insertMode={insertMode} onInsert={onInsert} onToggleMode={onToggleMode}
            agents={meta.agents} agent={agent} setAgent={setAgent}
            models={models} model={model} setModel={setModel} effort={effort} setEffort={setEffort}
            approvalMode={approvalMode} setApprovalMode={changeApprovalMode} modelInfo={modelInfo}
            collapsed={collapsed} onExpand={expand}
            attachments={attachments} onRemoveAttachment={removeAttachment} onOpenFiles={openFilePicker}
          />
        )}
      </main>
      {pendingApproval && <ApprovalDialog req={pendingApproval} onResolve={resolveApproval} />}
      {filePick && (
        <FilePicker
          workspace={pickWs}
          onPick={onPickFiles}
          onClose={() => setFilePick(false)}
        />
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
