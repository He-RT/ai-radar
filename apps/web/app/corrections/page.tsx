import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "更正中心" };
export const dynamic = "force-dynamic";
export default async function CorrectionsPage() { const dataset = await getRadarDataset(); const corrections = dataset.events.filter((event) => event.evidence === "已更正"); return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="PUBLIC CORRECTIONS / VERSIONED" title="我们之前哪里错了">更正不是在页面底部加一句免责声明。每一次事实、措辞或评分变动都保留范围、原因和可追溯记录。</PageIntro>{corrections.length ? <div className="stackedList">{corrections.map((event) => <article className="stackedRow" key={event.slug}><div><p className="correctionMark">CORRECTION · {event.time}</p><h2>{event.title}</h2><p>{event.delta}</p></div><p className="duration">影响：{event.affected.join(" / ") || event.kind}</p><Link href={`/event/${event.slug}`} className="textLink">查看记录 <span>→</span></Link></article>)}</div> : <p className="inlineEmpty">当前数据源没有已发布更正。</p>}<section className="actionStrip"><div><p className="eyebrow">发现问题？</p><h2>帮我们补上证据</h2></div><p>请提供原始材料、具体主张与受影响的页面。</p><Link href="/contribute" className="button buttonDark">提交更正 <span>→</span></Link></section></div>; }
