export type Uuid = string;
export type IsoDate = string;
export type IsoDateTime = string;

export type PublicationState = "draft" | "review" | "published" | "corrected" | "retracted";
export type PublicPublicationState = "published" | "corrected";
export type RiskLevel = "low" | "medium" | "high" | "critical";
export type ClaimImportance = "context" | "supporting" | "key";
export type ConfidenceGrade = "A" | "B" | "C" | "D" | "E";
export type EvidenceStatus = "verified" | "pending_cross_check" | "monitoring" | "corrected";
export type EvidenceStance = "supports" | "contradicts" | "context";
export type SourceTier = "primary" | "authoritative" | "secondary" | "community";

export interface Evidence {
  id: Uuid;
  source_item_id: Uuid;
  url: string;
  quote: string;
  locator: string;
  stance: EvidenceStance;
  source_tier: SourceTier;
}

export interface Claim {
  id: Uuid;
  text: string;
  importance: ClaimImportance;
  evidence_ids: Uuid[];
  confidence: number;
}

export interface ScoreSnapshot {
  id: Uuid;
  event_id: Uuid;
  score: number;
  components: Record<string, number>;
  algorithm_version: string;
  calculated_at: IsoDateTime;
}

export interface EventVersion {
  id: Uuid;
  event_id: Uuid;
  version: number;
  title: string;
  summary: string;
  claims: Claim[];
  changed_at: IsoDateTime;
  change_note: string;
}

/** Canonical API fact. UI-only relevance or recommendations do not belong here. */
export interface PublicEvent {
  id: Uuid;
  slug: string;
  title: string;
  summary: string;
  category: string;
  published_at: IsoDateTime;
  updated_at: IsoDateTime;
  state: PublicPublicationState;
  risk: RiskLevel;
  confidence_grade: ConfidenceGrade;
  evidence_status: EvidenceStatus;
  public_version: number;
  claims: Claim[];
  evidence: Evidence[];
  source_ids: Uuid[];
  score: ScoreSnapshot | null;
  tags: string[];
  versions: EventVersion[];
}

export interface ActionRecipe {
  id: Uuid;
  event_id: Uuid;
  title: string;
  audience: string;
  effort_minutes: number;
  steps: string[];
  expected_outcome: string;
  caveats: string[];
}

/** Immutable v1 envelope for a public event included in a briefing. */
export interface BriefingEventSnapshot {
  snapshot_schema_version: 1;
  event_id: Uuid;
  public_version: number;
  event: PublicEvent;
}

export interface BriefingSnapshot {
  id: Uuid;
  briefing_date: IsoDate;
  title: string;
  executive_summary: string;
  event_ids: Uuid[];
  event_snapshots: BriefingEventSnapshot[];
  generated_at: IsoDateTime;
  cutoff_at: IsoDateTime;
  state: PublicationState;
}

export interface Correction {
  id: Uuid;
  event_id: Uuid;
  published_at: IsoDateTime;
  reason: string;
  before: string;
  after: string;
}

export interface CoverageSnapshot {
  period: string;
  total_events: number;
  categories: Record<string, number>;
  source_tiers: Record<string, number>;
  evidence_coverage: number;
  generated_at: IsoDateTime;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export type EventPage = Page<PublicEvent>;
export type ActionRecipePage = Page<ActionRecipe>;
export type CorrectionPage = Page<Correction>;

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface RadarResponse {
  generated_at: IsoDateTime;
  knowledge_cutoff: IsoDateTime;
  headline_events: PublicEvent[];
  recommended_actions: ActionRecipe[];
  latest_briefing: BriefingSnapshot | null;
  coverage: CoverageSnapshot;
}

export interface PublicFactEnvelope {
  contract_version: "1.0.0";
  knowledge_cutoff: IsoDateTime;
  events: PublicEvent[];
}

export interface PersonalizedLens {
  relevance: number;
  explanation: string;
  recommended_action?: string;
}

export interface PersonalizedRadarView {
  contract_version: "1.0.0";
  knowledge_cutoff: IsoDateTime;
  items: Array<{ fact: PublicEvent; lens: PersonalizedLens }>;
}

export interface Citation {
  event_slug: string;
  title: string;
  url: string;
}

export interface Answer {
  answer: string;
  citations: Citation[];
  generated_by: string;
}

export interface UserPublic {
  id: Uuid;
  email: string;
  display_name: string;
  active: boolean;
  created_at: IsoDateTime;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

export interface Team {
  id: Uuid;
  name: string;
  owner_id: Uuid;
  member_ids: Uuid[];
}

export interface PublicationCheck {
  valid: boolean;
  automatic_publish_allowed: boolean;
  reasons: string[];
}

/** Existing localized web projection. It is not an independent public-fact source. */
export interface RadarEventProjection {
  slug: string;
  title: string;
  kicker: string;
  summary: string;
  delta: string;
  score: number;
  confidence: ConfidenceGrade;
  evidence: "已验证" | "待交叉验证" | "监测中" | "已更正";
  kind: "模型" | "产品" | "研究" | "基础设施" | "政策" | "安全";
  time: string;
  timeAgo: string;
  action: string;
  actionSlug: string;
  waveform: number[];
  sources: Array<{
    name: string;
    href: string;
    kind: "第一方" | "独立报道" | "论文" | "监管文件";
  }>;
  unknowns: string[];
  affected: string[];
}

export interface ActionRecipeProjection {
  slug: string;
  title: string;
  duration: string;
  difficulty: "5 分钟" | "30 分钟" | "半天";
  outcome: string;
  risk: string;
  relatedEvent: string;
  steps: string[];
}

export interface StoryProjection {
  slug: string;
  title: string;
  status: string;
  summary: string;
  movement: string;
  events: string[];
}

export interface BriefingProjection {
  date: IsoDate;
  title: string;
  count: number;
  note: string;
}

export interface ValidationIssue {
  path: string;
  code: string;
  message: string;
}

export type ValidationResult =
  | { ok: true; errors: readonly [] }
  | { ok: false; errors: readonly ValidationIssue[] };

export interface ApiRouteContract {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  audience: "system" | "public" | "identity" | "editorial";
  successStatus: number;
  responseContract: string;
  openapiSchema?: string;
  openapiItemSchema?: string;
}

export interface WebRouteContract {
  path: string;
  sourceFiles: string[];
  dataExports: string[];
  personalized?: boolean;
}

export const CONTRACT_VERSION: "1.0.0";
export const API_VERSION: "0.1.0";
export const API_ROUTE_CONTRACTS: readonly ApiRouteContract[];
export const WEB_ROUTE_CONTRACTS: readonly WebRouteContract[];

export function validatePublicEvent(value: unknown): ValidationResult;
export function validateRadarResponse(value: unknown): ValidationResult;
export function validateEventPage(value: unknown): ValidationResult;
export function validateActionRecipe(value: unknown): ValidationResult;
export function validateActionRecipePage(value: unknown): ValidationResult;
export function validateBriefingSnapshot(value: unknown): ValidationResult;
export function validateCorrection(value: unknown): ValidationResult;
export function validateCorrectionPage(value: unknown): ValidationResult;
export function validateCoverageSnapshot(value: unknown): ValidationResult;
export function validateAnswer(value: unknown): ValidationResult;
export function validatePublicFactEnvelope(value: unknown): ValidationResult;
export function validatePersonalizationBoundary(
  baseline: unknown,
  personalized: unknown,
): ValidationResult;
export function validateRadarEventProjection(value: unknown): ValidationResult;
export function validateActionRecipeProjection(value: unknown): ValidationResult;
export function validateStoryProjection(value: unknown): ValidationResult;
export function validateBriefingProjection(value: unknown): ValidationResult;
export function selectPublicFacts(event: PublicEvent): PublicEvent;
export function publicFactFingerprint(event: PublicEvent): string;
export function assertValid<T>(result: ValidationResult, value: T): T;
