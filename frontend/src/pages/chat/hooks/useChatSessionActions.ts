import { useCallback, type Dispatch, type SetStateAction } from 'react';

import { api } from '../../../shared/api';
import type { CurrentInfo, SessionSummary } from '../../../shared/types';

export function useChatSessionActions({
  isStreaming,
  setActiveDiff,
  setDiffFilePaths,
  applyCurrentView,
  scheduleScrollBottom,
  showToast,
  resetInteractionState,
  resetFlowState,
  setSidebarOpen,
}: {
  isStreaming: boolean;
  setActiveDiff: Dispatch<SetStateAction<string | null>>;
  setDiffFilePaths: Dispatch<SetStateAction<string[]>>;
  applyCurrentView: (view: CurrentInfo) => void;
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
      applyCurrentView(response.current);
      setSidebarOpen(false);
    } catch {
      showToast('Failed to create session');
    }
  }, [applyCurrentView, isStreaming, resetFlowState, resetInteractionState, setSidebarOpen, showToast]);

  const switchSession = useCallback(async (sessionId: string) => {
    if (isStreaming) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>('PUT', `/api/sessions/${encodeURIComponent(sessionId)}`);
      applyCurrentView(response.current);
      setSidebarOpen(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to switch session');
    }
  }, [applyCurrentView, isStreaming, setSidebarOpen, showToast]);

  const deleteSession = useCallback(async (sessionId: string) => {
    if (isStreaming || !window.confirm('Delete this session?')) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo; sessions: SessionSummary[] }>(
        'DELETE', `/api/sessions/${encodeURIComponent(sessionId)}`,
      );
      applyCurrentView(response.current);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to delete session');
    }
  }, [applyCurrentView, isStreaming, showToast]);

  const forkAtMessage = useCallback(async (messageIndex: number) => {
    if (isStreaming) {
      return;
    }

    try {
      const response = await api<{ ok: boolean; current: CurrentInfo }>(
        'POST', '/api/sessions/fork', { message_index: messageIndex },
      );
      applyCurrentView(response.current);
      showToast('Forked new session');
      scheduleScrollBottom();
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to fork session');
    }
  }, [applyCurrentView, isStreaming, scheduleScrollBottom, showToast]);

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
      applyCurrentView(response.current);
      setActiveDiff(null);
      setDiffFilePaths([]);
      showToast('回滚成功');
      scheduleScrollBottom();
    } catch (error) {
      showToast(error instanceof Error ? error.message : '回滚失败');
    }
  }, [applyCurrentView, isStreaming, scheduleScrollBottom, setActiveDiff, setDiffFilePaths, showToast]);

  return {
    newSession,
    switchSession,
    deleteSession,
    forkAtMessage,
    rollbackAtMessage,
  };
}
