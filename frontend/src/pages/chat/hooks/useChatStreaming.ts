import { useCallback, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';

import { cloneFlow } from '../utils/chatHelpers';
import type {
  ChatMessage,
  CurrentInfo,
  FileChangeItem,
  PermissionRequest,
  QuestionDialog,
  SubAgent,
  SubAgentFlow,
} from '../../../shared/types';

interface ChatResponse {
  response_id: string;
  accepted?: boolean;
}

export function useChatStreaming({
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
}: {
  commitMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  messagesRef: MutableRefObject<ChatMessage[]>;
  delegateFlowCounterRef: MutableRefObject<number>;
  setCollapsedCards: Dispatch<SetStateAction<Record<number, boolean>>>;
  setDelegateFlowMap: Dispatch<SetStateAction<Record<number, string>>>;
  setSubAgentFlows: Dispatch<SetStateAction<Record<string, SubAgentFlow>>>;
  setInputText: Dispatch<SetStateAction<string>>;
  setIsStreaming: Dispatch<SetStateAction<boolean>>;
  setSessionTitle: Dispatch<SetStateAction<string>>;
  applyCurrentView: (view: CurrentInfo) => void;
  resetFlowState: () => void;
  scheduleScrollBottom: () => void;
  enqueueQuestion: (payload: QuestionDialog) => void;
  receivePermissionRequest: (payload: PermissionRequest) => void;
  clearAfterStreamDone: () => void;
  loadCurrent: () => Promise<void>;
  updateLastAssistantMessage: (updater: (message: ChatMessage) => ChatMessage | null) => void;
  showToast: (message: string, timeout?: number) => void;
}) {
  const eventSourceRef = useRef<EventSource | null>(null);
  const responseIdRef = useRef<string | null>(null);

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    responseIdRef.current = null;
  }, []);

  const attachEventSource = useCallback((responseId: string) => {
    closeEventSource();
    responseIdRef.current = responseId;
    const eventSource = new EventSource(`/api/events?response_id=${encodeURIComponent(responseId)}`);
    eventSourceRef.current = eventSource;
    let toolPlaceholder: number | null = null;

    eventSource.addEventListener('message', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as Record<string, unknown>;
        const role = (payload.role as ChatMessage['role'] | undefined) ?? 'assistant';
        const type = (payload.type as ChatMessage['type'] | undefined) ?? 'text';

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
          return;
        }

        if (type === 'diff_summary') {
          commitMessages((prev) => [...prev, {
            role: 'diff_summary',
            type: 'diff_summary',
            checkpoint_filename: String(payload.checkpoint_filename ?? ''),
            summary: payload.summary as { files_changed: number; files: FileChangeItem[] } | undefined,
            timestamp: typeof payload.timestamp === 'number' ? payload.timestamp : undefined,
          } as ChatMessage]);
          scheduleScrollBottom();
        }
      });

      eventSource.addEventListener('question', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as QuestionDialog;
        enqueueQuestion(payload);
        scheduleScrollBottom();
      });

      eventSource.addEventListener('permission_request', (event) => {
        const payload = JSON.parse((event as MessageEvent<string>).data) as PermissionRequest;
        receivePermissionRequest(payload);
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
        clearAfterStreamDone();
        setIsStreaming(false);
        updateLastAssistantMessage((last) => (last.content.trim() ? last : null));
        try {
          await loadCurrent();
        } catch {
          // loadCurrent already handles errors.
        }
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
      });
  }, [clearAfterStreamDone, closeEventSource, commitMessages, delegateFlowCounterRef, enqueueQuestion, loadCurrent, messagesRef, receivePermissionRequest, scheduleScrollBottom, setCollapsedCards, setDelegateFlowMap, setIsStreaming, setSubAgentFlows, updateLastAssistantMessage]);

  const startChatStream = useCallback(async (text: string) => {
    resetFlowState();
    setInputText('');
    setIsStreaming(true);
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

      const data = (await response.json()) as ChatResponse & { current?: CurrentInfo };
      if (!data.response_id) {
        throw new Error('No response_id');
      }

      const currentInfo = data.current;
      if (currentInfo) {
        applyCurrentView(currentInfo);
        setSessionTitle(currentInfo.session_meta.title || 'nanoClaude');
      }

      attachEventSource(data.response_id);
    } catch (error) {
      updateLastAssistantMessage(() => ({ role: 'assistant', type: 'text', content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}` }));
      setIsStreaming(false);
      showToast(error instanceof Error ? error.message : 'Failed to send message');
    }
  }, [applyCurrentView, attachEventSource, resetFlowState, scheduleScrollBottom, setIsStreaming, setSessionTitle, setInputText, showToast, updateLastAssistantMessage]);

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
  }, [closeEventSource, scheduleScrollBottom, setIsStreaming, updateLastAssistantMessage]);

  const sendFollowup = useCallback(async (text: string): Promise<boolean> => {
    const responseId = responseIdRef.current;
    if (!responseId) {
      return false;
    }
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, response_id: responseId }),
      });
      if (!response.ok) {
        const errorData = (await response.json()) as { detail?: string };
        throw new Error(errorData.detail || 'Follow-up request failed');
      }

      const data = (await response.json()) as ChatResponse & { current?: CurrentInfo };
      // 后端监测到当前没有正在运行的回复时，会把这条消息回落为一条
      // 新的普通消息并开启新任务：此时响应带 response_id 但无 accepted，
      // 前端需要切换到新的 SSE 流继续接收。
      if (data.response_id && !data.accepted) {
        const currentInfo = data.current;
        if (currentInfo) {
          applyCurrentView(currentInfo);
          setSessionTitle(currentInfo.session_meta.title || 'nanoClaude');
        }
        attachEventSource(data.response_id);
      }
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Failed to send follow-up');
      return false;
    }
  }, [applyCurrentView, attachEventSource, setSessionTitle, showToast]);

  return {
    startChatStream,
    stopResponse,
    sendFollowup,
    getResponseId: () => responseIdRef.current,
    closeEventSource,
  };
}
