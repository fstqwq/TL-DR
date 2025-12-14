import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppConfig } from './types';

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error("Could not find root element to mount to");
}

const root = ReactDOM.createRoot(rootElement);

const loadConfig = async (): Promise<AppConfig> => {
  try {
    const response = await fetch('/config.json');
    if (response.ok) {
      const config = await response.json();
      return config;
    }
    console.warn('Failed to load config.json, using defaults');
    return {};
  } catch (error) {
    console.error('Error loading config.json:', error);
    return {};
  }
};

const bootstrap = async () => {
  const [config, appModule] = await Promise.all([
    loadConfig(),
    import('./App')
  ]);
  const { default: App } = appModule;
  root.render(
    <React.StrictMode>
      <App config={config} />
    </React.StrictMode>
  );
};

bootstrap().catch((err) => {
  console.error('Bootstrap failed', err);
  root.render(<div>Failed to start app.</div>);
});
