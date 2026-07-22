import { useEffect, useMemo, useState } from 'react';

import { api } from '../../shared/api';
import type { SetupStatus } from '../../shared/types';

const PRESET_MODELS = [
  { model: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'deepseek' },
  { model: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash (fast, cheap)', provider: 'deepseek' },
  { model: 'gpt-4o', label: 'OpenAI GPT-4o', provider: 'openai' },
  { model: 'gpt-4.1-mini', label: 'OpenAI GPT-4.1 Mini (fast, cheap)', provider: 'openai' },
  { model: 'claude-sonnet-4-20250514', label: 'Anthropic Claude Sonnet 4', provider: 'anthropic' },
] as const;

function detectProvider(model: string): string {
  const normalized = model.toLowerCase();
  if (normalized.startsWith('gpt-') || normalized.startsWith('o1-') || normalized.startsWith('o3-') || normalized.startsWith('o4-')) {
    return 'openai';
  }
  if (normalized.startsWith('deepseek')) {
    return 'deepseek';
  }
  if (normalized.startsWith('claude')) {
    return 'anthropic';
  }
  return 'openai';
}

function providerLabel(provider: string): string {
  const labels: Record<string, string> = {
    openai: 'OpenAI',
    deepseek: 'DeepSeek',
    anthropic: 'Anthropic',
    ollama: 'Ollama',
  };
  return labels[provider] || provider;
}

export function SetupApp() {
  const [step, setStep] = useState(1);
  const [selectedModel, setSelectedModel] = useState<string>(PRESET_MODELS[0].model);
  const [customModel, setCustomModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [hasEnvVars, setHasEnvVars] = useState(false);

  const displayModel = useMemo(
    () => (selectedModel === '__custom__' ? customModel : selectedModel),
    [customModel, selectedModel],
  );
  const customProvider = useMemo(
    () => (customModel ? providerLabel(detectProvider(customModel)) : ''),
    [customModel],
  );
  const customValid = customModel.trim().length > 0;
  const providerName = providerLabel(detectProvider(displayModel || PRESET_MODELS[0].model));
  const canProceed = (selectedModel !== '__custom__' || customValid) && (hasEnvVars || apiKey.trim().length > 0);
  const maskedKey = useMemo(() => {
    if (!apiKey) {
      return '(使用环境变量)';
    }
    if (apiKey.length <= 8) {
      return '*'.repeat(apiKey.length);
    }
    return `${apiKey.slice(0, 4)}${'*'.repeat(apiKey.length - 8)}${apiKey.slice(-4)}`;
  }, [apiKey]);

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const status = await api<SetupStatus>('GET', '/api/setup-status');
        if (status.configured) {
          window.location.href = '/';
          return;
        }
        setHasEnvVars(Boolean(status.has_env_vars));
        if (status.model) {
          const preset = PRESET_MODELS.find((entry) => entry.model === status.model);
          if (preset) {
            setSelectedModel(status.model);
          } else {
            setSelectedModel('__custom__');
            setCustomModel(status.model);
          }
        }
      } catch {
        // Ignore startup races while the backend finishes booting.
      }
    };

    void checkStatus();
  }, []);

  const nextStep = () => {
    setError('');
    setStep(2);
  };

  const saveConfig = async () => {
    setSaving(true);
    setError('');
    try {
      const model = selectedModel === '__custom__' ? customModel.trim() : selectedModel;
      await api('POST', '/api/setup', { model, api_key: apiKey || undefined });
      setStep(3);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存配置失败，请重试');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div id="app">
      <div className="card">
        {step === 1 ? (
          <>
            <div className="logo">
              <div className="icon">🤖</div>
              <h1>
                nano<span>Claude</span>
              </h1>
              <p>coding assistant — 配置向导</p>
            </div>
            <div className="step-indicator">
              <span className="step-dot active" />
              <span className="step-dot" />
              <span className="step-dot" />
            </div>

            {hasEnvVars ? (
              <div className="env-note">✅ 检测到环境变量已配置，你可直接 <strong>跳过</strong> 配置，或按需修改。</div>
            ) : null}

            <div className="form-group">
              <label>选择模型</label>
              <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)}>
                {PRESET_MODELS.map((preset) => (
                  <option key={preset.model} value={preset.model}>
                    {preset.label}
                  </option>
                ))}
                <option value="__custom__">自定义模型...</option>
              </select>
              <div className="hint">Provider 根据模型名称自动识别：deepseek → DeepSeek, gpt- → OpenAI, claude → Anthropic</div>
            </div>

            {selectedModel === '__custom__' ? (
              <div className="form-group">
                <label>自定义模型名称</label>
                <input
                  value={customModel}
                  placeholder="例如: gpt-4.1-mini 或 claude-sonnet-4-20250514"
                  onChange={(event) => setCustomModel(event.target.value)}
                />
                {customModel && !customValid ? <div className="error-text">模型名称不能为空</div> : null}
                {customModel && customProvider ? (
                  <div className="hint">
                    检测到 Provider: <span className="provider-badge">{customProvider}</span>
                  </div>
                ) : null}
              </div>
            ) : null}

            {!hasEnvVars ? (
              <div className="form-group">
                <label>API Key</label>
                <input
                  type="password"
                  value={apiKey}
                  placeholder="输入 API key..."
                  autoComplete="off"
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <div className="hint">支持的环境变量：NANO_CLAUDE_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY</div>
              </div>
            ) : null}

            <button className="btn" onClick={nextStep} disabled={!canProceed || saving}>
              {saving ? <span className="spinner" /> : <span>继续</span>}
            </button>

            {hasEnvVars ? (
              <div className="skip-link">
                <a onClick={() => (window.location.href = '/')}>⚡ 跳过配置，直接使用</a>
              </div>
            ) : null}
          </>
        ) : null}

        {step === 2 ? (
          <>
            <div className="logo">
              <div className="icon">📋</div>
              <h1>确认配置</h1>
            </div>
            <div className="step-indicator">
              <span className="step-dot done" />
              <span className="step-dot active" />
              <span className="step-dot" />
            </div>

            <div className="summary">
              <div className="row">
                <span className="label">模型</span>
                <span className="value">{displayModel}</span>
              </div>
              <div className="row">
                <span className="label">Provider</span>
                <span className="value">{providerName}</span>
              </div>
              {apiKey ? (
                <div className="row">
                  <span className="label">API Key</span>
                  <span className="value">{maskedKey}</span>
                </div>
              ) : null}
            </div>

            <button className="btn" onClick={() => void saveConfig()} disabled={saving}>
              {saving ? <span className="spinner" /> : <span>💾 保存并继续</span>}
            </button>

            <div className="skip-link">
              <a onClick={() => setStep(1)}>← 返回修改</a>
            </div>
          </>
        ) : null}

        {step === 3 ? (
          <div className="success-screen">
            <div className="check">🎉</div>
            <h2>配置完成！</h2>
            <p>nanoClaude 已准备就绪，即将进入主界面。</p>
            <div className="summary">
              <div className="row">
                <span className="label">模型</span>
                <span className="value">{displayModel}</span>
              </div>
              <div className="row">
                <span className="label">状态</span>
                <span className="value" style={{ color: 'var(--accent2)' }}>
                  ✅ 已保存
                </span>
              </div>
            </div>
            <button className="btn" onClick={() => (window.location.href = '/')}>
              🚀 开始使用
            </button>
          </div>
        ) : null}

        {error ? (
          <div style={{ marginTop: 16, padding: '10px 14px', background: 'rgba(248,81,73,0.1)', border: '1px solid var(--danger)', borderRadius: 'var(--radius-sm)', color: 'var(--danger)', fontSize: 13 }}>
            ⚠️ {error}
          </div>
        ) : null}
      </div>
    </div>
  );
}
