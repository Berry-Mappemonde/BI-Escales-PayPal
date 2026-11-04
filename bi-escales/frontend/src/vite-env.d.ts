/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_PAYPAL_CLIENT_ID?: string;
  readonly VITE_ENABLE_AG_GRID?: string;
  readonly VITE_API_BASE?: string;
  readonly VITE_NAVIGUIDE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
