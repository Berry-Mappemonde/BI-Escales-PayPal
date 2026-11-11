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
  kind?: string;
  target_id?: string;
  platform_fee_eur?: string | null;
  marina_net_eur?: string | null;
  platform_fee_simulated?: boolean;
  marina_payout_batch_id?: string | null;
  marina_payout_status?: string | null;
  marina_payout_receiver?: string | null;
  contributor?: string | null;
  order_id?: string | null;
  approve_link?: string | null;
  authorization_id?: string | null;
  authorization_expires_at?: string | null;
  setup_token_id?: string | null;
  vault_id?: string | null;
  paypal_status?: string | null;
  capture_id?: string | null;
  refunded_amount_eur?: string;
  pending_refund?: { key: string; amount: string } | null;
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
  captured_eur?: string;
  authorized_eur?: string;
  refunded_eur?: string;
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

export interface PriceUnit {
  kind?: string;
  amount_eur?: string;
  currency?: string;
  free_amount?: boolean;
  label?: string;
  simulated?: boolean;
}

export interface PriceCatalog {
  label?: string;
  simulated?: boolean;
  prices?: PriceUnit[];
}

export interface ScheduleResponse {
  source?: string;
  export?: { escales?: ScheduleEscale[] };
  milestones?: ScheduleEscale[];
  legs?: ScheduleLeg[];
  logbook?: Record<string, LogbookEntry[]>;
  prices?: PriceCatalog;
  clock?: { start?: string };
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
  /** Browser checkout on PayPal Web SDK v6 instead of JS SDK v5. Off unless ESCALES_PAYPAL_JS_V6_ENABLED is set. */
  paypal_js_v6?: boolean;
  clock_pinned?: boolean;
  crew_supporter_plan_id?: string | null;
  demo_treasurer?: boolean;
  channel3?: boolean;
  wishlists?: boolean;
}

/** Public Channel3 catalogue / wishlist line (GET catalog, wishlists). */
export interface Channel3CatalogItem {
  channel3_product_id: string;
  project_id: string;
  name: string;
  category?: string;
  catalog_optional?: boolean;
  core_catalogue?: boolean;
  quantity_needed?: number;
  /** Wishlist line quantity (C3-APP); absent on bare catalogue rows until contract ships on #133. */
  quantity?: number;
  unit_price_amount_minor?: number;
  unit_price_currency?: string;
  unit_price_display?: string;
  merchant?: string;
  merchant_country?: string;
  image_url?: string | null;
  caution?: string | null;
  price_amount_minor?: number;
  price_currency?: string;
  price_display?: string;
  target_amount_minor?: number;
  target_currency?: string;
  target_display?: string;
  funded_amount_minor?: number;
  funded_currency?: string;
  funded_display?: string;
  funded_pct?: number | null;
  fully_funded?: boolean;
  paypal_currency_supported?: boolean;
  catalog_default_target_amount_minor?: number;
  catalog_default_target_currency?: string;
  channel3_buy_url?: string;
  channel3_buy_disclosure?: string;
}

export interface PublicWishlist {
  wishlist_id: string;
  slug?: string;
  title: string;
  published?: boolean;
  updated_at?: string;
  items: Channel3CatalogItem[];
}

export interface TreasurerWishlistItem {
  channel3_product_id: string;
  project_id?: string;
  quantity?: number;
  target_amount_minor?: number;
  target_currency?: string;
}

export interface TreasurerWishlistDoc {
  _id: string;
  slug?: string;
  title: string;
  published?: boolean;
  updated_at?: string;
  items?: TreasurerWishlistItem[];
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
  meta?: { cancelled?: boolean } | null;
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

export interface CaptainToolCall {
  tool: string;
  resource_id?: string;
  read_only?: boolean;
  latency_ms?: number;
  status?: "ok" | "error";
  http_status?: number;
  debug_id?: string;
}

export interface CaptainTrace {
  model_label?: string;
  model_source?: { provider?: string; model?: string; reason?: string };
  latency_ms?: number;
  paypal_tools?: { tools?: string[]; called?: string[]; client?: string; calls?: CaptainToolCall[] } | string[];
  paypal_tool_calls?: CaptainToolCall[];
  /** True when the answer comes from a fixed rule in code on purpose (not a model failure). */
  rule_by_design?: boolean;
  /** Which fixed rule answered, e.g. "voyage_schedule" for boat position and ETA replies. */
  rule_source?: string;
  /** LangSmith run id when tracing is enabled on the server; null otherwise. */
  trace_id?: string | null;
}

export interface CaptainProposal extends CaptainTrace {
  milestone_id: string;
  proposal: "capture" | "void" | "wait" | string;
  report?: string;
  justification?: string;
  pledge_ids: string[];
  pending_authorizations?: PendingAuthorization[];
  evidence_flag?: string;
  model_source?: { provider?: string; model?: string };
  llm_proposal?: { proposal?: string | null; reason?: string | null };
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
  quantity?: string | number;
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

export interface CaptainChatResponse extends CaptainTrace {
  reply: string;
  model_source?: { provider?: string; model?: string; reason?: string };
  model_label?: string;
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
  agentic_action?: {
    kind: string;
    requires_confirm?: boolean;
    preview?: Record<string, string>;
    toolkit_note?: string;
  } | null;
}

export interface PledgeGaugeRow {
  milestone_id: string;
  authorized_count: number;
  authorized_total_eur: number;
  captured_count: number;
  captured_total_eur: number;
  voided_count: number;
}
