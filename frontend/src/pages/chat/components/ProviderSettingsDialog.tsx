import { useCallback, useEffect, useState } from 'react';
import { api } from '../../../shared/api';
import type { ProviderInfo } from '../../../shared/types';
import { ProviderSetupForm } from './ProviderSetupForm';

interface ProviderSettingsDialogProps {
  onClose: () => void;
  onProvidersChanged: () => void;
}

export function ProviderSettingsDialog({ onClose, onProvidersChanged }: ProviderSettingsDialogProps) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [selectedProvider, setSelectedProvider] = useState<ProviderInfo | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [editingProvider, setEditingProvider] = useState<ProviderInfo | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [modelsText, setModelsText] = useState('');
  const [savingModels, setSavingModels] = useState(false);

  const loadProviders = useCallback(async () => {
    try {
      const data = await api<{ providers: ProviderInfo[] }>('GET', '/api/providers');
      setProviders(data.providers);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);

  const handleSelectProvider = (p: ProviderInfo) => {
    setSelectedProvider(p);
    setShowAddForm(false);
    setEditingProvider(null);
    setModelsText(p.models.join('\n'));
  };

  const handleEdit = (p: ProviderInfo) => {
    setEditingProvider(p);
    setShowAddForm(false);
  };

  const handleDelete = async (name: string) => {
    try {
      await api('DELETE', `/api/providers/${encodeURIComponent(name)}`);
      setDeleteConfirm(null);
      if (selectedProvider?.name === name) {
        setSelectedProvider(null);
      }
      await loadProviders();
      onProvidersChanged();
    } catch {
      // ignore
    }
  };

  const handleRefresh = async (name: string) => {
    setRefreshing(name);
    try {
      await api('POST', `/api/providers/${encodeURIComponent(name)}/refresh`);
      await loadProviders();
      // Update selected provider if it's the one refreshed
      if (selectedProvider?.name === name) {
        const updated = providers.find(p => p.name === name);
        if (updated) setSelectedProvider(updated);
      }
      onProvidersChanged();
    } catch {
      // ignore
    } finally {
      setRefreshing(null);
    }
  };

  const handleSaveModels = async () => {
    if (!selectedProvider) return;
    setSavingModels(true);
    try {
      const models = modelsText
        .split('\n')
        .map(s => s.trim())
        .filter(s => s.length > 0);
      const updated = await api<ProviderInfo>(
        'PATCH',
        `/api/providers/${encodeURIComponent(selectedProvider.name)}/models`,
        { models },
      );
      setSelectedProvider(updated);
      // Refresh provider list in background
      await loadProviders();
      onProvidersChanged();
    } catch {
      // ignore
    } finally {
      setSavingModels(false);
    }
  };

  const handleFormSave = () => {
    setShowAddForm(false);
    setEditingProvider(null);
    setSelectedProvider(null);
    void loadProviders();
    onProvidersChanged();
  };

  const handleFormCancel = () => {
    setShowAddForm(false);
    setEditingProvider(null);
  };

  const existingNames = providers.map(p => p.name);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="provider-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="provider-dialog-header">
          <h2>Provider 设置</h2>
          <button className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="provider-dialog-body">
          {/* ── Left Panel: Provider List ── */}
          <div className="provider-left-panel">
            <button
              className="provider-add-btn"
              onClick={() => { setShowAddForm(true); setEditingProvider(null); setSelectedProvider(null); }}
            >
              + 添加 Provider
            </button>

            <div className="provider-list">
              {providers.length === 0 ? (
                <div className="provider-list-empty">暂无配置的 Provider</div>
              ) : (
                providers.map((p) => (
                  <div
                    key={p.name}
                    className={`provider-list-item ${selectedProvider?.name === p.name ? 'active' : ''}`}
                    onClick={() => handleSelectProvider(p)}
                  >
                    <div className="provider-item-info">
                      <span className="provider-item-name">{p.name}</span>
                      <span className="provider-item-type">{p.label}</span>
                    </div>
                    <div className="provider-item-actions">
                      <button
                        className="provider-action-btn edit-btn"
                        title="编辑"
                        onClick={(e) => { e.stopPropagation(); handleEdit(p); }}
                      >
                        ✏️
                      </button>
                      <button
                        className="provider-action-btn refresh-btn"
                        title="刷新模型列表"
                        disabled={refreshing === p.name}
                        onClick={(e) => { e.stopPropagation(); void handleRefresh(p.name); }}
                      >
                        {refreshing === p.name ? '⏳' : '🔄'}
                      </button>
                      <button
                        className="provider-action-btn delete-btn"
                        title="删除"
                        onClick={(e) => { e.stopPropagation(); setDeleteConfirm(p.name); }}
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── Right Panel: Content ── */}
          <div className="provider-right-panel">
            {showAddForm || editingProvider ? (
              <ProviderSetupForm
                editProvider={editingProvider}
                existingNames={existingNames}
                onSave={handleFormSave}
                onCancel={handleFormCancel}
              />
            ) : selectedProvider ? (
              <div className="provider-models-panel">
                <h3>{selectedProvider.name} — 模型列表</h3>
                <p className="hint" style={{ margin: '0 0 8px', fontSize: 12 }}>
                  每行一个模型名，修改后点击保存：
                </p>
                <textarea
                  className="provider-models-textarea"
                  value={modelsText}
                  onChange={(e) => setModelsText(e.target.value)}
                  placeholder="例如:&#10;claude-sonnet-5&#10;gpt-5.5&#10;gpt-5.6-luna&#10;claude-opus-4.8&#10;deepseek-r1"
                  rows={10}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
                  <span className="hint" style={{ fontSize: 12 }}>
                    共 {modelsText.split('\n').filter(s => s.trim()).length} 个模型
                  </span>
                  <button
                    className="btn"
                    onClick={handleSaveModels}
                    disabled={savingModels}
                  >
                    {savingModels ? <span className="spinner" /> : '💾 保存模型'}
                  </button>
                </div>
              </div>
            ) : (
              <div className="provider-right-placeholder">
                选择左侧一个 Provider 查看其模型列表，或点击「+ 添加 Provider」新增。
              </div>
            )}
          </div>
        </div>

        {/* ── Delete Confirmation Dialog ── */}
        {deleteConfirm ? (
          <div className="modal-overlay" onClick={() => setDeleteConfirm(null)}>
            <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
              <h3>确认删除</h3>
              <p>确定删除 provider '<strong>{deleteConfirm}</strong>' 吗？</p>
              <div className="confirm-dialog-actions">
                <button className="btn btn-secondary" onClick={() => setDeleteConfirm(null)}>否</button>
                <button className="btn btn-danger" onClick={() => void handleDelete(deleteConfirm)}>是，删除</button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
