import { useEffect, useState } from 'react';

import { api } from '../../../shared/api';
import type { CheckpointData } from '../../../shared/types';

export function DiffDetailView({ diffFilename }: { diffFilename: string }) {
  const [diffData, setDiffData] = useState<CheckpointData | null>(null);
  const [diffError, setDiffError] = useState(false);

  useEffect(() => {
    setDiffData(null);
    setDiffError(false);
    api<CheckpointData>('GET', `/api/diffs/${encodeURIComponent(diffFilename)}`)
      .then((data) => {
        setDiffData(data);
      })
      .catch(() => {
        setDiffError(true);
      });
  }, [diffFilename]);

  if (!diffData) {
    return (
      <div className="diff-loading">
        <div className="spinner" />
        <span>{diffError ? 'Failed to load diff' : 'Loading diff...'}</span>
      </div>
    );
  }

  const files = diffData.files || {};
  const fileList: { path: string; status: string }[] = [];

  for (const path of Object.keys(files.modified || {})) {
    fileList.push({ path, status: 'modified' });
  }
  for (const path of Object.keys(files.deleted || {})) {
    fileList.push({ path, status: 'deleted' });
  }
  for (const path of files.added || []) {
    fileList.push({ path, status: 'added' });
  }
  for (const path of files.binary || []) {
    fileList.push({ path, status: 'binary' });
  }

  const statusIcon: Record<string, string> = {
    added: '🆕',
    deleted: '🗑️',
    modified: '📄',
    binary: '🗄️',
  };

  return (
    <div className="diff-detail-view">
      {fileList.length === 0 ? (
        <div className="workspace-panel-empty">No file changes in this checkpoint</div>
      ) : (
        fileList.map((file) => (
          <div key={file.path} className="diff-file-item">
            <div className="diff-file-header">
              <span>
                {statusIcon[file.status] || '📄'}
              </span>
              <span className="diff-file-name">{file.path}</span>
              {file.status === 'binary' ? (
                <span className="diff-binary-badge">(binary)</span>
              ) : (
                <span className={`diff-file-status status-${file.status}`}>{file.status}</span>
              )}
            </div>
          </div>
        ))
      )}
      {fileList.length > 0 ? (
        <div className="diff-detail-footer">
          <span className="diff-stat-files">{diffData.summary.files_changed} files</span>
        </div>
      ) : null}
    </div>
  );
}
