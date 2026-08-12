import routeManifest from "../routes/v1/routes.json" with { type: "json" };

export const CONTRACT_VERSION = routeManifest.contractVersion;
export const API_VERSION = routeManifest.apiVersion;
export const API_ROUTE_CONTRACTS = deepFreeze(routeManifest.api);
export const WEB_ROUTE_CONTRACTS = deepFreeze(routeManifest.web);

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const DATETIME_PATTERN =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;

const PUBLICATION_STATES = ["draft", "review", "published", "corrected", "retracted"];
const PUBLIC_STATES = ["published", "corrected"];
const RISK_LEVELS = ["low", "medium", "high", "critical"];
const CLAIM_IMPORTANCE = ["context", "supporting", "key"];
const CONFIDENCE_GRADES = ["A", "B", "C", "D", "E"];
const EVIDENCE_STATUSES = ["verified", "pending_cross_check", "monitoring", "corrected"];
const EVIDENCE_STANCES = ["supports", "contradicts", "context"];
const SOURCE_TIERS = ["primary", "authoritative", "secondary", "community"];

export function validatePublicEvent(value) {
  const errors = [];
  validatePublicEventInto(value, "$", errors);
  return validationResult(errors);
}

export function validateRadarResponse(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(
    value,
    [
      "generated_at",
      "knowledge_cutoff",
      "headline_events",
      "recommended_actions",
      "latest_briefing",
      "coverage",
    ],
    "$",
    errors,
  );

  datetime(value.generated_at, "$.generated_at", errors);
  datetime(value.knowledge_cutoff, "$.knowledge_cutoff", errors);
  array(value.headline_events, "$.headline_events", errors, (event, path) =>
    validatePublicEventInto(event, path, errors),
  );
  array(value.recommended_actions, "$.recommended_actions", errors, (action, path) =>
    validateActionRecipeInto(action, path, errors),
  );
  if (value.latest_briefing !== null) {
    validateBriefingInto(value.latest_briefing, "$.latest_briefing", errors);
  }
  validateCoverageInto(value.coverage, "$.coverage", errors);

  compareInstants(
    value.knowledge_cutoff,
    value.generated_at,
    "$.knowledge_cutoff",
    errors,
    "cutoff_after_generation",
    "knowledge_cutoff must not be later than generated_at",
  );
  if (Array.isArray(value.headline_events) && validDateTime(value.knowledge_cutoff)) {
    for (let index = 0; index < value.headline_events.length; index += 1) {
      compareInstants(
        value.headline_events[index]?.updated_at,
        value.knowledge_cutoff,
        `$.headline_events[${index}].updated_at`,
        errors,
        "fact_after_cutoff",
        "event updated_at must not be later than knowledge_cutoff",
      );
    }
  }
  if (isRecord(value.latest_briefing) && validDateTime(value.knowledge_cutoff)) {
    compareInstants(
      value.latest_briefing.cutoff_at,
      value.knowledge_cutoff,
      "$.latest_briefing.cutoff_at",
      errors,
      "briefing_after_radar_cutoff",
      "latest briefing cutoff_at must not be later than radar knowledge_cutoff",
    );
  }
  return validationResult(errors);
}

export function validateEventPage(value) {
  const errors = [];
  validatePageInto(value, "$", errors, validatePublicEventInto);
  return validationResult(errors);
}

export function validateActionRecipe(value) {
  const errors = [];
  validateActionRecipeInto(value, "$", errors);
  return validationResult(errors);
}

export function validateActionRecipePage(value) {
  const errors = [];
  validatePageInto(value, "$", errors, validateActionRecipeInto);
  return validationResult(errors);
}

export function validateBriefingSnapshot(value) {
  const errors = [];
  validateBriefingInto(value, "$", errors);
  return validationResult(errors);
}

export function validateCorrection(value) {
  const errors = [];
  validateCorrectionInto(value, "$", errors);
  return validationResult(errors);
}

export function validateCorrectionPage(value) {
  const errors = [];
  validatePageInto(value, "$", errors, validateCorrectionInto);
  return validationResult(errors);
}

export function validateCoverageSnapshot(value) {
  const errors = [];
  validateCoverageInto(value, "$", errors);
  return validationResult(errors);
}

export function validateAnswer(value) {
  const errors = [];
  validateAnswerInto(value, "$", errors);
  return validationResult(errors);
}

export function validatePublicFactEnvelope(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(value, ["contract_version", "knowledge_cutoff", "events"], "$", errors);
  exact(value.contract_version, CONTRACT_VERSION, "$.contract_version", errors);
  datetime(value.knowledge_cutoff, "$.knowledge_cutoff", errors);
  array(value.events, "$.events", errors, (event, path) => {
    validatePublicEventInto(event, path, errors);
    compareInstants(
      event?.updated_at,
      value.knowledge_cutoff,
      `${path}.updated_at`,
      errors,
      "fact_after_cutoff",
      "event updated_at must not be later than knowledge_cutoff",
    );
  });
  return validationResult(errors);
}

export function validatePersonalizationBoundary(baseline, personalized) {
  const errors = [];
  const baselineResult = validatePublicFactEnvelope(baseline);
  if (!baselineResult.ok) {
    errors.push(
      ...baselineResult.errors.map((entry) => ({
        ...entry,
        path: `$.baseline${entry.path.slice(1)}`,
      })),
    );
  }
  if (!record(personalized, "$.personalized", errors)) return validationResult(errors);
  allowedKeys(
    personalized,
    ["contract_version", "knowledge_cutoff", "items"],
    "$.personalized",
    errors,
  );

  exact(
    personalized.contract_version,
    CONTRACT_VERSION,
    "$.personalized.contract_version",
    errors,
  );
  datetime(personalized.knowledge_cutoff, "$.personalized.knowledge_cutoff", errors);
  if (isRecord(baseline)) {
    exact(
      personalized.knowledge_cutoff,
      baseline.knowledge_cutoff,
      "$.personalized.knowledge_cutoff",
      errors,
      "personalized_cutoff_changed",
      "personalization must preserve knowledge_cutoff exactly",
    );
  }

  const publicEvents = new Map();
  if (isRecord(baseline) && Array.isArray(baseline.events)) {
    for (const event of baseline.events) {
      if (isRecord(event) && typeof event.id === "string") publicEvents.set(event.id, event);
    }
  }

  const seen = new Set();
  array(personalized.items, "$.personalized.items", errors, (item, itemPath) => {
    if (!record(item, itemPath, errors)) return;
    allowedKeys(item, ["fact", "lens"], itemPath, errors);
    validatePublicEventInto(item.fact, `${itemPath}.fact`, errors);
    validateLensInto(item.lens, `${itemPath}.lens`, errors);
    if (!isRecord(item.fact) || typeof item.fact.id !== "string") return;

    if (seen.has(item.fact.id)) {
      issue(
        errors,
        `${itemPath}.fact.id`,
        "duplicate_personalized_fact",
        "a personalized view may include a public event at most once",
      );
    }
    seen.add(item.fact.id);

    const publicEvent = publicEvents.get(item.fact.id);
    if (!publicEvent) {
      issue(
        errors,
        `${itemPath}.fact.id`,
        "unknown_public_fact",
        "personalized fact does not exist in the public baseline",
      );
      return;
    }
    if (publicFactFingerprint(publicEvent) !== publicFactFingerprint(item.fact)) {
      issue(
        errors,
        `${itemPath}.fact`,
        "personalized_fact_changed",
        "personalization may select or reorder public facts but must not alter them",
      );
    }
  });

  return validationResult(errors);
}

export function validateRadarEventProjection(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(
    value,
    [
      "slug",
      "title",
      "kicker",
      "summary",
      "delta",
      "score",
      "confidence",
      "evidence",
      "kind",
      "time",
      "timeAgo",
      "action",
      "actionSlug",
      "waveform",
      "sources",
      "unknowns",
      "affected",
    ],
    "$",
    errors,
  );
  slug(value.slug, "$.slug", errors);
  for (const key of [
    "title",
    "kicker",
    "summary",
    "delta",
    "time",
    "timeAgo",
    "action",
    "actionSlug",
  ]) {
    nonEmptyString(value[key], `$.${key}`, errors);
  }
  numberInRange(value.score, 0, 100, "$.score", errors);
  enumeration(value.confidence, CONFIDENCE_GRADES, "$.confidence", errors);
  enumeration(
    value.evidence,
    ["已验证", "待交叉验证", "监测中", "已更正"],
    "$.evidence",
    errors,
  );
  enumeration(
    value.kind,
    ["模型", "产品", "研究", "基础设施", "政策", "安全"],
    "$.kind",
    errors,
  );
  array(value.waveform, "$.waveform", errors, (point, path) => finiteNumber(point, path, errors));
  array(value.sources, "$.sources", errors, (source, path) => {
    if (!record(source, path, errors)) return;
    allowedKeys(source, ["name", "href", "kind"], path, errors);
    nonEmptyString(source.name, `${path}.name`, errors);
    httpUrl(source.href, `${path}.href`, errors);
    enumeration(source.kind, ["第一方", "独立报道", "论文", "监管文件"], `${path}.kind`, errors);
  });
  if (Array.isArray(value.sources) && value.sources.length === 0) {
    issue(errors, "$.sources", "missing_sources", "a public event projection needs a source");
  }
  stringArray(value.unknowns, "$.unknowns", errors);
  stringArray(value.affected, "$.affected", errors);
  return validationResult(errors);
}

export function validateActionRecipeProjection(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(
    value,
    ["slug", "title", "duration", "difficulty", "outcome", "risk", "relatedEvent", "steps"],
    "$",
    errors,
  );
  slug(value.slug, "$.slug", errors);
  for (const key of ["title", "duration", "outcome", "risk", "relatedEvent"]) {
    nonEmptyString(value[key], `$.${key}`, errors);
  }
  enumeration(value.difficulty, ["5 分钟", "30 分钟", "半天"], "$.difficulty", errors);
  stringArray(value.steps, "$.steps", errors);
  if (Array.isArray(value.steps) && value.steps.length === 0) {
    issue(errors, "$.steps", "missing_steps", "an action recipe needs at least one step");
  }
  return validationResult(errors);
}

export function validateStoryProjection(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(value, ["slug", "title", "status", "summary", "movement", "events"], "$", errors);
  slug(value.slug, "$.slug", errors);
  for (const key of ["title", "status", "summary", "movement"]) {
    nonEmptyString(value[key], `$.${key}`, errors);
  }
  stringArray(value.events, "$.events", errors);
  return validationResult(errors);
}

export function validateBriefingProjection(value) {
  const errors = [];
  if (!record(value, "$", errors)) return validationResult(errors);
  allowedKeys(value, ["date", "title", "count", "note"], "$", errors);
  date(value.date, "$.date", errors);
  nonEmptyString(value.title, "$.title", errors);
  integerAtLeast(value.count, 0, "$.count", errors);
  nonEmptyString(value.note, "$.note", errors);
  return validationResult(errors);
}

export function selectPublicFacts(event) {
  if (!isRecord(event)) return event;
  return {
    id: event.id,
    slug: event.slug,
    title: event.title,
    summary: event.summary,
    category: event.category,
    published_at: event.published_at,
    updated_at: event.updated_at,
    state: event.state,
    risk: event.risk,
    confidence_grade: event.confidence_grade,
    evidence_status: event.evidence_status,
    public_version: event.public_version,
    claims: cloneJson(event.claims),
    evidence: cloneJson(event.evidence),
    source_ids: cloneJson(event.source_ids),
    score: cloneJson(event.score),
    tags: cloneJson(event.tags),
    versions: cloneJson(event.versions),
  };
}

export function publicFactFingerprint(event) {
  return stableStringify(selectPublicFacts(event));
}

export function assertValid(result, value) {
  if (!result.ok) {
    const detail = result.errors.map((entry) => `${entry.path}: ${entry.message}`).join("; ");
    throw new TypeError(`contract validation failed: ${detail}`);
  }
  return value;
}

function validatePublicEventInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    [
      "id",
      "slug",
      "title",
      "summary",
      "category",
      "published_at",
      "updated_at",
      "state",
      "risk",
      "confidence_grade",
      "evidence_status",
      "public_version",
      "claims",
      "evidence",
      "source_ids",
      "score",
      "tags",
      "versions",
    ],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  slug(value.slug, `${path}.slug`, errors);
  nonEmptyString(value.title, `${path}.title`, errors);
  string(value.summary, `${path}.summary`, errors);
  nonEmptyString(value.category, `${path}.category`, errors);
  datetime(value.published_at, `${path}.published_at`, errors);
  datetime(value.updated_at, `${path}.updated_at`, errors);
  enumeration(value.state, PUBLICATION_STATES, `${path}.state`, errors);
  if (typeof value.state === "string" && !PUBLIC_STATES.includes(value.state)) {
    issue(errors, `${path}.state`, "non_public_state", "a public event must be published or corrected");
  }
  enumeration(value.risk, RISK_LEVELS, `${path}.risk`, errors);
  enumeration(value.confidence_grade, CONFIDENCE_GRADES, `${path}.confidence_grade`, errors);
  enumeration(value.evidence_status, EVIDENCE_STATUSES, `${path}.evidence_status`, errors);
  integerAtLeast(value.public_version, 1, `${path}.public_version`, errors);

  array(value.claims, `${path}.claims`, errors, (claim, claimPath) =>
    validateClaimInto(claim, claimPath, errors),
  );
  array(value.evidence, `${path}.evidence`, errors, (evidence, evidencePath) =>
    validateEvidenceInto(evidence, evidencePath, errors),
  );
  array(value.source_ids, `${path}.source_ids`, errors, (sourceId, sourcePath) =>
    uuid(sourceId, sourcePath, errors),
  );
  uniquePrimitives(value.source_ids, `${path}.source_ids`, errors);
  if (value.score !== null) validateScoreInto(value.score, `${path}.score`, errors);
  stringArray(value.tags, `${path}.tags`, errors);
  array(value.versions, `${path}.versions`, errors, (version, versionPath) =>
    validateEventVersionInto(version, versionPath, errors),
  );

  const evidenceIds = new Set(
    Array.isArray(value.evidence)
      ? value.evidence.filter(isRecord).map((evidence) => evidence.id).filter((id) => typeof id === "string")
      : [],
  );
  if (
    Array.isArray(value.claims) &&
    !value.claims.some((claim) => isRecord(claim) && claim.importance === "key")
  ) {
    issue(
      errors,
      `${path}.claims`,
      "missing_key_claim",
      "a public event needs at least one evidence-backed key claim",
    );
  }
  validateClaimEvidenceReferences(value.claims, evidenceIds, `${path}.claims`, errors);
  if (Array.isArray(value.versions)) {
    for (let index = 0; index < value.versions.length; index += 1) {
      const version = value.versions[index];
      if (!isRecord(version)) continue;
      if (version.event_id !== value.id) {
        issue(
          errors,
          `${path}.versions[${index}].event_id`,
          "version_event_mismatch",
          "event version must reference its containing event",
        );
      }
      validateClaimEvidenceReferences(
        version.claims,
        evidenceIds,
        `${path}.versions[${index}].claims`,
        errors,
      );
    }
  }
  if (isRecord(value.score) && value.score.event_id !== value.id) {
    issue(errors, `${path}.score.event_id`, "score_event_mismatch", "score must reference its event");
  }

  if (!Array.isArray(value.versions) || value.versions.length === 0) {
    issue(errors, `${path}.versions`, "missing_public_version", "a public event needs a version record");
  } else {
    const versionNumbers = value.versions
      .filter(isRecord)
      .map((version) => version.version)
      .filter((version) => Number.isInteger(version));
    const unique = new Set(versionNumbers);
    if (unique.size !== versionNumbers.length) {
      issue(errors, `${path}.versions`, "duplicate_version", "event version numbers must be unique");
    }
    const latest = versionNumbers.length > 0 ? Math.max(...versionNumbers) : undefined;
    if (latest !== undefined && value.public_version !== latest) {
      issue(
        errors,
        `${path}.public_version`,
        "public_version_mismatch",
        "public_version must equal the greatest version in versions",
      );
    }
  }
}

function validateClaimEvidenceReferences(claims, evidenceIds, path, errors) {
  if (!Array.isArray(claims)) return;
  for (let claimIndex = 0; claimIndex < claims.length; claimIndex += 1) {
    const claim = claims[claimIndex];
    if (!isRecord(claim) || !Array.isArray(claim.evidence_ids)) continue;
    if (claim.importance === "key" && claim.evidence_ids.length === 0) {
      issue(
        errors,
        `${path}[${claimIndex}].evidence_ids`,
        "key_claim_without_evidence",
        "a key claim must reference at least one evidence item",
      );
    }
    for (let refIndex = 0; refIndex < claim.evidence_ids.length; refIndex += 1) {
      if (!evidenceIds.has(claim.evidence_ids[refIndex])) {
        issue(
          errors,
          `${path}[${claimIndex}].evidence_ids[${refIndex}]`,
          "missing_evidence_reference",
          "claim evidence ID must resolve inside the event",
        );
      }
    }
  }
}

function validateEvidenceInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    ["id", "source_item_id", "url", "quote", "locator", "stance", "source_tier"],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  uuid(value.source_item_id, `${path}.source_item_id`, errors);
  httpUrl(value.url, `${path}.url`, errors);
  boundedString(value.quote, 1, 2000, `${path}.quote`, errors);
  nonEmptyString(value.locator, `${path}.locator`, errors);
  enumeration(value.stance, EVIDENCE_STANCES, `${path}.stance`, errors);
  enumeration(value.source_tier, SOURCE_TIERS, `${path}.source_tier`, errors);
}

function validateClaimInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["id", "text", "importance", "evidence_ids", "confidence"], path, errors);
  uuid(value.id, `${path}.id`, errors);
  boundedString(value.text, 1, 2000, `${path}.text`, errors);
  enumeration(value.importance, CLAIM_IMPORTANCE, `${path}.importance`, errors);
  array(value.evidence_ids, `${path}.evidence_ids`, errors, (id, idPath) => uuid(id, idPath, errors));
  uniquePrimitives(value.evidence_ids, `${path}.evidence_ids`, errors);
  numberInRange(value.confidence, 0, 1, `${path}.confidence`, errors);
}

function validateScoreInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    ["id", "event_id", "score", "components", "algorithm_version", "calculated_at"],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  uuid(value.event_id, `${path}.event_id`, errors);
  numberInRange(value.score, 0, 100, `${path}.score`, errors);
  if (record(value.components, `${path}.components`, errors)) {
    for (const [name, component] of Object.entries(value.components)) {
      finiteNumber(component, `${path}.components.${name}`, errors);
    }
  }
  nonEmptyString(value.algorithm_version, `${path}.algorithm_version`, errors);
  datetime(value.calculated_at, `${path}.calculated_at`, errors);
}

function validateEventVersionInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    ["id", "event_id", "version", "title", "summary", "claims", "changed_at", "change_note"],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  uuid(value.event_id, `${path}.event_id`, errors);
  integerAtLeast(value.version, 1, `${path}.version`, errors);
  nonEmptyString(value.title, `${path}.title`, errors);
  string(value.summary, `${path}.summary`, errors);
  array(value.claims, `${path}.claims`, errors, (claim, claimPath) =>
    validateClaimInto(claim, claimPath, errors),
  );
  datetime(value.changed_at, `${path}.changed_at`, errors);
  nonEmptyString(value.change_note, `${path}.change_note`, errors);
}

function validateActionRecipeInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    [
      "id",
      "event_id",
      "title",
      "audience",
      "effort_minutes",
      "steps",
      "expected_outcome",
      "caveats",
    ],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  uuid(value.event_id, `${path}.event_id`, errors);
  nonEmptyString(value.title, `${path}.title`, errors);
  nonEmptyString(value.audience, `${path}.audience`, errors);
  integerAtLeast(value.effort_minutes, 1, `${path}.effort_minutes`, errors);
  stringArray(value.steps, `${path}.steps`, errors);
  if (Array.isArray(value.steps) && value.steps.length === 0) {
    issue(errors, `${path}.steps`, "missing_steps", "an action recipe needs at least one step");
  }
  nonEmptyString(value.expected_outcome, `${path}.expected_outcome`, errors);
  stringArray(value.caveats, `${path}.caveats`, errors);
}

function validateBriefingInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    [
      "id",
      "briefing_date",
      "title",
      "executive_summary",
      "event_ids",
      "event_snapshots",
      "generated_at",
      "cutoff_at",
      "state",
    ],
    path,
    errors,
  );
  uuid(value.id, `${path}.id`, errors);
  date(value.briefing_date, `${path}.briefing_date`, errors);
  nonEmptyString(value.title, `${path}.title`, errors);
  string(value.executive_summary, `${path}.executive_summary`, errors);
  array(value.event_ids, `${path}.event_ids`, errors, (eventId, eventPath) =>
    uuid(eventId, eventPath, errors),
  );
  uniquePrimitives(value.event_ids, `${path}.event_ids`, errors);
  array(value.event_snapshots, `${path}.event_snapshots`, errors, (snapshot, snapshotPath) =>
    validateBriefingEventSnapshotInto(snapshot, snapshotPath, value.cutoff_at, errors),
  );
  if (Array.isArray(value.event_ids) && Array.isArray(value.event_snapshots)) {
    if (value.event_ids.length !== value.event_snapshots.length) {
      issue(
        errors,
        `${path}.event_snapshots`,
        "briefing_event_count_mismatch",
        "event_snapshots must contain exactly one envelope for each ordered event_id",
      );
    }
    const comparableLength = Math.min(value.event_ids.length, value.event_snapshots.length);
    for (let index = 0; index < comparableLength; index += 1) {
      if (value.event_snapshots[index]?.event_id !== value.event_ids[index]) {
        issue(
          errors,
          `${path}.event_snapshots[${index}].event_id`,
          "briefing_event_order_mismatch",
          "event snapshot IDs must exactly match event_ids in order",
        );
      }
    }
  }
  datetime(value.generated_at, `${path}.generated_at`, errors);
  datetime(value.cutoff_at, `${path}.cutoff_at`, errors);
  enumeration(value.state, PUBLICATION_STATES, `${path}.state`, errors);
  compareInstants(
    value.cutoff_at,
    value.generated_at,
    `${path}.cutoff_at`,
    errors,
    "cutoff_after_generation",
    "briefing cutoff_at must not be later than generated_at",
  );
}

function validateBriefingEventSnapshotInto(value, path, cutoffAt, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["snapshot_schema_version", "event_id", "public_version", "event"], path, errors);
  exact(value.snapshot_schema_version, 1, `${path}.snapshot_schema_version`, errors);
  uuid(value.event_id, `${path}.event_id`, errors);
  integerAtLeast(value.public_version, 1, `${path}.public_version`, errors);
  validatePublicEventInto(value.event, `${path}.event`, errors);

  if (!isRecord(value.event)) return;
  exact(
    value.event.id,
    value.event_id,
    `${path}.event.id`,
    errors,
    "snapshot_event_id_mismatch",
    "embedded event ID must match its snapshot envelope",
  );
  exact(
    value.event.public_version,
    value.public_version,
    `${path}.event.public_version`,
    errors,
    "snapshot_public_version_mismatch",
    "embedded event public_version must match its snapshot envelope",
  );
  if (Array.isArray(value.event.versions)) {
    const pinnedVersion = value.event.versions.find(
      (version) => isRecord(version) && version.version === value.public_version,
    );
    if (
      isRecord(pinnedVersion) &&
      (pinnedVersion.title !== value.event.title ||
        pinnedVersion.summary !== value.event.summary ||
        stableStringify(pinnedVersion.claims) !== stableStringify(value.event.claims))
    ) {
      issue(
        errors,
        `${path}.event`,
        "snapshot_version_fact_mismatch",
        "embedded event title, summary, and claims must match its pinned public version",
      );
    }
  }

  for (const timestamp of ["published_at", "updated_at"]) {
    compareInstants(
      value.event[timestamp],
      cutoffAt,
      `${path}.event.${timestamp}`,
      errors,
      "briefing_event_after_cutoff",
      `embedded event ${timestamp} must not be later than briefing cutoff_at`,
    );
  }
  if (isRecord(value.event.score)) {
    compareInstants(
      value.event.score.calculated_at,
      cutoffAt,
      `${path}.event.score.calculated_at`,
      errors,
      "briefing_score_after_cutoff",
      "embedded score calculated_at must not be later than briefing cutoff_at",
    );
  }
  if (Array.isArray(value.event.versions)) {
    for (let index = 0; index < value.event.versions.length; index += 1) {
      compareInstants(
        value.event.versions[index]?.changed_at,
        cutoffAt,
        `${path}.event.versions[${index}].changed_at`,
        errors,
        "briefing_version_after_cutoff",
        "embedded event version changed_at must not be later than briefing cutoff_at",
      );
    }
  }
}

function validateCoverageInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(
    value,
    ["period", "total_events", "categories", "source_tiers", "evidence_coverage", "generated_at"],
    path,
    errors,
  );
  nonEmptyString(value.period, `${path}.period`, errors);
  integerAtLeast(value.total_events, 0, `${path}.total_events`, errors);
  integerMap(value.categories, `${path}.categories`, errors);
  integerMap(value.source_tiers, `${path}.source_tiers`, errors);
  numberInRange(value.evidence_coverage, 0, 1, `${path}.evidence_coverage`, errors);
  datetime(value.generated_at, `${path}.generated_at`, errors);
}

function validateCorrectionInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["id", "event_id", "published_at", "reason", "before", "after"], path, errors);
  uuid(value.id, `${path}.id`, errors);
  uuid(value.event_id, `${path}.event_id`, errors);
  datetime(value.published_at, `${path}.published_at`, errors);
  nonEmptyString(value.reason, `${path}.reason`, errors);
  string(value.before, `${path}.before`, errors);
  string(value.after, `${path}.after`, errors);
}

function validateAnswerInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["answer", "citations", "generated_by"], path, errors);
  string(value.answer, `${path}.answer`, errors);
  array(value.citations, `${path}.citations`, errors, (citation, citationPath) => {
    if (!record(citation, citationPath, errors)) return;
    allowedKeys(citation, ["event_slug", "title", "url"], citationPath, errors);
    slug(citation.event_slug, `${citationPath}.event_slug`, errors);
    nonEmptyString(citation.title, `${citationPath}.title`, errors);
    nonEmptyString(citation.url, `${citationPath}.url`, errors);
  });
  nonEmptyString(value.generated_by, `${path}.generated_by`, errors);
}

function validatePageInto(value, path, errors, validateItem) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["items", "total", "limit", "offset"], path, errors);
  array(value.items, `${path}.items`, errors, (item, itemPath) =>
    validateItem(item, itemPath, errors),
  );
  integerAtLeast(value.total, 0, `${path}.total`, errors);
  integerAtLeast(value.limit, 1, `${path}.limit`, errors);
  integerAtLeast(value.offset, 0, `${path}.offset`, errors);
  if (Array.isArray(value.items) && Number.isInteger(value.limit) && value.items.length > value.limit) {
    issue(errors, `${path}.items`, "page_over_limit", "page item count must not exceed limit");
  }
  if (
    Array.isArray(value.items) &&
    value.items.length > 0 &&
    Number.isInteger(value.offset) &&
    Number.isInteger(value.total) &&
    value.offset + value.items.length > value.total
  ) {
    issue(errors, `${path}.items`, "page_total_mismatch", "non-empty page must fit inside total");
  }
}

function validateLensInto(value, path, errors) {
  if (!record(value, path, errors)) return;
  allowedKeys(value, ["relevance", "explanation", "recommended_action"], path, errors);
  numberInRange(value.relevance, 0, 100, `${path}.relevance`, errors);
  string(value.explanation, `${path}.explanation`, errors);
  if (value.recommended_action !== undefined) {
    string(value.recommended_action, `${path}.recommended_action`, errors);
  }
}

function record(value, path, errors) {
  if (!isRecord(value)) {
    issue(errors, path, "type", "expected an object");
    return false;
  }
  return true;
}

function allowedKeys(value, allowed, path, errors) {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(value)) {
    if (!allowedSet.has(key)) {
      issue(errors, `${path}.${key}`, "additional_property", `unexpected property: ${key}`);
    }
  }
}

function array(value, path, errors, visit) {
  if (!Array.isArray(value)) {
    issue(errors, path, "type", "expected an array");
    return;
  }
  for (let index = 0; index < value.length; index += 1) visit(value[index], `${path}[${index}]`);
}

function stringArray(value, path, errors) {
  array(value, path, errors, (item, itemPath) => string(item, itemPath, errors));
}

function integerMap(value, path, errors) {
  if (!record(value, path, errors)) return;
  for (const [name, count] of Object.entries(value)) integerAtLeast(count, 0, `${path}.${name}`, errors);
}

function string(value, path, errors) {
  if (typeof value !== "string") issue(errors, path, "type", "expected a string");
}

function nonEmptyString(value, path, errors) {
  if (typeof value !== "string" || value.length === 0) {
    issue(errors, path, "type", "expected a non-empty string");
  }
}

function boundedString(value, minimum, maximum, path, errors) {
  if (typeof value !== "string" || value.length < minimum || value.length > maximum) {
    issue(
      errors,
      path,
      "string_length",
      `expected a string with length between ${minimum} and ${maximum}`,
    );
  }
}

function uniquePrimitives(value, path, errors) {
  if (!Array.isArray(value)) return;
  const seen = new Set();
  for (let index = 0; index < value.length; index += 1) {
    const item = value[index];
    if (seen.has(item)) {
      issue(errors, `${path}[${index}]`, "unique_items", "array items must be unique");
    }
    seen.add(item);
  }
}

function uuid(value, path, errors) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) {
    issue(errors, path, "uuid", "expected a UUID string");
  }
}

function slug(value, path, errors) {
  if (typeof value !== "string" || !SLUG_PATTERN.test(value)) {
    issue(errors, path, "slug", "expected a lowercase kebab-case slug");
  }
}

function date(value, path, errors) {
  if (typeof value !== "string" || !DATE_PATTERN.test(value)) {
    issue(errors, path, "date", "expected an ISO date");
  }
}

function datetime(value, path, errors) {
  if (!validDateTime(value)) issue(errors, path, "date_time", "expected an offset-aware ISO date-time");
}

function validDateTime(value) {
  return typeof value === "string" && DATETIME_PATTERN.test(value) && !Number.isNaN(Date.parse(value));
}

function httpUrl(value, path, errors) {
  try {
    const parsed = new URL(value);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new TypeError("unsupported protocol");
  } catch {
    issue(errors, path, "url", "expected an HTTP(S) URL");
  }
}

function finiteNumber(value, path, errors) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    issue(errors, path, "number", "expected a finite number");
  }
}

function numberInRange(value, minimum, maximum, path, errors) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > maximum) {
    issue(errors, path, "range", `expected a number between ${minimum} and ${maximum}`);
  }
}

function integerAtLeast(value, minimum, path, errors) {
  if (!Number.isInteger(value) || value < minimum) {
    issue(errors, path, "integer", `expected an integer greater than or equal to ${minimum}`);
  }
}

function enumeration(value, allowed, path, errors) {
  if (!allowed.includes(value)) {
    issue(errors, path, "enum", `expected one of: ${allowed.join(", ")}`);
  }
}

function exact(value, expected, path, errors, code = "const", message) {
  if (value !== expected) {
    issue(errors, path, code, message ?? `expected ${JSON.stringify(expected)}`);
  }
}

function compareInstants(left, right, path, errors, code, message) {
  if (validDateTime(left) && validDateTime(right) && Date.parse(left) > Date.parse(right)) {
    issue(errors, path, code, message);
  }
}

function issue(errors, path, code, message) {
  errors.push({ path, code, message });
}

function validationResult(errors) {
  return errors.length === 0
    ? Object.freeze({ ok: true, errors: Object.freeze([]) })
    : Object.freeze({ ok: false, errors: Object.freeze(errors) });
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function cloneJson(value) {
  if (value === undefined) return undefined;
  return JSON.parse(JSON.stringify(value));
}

function stableStringify(value) {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function deepFreeze(value) {
  if (!isRecord(value) && !Array.isArray(value)) return value;
  for (const nested of Object.values(value)) deepFreeze(nested);
  return Object.freeze(value);
}
