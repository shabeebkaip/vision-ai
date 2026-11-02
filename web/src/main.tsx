import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createApiClient } from './api';
import { App } from './App';
import { initAppI18n } from './i18n';
import './styles/index.css';

const i18n = initAppI18n();
const api = createApiClient();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App api={api} i18n={i18n} />
  </StrictMode>,
);
