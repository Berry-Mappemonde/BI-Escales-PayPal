export const ESCALES_CREW_SUBSCRIBE_RETURN = "escales-crew-subscribe-return";

export type CrewSubscribeReturnOutcome = "confirmed" | "cancel";

export type CrewSubscribeReturnDetail = {
  outcome: CrewSubscribeReturnOutcome;
};

export function emitCrewSubscribeReturn(detail: CrewSubscribeReturnDetail): void {
  window.dispatchEvent(new CustomEvent(ESCALES_CREW_SUBSCRIBE_RETURN, { detail }));
}

export function subscribeCrewSubscribeReturn(handler: (detail: CrewSubscribeReturnDetail) => void): () => void {
  const listener = (event: Event) => {
    handler((event as CustomEvent<CrewSubscribeReturnDetail>).detail);
  };
  window.addEventListener(ESCALES_CREW_SUBSCRIBE_RETURN, listener);
  return () => window.removeEventListener(ESCALES_CREW_SUBSCRIBE_RETURN, listener);
}
