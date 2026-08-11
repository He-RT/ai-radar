import type { Metadata } from "next";
import { DataModeNotice, PageIntro } from "../../../components/atlas";
import { getRadarDataset } from "../../../data/server";

export const metadata: Metadata = { title: "覆盖与数据质量" };
export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  const dataset = await getRadarDataset();
  const verified = dataset.events.filter((event) => event.evidence === "已验证" || event.evidence === "已更正").length;
  return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="METHODOLOGY / COVERAGE" title="覆盖范围与数据质量">覆盖率描述当前数据源能支持什么判断，不把没有证据的领域包装成完整视野。</PageIntro><div className="adminStats"><div><strong>{dataset.totalSignals}</strong><span>已聚类公共事件</span></div><div><strong>{dataset.events.length}</strong><span>当前返回事件</span></div><div><strong>{Math.round(dataset.evidenceCoverage * 100)}%</strong><span>证据覆盖</span></div><div><strong>{verified}</strong><span>已验证或已更正</span></div></div><article className="prose"><h2>知识截止</h2><p>{new Date(dataset.knowledgeCutoff).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}。此后的材料不应被解释为已经进入当前读数。</p><h2>空白如何处理</h2><p>没有事件、行动或快照时，页面明确显示空状态；API 不可用或返回不符合契约的数据时，不会回退到演示事实。</p></article></div>;
}
