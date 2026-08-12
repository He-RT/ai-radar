import type { Metadata } from "next";
import { RadarWorkspace } from "../../components/radar-workspace";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "此刻", description: "当前 AI 行业变化、证据与行动优先级。" };
export const dynamic = "force-dynamic";
export default async function RadarPage() {
  const dataset = await getRadarDataset();
  return <RadarWorkspace events={dataset.events} actionCount={dataset.actions.length} mode={dataset.mode} knowledgeCutoff={dataset.knowledgeCutoff} totalSignals={dataset.totalSignals} latestBriefingDate={dataset.briefings[0]?.date} />;
}
