import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

import {
  CONTRACT_VERSION,
  publicFactFingerprint,
  validateActionRecipe,
  validateActionRecipePage,
  validateAnswer,
  validateBriefingSnapshot,
  validateCorrectionPage,
  validateCoverageSnapshot,
  validateEventPage,
  validatePersonalizationBoundary,
  validatePublicEvent,
  validatePublicFactEnvelope,
  validateRadarResponse,
} from "../../packages/contracts/src/index.js";

const IDS = {
  event: "11111111-1111-4111-8111-111111111111",
  evidence: "22222222-2222-4222-8222-222222222222",
  sourceItem: "33333333-3333-4333-8333-333333333333",
  source: "44444444-4444-4444-8444-444444444444",
  claim: "55555555-5555-4555-8555-555555555555",
  score: "66666666-6666-4666-8666-666666666666",
  version: "77777777-7777-4777-8777-777777777777",
  action: "88888888-8888-4888-8888-888888888888",
  briefing: "99999999-9999-4999-8999-999999999999",
  correction: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
};

function eventFixture() {
  const claim = {
    id: IDS.claim,
    text: "A verifiable model release occurred.",
    importance: "key",
    evidence_ids: [IDS.evidence],
    confidence: 0.92,
  };
  return {
    id: IDS.event,
    slug: "verifiable-model-release",
    title: "A verifiable model release",
    summary: "The event is backed by a directly addressable source item.",
    category: "models",
    published_at: "2026-08-12T00:00:00Z",
    updated_at: "2026-08-12T00:15:00Z",
    state: "published",
    risk: "low",
    confidence_grade: "A",
    evidence_status: "verified",
    public_version: 1,
    claims: [claim],
    evidence: [
      {
        id: IDS.evidence,
        source_item_id: IDS.sourceItem,
        url: "https://example.com/release",
        quote: "The release is available today.",
        locator: "Release notes, paragraph 1",
        stance: "supports",
        source_tier: "primary",
      },
    ],
    source_ids: [IDS.source],
    score: {
      id: IDS.score,
      event_id: IDS.event,
      score: 82,
      components: { relevance: 24.6, evidence_quality: 23 },
      algorithm_version: "radar-score-v1",
      calculated_at: "2026-08-12T00:16:00Z",
    },
    tags: ["inference"],
    versions: [
      {
        id: IDS.version,
        event_id: IDS.event,
        version: 1,
        title: "A verifiable model release",
        summary: "The event is backed by a directly addressable source item.",
        claims: [structuredClone(claim)],
        changed_at: "2026-08-12T00:15:00Z",
        change_note: "initial publication",
      },
    ],
  };
}

function envelopeFixture() {
  return {
    contract_version: CONTRACT_VERSION,
    knowledge_cutoff: "2026-08-12T00:30:00Z",
    events: [eventFixture()],
  };
}

function radarFixture() {
  return {
    generated_at: "2026-08-12T00:31:00Z",
    knowledge_cutoff: "2026-08-12T00:30:00Z",
    headline_events: [eventFixture()],
    recommended_actions: [
      {
        id: IDS.action,
        event_id: IDS.event,
        title: "Run a bounded evaluation",
        audience: "ML platform teams",
        effort_minutes: 30,
        steps: ["Choose a representative workload."],
        expected_outcome: "A measured adoption decision.",
        caveats: [],
      },
    ],
    latest_briefing: {
      id: IDS.briefing,
      briefing_date: "2026-08-12",
      title: "Morning snapshot",
      executive_summary: "One evidence-backed event.",
      event_ids: [IDS.event],
      event_snapshots: [
        {
          snapshot_schema_version: 1,
          event_id: IDS.event,
          public_version: 1,
          event: eventFixture(),
        },
      ],
      generated_at: "2026-08-12T00:30:30Z",
      cutoff_at: "2026-08-12T00:30:00Z",
      state: "published",
    },
    coverage: {
      period: "2026-08-12",
      total_events: 1,
      categories: { models: 1 },
      source_tiers: { primary: 1 },
      evidence_coverage: 1,
      generated_at: "2026-08-12T00:30:30Z",
    },
  };
}

test("v1 JSON Schemas publish the explicit public fact and cutoff fields", async () => {
  const publicSchema = JSON.parse(
    await readFile(new URL("../../packages/contracts/schemas/v1/public-facts.schema.json", import.meta.url)),
  );
  const personalizedSchema = JSON.parse(
    await readFile(
      new URL("../../packages/contracts/schemas/v1/personalized-radar.schema.json", import.meta.url),
    ),
  );
  const declarations = await readFile(
    new URL("../../packages/contracts/src/index.d.ts", import.meta.url),
    "utf8",
  );

  assert.equal(publicSchema["x-contract-version"], CONTRACT_VERSION);
  for (const field of ["confidence_grade", "evidence_status", "public_version"]) {
    assert.ok(publicSchema.$defs.PublicEvent.required.includes(field));
  }
  assert.deepEqual(publicSchema.$defs.PublicPublicationState.enum, ["published", "corrected"]);
  assert.ok(publicSchema.$defs.RadarResponse.required.includes("knowledge_cutoff"));
  assert.ok(publicSchema.$defs.BriefingSnapshot.required.includes("cutoff_at"));
  assert.ok(publicSchema.$defs.BriefingSnapshot.required.includes("event_snapshots"));
  assert.deepEqual(publicSchema.$defs.BriefingEventSnapshot.required, [
    "snapshot_schema_version",
    "event_id",
    "public_version",
    "event",
  ]);
  assert.ok(personalizedSchema.required.includes("knowledge_cutoff"));
  assert.match(declarations, new RegExp(`CONTRACT_VERSION: "${CONTRACT_VERSION.replaceAll(".", "\\.")}"`));
  assert.match(declarations, new RegExp(`contract_version: "${CONTRACT_VERSION.replaceAll(".", "\\.")}"`));
});

test("minimal runtime validators accept a complete public event and radar response", () => {
  const radar = radarFixture();
  assert.deepEqual(validatePublicEvent(eventFixture()), { ok: true, errors: [] });
  assert.deepEqual(validatePublicFactEnvelope(envelopeFixture()), { ok: true, errors: [] });
  assert.deepEqual(validateRadarResponse(radar), { ok: true, errors: [] });
  assert.deepEqual(validateEventPage({ items: radar.headline_events, total: 1, limit: 20, offset: 0 }), {
    ok: true,
    errors: [],
  });
  assert.deepEqual(validateActionRecipe(radar.recommended_actions[0]), { ok: true, errors: [] });
  assert.deepEqual(
    validateActionRecipePage({ items: radar.recommended_actions, total: 1, limit: 20, offset: 0 }),
    { ok: true, errors: [] },
  );
  assert.deepEqual(validateBriefingSnapshot(radar.latest_briefing), { ok: true, errors: [] });
  assert.deepEqual(validateCoverageSnapshot(radar.coverage), { ok: true, errors: [] });
  assert.deepEqual(
    validateCorrectionPage({
      items: [
        {
          id: IDS.correction,
          event_id: IDS.event,
          published_at: "2026-08-12T00:25:00Z",
          reason: "A value needed clarification.",
          before: "Old value",
          after: "Corrected value",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    }),
    { ok: true, errors: [] },
  );
  assert.deepEqual(
    validateAnswer({
      answer: "The event is evidence backed.",
      citations: [
        {
          event_slug: "verifiable-model-release",
          title: "A verifiable model release",
          url: "/api/v1/events/verifiable-model-release",
        },
      ],
      generated_by: "extractive-stub-v1",
    }),
    { ok: true, errors: [] },
  );
});

test("a key claim must cite evidence that resolves inside its event", () => {
  const unsupported = eventFixture();
  unsupported.claims[0].evidence_ids = [];
  const unsupportedCodes = validatePublicEvent(unsupported).errors.map(({ code }) => code);
  assert.ok(unsupportedCodes.includes("key_claim_without_evidence"));

  const dangling = eventFixture();
  dangling.claims[0].evidence_ids = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"];
  const danglingCodes = validatePublicEvent(dangling).errors.map(({ code }) => code);
  assert.ok(danglingCodes.includes("missing_evidence_reference"));

  const claimless = eventFixture();
  claimless.claims = [];
  const claimlessCodes = validatePublicEvent(claimless).errors.map(({ code }) => code);
  assert.ok(claimlessCodes.includes("missing_key_claim"));
});

test("public_version is the latest immutable event version", () => {
  const event = eventFixture();
  event.public_version = 2;
  const result = validatePublicEvent(event);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some(({ code }) => code === "public_version_mismatch"));
});

test("runtime shape checks match schema extra-key, unique-item, and length constraints", () => {
  const withExtra = eventFixture();
  withExtra.personalized_title = "Not a public field";
  assert.ok(
    validatePublicEvent(withExtra).errors.some(({ code }) => code === "additional_property"),
  );

  const duplicateSources = eventFixture();
  duplicateSources.source_ids.push(duplicateSources.source_ids[0]);
  assert.ok(
    validatePublicEvent(duplicateSources).errors.some(({ code }) => code === "unique_items"),
  );

  const duplicateEvidenceRefs = eventFixture();
  duplicateEvidenceRefs.claims[0].evidence_ids.push(duplicateEvidenceRefs.claims[0].evidence_ids[0]);
  assert.ok(
    validatePublicEvent(duplicateEvidenceRefs).errors.some(({ code }) => code === "unique_items"),
  );

  const longQuote = eventFixture();
  longQuote.evidence[0].quote = "x".repeat(2001);
  assert.ok(
    validatePublicEvent(longQuote).errors.some(({ code }) => code === "string_length"),
  );
});

test("radar facts cannot be newer than the declared knowledge cutoff", () => {
  const radar = radarFixture();
  radar.knowledge_cutoff = "2026-08-12T00:10:00Z";
  const result = validateRadarResponse(radar);
  assert.equal(result.ok, false);
  assert.ok(result.errors.some(({ code }) => code === "fact_after_cutoff"));
});

test("briefing snapshots pin complete, ordered event versions at their cutoff", () => {
  const valid = radarFixture().latest_briefing;
  assert.deepEqual(validateBriefingSnapshot(valid), { ok: true, errors: [] });

  const missing = structuredClone(valid);
  delete missing.event_snapshots;
  assert.equal(validateBriefingSnapshot(missing).ok, false);

  const wrongSchema = structuredClone(valid);
  wrongSchema.event_snapshots[0].snapshot_schema_version = 2;
  assert.ok(validateBriefingSnapshot(wrongSchema).errors.some(({ code }) => code === "const"));

  const wrongIdentity = structuredClone(valid);
  wrongIdentity.event_snapshots[0].event_id = IDS.correction;
  const identityCodes = validateBriefingSnapshot(wrongIdentity).errors.map(({ code }) => code);
  assert.ok(identityCodes.includes("briefing_event_order_mismatch"));
  assert.ok(identityCodes.includes("snapshot_event_id_mismatch"));

  const wrongVersion = structuredClone(valid);
  wrongVersion.event_snapshots[0].public_version = 2;
  assert.ok(
    validateBriefingSnapshot(wrongVersion).errors.some(
      ({ code }) => code === "snapshot_public_version_mismatch",
    ),
  );

  const incompleteEvent = structuredClone(valid);
  delete incompleteEvent.event_snapshots[0].event.title;
  assert.equal(validateBriefingSnapshot(incompleteEvent).ok, false);

  const factsDoNotMatchVersion = structuredClone(valid);
  factsDoNotMatchVersion.event_snapshots[0].event.title = "Unversioned replacement title";
  assert.ok(
    validateBriefingSnapshot(factsDoNotMatchVersion).errors.some(
      ({ code }) => code === "snapshot_version_fact_mismatch",
    ),
  );

  const wrongCount = structuredClone(valid);
  wrongCount.event_ids = [];
  assert.ok(
    validateBriefingSnapshot(wrongCount).errors.some(
      ({ code }) => code === "briefing_event_count_mismatch",
    ),
  );
});

test("briefing snapshots reject event, score, and version timestamps after cutoff", () => {
  const mutations = [
    ["briefing_event_after_cutoff", (snapshot) => {
      snapshot.event_snapshots[0].event.updated_at = "2026-08-12T00:30:01Z";
    }],
    ["briefing_event_after_cutoff", (snapshot) => {
      snapshot.event_snapshots[0].event.published_at = "2026-08-12T00:30:01Z";
    }],
    ["briefing_score_after_cutoff", (snapshot) => {
      snapshot.event_snapshots[0].event.score.calculated_at = "2026-08-12T00:30:01Z";
    }],
    ["briefing_version_after_cutoff", (snapshot) => {
      snapshot.event_snapshots[0].event.versions[0].changed_at = "2026-08-12T00:30:01Z";
    }],
  ];

  for (const [expectedCode, mutate] of mutations) {
    const snapshot = structuredClone(radarFixture().latest_briefing);
    mutate(snapshot);
    assert.ok(validateBriefingSnapshot(snapshot).errors.some(({ code }) => code === expectedCode));
  }

  const futureCutoff = structuredClone(radarFixture().latest_briefing);
  futureCutoff.cutoff_at = "2026-08-12T00:31:00Z";
  assert.ok(
    validateBriefingSnapshot(futureCutoff).errors.some(
      ({ code }) => code === "cutoff_after_generation",
    ),
  );
});

test("personalization may reorder and explain facts but cannot alter facts or cutoff", () => {
  const baseline = envelopeFixture();
  const personalized = {
    contract_version: CONTRACT_VERSION,
    knowledge_cutoff: baseline.knowledge_cutoff,
    items: [
      {
        fact: structuredClone(baseline.events[0]),
        lens: {
          relevance: 91,
          explanation: "This affects the reader's current deployment goal.",
          recommended_action: "Run a bounded evaluation.",
        },
      },
    ],
  };

  assert.deepEqual(validatePersonalizationBoundary(baseline, personalized), {
    ok: true,
    errors: [],
  });

  const mutations = [
    (view) => {
      view.knowledge_cutoff = "2026-08-12T00:31:00Z";
    },
    (view) => {
      view.items[0].fact.confidence_grade = "B";
    },
    (view) => {
      view.items[0].fact.evidence[0].quote = "Personalized evidence text";
    },
    (view) => {
      view.items[0].fact.public_version = 2;
      view.items[0].fact.versions[0].version = 2;
    },
  ];

  for (const mutate of mutations) {
    const changed = structuredClone(personalized);
    mutate(changed);
    const result = validatePersonalizationBoundary(baseline, changed);
    assert.equal(result.ok, false);
    assert.ok(
      result.errors.some(({ code }) =>
        ["personalized_cutoff_changed", "personalized_fact_changed"].includes(code),
      ),
    );
  }

  assert.equal(
    publicFactFingerprint(baseline.events[0]),
    publicFactFingerprint(personalized.items[0].fact),
  );
});
