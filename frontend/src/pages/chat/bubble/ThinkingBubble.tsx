import { renderMarkdown } from '../../../shared/markdown';
import type { ChatMessage, SubAgentFlow } from '../../../shared/types';

export function ThinkingBubble({
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
  formatTimestamp,
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
  formatTimestamp: (ts: number | undefined | null) => string;
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
                  <div className="msg-timestamp">{formatTimestamp(message.timestamp)}</div>
                  {message.content}
                </div>
              ) : null}

              {message.role === 'assistant' && message.type === 'text' ? (
                <div className="bubble">
                  <div className="msg-timestamp">{formatTimestamp(message.timestamp)}</div>
                  <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
                </div>
              ) : null}

              {message.type === 'tool_start' ? (
                <div className="tool-card args">
                  <div className="tool-card-header" onClick={() => onToggleCard(index)}>
                    <span className="collapse-arrow">{collapsedCards[index] !== false ? '▸' : '▾'}</span>
                    <span className="badge run">▶ {message.name}</span>
                    <span style={{ color: 'var(--text-dim)' }}>tool call</span>
                    <span className="msg-timestamp" style={{ marginLeft: 'auto', marginRight: 8 }}>{formatTimestamp(message.timestamp)}</span>
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
                    <span className="msg-timestamp" style={{ marginLeft: 'auto', marginRight: 8 }}>{formatTimestamp(message.timestamp)}</span>
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
