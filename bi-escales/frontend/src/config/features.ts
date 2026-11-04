export function featureAgGridEnabled(): boolean {
  const raw = import.meta.env.VITE_ENABLE_AG_GRID ?? "0";
  return ["1", "true", "yes", "on"].includes(String(raw).trim().toLowerCase());
}
