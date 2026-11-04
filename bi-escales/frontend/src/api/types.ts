export type PledgeStatus =
  | "created"
  | "authorized"
  | "vaulted"
  | "pending"
  | "captured"
  | "settled"
  | "failed"
  | "voided"
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

export interface ScheduleEscale {
  milestone_id?: string;
  name?: string;
  title?: string;
  arrival_iso?: string | null;
}

export interface ScheduleResponse {
  source?: string;
  export?: { escales?: ScheduleEscale[] };
  milestones?: ScheduleEscale[];
}

export interface FeatureFlags {
  bryntum?: boolean;
  vault?: boolean;
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
  meta?: { title?: string; arrival_iso?: string | null };
  updated_at?: string;
}

export interface CaptainProposal {
  milestone_id: string;
  proposal: "capture" | "void" | "wait" | string;
  report?: string;
  justification?: string;
  pledge_ids: string[];
  evidence_flag?: string;
  model_source?: { provider?: string; model?: string };
  at?: string;
}

export interface CaptainChatResponse {
  reply: string;
  membership_url?: string;
  suggested_pledge: {
    amount_eur: string;
    currency: string;
    description: string;
    milestone_id: string;
    intent: string;
    item?: string;
  };
  model_source?: { provider?: string; model?: string };
}

export interface PledgeGaugeRow {
  milestone_id: string;
  authorized_count: number;
  authorized_total_eur: number;
  captured_count: number;
  captured_total_eur: number;
  voided_count: number;
  created_count: number;
  vaulted_count: number;
  pending_count: number;
  failed_count: number;
  settled_count: number;
  refunded_count: number;
}
