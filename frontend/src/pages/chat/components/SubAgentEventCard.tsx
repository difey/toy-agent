import { useCallback, useState } from 'react';

import type { SubAgentEvent } from '../../../shared/types';

export function SubAgentEventCard({ event }: { event: SubAgentEvent }) {
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
