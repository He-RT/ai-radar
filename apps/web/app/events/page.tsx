import type { Metadata } from "next";
import { DataModeNotice, EmptyState, EventRow, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "全量事件" };
export const dynamic = "force-dynamic";
export default async function EventsPage() {
  const dataset = await getRadarDataset();
  if (!dataset.events.length) return <><DataModeNotice mode={dataset.mode} /><EmptyState title="当前没有公开事件" body="数据源已连接，但暂时没有符合公开发布条件的事件。" /></>;
  return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow={`EVENT LEDGER / ${dataset.events.length} CLUSTERS`} title="全量事件账本">每个事件簇只有一个持续更新的案卷。主榜按行业冲击排序；可信度决定你该相信到什么程度。</PageIntro><nav className="filterLine" aria-label="筛选事件"><span>筛选</span><a href="#all">全部</a><a href="#models">模型</a><a href="#products">产品</a><a href="#research">研究</a><a href="#policy">政策与安全</a></nav><div className="ledgerHeader"><span>序号</span><span>事件 / 今日增量</span><span>震幅</span><span /></div><div id="all" className="eventList">{dataset.events.map((event, index) => <EventRow key={event.slug} event={event} rank={index + 1} compact />)}</div></div>;
}
