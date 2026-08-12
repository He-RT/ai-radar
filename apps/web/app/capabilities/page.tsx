import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "能力地图" };
export const dynamic = "force-dynamic";
export default async function CapabilitiesPage() { const dataset = await getRadarDataset(); return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="CAPABILITY MAP" title="能力，不等于可采用">把模型名称映射到你实际关心的能力、依赖与已验证的使用边界。</PageIntro>{dataset.events.length ? <div className="stackedList">{dataset.events.slice(0, 8).map((event, index) => <article className="stackedRow" key={event.slug}><div><p className="eyebrow">{String(index + 1).padStart(2, "0")} · {event.kind}</p><h2>{event.title}</h2><p>{event.affected.join("、") || "影响范围待补充"}</p></div><p>{event.delta}</p><Link className="textLink" href={`/event/${event.slug}`}>关联证据 <span>→</span></Link></article>)}</div> : <p className="inlineEmpty">当前没有可映射的已发布能力事件。</p>}</div>; }
