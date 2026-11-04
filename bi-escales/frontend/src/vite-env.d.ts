/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PAYPAL_CLIENT_ID?: string;
  readonly VITE_ENABLE_AG_GRID?: string;
  readonly VITE_ENABLE_AG_STUDIO?: string;
  readonly VITE_AG_GRID_LICENSE_KEY?: string;
  readonly VITE_AG_STUDIO_LLM_ENDPOINT?: string;
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
