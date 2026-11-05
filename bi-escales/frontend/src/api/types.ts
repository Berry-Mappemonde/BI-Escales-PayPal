export type PledgeStatus =
  | "created"
  | "authorized"
  | "vaulted"
  | "pending"
  | "captured"
  | "settled"
  | "failed"
  | "voided"
  | "partially_refunded"
  | "refunded";

export interface PublicPledge {
  id: string;
  status: PledgeStatus;
  intent: string;
  payment_mode?: string;
  currency: string;
  amount_eur: string;
  description: string;
  milestone_id: string;
  contributor?: string | null;
  order_id?: string | null;
  approve_link?: string | null;
  authorization_id?: string | null;
  authorization_expires_at?: string | null;
  setup_token_id?: string | null;
  vault_id?: string | null;
  paypal_status?: string | null;
  capture_id?: string | null;
  created_at?: string;
  history?: string[];
}

export interface FundLine {
  id?: string;
  at?: string;
  kind?: string;
  amount_eur: string;
  currency?: string;
  description?: string | null;
  pledge_id?: string | null;
  pledge_kind?: string | null;
}

export interface FundView {
  milestone_id: string;
  currency: string;
  income_eur: string;
  spending_eur: string;
  balance_eur: string;
  overdrawn?: boolean;
  income?: FundLine[];
  spending?: FundLine[];
}

/** Public GET /projects/{id}/fund (N33). Donor-facing totals only. */
export interface PublicProjectDonationTotal {
  project_id: string;
  currency: string;
  amount_eur: string;
  donation_count: number;
  refunded_eur: string;
}

export interface ScheduleEscale {
  milestone_id?: string;
  name?: string;
  title?: string;
  arrival_iso?: string | null;
}

export interface ScheduleLeg {
  id: string;
  from_name?: string;
  to_name?: string;
  departure_iso?: string;
  arrival_iso?: string;
  capture_on?: string;
}

export interface ScheduleResponse {
  source?: string;
  export?: { escales?: ScheduleEscale[] };
  milestones?: ScheduleEscale[];
  legs?: ScheduleLeg[];
  logbook?: Record<string, LogbookEntry[]>;
}

export interface LogbookEntry {
  t: string;
  pos?: { lat?: number; lon?: number };
  label_fr?: string;
  label_en?: string;
  kind?: string;
}

export interface FeatureFlags {
  bryntum?: boolean;
  vault?: boolean;
  card_fields?: boolean;
  vault_on_purchase?: boolean;
  wallet_pay?: boolean;
  clock_pinned?: boolean;
  crew_supporter_plan_id?: string | null;
  demo_treasurer?: boolean;
}

export interface TreasurerAccessOptions {
  demoTreasurer?: boolean;
}

export interface ClockSettleAction {
  pledge_id: string;
  action: string;
  status?: string;
  capture_id?: string;
  paypal_status?: string;
  detail?: string;
}

export interface ClockSettleResult {
  now?: string;
  actions: ClockSettleAction[];
}

export interface ClockSettleResponse {
  start?: string;
  now?: string;
  settled?: ClockSettleResult;
}

export interface MilestoneEvidence {
  met?: boolean;
  facts?: Record<string, unknown>;
  flag?: string;
  provider?: string;
  source?: string;
  recorded_at?: string;
}

export interface Milestone {
  id: string;
  evidence: MilestoneEvidence[];
  proposal?: CaptainProposal | null;
  updated_at?: string;
}

export interface PendingAuthorization {
  pledge_id: string;
  authorization_id?: string | null;
  status?: string;
  amount_eur?: string;
  currency?: string;
  description?: string | null;
  kind?: string | null;
  target_id?: string | null;
  milestone_id?: string;
  authorization_expires_at?: string | null;
  authorization_age_days?: number | null;
}

export interface CaptainProposal {
  milestone_id: string;
  proposal: "capture" | "void" | "wait" | string;
  report?: string;
  justification?: string;
  pledge_ids: string[];
  pending_authorizations?: PendingAuthorization[];
  paypal_tool_calls?: { tool: string; resource_id?: string }[];
  evidence_flag?: string;
  at?: string;
}

export interface CartPledge {
  amount_eur: string;
  description: string;
  milestone_id: string;
  kind?: string;
  target_id?: string;
  lang?: string;
}

export interface CartLine {
  kind?: string;
  description?: string;
  amount_eur?: string;
  milestone_id?: string;
  intent?: string;
  price_label?: string;
  pledge?: CartPledge;
}

export interface PledgeCart {
  lines?: CartLine[];
  amount_eur?: string;
  currency?: string;
  description?: string;
  milestone_id?: string;
  intent?: string;
  clock_start?: string;
  eta?: string | null;
  simulated?: boolean;
  price_label?: string;
}

export interface CaptainChatResponse {
  reply: string;
  membership_url?: string;
  model_source?: { provider?: string; model?: string; reason?: string };
  model_label?: string;
  paypal_tools?: { tools?: string[]; called?: string[]; client?: string } | string[];
  suggested_pledge?: {
    amount_eur: string;
    currency: string;
    description: string;
    milestone_id: string;
    intent: string;
    item?: string;
    kind?: string;
  } | null;
  cart?: PledgeCart | null;
}

export interface PledgeGaugeRow {
  milestone_id: string;
  authorized_count: number;
  authorized_total_eur: number;
  captured_count: number;
  captured_total_eur: number;
  voided_count: number;
}
