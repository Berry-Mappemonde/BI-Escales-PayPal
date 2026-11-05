// Explicit comparisons are folded by Vite, so disabled builds omit the AG Grid chunk.
export function featureAgGridEnabled(): boolean {
  return import.meta.env.VITE_ENABLE_AG_GRID === "1"
    || import.meta.env.VITE_ENABLE_AG_GRID === "true"
    || import.meta.env.VITE_ENABLE_AG_GRID === "yes"
    || import.meta.env.VITE_ENABLE_AG_GRID === "on";
}
