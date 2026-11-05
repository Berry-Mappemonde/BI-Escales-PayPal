import type { ReactNode } from "react";

/** Named mount points so Escalés features can plug into the BI shell later. */
export type BiShellSlots = {
  /** Left sidebar — marinas list (priority) */
  leftMarinas?: ReactNode;
  /** Left sidebar — projects / filters */
  leftProjects?: ReactNode;
  /** Left sidebar — stopovers / escales */
  leftStopovers?: ReactNode;
  /** Left sidebar — captain chat */
  leftCaptain?: ReactNode;
  /** Left sidebar — membership / crew subscribe */
  leftMembership?: ReactNode;
  /** Map stage (Leaflet). Defaults to empty world map. */
  map?: ReactNode;
  /** BI-format popup host over the map */
  mapPopup?: ReactNode;
  /** Top Console tab body — Treasurer */
  treasurer?: ReactNode;
  /** Right settings drawer body */
  settings?: ReactNode;
  /** Header extras (optional) */
  headerExtras?: ReactNode;
};

export type BiShellView = "map" | "console";
