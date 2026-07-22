import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { api } from '../../shared/api';
import { renderMarkdown } from '../../shared/markdown';
import type {
  ChatMessage,
  CurrentInfo,
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
  return readStoredDimension(PLAN_DOCS_HEIGHT_STORAGE_KEY, MIN_PLAN_DOCS_HEIGHT, Number.MAX_SAFE_INTEGER, DEFAULT_PLAN_DOCS_HEIGHT);
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
  const [sessionTitle, setSessionTitle] = useState('nanoClaude');
  const [mode, setMode] = useState<Mode>('build');
  const [planDocs, setPlanDocs] = useState<PlanDocListItem[]>([]);
  const [modifiedFiles, setModifiedFiles] = useState<ModifiedFileItem[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({});
  const [darkMode, setDarkMode] = useState(readStoredTheme);
  const [toast, setToast] = useState({ visible: false, message: '' });
  const [subAgentFlows, setSubAgentFlows] = useState<Record<string, SubAgentFlow>>({});
  const [delegateFlowMap, setDelegateFlowMap] = useState<Record<number, string>>({});
  const [activeQuestion, setActiveQuestion] = useState<QuestionDialog | null>(null);
  const [questionAnswers, setQuestionAnswers] = useState<string[]>([]);
  const [customAnswer, setCustomAnswer] = useState('');
  const [activePermission, setActivePermission] = useState<PermissionRequest | null>(null);

  const messagesRef = useRef(messages);
  const activeQuestionRef = useRef(activeQuestion);
  const eventSourceRef = useRef<EventSource | null>(null);
  const delegateFlowCounterRef = useRef(0);
  const questionQueueRef = useRef<QuestionDialog[]>([]);
  const toastTimerRef = useRef<number | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
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
      commitMessages(() => data.messages || []);
      resetFlowState();
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
    [clampPlanDocsHeight, handlePlanDocsResizeEnd, handlePlanDocsResizeMove, planDocsHeight],
  );

  useEffect(() => {
    return () => {
      window.removeEventListener('mousemove', handleResizeMove);
      window.removeEventListener('mouseup', handleResizeEnd);
      window.removeEventListener('mousemove', handleWorkspaceResizeMove);
      window.removeEventListener('mouseup', handleWorkspaceResizeEnd);
      window.removeEventListener('mousemove', handlePlanDocsResizeMove);
      window.removeEventListener('mouseup', handlePlanDocsResizeEnd);
    };
  }, [handlePlanDocsResizeEnd, handlePlanDocsResizeMove, handleResizeEnd, handleResizeMove, handleWorkspaceResizeEnd, handleWorkspaceResizeMove]);

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

  const sendMessage = useCallback(async () => {
    const text = inputText.trim();
    if (!text || isStreaming) {
      return;
    }

    resetFlowState();
    setInputText('');
    setIsStreaming(true);
    commitMessages((prev) => [...prev, { role: 'user', type: 'text', content: text }, { role: 'assistant', type: 'text', content: '' }]);
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
  }, [closeEventSource, commitMessages, inputText, isStreaming, loadSessions, loadWorkspacePanel, resetFlowState, scheduleScrollBottom, showToast, updateLastAssistantMessage]);

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
    const element = inputRef.current;
    if (!element) {
      return;
    }
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [inputText]);

  useEffect(() => {
    scheduleScrollBottom();
  }, [messages, subAgentFlows, isStreaming, activeQuestion, activePermission, scheduleScrollBottom]);

  const flowEntries = useMemo(() => Object.entries(subAgentFlows), [subAgentFlows]);
  const modifiedFileTree = useMemo(() => buildModifiedFileTree(modifiedFiles), [modifiedFiles]);

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
  const renderedModifiedTree = useMemo(() => renderTreeNodes(modifiedFileTree), [modifiedFileTree, renderTreeNodes]);

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

        <div id="sidebar-footer">
          <button id="vscode-btn" onClick={() => void openVSCode()} title="Open current directory in VS Code">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M11.15 1.5L9.5 3.15L14.35 8L9.5 12.85L11.15 14.5L16 8L11.15 1.5Z" fill="currentColor" />
              <path d="M4.85 1.5L0 8L4.85 14.5L6.5 12.85L1.65 8L6.5 3.15L4.85 1.5Z" fill="currentColor" />
            </svg>
            <span>Open in VS Code</span>
          </button>
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

      <div id="main">
        <div id="chat-header" className="visible">
          <button id="menu-btn" onClick={() => setSidebarOpen((prev) => !prev)}>
            ☰
          </button>
          <div className="title">{sessionTitle}</div>
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
            messages.map((message, index) => {
              const flowId = delegateFlowMap[index] || null;
              const flowVisible = flowId ? subAgentFlows[flowId]?.visible : false;

              return (
                <div key={`${message.role}-${message.type}-${index}`} className={`msg ${message.role || 'assistant'}`}>
                  {message.role === 'user' && message.type === 'text' ? (
                    <div className="bubble">{message.content}</div>
                  ) : null}

                  {message.role === 'assistant' && message.type === 'text' ? (
                    <div className="bubble" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
                  ) : null}

                  {message.type === 'tool_start' ? (
                    <div>
                      <div className="tool-card args">
                        <div className="tool-card-header">
                          <span className="badge run">▶ {message.name}</span>
                          <span style={{ color: 'var(--text-dim)' }}>tool call</span>
                        </div>
                        <div className="tool-card-body">{JSON.stringify(message.arguments ?? {}, null, 2)}</div>
                      </div>
                    </div>
                  ) : null}

                  {message.type === 'tool_result' ? (
                    <div>
                      <div className="tool-card result">
                        <div className="tool-card-header">
                          <span className="badge done">✔ {message.name || message.title || 'done'}</span>
                          <span style={{ color: 'var(--text-dim)' }}>result</span>
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
                        <div className="tool-card-body">{truncate(message.content || '', 2000)}</div>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })
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

        <div id="streaming-indicator" className={isStreaming ? 'active' : ''}>
          <div className="spinner" />
          <span>AI is thinking...</span>
        </div>

        <div id="input-area">
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
              <button id="send-btn" onClick={() => void sendMessage()} disabled={!inputText.trim()}>
                发送
              </button>
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
          <div className="workspace-panel-header">Modified Files</div>
          <div className="workspace-panel-body">
            {modifiedFileTree.length > 0 ? (
              renderedModifiedTree
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
          <div className="workspace-panel-header">Plan Docs</div>
          <div className="workspace-panel-body">
            {planDocs.length > 0 ? (
              planDocs.map((doc) => (
                <button key={doc.filename} className="plan-doc-item" onClick={() => openPlanDoc(doc.filename)} type="button">
                  <div className="plan-doc-name">{doc.filename}</div>
                  <div className="plan-doc-meta">
                    {formatModifiedTimestamp(doc.modified)} · {(doc.size / 1024).toFixed(1)} KB
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

function SubAgentEventCard({ event }: { event: SubAgentEvent }) {
  if (event.type === 'reasoning') {
    return <div className="sub-agent-reasoning">{event.content}</div>;
  }

  if (event.type === 'tool_start') {
    return (
      <div className="tool-card args" style={{ margin: '4px 0' }}>
        <div className="tool-card-header">
          <span className="badge run">▶ {event.name}</span>
          <span style={{ color: 'var(--text-dim)' }}>tool call</span>
        </div>
        {event.arguments && Object.keys(event.arguments).length > 0 ? (
          <div className="tool-card-body">{JSON.stringify(event.arguments, null, 2)}</div>
        ) : null}
      </div>
    );
  }

  if (event.type === 'tool_result') {
    return (
      <div className="tool-card result" style={{ margin: '4px 0' }}>
        <div className="tool-card-header">
          <span className="badge done">✔ {event.name || event.title || 'done'}</span>
          <span style={{ color: 'var(--text-dim)' }}>result</span>
        </div>
        <div className="tool-card-body">{event.content || ''}</div>
      </div>
    );
  }

  if (event.type === 'error') {
    return (
      <div className="tool-card error-card" style={{ margin: '4px 0' }}>
        <div className="tool-card-header">
          <span className="badge error">✗ error</span>
        </div>
        <div className="tool-card-body">{event.content}</div>
      </div>
    );
  }

  return null;
}
