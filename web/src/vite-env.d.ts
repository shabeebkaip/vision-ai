/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Cloud API base URL, e.g. https://api.example.sa/v1. Empty = in-memory mock. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
