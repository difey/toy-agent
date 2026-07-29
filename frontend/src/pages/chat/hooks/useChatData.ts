import { useCallback, useEffect, useState, type Dispatch, type SetStateAction } from 'react';

import { api } from '../../../shared/api';
import type {
  ChatMessage,
  CheckpointData,
  CurrentInfo,
  DiffSummary,
  ModifiedFileItem,
  Mode,
  PlanDocListItem,
  SessionSummary,
} from '../../../shared/types';

export function useChatData({
  commitMessages,
  resetFlowState,
  scheduleScrollBottom,
  showToast,
  setMode,
  setSessionTitle,
  setCollapsedCards,
}: {
  commitMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  resetFlowState: () => void;
  scheduleScrollBottom: () => void;
  showToast: (message: string, timeout?: number) => void;
  setMode: Dispatch<SetStateAction<Mode>>;
  setSessionTitle: Dispatch<SetStateAction<string>>;
  setCollapsedCards: Dispatch<SetStateAction<Record<number, boolean>>>;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [currentSession, setCurrentSession] = useState<CurrentInfo | null>(null);
  const [planDocs, setPlanDocs] = useState<PlanDocListItem[]>([]);
  const [modifiedFiles, setModifiedFiles] = useState<ModifiedFileItem[]>([]);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [diffSummaries, setDiffSummaries] = useState<Record<string, DiffSummary>>({});
  const [activeDiff, setActiveDiff] = useState<string | null>(null);
  const [diffFilePaths, setDiffFilePaths] = useState<string[]>([]);
  const [activeDiffFiles, setActiveDiffFiles] = useState<ModifiedFileItem[]>([]);

  const applyCurrentView = useCallback((data: CurrentInfo) => {
    setCurrentSession(data);
    setSessions(data.session_catalog.sessions ?? []);
    setSessionTitle(data.session_meta.title || 'nanoClaude');
    setMode(data.app.mode || 'build');
    commitMessages((prev) => {
      const nextMessages = data.conversation.timeline || [];
      return JSON.stringify(prev) === JSON.stringify(nextMessages) ? prev : nextMessages;
    });
    const initialCollapsed: Record<number, boolean> = {};
    (data.conversation.timeline || []).forEach((msg, i) => {
      if (msg.type === 'tool_start' || msg.type === 'tool_result') {
        initialCollapsed[i] = true;
      }
    });
    setCollapsedCards(initialCollapsed);
    resetFlowState();
    setPlanDocs(data.workspace.plan_docs ?? []);
    setModifiedFiles(data.workspace.modified_files ?? []);
    setActiveDiff(data.workspace.active_diff ?? null);
    setActiveDiffFiles(data.workspace.active_diff_files ?? []);
    setDiffFilePaths((data.workspace.active_diff_files ?? []).map((file) => file.path));
    const map: Record<string, DiffSummary> = {};
    for (const ds of data.workspace.diff_summaries ?? []) {
      map[ds.checkpoint_filename] = ds;
    }
    setDiffSummaries(map);
  }, [commitMessages, resetFlowState, setCollapsedCards, setMode, setSessionTitle]);

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
      const data = await api<CurrentInfo>('GET', `/api/current${activeDiff ? `?active_diff=${encodeURIComponent(activeDiff)}` : ''}`);
      setPlanDocs(data.workspace.plan_docs ?? []);
      setModifiedFiles(data.workspace.modified_files ?? []);
      setActiveDiffFiles(data.workspace.active_diff_files ?? []);
      setDiffFilePaths((data.workspace.active_diff_files ?? []).map((file) => file.path));
      const map: Record<string, DiffSummary> = {};
      for (const ds of data.workspace.diff_summaries ?? []) {
        map[ds.checkpoint_filename] = ds;
      }
      setDiffSummaries(map);
    } catch {
      setPlanDocs([]);
      setModifiedFiles([]);
      setActiveDiffFiles([]);
      setDiffFilePaths([]);
    }
  }, [activeDiff]);

  const refreshWorkspace = useCallback(async () => {
    setActiveDiff(null);
    setDiffFilePaths([]);
    setActiveDiffFiles([]);
    setIsRefreshing(true);
    try {
      const data = await api<CurrentInfo>('GET', '/api/current');
      setPlanDocs(data.workspace.plan_docs ?? []);
      setModifiedFiles(data.workspace.modified_files ?? []);
      const map: Record<string, DiffSummary> = {};
      for (const ds of data.workspace.diff_summaries ?? []) {
        map[ds.checkpoint_filename] = ds;
      }
      setDiffSummaries(map);
    } catch {
      setPlanDocs([]);
      setModifiedFiles([]);
    } finally {
      setIsRefreshing(false);
    }
  }, []);

  const loadCurrent = useCallback(async () => {
    try {
      const data = await api<CurrentInfo>('GET', '/api/current');
      applyCurrentView(data);
      scheduleScrollBottom();
    } catch {
      showToast('Failed to load current session');
    }
  }, [applyCurrentView, scheduleScrollBottom, showToast]);

  useEffect(() => {
    if (!activeDiff) {
      setDiffFilePaths([]);
      setActiveDiffFiles([]);
      return;
    }
    api<CheckpointData>('GET', `/api/diffs/${encodeURIComponent(activeDiff)}`)
      .then((data) => {
        const files = data.files_list ?? [];
        setDiffFilePaths(files.map((file) => file.path));
        setActiveDiffFiles(files);
      })
      .catch(() => {
        setDiffFilePaths([]);
        setActiveDiffFiles([]);
      });
  }, [activeDiff]);

  return {
    sessions,
    currentSession,
    planDocs,
    modifiedFiles,
    isRefreshing,
    diffSummaries,
    activeDiff,
    diffFilePaths,
    activeDiffFiles,
    setSessions,
    setCurrentSession,
    setDiffSummaries,
    setActiveDiff,
    setDiffFilePaths,
    setActiveDiffFiles,
    loadSessions,
    loadWorkspacePanel,
    refreshWorkspace,
    loadCurrent,
    applyCurrentView,
  };
}
