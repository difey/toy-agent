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
  WorkspacePanelResponse,
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

  const refreshWorkspace = useCallback(async () => {
    setActiveDiff(null);
    setDiffFilePaths([]);
    setActiveDiffFiles([]);
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
      if (data.diff_summaries) {
        const map: Record<string, DiffSummary> = {};
        for (const ds of data.diff_summaries) {
          map[ds.checkpoint_filename] = ds;
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
  }, [commitMessages, loadSessions, loadWorkspacePanel, resetFlowState, scheduleScrollBottom, setCollapsedCards, setMode, setSessionTitle, showToast]);

  useEffect(() => {
    if (!activeDiff) {
      setDiffFilePaths([]);
      setActiveDiffFiles([]);
      return;
    }
    setDiffFilePaths([]);
    setActiveDiffFiles([]);
    api<CheckpointData>('GET', `/api/diffs/${encodeURIComponent(activeDiff)}`)
      .then((data) => {
        const paths: string[] = [];
        const files: ModifiedFileItem[] = [];
        if (data.files) {
          for (const path of Object.keys(data.files.modified || {})) {
            paths.push(path);
            files.push({ path, status: 'modified' });
          }
          for (const path of Object.keys(data.files.deleted || {})) {
            paths.push(path);
            files.push({ path, status: 'deleted' });
          }
          for (const path of data.files.added || []) {
            paths.push(path);
            files.push({ path, status: 'added' });
          }
          for (const path of data.files.binary || []) {
            paths.push(path);
            files.push({ path, status: 'binary' });
          }
        }
        setDiffFilePaths(paths);
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
  };
}
