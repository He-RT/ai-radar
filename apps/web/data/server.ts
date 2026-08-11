import "server-only";

import {
  validateActionRecipePage,
  validateBriefingSnapshot,
  validateEventPage,
  validatePublicEvent,
  validateRadarResponse
} from "@zhenfu/contracts";
import type {
  ActionRecipe as ApiActionRecipe,
  ActionRecipePage,
  BriefingSnapshot,
  EventPage,
  PublicEvent,
  RadarResponse,
  ValidationResult
} from "@zhenfu/contracts";
import {
  actions as fixtureActions,
  briefings as fixtureBriefings,
  radarEvents as fixtureEvents,
  stories as fixtureStories
} from "./radar";
import type { ActionRecipe, Briefing, EvidenceState, EventClaim, EventKind, RadarEvent, Source, Story } from "./radar";
import { isArxivUrl } from "./source-classification";

export type RadarDataMode = "api" | "fixture";

export interface RadarDataset {
  mode: RadarDataMode;
  knowledgeCutoff: string;
  generatedAt: string;
  totalSignals: number;
  evidenceCoverage: number;
  events: RadarEvent[];
  actions: ActionRecipe[];
  stories: Story[];
  briefings: Briefing[];
}

export interface BriefingDataset {
  mode: RadarDataMode;
  briefing: Briefing;
  events: RadarEvent[];
}

export class RadarApiError extends Error {
  constructor(public readonly status: number, path: string) {
    super(`AI Radar API ${path} returned ${status}`);
    this.name = "RadarApiError";
  }
}

function requestedMode(): RadarDataMode {
  const explicit = process.env.RADAR_DATA_MODE;
  if (process.env.NODE_ENV === "production") {
    if (explicit !== "api") throw new Error("RADAR_DATA_MODE=api is required in production");
    return "api";
  }
  if (explicit === "api" || explicit === "fixture") return explicit;
  return "fixture";
}

function fixtureDataset(): RadarDataset {
  return {
    mode: "fixture",
    knowledgeCutoff: "2026-08-12T08:30:00+08:00",
    generatedAt: "2026-08-12T08:35:00+08:00",
    totalSignals: 18,
    evidenceCoverage: 1,
    events: fixtureEvents,
    actions: fixtureActions,
    stories: fixtureStories,
    briefings: fixtureBriefings
  };
}

function evidenceState(value: PublicEvent["evidence_status"]): EvidenceState {
  const labels: Record<PublicEvent["evidence_status"], EvidenceState> = {
    verified: "已验证",
    pending_cross_check: "待交叉验证",
    monitoring: "监测中",
    corrected: "已更正"
  };
  return labels[value];
}

function eventKind(category: string): EventKind {
  const normalized = category.toLowerCase();
  if (normalized.includes("model")) return "模型";
  if (normalized.includes("product")) return "产品";
  if (normalized.includes("research")) return "研究";
  if (normalized.includes("infra") || normalized.includes("chip")) return "基础设施";
  if (normalized.includes("security")) return "安全";
  return "政策";
}

function sourceKind(source: PublicEvent["evidence"][number]): Source["kind"] {
  if (source.source_tier === "primary") return "第一方";
  if (source.source_tier === "authoritative") return "监管文件";
  return isArxivUrl(source.url) ? "论文" : "独立报道";
}

function waveform(score: number): number[] {
  return Array.from({ length: 18 }, (_, index) => {
    const baseline = Math.max(4, score * (0.18 + index / 26));
    const pulse = index === 12 ? score : baseline + ((index * 17) % 13);
    return Math.round(Math.min(score, pulse));
  });
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).format(new Date(value));
}

function mapAction(action: ApiActionRecipe, eventSlugById: Map<string, string>): ActionRecipe {
  const duration = action.effort_minutes <= 5 ? "5 分钟" : action.effort_minutes <= 30 ? "30 分钟" : "半天";
  return {
    slug: action.id,
    title: action.title,
    duration,
    difficulty: duration,
    outcome: action.expected_outcome,
    risk: action.caveats.join("；") || "先在可回滚范围内验证。",
    relatedEvent: eventSlugById.get(action.event_id) ?? "",
    steps: action.steps
  };
}

function mapEvent(event: PublicEvent, actionByEventId: Map<string, ActionRecipe>): RadarEvent {
  const score = Math.round(event.score?.score ?? 0);
  const action = actionByEventId.get(event.id);
  const sources = event.evidence.map((item, index) => ({
    id: item.id,
    name: item.locator.trim() || `证据 ${index + 1}`,
    href: item.url,
    kind: sourceKind(item)
  }));
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const claims: EventClaim[] = event.claims.map((claim) => {
    const evidence = claim.evidence_ids.map((id) => sourceById.get(id)).find(Boolean);
    return {
      id: claim.id,
      text: claim.text,
      status: claim.confidence >= 0.8 && evidence ? "成立" : "待验证",
      evidenceLabel: evidence?.name ?? "未关联公开证据",
      evidenceHref: evidence?.href
    };
  });
  const latest = event.versions.find((version) => version.version === event.public_version);
  return {
    apiId: event.id,
    slug: event.slug,
    title: event.title,
    kicker: `${eventKind(event.category)} / ${event.tags[0] ?? "事实增量"}`,
    summary: event.summary,
    delta: latest?.change_note ?? "事件案卷已更新",
    score,
    confidence: event.confidence_grade,
    evidence: evidenceState(event.evidence_status),
    kind: eventKind(event.category),
    time: formatTime(event.updated_at),
    timeAgo: `版本 ${event.public_version}`,
    action: action?.title ?? "继续观察本事件的下一项验证",
    actionSlug: action?.slug ?? "",
    waveform: waveform(score),
    sources,
    unknowns: event.claims
      .filter((claim) => claim.confidence < 0.72)
      .map((claim) => claim.text)
      .concat(event.claims.every((claim) => claim.confidence >= 0.72) ? ["真实采用与跨场景表现仍需持续回访"] : []),
    affected: event.tags.slice(0, 3),
    claims
  };
}

async function getJson(path: string): Promise<unknown> {
  const base = process.env.API_ORIGIN ?? (process.env.NODE_ENV === "production" ? "http://api:8000" : "http://localhost:8000");
  const response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
    headers: { Accept: "application/json" },
    next: { revalidate: 60 },
    signal: AbortSignal.timeout(Number(process.env.RADAR_API_TIMEOUT_MS ?? 8000))
  });
  if (!response.ok) throw new RadarApiError(response.status, path);
  return response.json();
}

function assertContract<T>(name: string, value: unknown, validation: ValidationResult): T {
  if (!validation.ok) {
    throw new Error(`AI Radar ${name} contract violation: ${validation.errors.map((item) => `${item.path}:${item.code}`).join(", ")}`);
  }
  return value as T;
}

async function getEventPage(): Promise<EventPage> {
  const firstValue = await getJson("/api/v1/events?limit=100&offset=0");
  const first = assertContract<EventPage>("event page", firstValue, validateEventPage(firstValue));
  const items = [...first.items];
  for (let offset = items.length; offset < first.total; offset += 100) {
    const value = await getJson(`/api/v1/events?limit=100&offset=${offset}`);
    const page = assertContract<EventPage>("event page", value, validateEventPage(value));
    items.push(...page.items);
  }
  return { ...first, items };
}

async function getActionPage(): Promise<ActionRecipePage> {
  const firstValue = await getJson("/api/v1/actions?limit=100&offset=0");
  const first = assertContract<ActionRecipePage>("action page", firstValue, validateActionRecipePage(firstValue));
  const items = [...first.items];
  for (let offset = items.length; offset < first.total; offset += 100) {
    const value = await getJson(`/api/v1/actions?limit=100&offset=${offset}`);
    const page = assertContract<ActionRecipePage>("action page", value, validateActionRecipePage(value));
    items.push(...page.items);
  }
  return { ...first, items };
}

const storySlug: Record<EventKind, string> = {
  "模型": "models",
  "产品": "products",
  "研究": "research",
  "基础设施": "infrastructure",
  "政策": "policy",
  "安全": "security"
};

function apiStories(events: RadarEvent[]): Story[] {
  const groups = new Map<EventKind, RadarEvent[]>();
  for (const event of events) groups.set(event.kind, [...(groups.get(event.kind) ?? []), event]);
  return [...groups.entries()].map(([kind, values]) => ({
    slug: storySlug[kind],
    title: `${kind}变化追踪`,
    status: values.some((event) => event.evidence === "待交叉验证") ? "持续验证" : "证据已更新",
    summary: `围绕「${values[0].title}」等已发布事件，持续记录证据与判断边界。`,
    movement: `关联 ${values.length} 条已发布事件`,
    events: values.map((event) => event.slug)
  }));
}

function briefingEvidenceCoverage(briefing: BriefingSnapshot): number {
  const events = briefing.event_snapshots.map((snapshot) => snapshot.event);
  const claims = events.flatMap((event) => event.claims.map((claim) => ({ event, claim })));
  if (!claims.length) return 1;
  const covered = claims.filter(({ event, claim }) => {
    const evidenceIds = new Set(event.evidence.map((evidence) => evidence.id));
    return claim.evidence_ids.some((evidenceId) => evidenceIds.has(evidenceId));
  }).length;
  return covered / claims.length;
}

function mapBriefing(briefing: BriefingSnapshot): Briefing {
  const evidenceCoverage = briefingEvidenceCoverage(briefing);
  return {
    date: briefing.briefing_date,
    title: briefing.title,
    count: briefing.event_snapshots.length,
    note: `知识截止 ${formatTime(briefing.cutoff_at)} · 证据覆盖 ${Math.round(evidenceCoverage * 100)}%`,
    summary: briefing.executive_summary,
    cutoffAt: briefing.cutoff_at,
    generatedAt: briefing.generated_at,
    eventSlugs: briefing.event_snapshots.map((snapshot) => snapshot.event.slug)
  };
}

export async function getRadarDataset(): Promise<RadarDataset> {
  if (requestedMode() === "fixture") return fixtureDataset();

  const [radarValue, eventPage, actionPage] = await Promise.all([
    getJson("/api/v1/radar"),
    getEventPage(),
    getActionPage()
  ]);
  const radar = assertContract<RadarResponse>("radar", radarValue, validateRadarResponse(radarValue));
  const eventSlugById = new Map(eventPage.items.map((event) => [event.id, event.slug]));
  const actions = actionPage.items.map((action) => mapAction(action, eventSlugById));
  const actionByEventId = new Map(actionPage.items.map((action, index) => [action.event_id, actions[index]]));
  const events = eventPage.items.map((event) => mapEvent(event, actionByEventId));

  return {
    mode: "api",
    knowledgeCutoff: radar.knowledge_cutoff,
    generatedAt: radar.generated_at,
    totalSignals: radar.coverage.total_events,
    evidenceCoverage: radar.coverage.evidence_coverage,
    events,
    actions,
    stories: apiStories(events),
    briefings: radar.latest_briefing
      ? [mapBriefing(radar.latest_briefing)]
      : []
  };
}

export async function getBriefingDataset(date: string): Promise<BriefingDataset | null> {
  const mode = requestedMode();
  if (mode === "fixture") {
    const dataset = fixtureDataset();
    const briefing = dataset.briefings.find((item) => item.date === date);
    return briefing ? { mode, briefing, events: dataset.events } : null;
  }

  try {
    const value = await getJson(`/api/v1/briefings/${encodeURIComponent(date)}`);
    const snapshot = assertContract<BriefingSnapshot>("briefing", value, validateBriefingSnapshot(value));
    const briefing = mapBriefing(snapshot);
    const events = snapshot.event_snapshots.map((eventSnapshot) =>
      mapEvent(eventSnapshot.event, new Map())
    );
    return { mode, briefing, events };
  } catch (error) {
    if (error instanceof RadarApiError && error.status === 404) return null;
    throw error;
  }
}

export async function getEventBySlug(slug: string): Promise<RadarEvent | undefined> {
  if (requestedMode() === "fixture") return fixtureEvents.find((event) => event.slug === slug);
  try {
    const value = await getJson(`/api/v1/events/${encodeURIComponent(slug)}`);
    const event = assertContract<PublicEvent>("event", value, validatePublicEvent(value));
    const dataset = await getRadarDataset();
    const action = dataset.actions.find((item) => item.relatedEvent === event.slug);
    return mapEvent(event, new Map(action ? [[event.id, action]] : []));
  } catch (error) {
    if (error instanceof RadarApiError && error.status === 404) return undefined;
    throw error;
  }
}
