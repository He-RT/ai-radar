import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, EventRow, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "为你" };
export const dynamic = "force-dynamic";
export default async function ForYouPage() { const dataset = await getRadarDataset(); const action = dataset.actions[0]; return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="YOUR LENS / DEVELOPMENT · COST · CONTROL" title="和你当前目标有关的变化" aside={<>偏好：开发与工作流<br /><Link href="/settings">调整偏好 →</Link></>}>事实与证据对所有人相同；这里仅按你的目标解释优先级，不生成另一套事实。</PageIntro><section><div className="sectionBar"><div><p className="eyebrow">优先阅读</p><h2>减少返工的信号</h2></div></div>{dataset.events.length ? <div className="eventList">{dataset.events.slice(0, 3).map((event, index) => <EventRow key={event.slug} event={event} rank={index + 1} compact />)}</div> : <p className="inlineEmpty">当前没有与你的偏好匹配的公开事件。</p>}</section>{action && <section className="actionStrip"><div><p className="eyebrow">下一个动作</p><h2>{action.title}</h2></div><p>{action.outcome}</p><Link href={`/action/${action.slug}`} className="button buttonDark">打开行动步骤 <span>→</span></Link></section>}</div>; }
