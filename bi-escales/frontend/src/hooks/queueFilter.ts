const QUEUED = new Set([
  "created",
  "authorized",
  "vaulted",
  "pending",
  "captured",
  "settled",
  "failed",
  "voided",
  "refunded",
]);

export function isQueuedPledge(status: string): boolean {
  return QUEUED.has(status);
}

export function canCapturePledge(status: string): boolean {
  return status === "authorized" || status === "vaulted";
}

export function canVoidPledge(status: string): boolean {
  return status === "authorized" || status === "vaulted" || status === "pending";
}
