import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { api } from '../../shared/api';
import { renderMarkdown } from '../../shared/markdown';
import type {
  ChatMessage,
  CurrentInfo,
  DiffDetail,
  DiffSummary,
  ModifiedFileItem,
  Mode,
  PermissionRequest,
  PlanDocListItem,
  QuestionDialog,
  SessionSummary,
  SubAgent,
  SubAgentEvent,
  SubAgentFlow,
  WorkspacePanelResponse,
} from '../../shared/types';

interface ChatResponse {
  response_id: string;
}

const SIDEBAR_WIDTH_STORAGE_KEY = 'sidebar-width';
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH = 520;
const DEFAULT_SIDEBAR_WIDTH = 280;
const WORKSPACE_WIDTH_STORAGE_KEY = 'workspace-width';
const MIN_WORKSPACE_WIDTH = 240;
const MAX_WORKSPACE_WIDTH = 560;
const DEFAULT_WORKSPACE_WIDTH = 320;
const PLAN_DOCS_HEIGHT_STORAGE_KEY = 'plan-docs-height';
const MIN_PLAN_DOCS_HEIGHT = 120;
const MIN_MODIFIED_FILES_HEIGHT = 140;
const DEFAULT_PLAN_DOCS_HEIGHT = 220;
const WORKSPACE_SECTION_RESIZER_SIZE = 6;
const INPUT_AREA_HEIGHT_STORAGE_KEY = 'input-area-height';
const MIN_INPUT_AREA_HEIGHT = 180;
const DEFAULT_INPUT_AREA_HEIGHT = 200;
const INPUT_AREA_RESIZER_SIZE = 6;
const MIN_CHAT_HEIGHT = 180;
const MAX_STORED_PANEL_HEIGHT = 2000;
const BYTES_IN_KIBIBYTE = 1024;
const TREE_INDENT_PER_LEVEL = 16;
const TREE_FOLDER_BASE_INDENT = 12;
const TREE_FILE_BASE_INDENT = 36;
const TIMESTAMP_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const MSG_TIMESTAMP_FORMATTER = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
function formatMsgTimestamp(ts: number | undefined | null): string {
  if (!ts || ts === 0) return '';
  return MSG_TIMESTAMP_FORMATTER.format(new Date(ts * 1000));
}
function readStoredDimension(storageKey: string, minValue: number, maxValue: number, defaultValue: number): number {
  const stored = Number(localStorage.getItem(storageKey));
  if (Number.isFinite(stored) && stored >= minValue && stored <= maxValue) {
    return stored;
  }
  return defaultValue;
}

function readStoredSidebarWidth(): number {
  return readStoredDimension(SIDEBAR_WIDTH_STORAGE_KEY, MIN_SIDEBAR_WIDTH, MAX_SIDEBAR_WIDTH, DEFAULT_SIDEBAR_WIDTH);
}

function readStoredWorkspaceWidth(): number {
  return readStoredDimension(WORKSPACE_WIDTH_STORAGE_KEY, MIN_WORKSPACE_WIDTH, MAX_WORKSPACE_WIDTH, DEFAULT_WORKSPACE_WIDTH);
}

function readStoredPlanDocsHeight(): number {
  return readStoredDimension(PLAN_DOCS_HEIGHT_STORAGE_KEY, MIN_PLAN_DOCS_HEIGHT, MAX_STORED_PANEL_HEIGHT, DEFAULT_PLAN_DOCS_HEIGHT);
}

function readStoredInputAreaHeight(): number {
  return readStoredDimension(INPUT_AREA_HEIGHT_STORAGE_KEY, MIN_INPUT_AREA_HEIGHT, MAX_STORED_PANEL_HEIGHT, DEFAULT_INPUT_AREA_HEIGHT);
}

function detectSystemDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function readStoredTheme(): boolean {
  const stored = localStorage.getItem('theme');
  return stored !== null ? stored === 'dark' : detectSystemDark();
}

function applyTheme(dark: boolean) {
  const theme = dark ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}

function truncate(text: string, max: number): string {
  if (text.length > max) {
    return `${text.slice(0, max)}\n... (truncated)`;
  }
  return text;
}

function cloneFlow(flow: SubAgentFlow): SubAgentFlow {
  return {
    ...flow,
    agents: flow.agents.map((agent) => ({ ...agent, events: [...agent.events] })),
  };
}

interface FileTreeNode {
  name: string;
  path: string;
  type: 'folder' | 'file';
  status?: string;
  children?: FileTreeNode[];
}

function formatModifiedTimestamp(value: number | null | undefined): string {
  if (!value) {
    return '';
  }
  return TIMESTAMP_FORMATTER.format(new Date(value * 1000));
}

function buildModifiedFileTree(files: ModifiedFileItem[]): FileTreeNode[] {
  const root: FileTreeNode[] = [];

  for (const file of files) {
    const segments = file.path.split('/').filter(Boolean);
    if (segments.length === 0) {
      continue;
    }

    let currentLevel = root;
    let currentPath = '';
    segments.forEach((segment, index) => {
      currentPath = currentPath ? `${currentPath}/${segment}` : segment;
      const isFile = index === segments.length - 1;
      let existing = currentLevel.find((node) => node.name === segment && node.type === (isFile ? 'file' : 'folder'));

      if (existing) {
        if (!isFile && existing.children) {
          currentLevel = existing.children;
        }
        return;
      }

      existing = isFile
        ? { name: segment, path: currentPath, type: 'file', status: file.status }
        : { name: segment, path: currentPath, type: 'folder', children: [] };
      currentLevel.push(existing);
      if (!isFile) {
        currentLevel = existing.children ?? [];
      }
    });
  }

  const normalize = (nodes: FileTreeNode[]): FileTreeNode[] =>
    nodes
      .map((node) => (
        node.type === 'folder'
          ? { ...node, children: normalize(node.children ?? []) }
          : node
      ))
      .sort((left, right) => {
        if (left.type !== right.type) {
          return left.type === 'folder' ? -1 : 1;
        }
        return left.name.localeCompare(right.name);
      });

  return normalize(root);
}

function collectFolderPaths(nodes: FileTreeNode[]): string[] {
  return nodes.flatMap((node) => (
    node.type === 'folder'
      ? [node.path, ...collectFolderPaths(node.children ?? [])]
      : []
  ));
}

interface MessageSegment {
  key: string;
  userMessage: { message: ChatMessage; index: number } | null;
  foldingMessages: { message: ChatMessage; index: number }[];
  lastMessage: { message: ChatMessage; index: number } | null;
}

function buildMessageSegments(messages: ChatMessage[]): MessageSegment[] {
  if (messages.length === 0) return [];

  const segments: MessageSegment[] = [];
  const finalize = (key: string, userMsg: ChatMessage | null, msgs: ChatMessage[], startIdx: number) => {
    const mapped = msgs.map((m, i) => ({ message: m, index: startIdx + i }));
    if (mapped.length <= 1) {
      segments.push({ key, userMessage: userMsg ? { message: userMsg, index: startIdx - 1 } : null, foldingMessages: [], lastMessage: mapped[0] ?? null });
    } else {
      segments.push({
        key,
        userMessage: userMsg ? { message: userMsg, index: startIdx - 1 } : null,
        foldingMessages: mapped.slice(0, -1),
        lastMessage: mapped[mapped.length - 1],
      });
    }
  };

  let segUser: ChatMessage | null = null;
  let segMsgs: ChatMessage[] = [];
  let segStartIdx = 0;
  let segCount = 0;

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];
    if (msg.role === 'user' && msg.type === 'text') {
      if (segUser !== null || segMsgs.length > 0) {
        finalize(`seg-${segCount++}`, segUser, segMsgs, segStartIdx);
      }
      segUser = msg;
      segMsgs = [];
      segStartIdx = i + 1;
    } else {
      segMsgs.push(msg);
    }
  }
  if (segUser !== null || segMsgs.length > 0) {
    finalize(`seg-${segCount}`, segUser, segMsgs, segStartIdx);
  }

  return segments;
}

export function ChatApp() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentSession, setCurrentSession] = useState<CurrentInfo | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [inputText, setInputText] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(readStoredSidebarWidth);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [workspaceWidth, setWorkspaceWidth] = useState(readStoredWorkspaceWidth);
  const [isWorkspaceResizing, setIsWorkspaceResizing] = useState(false);
  const workspaceResizeStateRef = useRef<{ startX: number; startWidth: number } | null>(null);
  const [planDocsHeight, setPlanDocsHeight] = useState(readStoredPlanDocsHeight);
  const [isPlanDocsResizing, setIsPlanDocsResizing] = useState(false);
  const planDocsResizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const [inputAreaHeight, setInputAreaHeight] = useState(readStoredInputAreaHeight);
  const [isInputAreaResizing, setIsInputAreaResizing] = useState(false);
  const inputAreaResizeStateRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const [sessionTitle, setSessionTitle] = useState('nanoClaude');
  const [mode, setMode] = useState<Mode>('build');
  const [planDocs, setPlanDocs] = useState<PlanDocListItem[]>([]);
  const [modifiedFiles, setModifiedFiles] = useState<ModifiedFileItem[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({});
  const [darkMode, setDarkMode] = useState(readStoredTheme);
  const [toast, setToast] = useState({ visible: false, message: '' });
  const [collapsedCards, setCollapsedCards] = useState<Record<number, boolean>>({});
  const [collapsedThinkingSections, setCollapsedThinkingSections] = useState<Record<string, boolean>>({});
  const [subAgentFlows, setSubAgentFlows] = useState<Record<string, SubAgentFlow>>({});
  const [delegateFlowMap, setDelegateFlowMap] = useState<Record<number, string>>({});
  const [activeQuestion, setActiveQuestion] = useState<QuestionDialog | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [customAnswer, setCustomAnswer] = useState('');
  const [activePermission, setActivePermission] = useState<PermissionRequest | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [diffSummaries, setDiffSummaries] = useState<Record<string, DiffSummary>>({});
  const [activeDiff, setActiveDiff] = useState<string | null>(null);
  const [diffFilePaths, setDiffFilePaths] = useState<string[]>([]);

  const messagesRef = useRef(messages);
  const activeQuestionRef = useRef(activeQuestion);
  const eventSourceRef = useRef<EventSource | null>(null);
  const delegateFlowCounterRef = useRef(0);
  const questionQueueRef = useRef<QuestionDialog[]>([]);
  const toastTimerRef = useRef<number | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const mainPanelRef = useRef<HTMLDivElement | null>(null);
  const chatHeaderRef = useRef<HTMLDivElement | null>(null);
  const streamingIndicatorRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const customInputRef = useRef<HTMLTextAreaElement | null>(null);
  const newSessionRef = useRef<() => Promise<void>>(async () => {});
  const workspacePanelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    activeQuestionRef.current = activeQuestion;
  }, [activeQuestion]);

  const isInputDisabled = isStreaming || activeQuestion !== null || activePermission !== null;

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

  const resetInteractionState = useCallback(() => {
    resetFlowState();
    setActivePermission(null);
    setActiveQuestion(null);
    setQuestionAnswers([]);
    setCustomAnswer('');
    questionQueueRef.current = [];
  }, [resetFlowState]);

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const nextSessions = await api<SessionSummary[]>('GET', '/api/sessions');
      setSessions(nextSessions);
    } catch {
      showToast('Failed to load sessions');
    }
  }, [showToast]);

  const refreshWorkspace = useCallback(async () => {
    setActiveDiff(null);
    setDiffFilePaths([]);
    setIsRefreshing(true);
    try {
      const data = await api<WorkspacePanelResponse>('GET', '/api/workspace-panel');
      setPlanDocs(data.plan_docs ?? []);
      setModifiedFiles(data.modified_files ?? []);
    } catch {
      setPlanDocs([]);
      setModifiedFiles([]);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  const loadWorkspacePanel = useCallback(async () => {
    try {
      const data = await api<WorkspacePanelResponse>('GET', '/api/workspace-panel');
      setPlanDocs(data.plan_docs ?? []);
      setModifiedFiles(data.modified_files ?? []);
    } catch {
      setPlanDocs([]);
      setModifiedFiles([]);
    }
  }, []);

  const loadCurrent = useCallback(async () => {
    try {
      const data = await api<CurrentInfo>('GET', '/api/current');
      setCurrentSession(data);
      setSessionTitle(data.title || 'nanoClaude');
      setMode(data.mode || 'build');
      commitMessages((prev) => {
        const nextMessages = data.messages || [];
        return JSON.stringify(prev) === JSON.stringify(nextMessages) ? prev : nextMessages;
      });
      const initialCollapsed: Record<number, boolean> = {};
      (data.messages || []).forEach((msg, i) => {
        if (msg.type === 'tool_start' || msg.type === 'tool_result') {
          initialCollapsed[i] = true;
        }
      });
      setCollapsedCards(initialCollapsed);
      resetFlowState();
      // Load diff summaries for the current session
      if (data.diff_summaries) {
        const map: Record<string, DiffSummary> = {};
        for (const ds of data.diff_summaries) {
          map[ds.segment_key] = ds;
        }
        setDiffSummaries(map);
      } else {
        setDiffSummaries({});
      }
      await loadSessions();
      await loadWorkspacePanel();
      scheduleScrollBottom();
    } catch {
      showToast('Failed to load current session');
    }
  }, [commitMessages, loadSessions, loadWorkspacePanel, resetFlowState, scheduleScrollBottom, showToast]);

  const toggleTheme = useCallback(() => {
    setDarkMode((prev) => {
      const next = !prev;
      applyTheme(next);
      return next;
    });
  }, []);

  const openPlanDoc = useCallback((filename?: string | null) => {
    const url = filename ? `/plan-view?filename=${encodeURIComponent(filename)}` : '/plan-view';
    window.open(url, '_blank');
  }, []);

  const toggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => ({ ...prev, [path]: !prev[path] }));
  }, []);

  const clampPlanDocsHeight = useCallback((height: number) => {
    const containerHeight = workspacePanelRef.current?.clientHeight;
    if (!containerHeight) {
      return Math.max(MIN_PLAN_DOCS_HEIGHT, height);
    }
    const maxHeight = Math.max(0, containerHeight - MIN_MODIFIED_FILES_HEIGHT - WORKSPACE_SECTION_RESIZER_SIZE);
    const minHeight = Math.min(MIN_PLAN_DOCS_HEIGHT, maxHeight);
    return Math.min(maxHeight, Math.max(minHeight, height));
  }, []);

  const clampInputAreaHeight = useCallback((height: number) => {
    const containerHeight = mainPanelRef.current?.clientHeight;
    if (!containerHeight) {
      return Math.max(MIN_INPUT_AREA_HEIGHT, height);
    }
    const headerHeight = chatHeaderRef.current?.offsetHeight ?? 0;
    const streamingHeight = streamingIndicatorRef.current?.offsetHeight ?? 0;
    const maxHeight = Math.max(0, containerHeight - headerHeight - streamingHeight - MIN_CHAT_HEIGHT - INPUT_AREA_RESIZER_SIZE);
    const minHeight = Math.min(MIN_INPUT_AREA_HEIGHT, maxHeight);
    return Math.min(maxHeight, Math.max(minHeight, height));
  }, []);

  const handleResizeMove = useCallback((event: MouseEvent) => {
    const state = resizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientX - state.startX;
    const nextWidth = Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, state.startWidth + delta));
    setSidebarWidth(nextWidth);
  }, []);

  const handleResizeEnd = useCallback(() => {
    resizeStateRef.current = null;
    setIsResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleResizeMove);
    window.removeEventListener('mouseup', handleResizeEnd);
    setSidebarWidth((current) => {
      localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(current));
      return current;
    });
  }, [handleResizeMove]);

  const handleResizeStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      resizeStateRef.current = { startX: event.clientX, startWidth: sidebarWidth };
      setIsResizing(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleResizeMove);
      window.addEventListener('mouseup', handleResizeEnd);
    },
    [handleResizeEnd, handleResizeMove, sidebarWidth],
  );

  const handleWorkspaceResizeMove = useCallback((event: MouseEvent) => {
    const state = workspaceResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientX - state.startX;
    const nextWidth = Math.min(MAX_WORKSPACE_WIDTH, Math.max(MIN_WORKSPACE_WIDTH, state.startWidth - delta));
    setWorkspaceWidth(nextWidth);
  }, []);

  const handleWorkspaceResizeEnd = useCallback(() => {
    workspaceResizeStateRef.current = null;
    setIsWorkspaceResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleWorkspaceResizeMove);
    window.removeEventListener('mouseup', handleWorkspaceResizeEnd);
    setWorkspaceWidth((current) => {
      localStorage.setItem(WORKSPACE_WIDTH_STORAGE_KEY, String(current));
      return current;
    });
  }, [handleWorkspaceResizeMove]);

  const handleWorkspaceResizeStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      workspaceResizeStateRef.current = { startX: event.clientX, startWidth: workspaceWidth };
      setIsWorkspaceResizing(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleWorkspaceResizeMove);
      window.addEventListener('mouseup', handleWorkspaceResizeEnd);
    },
    [handleWorkspaceResizeEnd, handleWorkspaceResizeMove, workspaceWidth],
  );

  const handlePlanDocsResizeMove = useCallback((event: MouseEvent) => {
    const state = planDocsResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientY - state.startY;
    setPlanDocsHeight(clampPlanDocsHeight(state.startHeight - delta));
  }, [clampPlanDocsHeight]);

  const handlePlanDocsResizeEnd = useCallback(() => {
    planDocsResizeStateRef.current = null;
    setIsPlanDocsResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handlePlanDocsResizeMove);
    window.removeEventListener('mouseup', handlePlanDocsResizeEnd);
    setPlanDocsHeight((current) => {
      const next = clampPlanDocsHeight(current);
      localStorage.setItem(PLAN_DOCS_HEIGHT_STORAGE_KEY, String(next));
      return next;
    });
  }, [clampPlanDocsHeight, handlePlanDocsResizeMove]);

  const handlePlanDocsResizeStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      planDocsResizeStateRef.current = { startY: event.clientY, startHeight: planDocsHeight };
      setIsPlanDocsResizing(true);
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handlePlanDocsResizeMove);
      window.addEventListener('mouseup', handlePlanDocsResizeEnd);
    },
    [handlePlanDocsResizeEnd, handlePlanDocsResizeMove, planDocsHeight],
  );

  const handleInputAreaResizeMove = useCallback((event: MouseEvent) => {
    const state = inputAreaResizeStateRef.current;
    if (!state) {
      return;
    }
    const delta = event.clientY - state.startY;
    setInputAreaHeight(clampInputAreaHeight(state.startHeight - delta));
  }, [clampInputAreaHeight]);

  const handleInputAreaResizeEnd = useCallback(() => {
    inputAreaResizeStateRef.current = null;
    setIsInputAreaResizing(false);
    document.body.style.removeProperty('cursor');
    document.body.style.removeProperty('user-select');
    window.removeEventListener('mousemove', handleInputAreaResizeMove);
    window.removeEventListener('mouseup', handleInputAreaResizeEnd);
    setInputAreaHeight((current) => {
      const next = clampInputAreaHeight(current);
      localStorage.setItem(INPUT_AREA_HEIGHT_STORAGE_KEY, String(next));
      return next;
    });
  }, [clampInputAreaHeight, handleInputAreaResizeMove]);

  const handleInputAreaResizeStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.preventDefault();
      inputAreaResizeStateRef.current = { startY: event.clientY, startHeight: inputAreaHeight };
      setIsInputAreaResizing(true);
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('mousemove', handleInputAreaResizeMove);
      window.addEventListener('mouseup', handleInputAreaResizeEnd);
    },
    [handleInputAreaResizeEnd, handleInputAreaResizeMove, inputAreaHeight],
  );

  useEffect(() => {
    return () => {
      window.removeEventListener('mousemove', handleResizeMove);
      window.removeEventListener('mouseup', handleResizeEnd);
      window.removeEventListener('mousemove', handleWorkspaceResizeMove);
      window.removeEventListener('mouseup', handleWorkspaceResizeEnd);
      window.removeEventListener('mousemove', handlePlanDocsResizeMove);
      window.removeEventListener('mouseup', handlePlanDocsResizeEnd);
      window.removeEventListener('mousemove', handleInputAreaResizeMove);
      window.removeEventListener('mouseup', handleInputAreaResizeEnd);
    };
  }, [handleInputAreaResizeEnd, handleInputAreaResizeMove, handlePlanDocsResizeEnd, handlePlanDocsResizeMove, handleResizeEnd, handleResizeMove, handleWorkspaceResizeEnd, handleWorkspaceResizeMove]);

  useEffect(() => {
    const syncPlanDocsHeight = () => {
      setPlanDocsHeight((current) => clampPlanDocsHeight(current));
    };
    syncPlanDocsHeight();
    window.addEventListener('resize', syncPlanDocsHeight);
    return () => {
      window.removeEventListener('resize', syncPlanDocsHeight);
    };
  }, [clampPlanDocsHeight]);

  useEffect(() => {
    setInputAreaHeight((current) => clampInputAreaHeight(current));
  }, [clampInputAreaHeight, isStreaming]);

  useEffect(() => {
    const syncInputAreaHeight = () => {
      setInputAreaHeight((current) => clampInputAreaHeight(current));
    };
    syncInputAreaHeight();
    window.addEventListener('resize', syncInputAreaHeight);
    return () => {
      window.removeEventListener('resize', syncInputAreaHeight);
    };
  }, [clampInputAreaHeight]);

  useEffect(() => {
    if (!activeDiff) {
      setDiffFilePaths([]);
      return;
    }
    setDiffFilePaths([]);
    api<DiffDetail>('GET', `/api/diffs/${encodeURIComponent(activeDiff)}`)
      .then((data) => {
        setDiffFilePaths(data.files.map(f => f.path));
      })
      .catch(() => {
        setDiffFilePaths([]);
      });
  }, [activeDiff]);

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
      const result = await api<{ mode: Mode }>('POST', '/api/mode', { mode: nextMode });
      setMode(result.mode);
      await loadCurrent();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch mode');
    }
  }, [isStreaming, loadCurrent, mode, showToast]);

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

  const newSession = useCallback(async () => {
    if (isStreaming) {
      return;
    }

    resetInteractionState();
    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>('POST', '/api/sessions');
      setCurrentSession(response.current);
      commitMessages(() => []);
      setSessionTitle('nanoClaude');
      await loadSessions();
      setSidebarOpen(false);
    } catch {
      showToast('Failed to create session');
    }
  }, [commitMessages, isStreaming, loadSessions, resetInteractionState, showToast]);

  const switchSession = useCallback(async (index: number) => {
    if (isStreaming) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>('PUT', `/api/sessions/${index}`);
      setCurrentSession(response.current);
      await loadCurrent();
      setSidebarOpen(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch session');
    }
  }, [isStreaming, loadCurrent, showToast]);

  const deleteSession = useCallback(async (index: number) => {
    if (isStreaming || !window.confirm('Delete this session?')) {
      return;
    }

    try {
      await api('DELETE', `/api/sessions/${index}`);
      await loadSessions();
      if (currentSession?.index === index) {
        await loadCurrent();
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to delete session');
    }
  }, [currentSession?.index, isStreaming, loadCurrent, loadSessions, showToast]);

  const forkAtMessage = useCallback(async (messageIndex: number) => {
    if (isStreaming) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>(
        'POST', '/api/sessions/fork', { message_index: messageIndex },
      );
      setCurrentSession(response.current);
      commitMessages(() => response.current.messages);
      setSessionTitle(response.current.title || 'nanoClaude');
      await loadSessions();
      showToast('Forked new session');
      scheduleScrollBottom();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to fork session');
    }
  }, [commitMessages, isStreaming, loadSessions, showToast, scheduleScrollBottom]);

  const rollbackAtMessage = useCallback(async (messageIndex: number) => {
    if (isStreaming) {
      return;
    }

    if (!window.confirm('确定要回滚吗？\n\n将撤销此消息之后的所有文件更改（跳过二进制文件），并删除此消息之后的所有消息。')) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>(
        'POST', '/api/sessions/rollback', { message_index: messageIndex },
      );
      setCurrentSession(response.current);
      commitMessages(() => response.current.messages);
      setSessionTitle(response.current.title || 'nanoClaude');
      setDiffSummaries((prev) => {
        // Keep only diff summaries for segments that still exist
        const newSummaries: Record<string, DiffSummary> = {};
        if (response.current.diff_summaries) {
          for (const ds of response.current.diff_summaries) {
            newSummaries[ds.segment_key] = ds;
          }
        }
        return newSummaries;
      });
      setActiveDiff(null);
      setDiffFilePaths([]);
      await loadSessions();
      await loadWorkspacePanel();
      showToast('回滚成功');
      scheduleScrollBottom();
    } catch (error) {
      showToast(error instanceof Error ? error.message : '回滚失败');
    }
  }, [commitMessages, isStreaming, loadSessions, loadWorkspacePanel, showToast, scheduleScrollBottom]);

  const toggleQuestionOption = useCallback((label: string) => {
    setQuestionAnswers((prev) => {
      if (activeQuestionRef.current?.multiple) {
        return prev.includes(label) ? prev.filter((entry) => entry !== label) : [...prev, label];
      }
      return [label];
    });
  }, []);

  const selectCustomOption = useCallback(() => {
    setQuestionAnswers(['__custom__']);
    window.requestAnimationFrame(() => {
      customInputRef.current?.focus();
    });
  }, []);

  const showNextOrCloseQuestion = useCallback(() => {
    const nextQuestion = questionQueueRef.current.shift() ?? null;
    setActiveQuestion(nextQuestion);
    setQuestionAnswers([]);
    setCustomAnswer('');
  }, []);

  const clearPermission = useCallback(() => {
    setActivePermission(null);
    if (questionQueueRef.current.length > 0) {
      const nextQuestion = questionQueueRef.current.shift() ?? null;
      setActiveQuestion(nextQuestion);
      setQuestionAnswers([]);
      setCustomAnswer('');
    }
  }, []);

  const sendPermissionDecision = useCallback(async (decision: 'allow' | 'deny' | 'allow_always') => {
    try {
      await fetch('/api/permission-response', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision }),
      });
    } catch {
      // Best-effort only; the backend manages timeout fallback.
    }
    clearPermission();
  }, [clearPermission]);

  const permissionDeny = useCallback(() => void sendPermissionDecision('deny'), [sendPermissionDecision]);
  const permissionAllow = useCallback(() => void sendPermissionDecision('allow'), [sendPermissionDecision]);
  const permissionAlwaysAllow = useCallback(() => void sendPermissionDecision('allow_always'), [sendPermissionDecision]);

  const submitQuestion = useCallback(async () => {
    let answer = questionAnswers;
    if (answer.includes('__custom__')) {
      answer = [customAnswer.trim() || '(skipped)'];
    }
    if (answer.length === 0) {
      answer = ['(skipped)'];
    }

    await fetch('/api/question-answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer }),
    });
    showNextOrCloseQuestion();
  }, [customAnswer, questionAnswers, showNextOrCloseQuestion]);

  const cancelQuestion = useCallback(() => {
    void fetch('/api/question-answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answer: ['(skipped)'] }),
    });
    showNextOrCloseQuestion();
  }, [showNextOrCloseQuestion]);

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

  const startChatStream = useCallback(async (text: string) => {
    resetFlowState();
    setInputText('');
    setIsStreaming(true);
    commitMessages((prev) => [...prev, { role: 'user', type: 'text', content: text }]);
    scheduleScrollBottom();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      if (!response.ok) {
        const errorData = (await response.json()) as { detail?: string };
        throw new Error(errorData.detail || 'Chat request failed');
      }

      const data = (await response.json()) as ChatResponse;
      if (!data.response_id) {
        throw new Error('No response_id');
      }

      closeEventSource();
      const eventSource = new EventSource(`/api/events?response_id=${encodeURIComponent(data.response_id)}`);
      eventSourceRef.current = eventSource;
      let toolPlaceholder: number | null = null;

      eventSource.addEventListener('message', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as Record<string, unknown>;
        const role = (payload.role as ChatMessage['role'] | undefined) ?? 'assistant';
        const type = (payload.type as ChatMessage['type'] | undefined) ?? 'text';

        if (role === 'user' && type === 'text') {
          commitMessages((prev) => [...prev, { role: 'user', type: 'text', content: String(payload.content ?? '') }]);
          scheduleScrollBottom();
          return;
        }

        if (role === 'assistant' && type === 'text') {
          commitMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === 'assistant' && last.type === 'text') {
              next[next.length - 1] = { ...last, content: last.content + String(payload.content ?? '') };
            } else {
              next.push({ role: 'assistant', type: 'text', content: String(payload.content ?? '') });
            }
            return next;
          });
          scheduleScrollBottom();
          return;
        }

        if (type === 'tool_start') {
          const toolMessage: ChatMessage = {
            role: 'assistant',
            type: 'tool_start',
            name: String(payload.name ?? ''),
            arguments: (payload.arguments as Record<string, unknown> | undefined) ?? {},
            content: '',
          };
          toolPlaceholder = messagesRef.current.length;
          commitMessages((prev) => [...prev, toolMessage]);
          setCollapsedCards((prev) => ({ ...prev, [toolPlaceholder as number]: true }));

          if (toolMessage.name === 'delegate') {
            delegateFlowCounterRef.current += 1;
            const flowId = `delegate_${delegateFlowCounterRef.current}`;
            setDelegateFlowMap((prev) => ({ ...prev, [toolPlaceholder as number]: flowId }));
            setSubAgentFlows((prev) => ({
              ...prev,
              [flowId]: { agents: [], visible: true, done: false },
            }));
          }

          scheduleScrollBottom();
          return;
        }

        if (type === 'tool_result') {
          const resultMessage: ChatMessage = {
            role: 'tool',
            type: 'tool_result',
            name: String(payload.name ?? payload.title ?? ''),
            title: String(payload.title ?? ''),
            content: String(payload.content ?? ''),
            flow_id: typeof payload.flow_id === 'string' ? payload.flow_id : '',
          };

          if (toolPlaceholder !== null) {
            const placeholderIndex = toolPlaceholder;
            commitMessages((prev) => {
              const next = [...prev];
              next[placeholderIndex] = resultMessage;
              return next;
            });
            setCollapsedCards((prev) => ({ ...prev, [placeholderIndex]: true }));
            if (resultMessage.flow_id) {
              setDelegateFlowMap((prev) => ({ ...prev, [placeholderIndex]: resultMessage.flow_id as string }));
            }
            toolPlaceholder = null;
          } else {
            commitMessages((prev) => [...prev, resultMessage]);
          }
          scheduleScrollBottom();
        }
      });

      eventSource.addEventListener('question', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as QuestionDialog;
        if (activeQuestionRef.current === null) {
          setActiveQuestion(payload);
          setQuestionAnswers([]);
          setCustomAnswer('');
        } else {
          questionQueueRef.current.push(payload);
        }
        scheduleScrollBottom();
      });

      eventSource.addEventListener('permission_request', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as PermissionRequest;
        if (activeQuestionRef.current !== null) {
          questionQueueRef.current.unshift(activeQuestionRef.current);
          setActiveQuestion(null);
          setQuestionAnswers([]);
          setCustomAnswer('');
        }
        setActivePermission(payload);
        scheduleScrollBottom();
      });

      eventSource.addEventListener('sub_agent_message', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as {
          flow_id?: string;
          agent_id?: string;
          type?: string;
          content?: string;
          name?: string;
          title?: string;
          arguments?: Record<string, unknown>;
        };
        const flowId = payload.flow_id;
        const agentId = payload.agent_id;
        if (!flowId || !agentId) {
          return;
        }

        setSubAgentFlows((prev) => {
          const next = { ...prev };
          const flow = cloneFlow(next[flowId] ?? { agents: [], visible: true, done: false });
          let agent: SubAgent | undefined = flow.agents.find((entry) => entry.id === agentId);
          if (!agent) {
            agent = { id: agentId, status: 'running', events: [] };
            flow.agents.push(agent);
          }

          const eventType = payload.type ?? '';
          if (eventType === 'start') {
            agent.status = 'running';
          } else if (eventType === 'reasoning') {
            const lastEvent = agent.events[agent.events.length - 1];
            if (lastEvent?.type === 'reasoning') {
              lastEvent.content = `${lastEvent.content ?? ''}${payload.content ?? ''}`;
            } else {
              agent.events.push({ type: 'reasoning', content: payload.content ?? '' });
            }
          } else if (eventType === 'tool_start') {
            agent.events.push({
              type: 'tool_start',
              name: payload.name ?? '',
              arguments: payload.arguments ?? {},
            });
          } else if (eventType === 'tool_end') {
            agent.events.push({
              type: 'tool_result',
              name: payload.name ?? payload.title ?? '',
              title: payload.title ?? '',
              content: payload.content ?? '',
            });
          } else if (eventType === 'end') {
            agent.status = 'done';
            if (flow.agents.every((entry) => entry.status !== 'running')) {
              flow.done = true;
              flow.visible = false;
            }
          } else if (eventType === 'error') {
            agent.status = 'error';
            agent.events.push({ type: 'error', content: payload.content ?? '' });
            if (flow.agents.every((entry) => entry.status !== 'running')) {
              flow.done = true;
              flow.visible = false;
            }
          }

          next[flowId] = flow;
          return next;
        });
        scheduleScrollBottom();
      });

      eventSource.addEventListener('diff_summary', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as DiffSummary;
        setDiffSummaries((prev) => ({ ...prev, [payload.segment_key]: payload }));
        scheduleScrollBottom();
      });

      eventSource.addEventListener('done', async () => {
        closeEventSource();
        setActivePermission(null);
        questionQueueRef.current = [];
        setIsStreaming(false);
        updateLastAssistantMessage((last) => (last.content.trim() ? last : null));
        try {
          await loadSessions();
        } catch {
          // loadSessions already handles errors.
        }
        void loadWorkspacePanel();
        scheduleScrollBottom();
      });

      eventSource.addEventListener('error', async (event) => {
        let message = 'Connection error';
        try {
          const data = JSON.parse((event as MessageEvent<string>).data) as { message?: string };
          message = data.message || message;
        } catch {
          // Keep the fallback message.
        }
        closeEventSource();
        setIsStreaming(false);
        updateLastAssistantMessage((last) => ({ ...last, content: `${last.content}\n\n⚠️ Error: ${message}` }));
        scheduleScrollBottom();
        try {
          await loadSessions();
        } catch {
          // loadSessions already handles errors.
        }
        void loadWorkspacePanel();
      });
    } catch (error) {
      updateLastAssistantMessage(() => ({ role: 'assistant', type: 'text', content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}` }));
      setIsStreaming(false);
      showToast(error instanceof Error ? error.message : 'Failed to send message');
    }
  }, [closeEventSource, commitMessages, loadSessions, loadWorkspacePanel, resetFlowState, scheduleScrollBottom, showToast, updateLastAssistantMessage]);

  const sendMessage = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isStreaming) {
      return;
    }
    await startChatStream(text);
  }, [inputText, isStreaming, startChatStream]);

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

  const stopResponse = useCallback(async () => {
    try {
      await fetch('/api/stop', { method: 'POST' });
    } catch {
      // Best effort; frontend still stops listening locally.
    }
    closeEventSource();
    setIsStreaming(false);
    updateLastAssistantMessage((last) => (last.content.trim() ? last : null));
    scheduleScrollBottom();
  }, [closeEventSource, scheduleScrollBottom, updateLastAssistantMessage]);

  const handleInputKeydown = useCallback((event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void sendMessage();
    }
  }, [sendMessage]);

  useEffect(() => {
    applyTheme(darkMode);
  }, [darkMode]);

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
    void loadSessions();
    void loadCurrent();

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
  }, [closeEventSource, loadCurrent, loadSessions]);

  useEffect(() => {
    scheduleScrollBottom();
  }, [messages, subAgentFlows, isStreaming, activeQuestion, activePermission, scheduleScrollBottom]);

  const flowEntries = useMemo(() => Object.entries(subAgentFlows), [subAgentFlows]);
  const segments = useMemo(() => buildMessageSegments(messages), [messages]);

  const filteredFiles = useMemo(() => {
    if (!activeDiff || diffFilePaths.length === 0) return modifiedFiles;
    return modifiedFiles.filter(mf => diffFilePaths.includes(mf.path));
  }, [modifiedFiles, activeDiff, diffFilePaths]);
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
                <div className="msg-timestamp">{formatMsgTimestamp(message.timestamp)}</div>
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
        </div>
      );
    },
    [collapsedCards, delegateFlowMap, forkAtMessage, isStreaming, rollbackAtMessage, subAgentFlows, toggleCard, toggleSubAgentFlow],
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
            sessions.map((session) => (
              <div
                key={session.index}
                className={`session-item ${session.is_current ? 'active' : ''}`}
                onClick={() => void switchSession(session.index)}
              >
                <span className="idx">{session.index}.</span>
                <div className="info">
                  <div className="title">{session.title || '(untitled)'}</div>
                  <div className="meta">{session.messages} msgs</div>
                </div>
                <button
                  className="del-btn"
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteSession(session.index);
                  }}
                  title="Delete session"
                >
                  ✕
                </button>
              </div>
            ))
          )}
        </div>

      </aside>

      <div
        id="sidebar-resizer"
        className={isResizing ? 'resizing' : ''}
        onMouseDown={handleResizeStart}
        onDoubleClick={() => {
          setSidebarWidth(DEFAULT_SIDEBAR_WIDTH);
          localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(DEFAULT_SIDEBAR_WIDTH));
        }}
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
            segments.map((seg) => (
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
                  />
                ) : null}
                {seg.lastMessage ? renderMessageNode(seg.lastMessage.message, seg.lastMessage.index) : null}
                {diffSummaries[seg.key] ? (
                  <DiffOverviewBubble
                    summary={diffSummaries[seg.key]}
                    isActive={activeDiff === diffSummaries[seg.key].diff_filename}
                    onClick={() => {
                      setActiveDiff(
                        activeDiff === diffSummaries[seg.key].diff_filename
                          ? null
                          : diffSummaries[seg.key].diff_filename
                      );
                      setDiffFilePaths([]);
                    }}
                  />
                ) : null}
              </div>
            ))
          )}
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
          onDoubleClick={() => {
            const next = clampInputAreaHeight(DEFAULT_INPUT_AREA_HEIGHT);
            setInputAreaHeight(next);
            localStorage.setItem(INPUT_AREA_HEIGHT_STORAGE_KEY, String(next));
          }}
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
            </div>

            {!isStreaming ? (
              showBuildButton ? (
                <button id="send-btn" onClick={() => void executePlan(latestUnexecutedPlan!.filename)} title={latestUnexecutedPlan!.filename}>
                  ▶ 执行计划
                </button>
              ) : (
                <button id="send-btn" onClick={() => void sendMessage()} disabled={!inputText.trim()}>
                  发送
                </button>
              )
            ) : (
              <button id="stop-btn" onClick={() => void stopResponse()}>
                ⏹ 停止
              </button>
            )}
          </div>
        </div>
      </div>

      <div
        id="workspace-resizer"
        className={isWorkspaceResizing ? 'resizing' : ''}
        onMouseDown={handleWorkspaceResizeStart}
        onDoubleClick={() => {
          setWorkspaceWidth(DEFAULT_WORKSPACE_WIDTH);
          localStorage.setItem(WORKSPACE_WIDTH_STORAGE_KEY, String(DEFAULT_WORKSPACE_WIDTH));
        }}
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
          onDoubleClick={() => {
            const next = clampPlanDocsHeight(DEFAULT_PLAN_DOCS_HEIGHT);
            setPlanDocsHeight(next);
            localStorage.setItem(PLAN_DOCS_HEIGHT_STORAGE_KEY, String(next));
          }}
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

      {activePermission ? (
        <div id="permission-overlay">
          <div className="permission-card">
            <div className="p-header">🔒 File Access Permission Request</div>
            <div className="p-body">
              <div style={{ marginBottom: 10 }}>
                <strong>Tool:</strong>
                <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', marginLeft: 6 }}>{activePermission.tool}</span>
                wants to access a file outside the working directory.
              </div>
              <div className="p-path-block">
                <div className="p-path-label">Requested Path</div>
                <div className="p-path-value">{activePermission.target}</div>
              </div>
              <div className="p-path-block" style={{ marginTop: 2 }}>
                <div className="p-path-label">Resolved Path</div>
                <div className="p-path-value" style={{ color: 'var(--accent4)' }}>
                  {activePermission.resolved_path}
                </div>
              </div>
              <div className="p-cwd">
                📁 Working Directory: <span style={{ color: 'var(--text-bright)', fontFamily: 'var(--mono)' }}>{activePermission.cwd}</span>
              </div>
            </div>
            <div className="p-actions">
              <button className="p-btn deny" onClick={permissionDeny}>
                Deny
              </button>
              <button className="p-btn allow" onClick={permissionAllow}>
                Allow
              </button>
              <button className="p-btn always" onClick={permissionAlwaysAllow}>
                Always Allow
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {activeQuestion ? (
        <div id="question-overlay" onClick={(event) => event.target === event.currentTarget && cancelQuestion()}>
          <div className="question-card">
            <div className="q-header">{activeQuestion.header}</div>
            <div className="q-body">{activeQuestion.question}</div>
            <div className="q-options">
              {activeQuestion.options.map((option, index) => {
                const selected = questionAnswers.includes(option.label);
                return (
                  <label
                    key={`${option.label}-${index}`}
                    className={`q-option ${selected ? 'selected' : ''}`}
                    onClick={() => toggleQuestionOption(option.label)}
                  >
                    <input
                      type={activeQuestion.multiple ? 'checkbox' : 'radio'}
                      name={`q-opt-${index}`}
                      checked={selected}
                      onChange={() => toggleQuestionOption(option.label)}
                      onClick={(event) => event.stopPropagation()}
                    />
                    <span style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                      <span className="q-label">{option.label}</span>
                      {option.description ? <span className="q-desc">{option.description}</span> : null}
                    </span>
                  </label>
                );
              })}

              <div className={`q-option ${questionAnswers.includes('__custom__') ? 'selected' : ''}`} onClick={selectCustomOption}>
                <input
                  type="radio"
                  name="q-custom"
                  checked={questionAnswers.includes('__custom__')}
                  onChange={selectCustomOption}
                  onClick={(event) => event.stopPropagation()}
                />
                <span style={{ display: 'flex', flexDirection: 'column', gap: 1, flex: 1 }}>
                  <span className="q-label">Custom (type your own answer)</span>
                  {questionAnswers.includes('__custom__') ? (
                    <textarea
                      ref={customInputRef}
                      value={customAnswer}
                      className="q-custom-input"
                      placeholder="Type your answer here..."
                      onChange={(event) => setCustomAnswer(event.target.value)}
                      onClick={(event) => event.stopPropagation()}
                    />
                  ) : null}
                </span>
              </div>
            </div>
            <div className="q-actions">
              <button className="q-btn cancel" onClick={cancelQuestion}>
                Skip
              </button>
              <button className="q-btn submit" onClick={() => void submitQuestion()}>
                Submit
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <div id="toast" className={toast.visible ? 'show' : ''}>
        {toast.message}
      </div>
    </div>
  );
}

function DiffOverviewBubble({
  summary, isActive, onClick,
}: {
  summary: DiffSummary; isActive: boolean; onClick: () => void;
}) {
  return (
    <div className="diff-overview">
      <div className={`diff-overview-card ${isActive ? 'active' : ''}`} onClick={onClick}>
        <span className="diff-overview-icon">📝</span>
        <span className="diff-overview-stats">
          <span className="diff-stat-files">{summary.summary.files_changed} file{summary.summary.files_changed !== 1 ? 's' : ''}</span>
          <span className="diff-stat-insertions">+{summary.summary.insertions}</span>
          <span className="diff-stat-deletions">-{summary.summary.deletions}</span>
        </span>
        <span className="diff-overview-arrow">{isActive ? '▾' : '▸'}</span>
      </div>
    </div>
  );
}

/** Escape HTML special chars in diff text */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Apply syntax highlighting to unified diff text */
function highlightDiff(diffText: string): string {
  return diffText
    .split('\n')
    .map((line) => {
      const escaped = escapeHtml(line);
      if (line.startsWith('+') && !line.startsWith('+++')) {
        return `<span class="diff-line-add">${escaped}</span>`;
      }
      if (line.startsWith('-') && !line.startsWith('---')) {
        return `<span class="diff-line-del">${escaped}</span>`;
      }
      if (line.startsWith('@@')) {
        return `<span class="diff-line-hdr">${escaped}</span>`;
      }
      return escaped;
    })
    .join('\n');
}

function DiffDetailView({ diffFilename }: { diffFilename: string }) {
  const [diffData, setDiffData] = useState<DiffDetail | null>(null);
  const [diffError, setDiffError] = useState(false);
  const [expandedFiles, setExpandedFiles] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setDiffData(null);
    setDiffError(false);
    api<DiffDetail>('GET', `/api/diffs/${encodeURIComponent(diffFilename)}`)
      .then((data) => {
        setDiffData(data);
        const expanded: Record<string, boolean> = {};
        // Start with only the first file expanded, rest collapsed
        data.files.forEach((f, i) => { expanded[f.path] = i === 0; });
        setExpandedFiles(expanded);
      })
      .catch(() => {
        setDiffError(true);
      });
  }, [diffFilename]);

  if (!diffData) {
    return (
      <div className="diff-loading">
        <div className="spinner" />
        <span>{diffError ? 'Failed to load diff' : 'Loading diff...'}</span>
      </div>
    );
  }

  return (
    <div className="diff-detail-view">
      {diffData.files.length === 0 ? (
        <div className="workspace-panel-empty">No file changes in this diff</div>
      ) : (
        diffData.files.map((file) => (
          <div key={file.path} className="diff-file-item">
            <div
              className="diff-file-header"
              onClick={() =>
                setExpandedFiles((prev) => ({
                  ...prev,
                  [file.path]: !prev[file.path],
                }))
              }
            >
              <span className="diff-overview-caret">
                {expandedFiles[file.path] ? '▾' : '▸'}
              </span>
              <span>
                {file.status === 'added'
                  ? '🆕'
                  : file.status === 'deleted'
                    ? '🗑️'
                    : '📄'}
              </span>
              <span className="diff-file-name">{file.path}</span>
              {file.binary ? <span className="diff-binary-badge">(binary)</span> : null}
              <span className="diff-file-stats">
                <span className="diff-stat-insertions">+{file.insertions}</span>
                <span className="diff-stat-deletions">-{file.deletions}</span>
              </span>
            </div>
            {expandedFiles[file.path] && !file.binary ? (
              <pre
                className="diff-file-content"
                dangerouslySetInnerHTML={{ __html: highlightDiff(file.diff) }}
              />
            ) : expandedFiles[file.path] && file.binary ? (
              <div className="diff-file-content diff-binary-msg">
                Binary file — changes cannot be displayed as line-by-line diff
              </div>
            ) : null}
          </div>
        ))
      )}
      {diffData.files.length > 0 ? (
        <div className="diff-detail-footer">
          <span className="diff-stat-files">{diffData.summary.files_changed} files</span>
          <span className="diff-stat-insertions">+{diffData.summary.insertions}</span>
          <span className="diff-stat-deletions">-{diffData.summary.deletions}</span>
        </div>
      ) : null}
    </div>
  );
}

function SubAgentEventCard({ event }: { event: SubAgentEvent }) {
  const [collapsed, setCollapsed] = useState(true);
  const toggle = useCallback(() => setCollapsed((prev) => !prev), []);

  if (event.type === 'reasoning') {
    return <div className="sub-agent-reasoning">{event.content}</div>;
  }

  if (event.type === 'tool_start') {
    return (
      <div className="tool-card args" style={{ margin: '4px 0' }}>
        <div className="tool-card-header" onClick={toggle}>
          <span className="collapse-arrow">{collapsed ? '▸' : '▾'}</span>
          <span className="badge run">▶ {event.name}</span>
          <span style={{ color: 'var(--text-dim)' }}>tool call</span>
        </div>
        {!collapsed && event.arguments && Object.keys(event.arguments).length > 0 ? (
          <div className="tool-card-body">{JSON.stringify(event.arguments, null, 2)}</div>
        ) : null}
      </div>
    );
  }

  if (event.type === 'tool_result') {
    return (
      <div className="tool-card result" style={{ margin: '4px 0' }}>
        <div className="tool-card-header" onClick={toggle}>
          <span className="collapse-arrow">{collapsed ? '▸' : '▾'}</span>
          <span className="badge done">✔ {event.name || event.title || 'done'}</span>
          <span style={{ color: 'var(--text-dim)' }}>result</span>
        </div>
        {!collapsed ? <div className="tool-card-body">{event.content || ''}</div> : null}
      </div>
    );
  }

  if (event.type === 'error') {
    return (
      <div className="tool-card error-card" style={{ margin: '4px 0' }}>
        <div className="tool-card-header" onClick={toggle}>
          <span className="collapse-arrow">{collapsed ? '▸' : '▾'}</span>
          <span className="badge error">✗ error</span>
        </div>
        {!collapsed ? <div className="tool-card-body">{event.content}</div> : null}
      </div>
    );
  }

  return null;
}

function ThinkingBubble({
  segmentKey,
  messages,
  collapsed,
  onToggle,
  collapsedCards,
  onToggleCard,
  delegateFlowMap,
  subAgentFlows,
  onToggleSubAgentFlow,
  truncate,
}: {
  segmentKey: string;
  messages: { message: ChatMessage; index: number }[];
  collapsed: boolean;
  onToggle: (key: string) => void;
  collapsedCards: Record<number, boolean>;
  onToggleCard: (index: number) => void;
  delegateFlowMap: Record<number, string>;
  subAgentFlows: Record<string, SubAgentFlow>;
  onToggleSubAgentFlow: (flowId: string | null) => void;
  truncate: (text: string, max: number) => string;
}) {
  const count = messages.length;

  return (
    <div className="thinking-bubble">
      <div className="thinking-bubble-header" onClick={() => onToggle(segmentKey)}>
        <span className="collapse-arrow">{collapsed ? '▸' : '▾'}</span>
        <span className="thinking-bubble-icon">💭</span>
        <span className="thinking-bubble-label">思考过程</span>
        <span className="thinking-bubble-count">({count} 条消息)</span>
      </div>
      {!collapsed ? (
        <div className="thinking-bubble-body">
          {messages.map(({ message, index }) => (
            <div key={`${message.role}-${message.type}-${index}`} className={`msg ${message.role || 'assistant'}`}>
              {message.role === 'user' && message.type === 'text' ? (
                <div className="bubble">
                  <div className="msg-timestamp">{formatMsgTimestamp(message.timestamp)}</div>
                  {message.content}
                </div>
              ) : null}

              {message.role === 'assistant' && message.type === 'text' ? (
                <div className="bubble">
                  <div className="msg-timestamp">{formatMsgTimestamp(message.timestamp)}</div>
                  <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
                </div>
              ) : null}

              {message.type === 'tool_start' ? (
                <div className="tool-card args">
                  <div className="tool-card-header" onClick={() => onToggleCard(index)}>
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
                  <div className="tool-card-header" onClick={() => onToggleCard(index)}>
                    <span className="collapse-arrow">{collapsedCards[index] !== false ? '▸' : '▾'}</span>
                    <span className="badge done">✔ {message.name || message.title || 'done'}</span>
                    <span style={{ color: 'var(--text-dim)' }}>result</span>
                    <span className="msg-timestamp" style={{ marginLeft: 'auto', marginRight: 8 }}>{formatMsgTimestamp(message.timestamp)}</span>
                    {message.name === 'delegate' ? (
                      <button
                        onClick={(event) => {
                          event.stopPropagation();
                          onToggleSubAgentFlow(delegateFlowMap[index] || null);
                        }}
                        style={{
                          marginLeft: 'auto',
                          background: 'none',
                          border: '1px solid var(--border)',
                          borderRadius: 4,
                          color: (delegateFlowMap[index] && subAgentFlows[delegateFlowMap[index]]?.visible) ? 'var(--accent)' : 'var(--text-dim)',
                          borderColor: (delegateFlowMap[index] && subAgentFlows[delegateFlowMap[index]]?.visible) ? 'var(--accent)' : 'var(--border)',
                          cursor: 'pointer',
                          fontSize: 11,
                          padding: '2px 8px',
                          transition: 'all 0.12s',
                          whiteSpace: 'nowrap',
                        }}
                        title={(delegateFlowMap[index] && subAgentFlows[delegateFlowMap[index]]?.visible) ? 'Hide sub-agent execution flow' : 'Show sub-agent execution flow'}
                      >
                        {(delegateFlowMap[index] && subAgentFlows[delegateFlowMap[index]]?.visible) ? '▲ Hide Agents' : '▼ Show Agents'}
                      </button>
                    ) : null}
                  </div>
                  {collapsedCards[index] !== false ? null : (
                    <div className="tool-card-body">{truncate(message.content || '', 2000)}</div>
                  )}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
