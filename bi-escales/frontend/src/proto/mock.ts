/** Static preview data. Nothing here comes from PayPal or the Escales API. */

export const stop = {
  name: "Ajaccio",
  from: "La Rochelle",
  marina: "Port de plaisance Tino Rossi",
  arrivalEta: "2026-11-18",
  departurePlanned: "2026-11-22",
  pledgeEur: 25,
  logbook: [
    { key: "departed", at: "2026-10-28T09:00:00Z" },
    { key: "gibraltar", at: "2026-11-03T18:20:00Z" },
    { key: "cartagena", at: "2026-11-05T07:40:00Z" },
  ],
} as const;

export const review = {
  authorizationId: "7AG23904…",
  authorizationValidTo: "2026-12-03",
} as const;

/** Display states, paired with the PledgeStatus each one stands for in src/api/types.ts. */
export const pledgeStates = [
  { id: "held", backend: "authorized" },
  { id: "saved", backend: "vaulted" },
  { id: "captured", backend: "captured" },
  { id: "released", backend: "voided" },
  { id: "refunded", backend: "refunded" },
] as const;
