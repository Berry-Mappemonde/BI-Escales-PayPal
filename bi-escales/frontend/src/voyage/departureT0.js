/**
 * Départ du mini-mix.
 * Reprend simulationT0Iso (naviguide-escales/src/engine/voyageClock.js) :
 * en développement le t0 reste réglable ; en production il est le 12 novembre 2026.
 */
import { DEFAULT_T0_ISO, simulationT0Iso } from "./voyageClock.js";

export const PRODUCTION_T0_ISO = DEFAULT_T0_ISO;

export function resolveDepartureT0(prod, override) {
  if (prod) return PRODUCTION_T0_ISO;
  return override || simulationT0Iso();
}
