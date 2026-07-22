import { useEffect, useMemo, useState } from 'react';

import { renderMarkdown } from '../../shared/markdown';
import type { PlanDocResponse } from '../../shared/types';

function formatModifiedTimestamp(value: number | null | undefined): string {
  if (!value) {
    return '';
  }
  const date = new Date(value * 1000);
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function PlanViewApp() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [planDoc, setPlanDoc] = useState<PlanDocResponse | null>(null);

  useEffect(() => {
    const loadPlan = async () => {
      try {
        const response = await fetch('/api/plan-doc');
        const data = (await response.json()) as PlanDocResponse;
        setPlanDoc(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    void loadPlan();
  }, []);

  const renderedContent = useMemo(() => renderMarkdown(planDoc?.content || ''), [planDoc?.content]);

  const downloadDoc = () => {
    if (!planDoc?.content) {
      return;
    }
    const blob = new Blob([planDoc.content], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = planDoc.filename || 'plan.md';
    link.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <>
        <div id="header">
          <span className="name" />
          <span className="meta" />
          <span className="spacer" />
          <button id="download-btn" disabled>
            ⬇ Download .md
          </button>
        </div>
        <div id="loading">
          <div className="spinner" />
          <br />
          <br />
          Loading plan document...
        </div>
      </>
    );
  }

  if (error) {
    return <div id="loading" style={{ color: 'var(--danger)' }}>Failed to load: {error}</div>;
  }

  if (!planDoc?.exists) {
    return (
      <div id="empty-state">
        <div className="icon">📋</div>
        <h2>No Plan Document</h2>
        <p>
          No plan document has been created yet.
          <br />
          Switch to Plan mode and ask AI to create a plan.
        </p>
      </div>
    );
  }

  return (
    <>
      <div id="header">
        <span className="name">{planDoc.filename}</span>
        <span className="meta">
          {formatModifiedTimestamp(planDoc.modified)} · {((planDoc.size || 0) / 1000).toFixed(1)} KB
        </span>
        <span className="spacer" />
        <button id="download-btn" onClick={downloadDoc}>
          ⬇ Download .md
        </button>
      </div>
      <div id="content" dangerouslySetInnerHTML={{ __html: renderedContent }} />
    </>
  );
}
