import { createPledge } from "../api/escales";
import type { PublicPledge } from "../api/types";

export const PLEDGE_CREATE_TIMEOUT_MS = 20_000;

export class PledgeCreateTimeoutError extends Error {
  readonly code = "PLEDGE_CREATE_TIMEOUT" as const;

  constructor() {
    super("PLEDGE_CREATE_TIMEOUT");
    this.name = "PledgeCreateTimeoutError";
  }
}

type CreatePledgeBody = Parameters<typeof createPledge>[0];

/** Sandbox pledge POST with a hard ceiling so the UI cannot hang on "Creating pledge…". */
export function createPledgeWithTimeout(
  body: CreatePledgeBody,
  paypalRequestId: string,
  timeoutMs = PLEDGE_CREATE_TIMEOUT_MS,
): Promise<PublicPledge> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new PledgeCreateTimeoutError()), timeoutMs);
  });
  return Promise.race([createPledge(body, paypalRequestId), timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer);
  });
}

export function pledgeCreateErrorMessage(err: unknown, t: (key: string) => string): string {
  if (err instanceof PledgeCreateTimeoutError) return t("pledge.createTimeout");
  return err instanceof Error ? err.message : String(err);
}
