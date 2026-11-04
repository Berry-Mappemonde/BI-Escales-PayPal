const QUEUED = new Set(["authorized", "vaulted", "pending"]);

export function isQueuedPledge(status: string): boolean {
  return QUEUED.has(status);
}
