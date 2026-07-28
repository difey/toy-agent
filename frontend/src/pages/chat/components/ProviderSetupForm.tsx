import { useEffect, useMemo, useState } from 'react';
import { api } from '../../../shared/api';
import type { ProviderInfo } from '../../../shared/types';

const PROVIDER_TYPES = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'ollama', label: 'Ollama' },
  { value: 'custom', label: 'Custom (OpenAI-compatible)' },
];

const DEFAULT_BASE_URLS: Record<string, string> = {
  deepseek: 'https://api.deepseek.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  ollama: 'http://localhost:11434/v1',
};

interface ProviderSetupFormProps {
  /** If provided, we're editing an existing provider (name is read-only) */
  editProvider?: ProviderInfo | null;
  existingNames: string[];
  onSave: () => void;
  onCancel: () => void;
}

export function ProviderSetupForm({ editProvider, existingNames, onSave, onCancel }: ProviderSetupFormProps) {
  const isEditing = !!editProvider;
  const [name, setName] = useState(editProvider?.name ?? '');
  const [type, setType] = useState(editProvider?.type ?? 'openai');
  const [apiKey, setApiKey] = useState(editProvider?.api_key ?? '');
  const [baseUrl, setBaseUrl] = useState(editProvider?.base_url ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const nameError = useMemo(() => {
    if (isEditing) return '';
    if (!name.trim()) return '名称不能为空';
    if (existingNames.includes(name.trim())) return `Provider '${name}' 已存在`;
    return '';
  }, [name, existingNames, isEditing]);

  // Auto-fill base URL when type changes (only for new providers)
  useEffect(() => {
    if (!isEditing && !baseUrl) {
      setBaseUrl(DEFAULT_BASE_URLS[type] ?? '');
    }
  }, [type, isEditing, baseUrl]);

  const handleSubmit = async () => {
    if (!isEditing && nameError) return;
    setSaving(true);
    setError('');

    try {
      const body = {
        name: name.trim(),
        type,
        api_key: apiKey.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      };

      if (isEditing) {
        await api<ProviderInfo>('PUT', `/api/providers/${encodeURIComponent(editProvider!.name)}`, body);
      } else {
        await api<ProviderInfo>('POST', '/api/providers', body);
      }
      onSave();
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="provider-form">
      <h3 className="provider-form-title">{isEditing ? '编辑 Provider' : '添加 Provider'}</h3>

      <div className="form-group">
        <label>名称</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如: My OpenAI"
          disabled={isEditing}
          style={isEditing ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
        />
        {nameError ? <div className="error-text">{nameError}</div> : null}
      </div>

      <div className="form-group">
        <label>Provider 类型</label>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {PROVIDER_TYPES.map((pt) => (
            <option key={pt.value} value={pt.value}>{pt.label}</option>
          ))}
        </select>
      </div>

      <div className="form-group">
        <label>API Key</label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="留空则使用环境变量"
          autoComplete="off"
        />
        <div className="hint">可留空，优先使用环境变量</div>
      </div>

      <div className="form-group">
        <label>Base URL</label>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={type === 'openai' || type === 'custom' ? '例如: https://api.openai.com/v1' : ''}
        />
        <div className="hint">留空则使用当前类型的默认地址</div>
      </div>

      {error ? <div className="error-text">{error}</div> : null}

      <div className="provider-form-actions">
        <button className="btn btn-secondary" onClick={onCancel} disabled={saving}>取消</button>
        <button className="btn" onClick={() => void handleSubmit()} disabled={saving || (!isEditing && !!nameError)}>
          {saving ? <span className="spinner" /> : <span>{isEditing ? '💾 保存' : '✅ 添加并获取模型'}</span>}
        </button>
      </div>
    </div>
  );
}
