import type { DiffSummary } from '../../../shared/types';

export function DiffOverviewBubble({
  summary, isActive, onClick,
}: {
  summary: DiffSummary; isActive: boolean; onClick: () => void;
}) {
  return (
    <div className="diff-overview">
      <div className={`diff-overview-card ${isActive ? 'active' : ''}`} onClick={onClick}>
        <span className="diff-overview-icon">📝</span>
        <span className="diff-overview-stats">
          <span className="diff-stat-files">{summary.summary.files_changed} file{summary.summary.files_changed !== 1 ? 's' : ''}</span>
        </span>
        <span className="diff-overview-arrow">{isActive ? '▾' : '▸'}</span>
      </div>
    </div>
  );
}
