import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, EventRow, PageIntro } from "../../../components/atlas";
import { getBriefingDataset } from "../../../data/server";
import { notFound } from "next/navigation";
export const dynamic = "force-dynamic";
export async function generateMetadata({ params }: { params: Promise<{ date: string }> }): Promise<Metadata> { return { title: `快照 ${(await params).date}` }; }
export default async function BriefingPage({ params }: { params: Promise<{ date: string }> }) { const { date } = await params; const result = await getBriefingDataset(date); if (!result) notFound(); const { briefing, events, mode } = result; return <div className="contentPage"><DataModeNotice mode={mode} /><PageIntro eyebrow={`IMMUTABLE BRIEFING / ${date}`} title={briefing.title} aside={<>{briefing.note}<br />{briefing.cutoffAt ? `截至 ${new Date(briefing.cutoffAt).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}` : "演示快照"}</>}>{briefing.summary ?? "这是当时刻的只读记录。之后出现的证据、修正和评分变化会留在活事件案卷中，不会静默回写这里。"}</PageIntro><div className="dataNote"><span aria-hidden="true">⊙</span><p>该快照包含 {briefing.count} 条原始条目聚类后的判断。<Link href="/methodology/coverage">查看覆盖口径 →</Link></p></div>{events.length ? <div className="eventList">{events.map((event, index) => <EventRow key={event.slug} event={event} rank={index + 1} compact />)}</div> : <p className="inlineEmpty">该快照没有发布事件条目。</p>}</div>; }
