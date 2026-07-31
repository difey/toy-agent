import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { api } from '../../shared/api';
import { renderMarkdown } from '../../shared/markdown';
import { DiffOverviewBubble } from './bubble/DiffOverviewBubble';
import { SystemPromptBubble } from './bubble/SystemPromptBubble';
import { ThinkingBubble } from './bubble/ThinkingBubble';
import { ModelSelector } from './components/ModelSelector';
import { PermissionOverlay } from './components/PermissionOverlay';
import { ProviderSettingsDialog } from './components/ProviderSettingsDialog';
import { QuestionOverlay } from './components/QuestionOverlay';
import { SessionGroup } from './components/SessionGroup';
import { SubAgentEventCard } from './components/SubAgentEventCard';
import { Toast } from './components/Toast';
import { useChatData } from './hooks/useChatData';
import { useChatPanelResizers } from './hooks/useChatPanelResizers';
import { useChatQuestionPermission } from './hooks/useChatQuestionPermission';
import { useChatSessionActions } from './hooks/useChatSessionActions';
import { useChatStreaming } from './hooks/useChatStreaming';
import { useChatTheme } from './hooks/useChatTheme';
import {
  buildMessageSegments,
  buildModifiedFileTree,
  collectFolderPaths,
  formatModifiedTimestamp,
  formatMsgTimestamp,
  groupSessions,
  truncate,
  type FileTreeNode,
} from './utils/chatHelpers';
import type {
  ChatMessage,
  CurrentInfo,
  DiffSummary,
  Mode,
  SessionSummary,
  SubAgentFlow,
} from '../../shared/types';

const BYTES_IN_KIBIBYTE = 1024;
const TREE_INDENT_PER_LEVEL = 16;
const TREE_FOLDER_BASE_INDENT = 12;
const TREE_FILE_BASE_INDENT = 36;

export function ChatApp() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputText, setInputText] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sessionTitle, setSessionTitle] = useState('nanoClaude');
  const [mode, setMode] = useState<Mode>('build');
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({});
  const [toast, setToast] = useState({ visible: false, message: '' });
  const [collapsedCards, setCollapsedCards] = useState<Record<number, boolean>>({});
  const [collapsedThinkingSections, setCollapsedThinkingSections] = useState<Record<string, boolean>>({});
  const [subAgentFlows, setSubAgentFlows] = useState<Record<string, SubAgentFlow>>({});
  const [delegateFlowMap, setDelegateFlowMap] = useState<Record<number, string>>({});
  const [showProviderDialog, setShowProviderDialog] = useState(false);
  const [activeModel, setActiveModel] = useState<string | null | undefined>(null);
  const [activeProvider, setActiveProvider] = useState<string | null | undefined>(null);

  const messagesRef = useRef(messages);
  const delegateFlowCounterRef = useRef(0);
  const toastTimerRef = useRef<number | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const mainPanelRef = useRef<HTMLDivElement | null>(null);
  const chatHeaderRef = useRef<HTMLDivElement | null>(null);
  const streamingIndicatorRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const customInputRef = useRef<HTMLTextAreaElement | null>(null);
  const newSessionRef = useRef<() => Promise<void>>(async () => {});
  const workspacePanelRef = useRef<HTMLElement | null>(null);

  const { darkMode, toggleTheme } = useChatTheme();

  const {
    activeQuestion,
    questionAnswers,
    customAnswer,
    activePermission,
    setCustomAnswer,
    toggleQuestionOption,
    selectCustomOption,
    submitQuestion,
    cancelQuestion,
    permissionDeny,
    permissionAllow,
    permissionAlwaysAllow,
    enqueueQuestion,
    receivePermissionRequest,
    clearAfterStreamDone,
    resetInteractionState,
  } = useChatQuestionPermission({ customInputRef });

  const {
    sidebarWidth,
    workspaceWidth,
    planDocsHeight,
    inputAreaHeight,
    isResizing,
    isWorkspaceResizing,
    isPlanDocsResizing,
    isInputAreaResizing,
    handleResizeStart,
    handleWorkspaceResizeStart,
    handlePlanDocsResizeStart,
    handleInputAreaResizeStart,
    resetSidebarWidth,
    resetWorkspaceWidth,
    resetPlanDocsHeight,
    resetInputAreaHeight,
  } = useChatPanelResizers({
    mainPanelRef,
    chatHeaderRef,
    streamingIndicatorRef,
    workspacePanelRef,
    isStreaming,
  });

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // 回复过程中允许输入框与发送按钮继续可用，用于提交额外说明；
  // 仅在弹出问题/权限对话框时禁用。
  const isInputDisabled = activeQuestion !== null || activePermission !== null;

  const commitMessages = useCallback((updater: (prev: ChatMessage[]) => ChatMessage[]) => {
    setMessages((prev) => {
      const next = updater(prev);
      messagesRef.current = next;
      return next;
    });
  }, []);

  const showToast = useCallback((message: string, timeout = 4000) => {
    setToast({ visible: true, message });
    if (toastTimerRef.current !== null) {
      window.clearTimeout(toastTimerRef.current);
    }
    toastTimerRef.current = window.setTimeout(() => {
      setToast((prev) => ({ ...prev, visible: false }));
    }, timeout);
  }, []);

  const scheduleScrollBottom = useCallback(() => {
    window.requestAnimationFrame(() => {
      const container = chatContainerRef.current;
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    });
  }, []);

  const resetFlowState = useCallback(() => {
    setSubAgentFlows({});
    setDelegateFlowMap({});
    setCollapsedThinkingSections({});
    delegateFlowCounterRef.current = 0;
  }, []);

  const handleModelChanged = useCallback(async () => {
    // Reload current info to get updated active_model/active_provider
    try {
      const current = await api<CurrentInfo>('GET', '/api/current');
      setActiveModel(current.app.active_model);
      setActiveProvider(current.app.active_provider);
    } catch {
      // ignore
    }
  }, []);

  const {
    sessions,
    planDocs,
    modifiedFiles,
    isRefreshing,
    activeDiff,
    activeDiffFiles,
    setActiveDiff,
    setDiffFilePaths,
    setActiveDiffFiles,
    refreshWorkspace,
    loadCurrent,
    applyCurrentView,
  } = useChatData({
    commitMessages,
    resetFlowState,
    scheduleScrollBottom,
    showToast,
    setMode,
    setSessionTitle,
    setCollapsedCards,
  });

  const openPlanDoc = useCallback((filename?: string | null) => {
    const url = filename ? `/plan-view?filename=${encodeURIComponent(filename)}` : '/plan-view';
    window.open(url, '_blank');
  }, []);

  const toggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => ({ ...prev, [path]: !prev[path] }));
  }, []);

  const openVSCode = useCallback(async () => {
    try {
      await api('POST', '/api/vscode');
      showToast('Opened in VS Code');
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to open VS Code');
    }
  }, [showToast]);

  const toggleMode = useCallback(async () => {
    if (isStreaming) {
      return;
    }

    const nextMode: Mode = mode === 'plan' ? 'build' : 'plan';
    try {
      const result = await api<{ mode: Mode; current: CurrentInfo }>('POST', '/api/mode', { mode: nextMode });
      setMode(result.mode);
      if (result.current) {
        applyCurrentView(result.current);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch mode');
    }
  }, [applyCurrentView, isStreaming, mode, showToast]);

  const toggleCard = useCallback((index: number) => {
    setCollapsedCards((prev) => {
      const current = prev[index];
      return { ...prev, [index]: current === undefined ? false : !current };
    });
  }, []);

  const toggleThinkingSection = useCallback((key: string) => {
    setCollapsedThinkingSections((prev) => ({
      ...prev,
      [key]: prev[key] === undefined ? false : !prev[key],
    }));
  }, []);

  const {
    newSession,
    switchSession,
    deleteSession,
    forkAtMessage,
    rollbackAtMessage,
  } = useChatSessionActions({
    isStreaming,
    setActiveDiff,
    setDiffFilePaths,
    applyCurrentView,
    scheduleScrollBottom,
    showToast,
    resetInteractionState,
    resetFlowState,
    setSidebarOpen,
  });

  const toggleSubAgentFlow = useCallback((flowId: string | null) => {
    if (!flowId) {
      return;
    }
    setSubAgentFlows((prev) => {
      const flow = prev[flowId];
      if (!flow) {
        return prev;
      }
      return {
        ...prev,
        [flowId]: {
          ...flow,
          visible: !flow.visible,
        },
      };
    });
  }, []);

  const updateLastAssistantMessage = useCallback((updater: (message: ChatMessage) => ChatMessage | null) => {
    commitMessages((prev) => {
      if (prev.length === 0) {
        return prev;
      }
      const next = [...prev];
      const last = next[next.length - 1];
      if (last.role === 'assistant' && last.type === 'text') {
        const updated = updater(last);
        if (updated === null) {
          next.pop();
        } else {
          next[next.length - 1] = updated;
        }
      }
      return next;
    });
  }, [commitMessages]);

  const {
    startChatStream,
    stopResponse,
    sendFollowup,
    closeEventSource,
  } = useChatStreaming({
    commitMessages,
    messagesRef,
    delegateFlowCounterRef,
    setCollapsedCards,
    setDelegateFlowMap,
    setSubAgentFlows,
    setInputText,
    setIsStreaming,
    setSessionTitle,
    applyCurrentView,
    resetFlowState,
    scheduleScrollBottom,
    enqueueQuestion,
    receivePermissionRequest,
    clearAfterStreamDone,
    loadCurrent,
    updateLastAssistantMessage,
    showToast,
  });

  const sendMessage = useCallback(async () => {
    const text = inputText.trim();
    if (!text) {
      return;
    }
    if (isStreaming) {
      // 回复过程中发送的为额外说明：先本地暂存显示，再提交给后端队列。
      commitMessages((prev) => [...prev, {
        role: 'user',
        type: 'text',
        content: text,
        pending: true,
      }]);
      setInputText('');
      scheduleScrollBottom();
      await sendFollowup(text);
      return;
    }
    await startChatStream(text);
  }, [commitMessages, inputText, isStreaming, scheduleScrollBottom, sendFollowup, setInputText, startChatStream]);

  const executePlan = useCallback(async (_planFilename: string) => {
    if (isStreaming) return;

    try {
      const modeResult = await api<{ mode: Mode }>('POST', '/api/mode', { mode: 'build' });
      setMode(modeResult.mode);
      await loadCurrent();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch mode');
      return;
    }

    await startChatStream('请执行当前plan');
  }, [isStreaming, loadCurrent, showToast, startChatStream]);

  const handleInputKeydown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void sendMessage();
    }
  }, [sendMessage]);

  useEffect(() => {
    newSessionRef.current = newSession;
  }, [newSession]);

  // Mount-only bootstrap. `newSession` is intentionally accessed via a ref
  // instead of being listed as a dependency: its identity changes whenever
  // `isStreaming` toggles, which previously caused this effect to tear down
  // and re-run on every AI turn (closing the SSE connection and reloading
  // messages from the last saved session), producing a visible flicker and
  // dropping the just-sent user message until the turn finished.
  useEffect(() => {
    void loadCurrent();
    void handleModelChanged();

    const handleGlobalKeydown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && (event.key === 'k' || event.key === 'n')) {
        event.preventDefault();
        void newSessionRef.current();
      }
    };

    document.addEventListener('keydown', handleGlobalKeydown);
    return () => {
      document.removeEventListener('keydown', handleGlobalKeydown);
      closeEventSource();
      if (toastTimerRef.current !== null) {
        window.clearTimeout(toastTimerRef.current);
      }
    };
  }, [closeEventSource, handleModelChanged, loadCurrent]);

  useEffect(() => {
    scheduleScrollBottom();
  }, [messages, subAgentFlows, isStreaming, activeQuestion, activePermission, scheduleScrollBottom]);

  const flowEntries = useMemo(() => Object.entries(subAgentFlows), [subAgentFlows]);
  const segments = useMemo(() => buildMessageSegments(messages), [messages]);

  const filteredFiles = useMemo(() => {
    if (!activeDiff) {
      return modifiedFiles;
    }
    return activeDiffFiles;
  }, [modifiedFiles, activeDiff, activeDiffFiles]);
  const modifiedFileTree = useMemo(() => buildModifiedFileTree(filteredFiles), [filteredFiles]);

  const unexecutedPlans = useMemo(() => {
    return planDocs
      .filter((doc) => doc.filename.endsWith('.md') && !doc.filename.endsWith('.md.resolved'))
      .sort((a, b) => b.modified - a.modified);
  }, [planDocs]);

  const latestUnexecutedPlan = unexecutedPlans[0] ?? null;
  const showBuildButton = mode === 'plan' && latestUnexecutedPlan !== null && inputText.trim() === '' && !isStreaming;

  useEffect(() => {
    setExpandedFolders((prev) => {
      const next = { ...prev };
      for (const path of collectFolderPaths(modifiedFileTree)) {
        if (!(path in next)) {
          next[path] = true;
        }
      }
      return next;
    });
  }, [modifiedFileTree]);

  const renderTreeNodes = useCallback((nodes: FileTreeNode[], depth = 0): ReactNode => (
    nodes.map((node) => {
      if (node.type === 'folder') {
        const expanded = expandedFolders[node.path] ?? true;
        return (
          <div key={node.path}>
            <button
              className="workspace-tree-row workspace-tree-folder"
              style={{ paddingLeft: TREE_FOLDER_BASE_INDENT + depth * TREE_INDENT_PER_LEVEL }}
              onClick={() => toggleFolder(node.path)}
              type="button"
            >
              <span className="workspace-tree-caret">{expanded ? '▾' : '▸'}</span>
              <span className="workspace-tree-icon">📁</span>
              <span className="workspace-tree-name">{node.name}</span>
            </button>
            {expanded ? renderTreeNodes(node.children ?? [], depth + 1) : null}
          </div>
        );
      }

      return (
        <div
          key={node.path}
          className="workspace-tree-row workspace-tree-file"
          style={{ paddingLeft: TREE_FILE_BASE_INDENT + depth * TREE_INDENT_PER_LEVEL }}
        >
          <span className="workspace-tree-icon">📄</span>
          <span className="workspace-tree-name">{node.name}</span>
          <span className="workspace-tree-status">{node.status}</span>
        </div>
      );
    })
  ), [expandedFolders, toggleFolder]);


  const renderMessageNode = useCallback(
    (message: ChatMessage, index: number): ReactNode => {
      const flowId = delegateFlowMap[index] || null;
      const flowVisible = flowId ? subAgentFlows[flowId]?.visible : false;

      return (
        <div key={`${message.role}-${message.type}-${index}`} className={`msg ${message.role || 'assistant'}`}>
          {message.role === 'user' && message.type === 'text' ? (
            <div className="bubble-wrapper">
              <div className="bubble">
                <div className="msg-timestamp">
                  {formatMsgTimestamp(message.timestamp)}
                  {message.pending ? <span className="pending-badge">⏳ 已提交</span> : null}
                </div>
                {message.content}
              </div>
              <button
                className="rollback-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  void rollbackAtMessage(index);
                }}
                title="Rollback to this point"
                disabled={isStreaming}
              >
                ↩
              </button>
              <button
                className="fork-btn"
                onClick={(event) => {
                  event.stopPropagation();
                  void forkAtMessage(index);
                }}
                title="Fork conversation from this point"
                disabled={isStreaming}
              >
                ⤴
              </button>
            </div>
          ) : null}

          {message.role === 'assistant' && message.type === 'text' ? (
            <div className="bubble">
              <div className="msg-timestamp">{formatMsgTimestamp(message.timestamp)}</div>
              <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
            </div>
          ) : null}

          {message.role === 'system' && message.type === 'system' ? (
            <SystemPromptBubble content={message.content} />
          ) : null}

          {message.type === 'tool_start' ? (
            <div className="tool-card args">
              <div className="tool-card-header" onClick={() => toggleCard(index)}>
                <span className="collapse-arrow">{collapsedCards[index] !== false ? '▸' : '▾'}</span>
                <span className="badge run">▶ {message.name}</span>
                <span style={{ color: 'var(--text-dim)' }}>tool call</span>
                <span className="msg-timestamp" style={{ marginLeft: 'auto', marginRight: 8 }}>{formatMsgTimestamp(message.timestamp)}</span>
              </div>
              {collapsedCards[index] !== false ? null : (
                <div className="tool-card-body">{JSON.stringify(message.arguments ?? {}, null, 2)}</div>
              )}
            </div>
          ) : null}

          {message.type === 'tool_result' ? (
            <div className="tool-card result">
              <div className="tool-card-header" onClick={() => toggleCard(index)}>
                <span className="collapse-arrow">{collapsedCards[index] !== false ? '▸' : '▾'}</span>
                <span className="badge done">✔ {message.name || message.title || 'done'}</span>
                <span style={{ color: 'var(--text-dim)' }}>result</span>
                <span className="msg-timestamp" style={{ marginLeft: 'auto', marginRight: 8 }}>{formatMsgTimestamp(message.timestamp)}</span>
                {message.name === 'delegate' ? (
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSubAgentFlow(flowId);
                    }}
                    style={{
                      marginLeft: 'auto',
                      background: 'none',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      color: flowVisible ? 'var(--accent)' : 'var(--text-dim)',
                      borderColor: flowVisible ? 'var(--accent)' : 'var(--border)',
                      cursor: 'pointer',
                      fontSize: 11,
                      padding: '2px 8px',
                      transition: 'all 0.12s',
                      whiteSpace: 'nowrap',
                    }}
                    title={flowVisible ? 'Hide sub-agent execution flow' : 'Show sub-agent execution flow'}
                  >
                    {flowVisible ? '▲ Hide Agents' : '▼ Show Agents'}
                  </button>
                ) : null}
              </div>
              {collapsedCards[index] !== false ? null : (
                <div className="tool-card-body">{truncate(message.content || '', 2000)}</div>
              )}
            </div>
          ) : null}

          {message.type === 'diff_summary' ? (
            <DiffOverviewBubble
              summary={{
                checkpoint_filename: message.checkpoint_filename ?? '',
                summary: message.summary ?? { files_changed: 0, files: [] },
              }}
              isActive={activeDiff === message.checkpoint_filename}
              onClick={() => {
                setActiveDiff(
                  activeDiff === message.checkpoint_filename
                    ? null
                    : message.checkpoint_filename ?? null
                );
                setDiffFilePaths([]);
                setActiveDiffFiles([]);
              }}
            />
          ) : null}
        </div>
      );
    },
    [activeDiff, collapsedCards, delegateFlowMap, forkAtMessage, isStreaming, rollbackAtMessage, subAgentFlows, toggleCard, toggleSubAgentFlow],
  );

  return (
    <div id="app">
      <div id="overlay" className={sidebarOpen ? 'show' : ''} onClick={() => setSidebarOpen(false)} />

      <aside id="sidebar" className={sidebarOpen ? 'open' : ''} style={{ width: sidebarWidth, minWidth: sidebarWidth }}>
        <div id="sidebar-header">
          <div className="top">
            <div>
              <h1>
                nano<span>Claude</span>
              </h1>
              <div className="sub">coding assistant</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button className="theme-btn" onClick={toggleTheme} title={darkMode ? 'Switch to light' : 'Switch to dark'}>
                {darkMode ? '☀️' : '🌙'}
              </button>
              <button id="close-sidebar" onClick={() => setSidebarOpen(false)}>
                ✕
              </button>
            </div>
          </div>
          <button id="new-session-btn" onClick={() => void newSession()}>
            <span>+</span>
            <span>New Session</span>
          </button>
        </div>

        <div id="session-list">
          {sessions.length === 0 ? (
            <div style={{ padding: 16, color: 'var(--text-dim)', textAlign: 'center', fontSize: 13 }}>No saved sessions</div>
          ) : (
            (() => {
              const { recent, older } = groupSessions(sessions);
              return (
                <>
                  <SessionGroup
                    title="最近会话"
                    defaultOpen={true}
                    sessions={recent}
                    onSwitch={switchSession}
                    onDelete={deleteSession}
                    isStreaming={isStreaming}
                  />
                  {older.length > 0 && (
                    <SessionGroup
                      title="更早的会话"
                      defaultOpen={false}
                      sessions={older}
                      onSwitch={switchSession}
                      onDelete={deleteSession}
                      isStreaming={isStreaming}
                    />
                  )}
                </>
              );
            })()
          )}
        </div>

      </aside>

      <div
        id="sidebar-resizer"
        className={isResizing ? 'resizing' : ''}
        onMouseDown={handleResizeStart}
        onDoubleClick={resetSidebarWidth}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize sidebar"
        title="Drag to resize, double-click to reset"
      />

      <div id="main" ref={mainPanelRef}>
        <div id="chat-header" className="visible" ref={chatHeaderRef}>
          <button id="menu-btn" onClick={() => setSidebarOpen((prev) => !prev)}>
            ☰
          </button>
          <div className="title">{sessionTitle}</div>
          <button id="vscode-btn" onClick={() => void openVSCode()} title="Open current directory in VS Code">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M11.15 1.5L9.5 3.15L14.35 8L9.5 12.85L11.15 14.5L16 8L11.15 1.5Z" fill="currentColor" />
              <path d="M4.85 1.5L0 8L4.85 14.5L6.5 12.85L1.65 8L6.5 3.15L4.85 1.5Z" fill="currentColor" />
            </svg>
            <span>Open in VS Code</span>
          </button>
        </div>

        <div id="chat" ref={chatContainerRef}>
          {messages.length === 0 ? (
            <div id="empty-state">
              <div className="icon">⚡</div>
              <h2>nanoClaude</h2>
              <p>Ask me anything about your code. I can read, write, edit files, run commands, search the web, and more.</p>
              <div className="shortcuts">
                <span className="shortcut">⌘↩ Send message</span>
                <span className="shortcut">⌘K New session</span>
                <span className="shortcut">⌘N New session</span>
                <span className="shortcut">↑↓ Navigate history</span>
              </div>
            </div>
          ) : (
            segments.map((seg) => {
              return (
              <div key={seg.key} className="msg-group">
                {seg.userMessage ? renderMessageNode(seg.userMessage.message, seg.userMessage.index) : null}
                {seg.foldingMessages.length > 0 ? (
                  <ThinkingBubble
                    segmentKey={seg.key}
                    messages={seg.foldingMessages}
                    collapsed={collapsedThinkingSections[seg.key] !== false}
                    onToggle={toggleThinkingSection}
                    collapsedCards={collapsedCards}
                    onToggleCard={toggleCard}
                    delegateFlowMap={delegateFlowMap}
                    subAgentFlows={subAgentFlows}
                    onToggleSubAgentFlow={toggleSubAgentFlow}
                    truncate={truncate}
                    formatTimestamp={formatMsgTimestamp}
                  />
                ) : null}
                {seg.lastMessage ? renderMessageNode(seg.lastMessage.message, seg.lastMessage.index) : null}
                {seg.diffSummaryMessages.map(m => renderMessageNode(m.message, m.index))}
              </div>
              );
            }))}
        </div>

        {flowEntries.map(([flowId, flow]) =>
          flow.visible && flow.agents.length > 0 ? (
            <div key={flowId} className="msg assistant" style={{ marginBottom: 4 }}>
              <div className="bubble" style={{ padding: 0, border: 'none', maxWidth: '100%', width: '100%', background: 'transparent' }}>
                <div className="sub-agent-section-label">
                  🤖 Parallel Sub-Agents <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-dim)' }}>({flowId})</span>
                  <button
                    onClick={(event) => {
                      event.stopPropagation();
                      toggleSubAgentFlow(flowId);
                    }}
                    style={{
                      marginLeft: 'auto',
                      background: 'none',
                      border: '1px solid var(--border)',
                      borderRadius: 4,
                      color: 'var(--text-dim)',
                      cursor: 'pointer',
                      fontSize: 11,
                      padding: '2px 8px',
                      transition: 'all 0.12s',
                      whiteSpace: 'nowrap',
                    }}
                    title="Hide this sub-agent execution panel"
                  >
                    ✕ Hide
                  </button>
                </div>
                <div className="sub-agent-container">
                  {flow.agents.map((agent) => (
                    <div key={agent.id} className="sub-agent-col">
                      <div className="sub-agent-header">
                        <span className={`status-dot ${agent.status}`} />
                        <span>{agent.id}</span>
                        <span style={{ color: 'var(--text-dim)', fontWeight: 400, fontSize: 11, marginLeft: 'auto' }}>
                          {agent.status === 'running' ? '⏳ running' : agent.status === 'done' ? '✅ done' : '❌ error'}
                        </span>
                      </div>
                      <div className="sub-agent-body">
                        {agent.events.map((eventItem, eventIndex) => (
                          <SubAgentEventCard key={`${agent.id}-${eventIndex}`} event={eventItem} />
                        ))}
                        {agent.events.length === 0 ? <div className="sub-agent-placeholder">Waiting for task to start...</div> : null}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null,
        )}

        <div id="streaming-indicator" className={isStreaming ? 'active' : ''} ref={streamingIndicatorRef}>
          <div className="spinner" />
          <span>AI is thinking...</span>
        </div>

        <div
          id="input-area-resizer"
          className={isInputAreaResizing ? 'resizing' : ''}
          onMouseDown={handleInputAreaResizeStart}
          onDoubleClick={resetInputAreaHeight}
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize input area"
          title="Drag to resize, double-click to reset"
        />

        <div id="input-area" style={{ flex: '0 0 auto', height: inputAreaHeight }}>
          <div id="input-row">
            <textarea
              id="msg-input"
              ref={inputRef}
              value={inputText}
              rows={1}
              placeholder="Type a message..."
              onChange={(event) => setInputText(event.target.value)}
              onKeyDown={handleInputKeydown}
              disabled={isInputDisabled}
            />
          </div>
          <div id="input-footer">
            <div className="left-group">
              <div
                className="mode-toggle"
                onClick={() => void toggleMode()}
                title={mode === 'plan' ? 'Current: Plan mode - Click to switch to Build' : 'Current: Build mode - Click to switch to Plan'}
              >
                <span className={`mode-opt plan ${mode === 'plan' ? 'active' : ''}`}>📋 Plan</span>
                <span className={`mode-opt build ${mode === 'build' ? 'active' : ''}`}>🔨 Build</span>
              </div>
              <ModelSelector
                activeModel={activeModel}
                activeProvider={activeProvider}
                onOpenProviderSettings={() => setShowProviderDialog(true)}
                onModelChanged={handleModelChanged}
                disabled={isStreaming}
              />
            </div>

            {isStreaming ? (
              <div className="action-buttons">
                <button
                  id="stop-btn"
                  className="stop-circle"
                  onClick={() => void stopResponse()}
                  title="停止"
                  aria-label="Stop"
                >
                  <span className="stop-icon" />
                </button>
                <button id="send-btn" onClick={() => void sendMessage()} disabled={!inputText.trim()}>
                  发送
                </button>
              </div>
            ) : showBuildButton ? (
              <button id="send-btn" onClick={() => void executePlan(latestUnexecutedPlan!.filename)} title={latestUnexecutedPlan!.filename}>
                ▶ 执行计划
              </button>
            ) : (
              <button id="send-btn" onClick={() => void sendMessage()} disabled={!inputText.trim()}>
                发送
              </button>
            )}
          </div>
        </div>
      </div>

      <div
        id="workspace-resizer"
        className={isWorkspaceResizing ? 'resizing' : ''}
        onMouseDown={handleWorkspaceResizeStart}
        onDoubleClick={resetWorkspaceWidth}
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize workspace panel"
        title="Drag to resize, double-click to reset"
      />

      <aside id="workspace-panel" ref={workspacePanelRef} style={{ width: workspaceWidth, minWidth: workspaceWidth }}>
        <div className="workspace-panel-section">
          <div className="workspace-panel-header">
            <span className="header-title">
              <span className="header-label">Modified Files</span>
              {activeDiff ? <span className="header-diff-badge">filtered</span> : null}
            </span>
            <button
              className={`workspace-refresh-btn ${!activeDiff && isRefreshing ? 'spinning' : ''}`}
              onClick={() => void refreshWorkspace()}
              title={activeDiff ? 'Back to all modified files' : 'Refresh modified files and plan docs'}
              type="button"
            >
              {activeDiff ? '←' : '↻'}
            </button>
          </div>
          <div className="workspace-panel-body">
            {modifiedFileTree.length > 0 ? (
              renderTreeNodes(modifiedFileTree)
            ) : (
              <div className="workspace-panel-empty">No modified files</div>
            )}
          </div>
        </div>

        <div
          id="workspace-section-resizer"
          className={isPlanDocsResizing ? 'resizing' : ''}
          onMouseDown={handlePlanDocsResizeStart}
          onDoubleClick={resetPlanDocsHeight}
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize plan docs panel"
          title="Drag to resize, double-click to reset"
        />

        <div
          className="workspace-panel-section workspace-panel-plan-section"
          style={{ flex: '0 0 auto', height: planDocsHeight, minHeight: planDocsHeight }}
        >
          <div className="workspace-panel-header">
            <span>Plan Docs</span>
            <button
              className={`workspace-refresh-btn ${isRefreshing ? 'spinning' : ''}`}
              onClick={() => void refreshWorkspace()}
              title="Refresh modified files and plan docs"
              type="button"
            >
              ↻
            </button>
          </div>
          <div className="workspace-panel-body">
            {planDocs.length > 0 ? (
              planDocs.map((doc) => (
                <button key={doc.filename} className="plan-doc-item" onClick={() => openPlanDoc(doc.filename)} type="button">
                  <div className="plan-doc-name">{doc.filename}</div>
                  <div className="plan-doc-meta">
                    {formatModifiedTimestamp(doc.modified)} · {(doc.size / BYTES_IN_KIBIBYTE).toFixed(1)} KiB
                  </div>
                </button>
              ))
            ) : (
              <div className="workspace-panel-empty">No plan docs</div>
            )}
          </div>
        </div>
      </aside>

      {showProviderDialog ? (
        <ProviderSettingsDialog
          onClose={() => setShowProviderDialog(false)}
          onProvidersChanged={handleModelChanged}
        />
      ) : null}

      <PermissionOverlay
        activePermission={activePermission}
        onDeny={permissionDeny}
        onAllow={permissionAllow}
        onAlwaysAllow={permissionAlwaysAllow}
      />

      <QuestionOverlay
        activeQuestion={activeQuestion}
        questionAnswers={questionAnswers}
        customAnswer={customAnswer}
        customInputRef={customInputRef}
        onToggleOption={toggleQuestionOption}
        onSelectCustomOption={selectCustomOption}
        onSetCustomAnswer={setCustomAnswer}
        onCancel={cancelQuestion}
        onSubmit={() => void submitQuestion()}
      />

      <Toast visible={toast.visible} message={toast.message} />
    </div>
  );
}
