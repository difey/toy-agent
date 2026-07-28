import { useState } from 'react';

import type { SessionSummary } from '../../../shared/types';

export function SessionGroup({
  title,
  defaultOpen,
  sessions,
  onSwitch,
  onDelete,
  isStreaming: _isStreaming,
}: {
  title: string;
  defaultOpen: boolean;
  sessions: SessionSummary[];
  onSwitch: (sessionId: string) => void;
  onDelete: (sessionId: string) => void;
  isStreaming: boolean;
}) {
  const [collapsed, setCollapsed] = useState(!defaultOpen);

  return (
    <div className="session-group">
      <div className="session-group-header" onClick={() => setCollapsed(!collapsed)}>
        <span className="collapse-arrow">{collapsed ? '▸' : '▾'}</span>
        <span className="session-group-title">{title}</span>
        <span className="session-group-count">({sessions.length})</span>
      </div>
      {!collapsed && sessions.map((session) => (
        <div
          key={session.id}
          className={`session-item ${session.is_current ? 'active' : ''}`}
          onClick={() => onSwitch(session.id)}
        >
          <div className="info">
            <div className="title">{session.title || '(untitled)'}</div>
            <div className="meta">{session.messages} msgs</div>
          </div>
          <button
            className="del-btn"
            onClick={(event) => {
              event.stopPropagation();
              onDelete(session.id);
            }}
            title="Delete session"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
