import React, { startTransition, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { AppConfig } from './types';
import App from './App';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/inter/800.css';
import './styles.css';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const root = ReactDOM.createRoot(rootElement);

const normalizeConfig = (value: unknown): AppConfig => {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const config: AppConfig = {};

  if (typeof raw.BACKEND_URL === 'string') {
    config.BACKEND_URL = raw.BACKEND_URL;
  }

  if (Array.isArray(raw.MODELS)) {
    const models = raw.MODELS
      .filter((item): item is { id: string; name: string } =>
        !!item &&
        typeof item === 'object' &&
        typeof (item as { id?: unknown }).id === 'string' &&
        typeof (item as { name?: unknown }).name === 'string'
      )
      .map((item) => ({ id: item.id, name: item.name }));
    if (models.length > 0) {
      config.MODELS = models;
    }
  }

  if (typeof raw.FAST_MODEL === 'string') {
    config.FAST_MODEL = raw.FAST_MODEL;
  }

  return config;
};

const configsEqual = (left: AppConfig, right: AppConfig) =>
  JSON.stringify(normalizeConfig(left)) === JSON.stringify(normalizeConfig(right));

const fetchRuntimeConfig = async (): Promise<AppConfig | null> => {
  try {
    const response = await fetch('/config.json', { cache: 'no-store' });
    if (response.ok) {
      return normalizeConfig(await response.json());
    }
    console.warn('Failed to load config.json, keeping current config');
    return null;
  } catch (error) {
    console.error('Error loading config.json:', error);
    return null;
  }
};

function BootstrapApp() {
  const [config, setConfig] = useState<AppConfig>({});

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const latestConfig = await fetchRuntimeConfig();
      if (!latestConfig || cancelled) return;

      startTransition(() => {
        setConfig((currentConfig) => (
          configsEqual(currentConfig, latestConfig) ? currentConfig : latestConfig
        ));
      });
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <React.StrictMode>
      <App config={config} />
    </React.StrictMode>
  );
}

root.render(<BootstrapApp />);
