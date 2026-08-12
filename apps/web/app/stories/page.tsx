import type { Metadata } from "next";
import Link from "next/link";
import { DataModeNotice, EmptyState, PageIntro } from "../../components/atlas";
import { getRadarDataset } from "../../data/server";
export const metadata: Metadata = { title: "故事线" };
export const dynamic = "force-dynamic";
export default async function StoriesPage() { const dataset = await getRadarDataset(); if (!dataset.stories.length) return <><DataModeNotice mode={dataset.mode} /><EmptyState title="当前没有可追踪的故事线" body="有足够的已发布事件形成长期变化后，故事线会出现在这里。" /></>; return <div className="contentPage"><DataModeNotice mode={dataset.mode} /><PageIntro eyebrow="LONG-RUNNING CHANGE" title="故事线">跨日追踪那些会改变工作方式、竞争格局或规则的长期变化。没有新证据，就不制造新叙事。</PageIntro><div className="storyList">{dataset.stories.map((story) => <article className="storyRow" key={story.slug}><div><p className="eyebrow">{story.status}</p><h2><Link href={`/story/${story.slug}`}>{story.title}</Link></h2><p>{story.summary}</p></div><span className="duration">{story.movement}</span><Link className="textLink" href={`/story/${story.slug}`}>查看演进 <span>→</span></Link></article>)}</div></div>; }
