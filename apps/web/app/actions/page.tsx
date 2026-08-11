import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, EmptyState, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "行动中心" };
export const dynamic = "force-dynamic";
export default async function ActionsPage() { const dataset = await getRadarDataset(); if (!dataset.actions.length) return <><DataModeNotice mode={dataset.mode} /><EmptyState title="当前没有公开行动建议" body="事件仍可阅读；编辑审核通过后，低风险行动步骤会出现在这里。" /></>; return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="ACTION RECIPES / LOW-RISK FIRST" title="今天可以做什么">行动不是“立即采购”。选择一个可回滚任务，定义成功条件，并留下人工复核点。</PageIntro><div className="actionList">{dataset.actions.map((action) => <article className="actionRow" key={action.slug}><div><p className="eyebrow">{action.difficulty}</p><h2><Link href={`/action/${action.slug}`}>{action.title}</Link></h2><p>{action.outcome}</p></div><span className="duration">预计 {action.duration}</span><Link className="textLink" href={`/action/${action.slug}`}>打开步骤 <span>→</span></Link></article>)}</div></div>; }
