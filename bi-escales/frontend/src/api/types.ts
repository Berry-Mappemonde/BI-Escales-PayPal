export type PledgeStatus = "created" | "authorized" | "captured" | "voided";

export interface PublicPledge {
  id: string;
  status: PledgeStatus;
  intent: string;
  currency: string;
  amount_eur: string;
  description: string;
  milestone_id: string;
  contributor?: string | null;
  order_id?: string;
  approve_link?: string;
  authorization_id?: string | null;
  authorization_expires_at?: string | null;
  created_at?: string;
  history?: string[];
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

export interface CaptainProposal {
  milestone_id: string;
  proposal: "capture" | "void" | "wait" | string;
  report?: string;
  justification?: string;
  pledge_ids: string[];
  evidence_flag?: string;
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
}

export interface PledgeGaugeRow {
  milestone_id: string;
  authorized_count: number;
  authorized_total_eur: number;
  captured_count: number;
  captured_total_eur: number;
  voided_count: number;
}
