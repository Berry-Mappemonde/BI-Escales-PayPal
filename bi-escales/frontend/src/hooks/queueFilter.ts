const QUEUED = new Set(["authorized", "vaulted", "pending"]);
/** Captured money the treasurer may still refund (fully or the remainder). */
const REFUNDABLE = new Set(["captured", "partially_refunded"]);

export function isQueuedPledge(status: string): boolean {
  return QUEUED.has(status);
}

export function isRefundablePledge(status: string): boolean {
  return REFUNDABLE.has(status);
}

/** Rows the treasurer queue lists: pending decisions plus refundable captures. */
export function isTreasurerQueueRow(status: string): boolean {
  return isQueuedPledge(status) || isRefundablePledge(status);
}
