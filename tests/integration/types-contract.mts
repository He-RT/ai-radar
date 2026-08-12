import type {
  BriefingSnapshot,
  BriefingEventSnapshot,
  ConfidenceGrade,
  EvidenceStatus,
  PersonalizedLens,
  PublicEvent,
  RadarResponse,
} from "../../packages/contracts/src/index.js";

declare const event: PublicEvent;
declare const radar: RadarResponse;
declare const briefing: BriefingSnapshot;

const grade: ConfidenceGrade = event.confidence_grade;
const status: EvidenceStatus = event.evidence_status;
const publicVersion: number = event.public_version;
const radarCutoff: string = radar.knowledge_cutoff;
const briefingCutoff: string = briefing.cutoff_at;
const briefingEventSnapshot: BriefingEventSnapshot = briefing.event_snapshots[0];
const snapshotSchemaVersion: 1 = briefingEventSnapshot.snapshot_schema_version;
const snapshotEvent: PublicEvent = briefingEventSnapshot.event;

const lens: PersonalizedLens = {
  relevance: 80,
  explanation: "Personalized explanation remains outside the public event.",
};

// @ts-expect-error public confidence belongs to PublicEvent, not a personalized lens.
lens.confidence_grade = "B";

void [
  grade,
  status,
  publicVersion,
  radarCutoff,
  briefingCutoff,
  briefingEventSnapshot,
  snapshotSchemaVersion,
  snapshotEvent,
  lens,
];
