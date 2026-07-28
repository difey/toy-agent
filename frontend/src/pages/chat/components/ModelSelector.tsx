import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../../shared/api';
import type { ModelItem } from '../../../shared/types';

interface ModelSelectorProps {
  activeModel: string | null | undefined;
  activeProvider: string | null | undefined;
  onOpenProviderSettings: () => void;
  onModelChanged: () => void;
  disabled?: boolean;
}

export function ModelSelector({ activeModel, activeProvider, onOpenProviderSettings, onModelChanged, disabled }: ModelSelectorProps) {
  const [models, setModels] = useState<ModelItem[]>([]);
  const [selectedDisplay, setSelectedDisplay] = useState('');
  const selectRef = useRef<HTMLSelectElement | null>(null);

  const loadModels = useCallback(async () => {
    try {
      const data = await api<{ models: ModelItem[] }>('GET', '/api/models');
      setModels(data.models);
    } catch {
      setModels([]);
    }
  }, []);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  // Set selected display based on active model/provider
  useEffect(() => {
    if (activeModel && activeProvider) {
      // Find matching model item
      const match = models.find(
        (m) => m.provider === activeProvider && m.litellm_model === activeModel
      );
      if (match) {
        setSelectedDisplay(match.display);
        return;
      }
      // Fallback: try to match by model name only
      const fallback = models.find(
        (m) => m.provider === activeProvider && m.model === activeModel.replace('anthropic/', '')
      );
      if (fallback) {
        setSelectedDisplay(fallback.display);
        return;
      }
    }
    setSelectedDisplay('');
  }, [activeModel, activeProvider, models]);

  const handleChange = async (value: string) => {
    if (value === '__settings__') {
      onOpenProviderSettings();
      // Reset selection back to current
      if (selectRef.current) {
        selectRef.current.value = selectedDisplay;
      }
      return;
    }

    // Parse display: "ProviderName/model" → provider and model
    const slashIdx = value.indexOf('/');
    if (slashIdx === -1) return;

    const provider = value.substring(0, slashIdx);
    const model = value.substring(slashIdx + 1);

    setSelectedDisplay(value);

    try {
      await api('POST', '/api/model', { model, provider });
      onModelChanged();
    } catch {
      // Revert on error
      if (selectRef.current) {
        selectRef.current.value = selectedDisplay;
      }
    }
  };

  const groups = models.reduce<Record<string, ModelItem[]>>((acc, m) => {
    if (!acc[m.provider]) acc[m.provider] = [];
    acc[m.provider].push(m);
    return acc;
  }, {});

  const handleFocus = useCallback(() => {
    void loadModels();
  }, [loadModels]);

  return (
    <div className="model-selector">
      <select
        ref={selectRef}
        value={selectedDisplay || ''}
        onChange={(e) => void handleChange(e.target.value)}
        onFocus={handleFocus}
        disabled={disabled}
        title={selectedDisplay || '选择模型'}
      >
        <option value="" disabled={models.length > 0} hidden={models.length > 0}>
          {models.length === 0 ? '暂无模型，请先设置 Provider' : '选择模型...'}
        </option>
        <option value="__settings__">⚙️ 设置 Provider</option>
        {Object.entries(groups).map(([providerName, items]) => (
          <optgroup key={providerName} label={providerName}>
            {items.map((m) => (
              <option key={m.display} value={m.display}>
                {m.display}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </div>
  );
}
