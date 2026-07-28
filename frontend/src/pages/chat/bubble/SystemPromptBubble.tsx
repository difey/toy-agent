import { useState } from 'react';

export function SystemPromptBubble({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="system-prompt-overview">
      <div
        className={`system-prompt-card ${expanded ? 'expanded' : ''}`}
        onClick={() => setExpanded(!expanded)}
      >
        <span className="system-prompt-icon">⚙️</span>
        <span className="system-prompt-label">System Prompt</span>
        {expanded ? <span className="system-prompt-badge">visible</span> : null}
        <span className="system-prompt-arrow">{expanded ? '▾' : '▸'}</span>
      </div>
      {expanded ? (
        <div className="system-prompt-body">
          <pre>{content}</pre>
        </div>
      ) : null}
    </div>
  );
}
