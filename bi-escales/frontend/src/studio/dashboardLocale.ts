import { formatPledgeStatus, studioLanguage, studioT } from "./locale";
import { milestoneLabel, type StopNames } from "../utils/milestoneLabel";
import type { LedgerPledge } from "./dashboardLedger";

const en = {
  title: "Treasurer dashboard",
  readOnly: "Read-only ledger",
  demo: "Sandbox demo",
  ledger: "Pledges",
  crew: "Crew memberships",
  charts: "Chart",
  report: "Studio report",
  agent: "Studio agent",
  refresh: "Refresh data",
  close: "Close",
  loading: "Loading the treasurer ledger…",
  loadError: "The ledger could not be loaded. Check your treasurer access and try again.",
  crewLoading: "Loading Crew memberships…",
  crewError: "Crew memberships could not be loaded.",
  crewDemo: "Membership records are available with treasurer access.",
  crewEmpty: "No memberships match these filters.",
  memberships: "Memberships",
  active: "Active memberships",
  member: "Member email",
  subscription: "Subscription",
  updated: "Last updated",
  unknown: "Unknown",
  count: "Records",
  target: "Funding target",
  status: "Status",
  type: "Funding type",
  currency: "Currency",
  captured: "Net captured",
  authorized: "Authorised",
  vaulted: "Saved in Vault",
  voided: "Voided",
  refunded: "Refunded",
  pledged: "Pledged",
  search: "Find a funding target",
  searchPlaceholder: "Stop, leg or project",
  allTypes: "All funding types",
  allStatuses: "All statuses",
  groupBy: "Group by",
  ungrouped: "Individual pledges",
  clear: "Clear filters",
  stop: "Stop",
  leg: "Leg",
  common: "Common fund",
  project: "Project",
  unassigned: "Unassigned",
  noRows: "No pledges match these filters.",
  refundUnknown: "Some refund amounts are unavailable. A dash marks any affected total.",
  chartTitle: "Ledger amounts by status",
  chartEmpty: "No amounts to chart for these filters.",
  fundingTitle: "Funding by destination",
  agentAdding: "Adding funding totals by destination.",
  agentAdded: "Funding totals by destination are on the page.",
  promptFunding: "Show funding by destination",
  promptFundingText: "Show crowdfunding totals by funding destination.",
};

const fr: typeof en = {
  title: "Tableau de bord de trésorerie",
  readOnly: "Grand livre en lecture seule",
  demo: "Démo sandbox",
  ledger: "Promesses",
  crew: "Adhésions Crew",
  charts: "Graphique",
  report: "Rapport Studio",
  agent: "Agent Studio",
  refresh: "Actualiser les données",
  close: "Fermer",
  loading: "Chargement du grand livre…",
  loadError: "Impossible de charger le grand livre. Vérifiez votre accès trésorier et réessayez.",
  crewLoading: "Chargement des adhésions Crew…",
  crewError: "Impossible de charger les adhésions Crew.",
  crewDemo: "Les adhésions sont accessibles avec la clé trésorier.",
  crewEmpty: "Aucune adhésion ne correspond à ces filtres.",
  memberships: "Adhésions",
  active: "Adhésions actives",
  member: "Courriel du membre",
  subscription: "Abonnement",
  updated: "Dernière mise à jour",
  unknown: "Inconnu",
  count: "Entrées",
  target: "Destination du financement",
  status: "Statut",
  type: "Type de financement",
  currency: "Devise",
  captured: "Net encaissé",
  authorized: "Autorisé",
  vaulted: "Enregistré dans Vault",
  voided: "Annulé",
  refunded: "Remboursé",
  pledged: "Promis",
  search: "Rechercher une destination",
  searchPlaceholder: "Escale, étape ou projet",
  allTypes: "Tous les types",
  allStatuses: "Tous les statuts",
  groupBy: "Regrouper par",
  ungrouped: "Promesses individuelles",
  clear: "Effacer les filtres",
  stop: "Escale",
  leg: "Étape",
  common: "Fonds commun",
  project: "Projet",
  unassigned: "Sans destination",
  noRows: "Aucune promesse ne correspond à ces filtres.",
  refundUnknown: "Certains montants remboursés sont indisponibles. Un tiret signale les totaux concernés.",
  chartTitle: "Montants par statut",
  chartEmpty: "Aucun montant à afficher pour ces filtres.",
  fundingTitle: "Financement par destination",
  agentAdding: "Ajout des totaux par destination de financement.",
  agentAdded: "Les totaux par destination de financement sont sur la page.",
  promptFunding: "Voir le financement par destination",
  promptFundingText: "Afficher les totaux du financement participatif par destination.",
};

export function dashboardCopy(language: string) {
  return studioLanguage(language) === "fr" ? fr : en;
}

export function ledgerStatus(status: string, language: string): string {
  const copy = dashboardCopy(language);
  if (status === "captured") return studioT(language)("studio.captured");
  if (status === "authorized" || status === "vaulted" || status === "voided") return copy[status];
  return formatPledgeStatus(status, language);
}

export function fundingLabel(row: LedgerPledge, names: StopNames | undefined, language: string): string {
  const copy = dashboardCopy(language);
  if (row.type === "common") return copy.common;
  if (row.type === "project" && row.target) {
    return row.target.replaceAll("-", " ").replace(/^./, (letter) => letter.toLocaleUpperCase(language));
  }
  return milestoneLabel(names, row.target, (_, { from, to }) => `${from} → ${to}`) || copy.unassigned;
}
