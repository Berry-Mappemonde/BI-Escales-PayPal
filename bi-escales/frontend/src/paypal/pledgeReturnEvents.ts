export const ESCALES_PLEDGE_RETURN = "escales-pledge-return";

export type PledgeReturnOutcome = "authorized" | "error" | "cancel";

export type PledgeReturnDetail = {
  pledgeId: string;
  outcome: PledgeReturnOutcome;
  message?: string;
};

export function emitPledgeReturn(detail: PledgeReturnDetail): void {
  window.dispatchEvent(new CustomEvent(ESCALES_PLEDGE_RETURN, { detail }));
}

export function subscribePledgeReturn(handler: (detail: PledgeReturnDetail) => void): () => void {
  const listener = (event: Event) => {
    handler((event as CustomEvent<PledgeReturnDetail>).detail);
  };
  window.addEventListener(ESCALES_PLEDGE_RETURN, listener);
  return () => window.removeEventListener(ESCALES_PLEDGE_RETURN, listener);
}
