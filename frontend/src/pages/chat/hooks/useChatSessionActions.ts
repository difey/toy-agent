import { useCallback, type Dispatch, type SetStateAction } from 'react';

import { api } from '../../../shared/api';
import type { ChatMessage, CurrentInfo, DiffSummary, SessionSummary } from '../../../shared/types';

export function useChatSessionActions({
  isStreaming,
  commitMessages,
  setCurrentSession,
  setSessionTitle,
  setSessions,
  setDiffSummaries,
  setActiveDiff,
  setDiffFilePaths,
  loadSessions,
  loadWorkspacePanel,
  scheduleScrollBottom,
  showToast,
  resetInteractionState,
  resetFlowState,
  setSidebarOpen,
}: {
  isStreaming: boolean;
  commitMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  setCurrentSession: Dispatch<SetStateAction<CurrentInfo | null>>;
  setSessionTitle: Dispatch<SetStateAction<string>>;
  setSessions: Dispatch<SetStateAction<SessionSummary[]>>;
  setDiffSummaries: Dispatch<SetStateAction<Record<string, DiffSummary>>>;
  setActiveDiff: Dispatch<SetStateAction<string | null>>;
  setDiffFilePaths: Dispatch<SetStateAction<string[]>>;
  loadSessions: () => Promise<void>;
  loadWorkspacePanel: () => Promise<void>;
  scheduleScrollBottom: () => void;
  showToast: (message: string, timeout?: number) => void;
  resetInteractionState: (resetFlowState: () => void) => void;
  resetFlowState: () => void;
  setSidebarOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const newSession = useCallback(async () => {
    if (isStreaming) {
      return;
    }

    resetInteractionState(resetFlowState);
    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>('POST', '/api/sessions');
      setCurrentSession(response.current);
      commitMessages(() => response.current.messages);
      setSessionTitle(response.current.title || 'nanoClaude');
      await loadSessions();
      setSidebarOpen(false);
    } catch {
      showToast('Failed to create session');
    }
  }, [commitMessages, isStreaming, loadSessions, resetFlowState, resetInteractionState, setCurrentSession, setSessionTitle, setSidebarOpen, showToast]);

  const switchSession = useCallback(async (sessionId: string) => {
    if (isStreaming) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>('PUT', `/api/sessions/${encodeURIComponent(sessionId)}`);
      setCurrentSession(response.current);
      commitMessages(() => response.current.messages);
      setSessionTitle(response.current.title || 'nanoClaude');
      setSidebarOpen(false);
      await loadSessions();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch session');
    }
  }, [commitMessages, isStreaming, loadSessions, setCurrentSession, setSessionTitle, setSidebarOpen, showToast]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (isStreaming || !window.confirm('Delete this session?')) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo; sessions: SessionSummary[] }>(
        'DELETE', `/api/sessions/${encodeURIComponent(sessionId)}`,
      );
      commitMessages(() => response.current.messages);
      setSessionTitle(response.current.title || 'nanoClaude');
      setCurrentSession(response.current);
      setSessions(response.sessions);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to delete session');
    }
  }, [commitMessages, isStreaming, setCurrentSession, setSessionTitle, setSessions, showToast]);

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
  }, [commitMessages, isStreaming, loadSessions, scheduleScrollBottom, setCurrentSession, setSessionTitle, showToast]);

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
      setDiffSummaries(() => {
        const newSummaries: Record<string, DiffSummary> = {};
        if (response.current.diff_summaries) {
          for (const ds of response.current.diff_summaries) {
            newSummaries[ds.checkpoint_filename] = ds;
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
  }, [commitMessages, isStreaming, loadSessions, loadWorkspacePanel, scheduleScrollBottom, setActiveDiff, setCurrentSession, setDiffFilePaths, setDiffSummaries, setSessionTitle, showToast]);

  return {
    newSession,
    switchSession,
    deleteSession,
    forkAtMessage,
    rollbackAtMessage,
  };
}
