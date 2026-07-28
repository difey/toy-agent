import type { PermissionRequest } from '../../../shared/types';

export function PermissionOverlay({
  activePermission,
  onDeny,
  onAllow,
  onAlwaysAllow,
}: {
  activePermission: PermissionRequest | null;
  onDeny: () => void;
  onAllow: () => void;
  onAlwaysAllow: () => void;
}) {
  if (!activePermission) {
    return null;
  }

  return (
    <div id="permission-overlay">
      <div className="permission-card">
        <div className="p-header">🔒 File Access Permission Request</div>
        <div className="p-body">
          <div style={{ marginBottom: 10 }}>
            <strong>Tool:</strong>
            <span style={{ fontFamily: 'var(--mono)', color: 'var(--accent)', marginLeft: 6 }}>{activePermission.tool}</span>
            wants to access a file outside the working directory.
          </div>
          <div className="p-path-block">
            <div className="p-path-label">Requested Path</div>
            <div className="p-path-value">{activePermission.target}</div>
          </div>
          <div className="p-path-block" style={{ marginTop: 2 }}>
            <div className="p-path-label">Resolved Path</div>
            <div className="p-path-value" style={{ color: 'var(--accent4)' }}>
              {activePermission.resolved_path}
            </div>
          </div>
          <div className="p-cwd">
            📁 Working Directory: <span style={{ color: 'var(--text-bright)', fontFamily: 'var(--mono)' }}>{activePermission.cwd}</span>
          </div>
        </div>
        <div className="p-actions">
          <button className="p-btn deny" onClick={onDeny}>
            Deny
          </button>
          <button className="p-btn allow" onClick={onAllow}>
            Allow
          </button>
          <button className="p-btn always" onClick={onAlwaysAllow}>
            Always Allow
          </button>
        </div>
      </div>
    </div>
  );
}
