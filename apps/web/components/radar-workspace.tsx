"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { EventRow, Signal, Waveform } from "./atlas";
import { DataModeNotice } from "./atlas";
import type { RadarEvent } from "../data/radar";
import type { RadarDataMode } from "../data/server";

type SortMode = "impact" | "latest" | "relevant" | "ready";
const sortLabel: Record<SortMode, string> = { impact: "总冲击", latest: "时间", relevant: "与我相关", ready: "立即可用" };

export function RadarWorkspace({ events, actionCount, mode: dataMode, knowledgeCutoff, totalSignals, latestBriefingDate }: { events: RadarEvent[]; actionCount: number; mode: RadarDataMode; knowledgeCutoff: string; totalSignals: number; latestBriefingDate?: string }) {
  const [mode, setMode] = useState<SortMode>("impact");
  const [read, setRead] = useState(false);
  const [active, setActive] = useState(events[0]?.slug ?? "");
  const ordered = useMemo(() => [...events].sort((a, b) => {
    if (mode === "latest") return b.time.localeCompare(a.time);
    if (mode === "ready") return b.score - a.score + (a.kind === "产品" ? 14 : 0);
    if (mode === "relevant") return b.score - a.score + (a.affected.includes("开发") ? 10 : 0);
    return b.score - a.score;
  }), [events, mode]);
  const lead = events.find((event) => event.slug === active) ?? events[0];
  const cutoff = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(knowledgeCutoff));
  const waveform = events.length ? events.flatMap((event) => event.waveform.slice(-5)) : [0, 0];
  return <div className="radarPage">
    <DataModeNotice mode={dataMode} />
    <section className="instrumentHero" aria-labelledby="radar-title">
      <div className="instrumentHead">
        <div><p className="eyebrow">公共雷达 / 北京时间 {cutoff} 截点</p><h1 id="radar-title">此刻的真实变化</h1><p className="instrumentSub">截至 {cutoff}，系统已聚类 {totalSignals} 条公共事件；以下读数只来自当前数据源。</p></div>
        <div className="readBudget"><span>今日阅读预算</span><strong>10 <small>分钟</small></strong><p>{Math.min(events.length, 3)} 个变化 · {Math.min(actionCount, 2)} 个行动 · {events.filter((event) => event.evidence === "待交叉验证" || event.evidence === "监测中").length} 个待验证</p></div>
      </div>
      <div className="waveConsole">
        <div className="waveLabels"><span>过去 24 小时</span><span>行业震幅</span><span>高</span></div>
        <Waveform values={waveform} active />
        <div className="waveTimes"><span>08.11 08:30</span><span>02:00</span><span>现在</span></div>
      </div>
      <div className="heroReadout">
        <p><span className="signalDot" />最高波峰 <b>{lead?.score ?? 0}</b> · {lead?.title ?? "暂无公开事件"}</p>
        <p><span>证据状态</span>{lead ? <Signal grade={lead.confidence} state={lead.evidence} /> : <span>等待数据</span>}</p>
        <button type="button" onClick={() => setRead(true)} className={read ? "updateNudge done" : "updateNudge"}>{read ? "已读取本轮更新" : "将本轮变化标为已读"}</button>
      </div>
    </section>

    <section className="radarGrid">
      <div className="mainColumn">
        <div className="sectionBar"><div><p className="eyebrow">TOP 变化</p><h2>现在先判断这些</h2></div>{latestBriefingDate && <Link href={`/briefings/${latestBriefingDate}`}>查看不可变快照 <span>→</span></Link>}</div>
        <div className="sorter" aria-label="排序方式">
          {(Object.keys(sortLabel) as SortMode[]).map((item) => <button type="button" key={item} className={mode === item ? "isActive" : ""} onClick={() => setMode(item)}>{sortLabel[item]}</button>)}
          <span>当前：{sortLabel[mode]}</span>
        </div>
        <div className="eventList">
          {ordered.length ? ordered.slice(0, 4).map((event, index) => <div key={event.slug} onMouseEnter={() => setActive(event.slug)} onFocus={() => setActive(event.slug)}><EventRow event={event} rank={index + 1} /></div>) : <p className="inlineEmpty">当前没有可公开展示的事件。</p>}
        </div>
        <Link className="textLink moreEvents" href="/events">进入全量事件账本 <span>→</span></Link>
      </div>
      {lead && <aside className="sideColumn" aria-label="当前焦点">
        <div className="focusLabel"><span className="signalDot" /> 波峰解读</div>
        <p className="sideKicker">{lead.kicker}</p><h2>{lead.title}</h2><p>{lead.summary}</p>
        <dl className="miniFacts"><div><dt>证据</dt><dd><Signal grade={lead.confidence} state={lead.evidence} /></dd></div><div><dt>新增</dt><dd>{lead.delta}</dd></div></dl>
        <Link href={`/event/${lead.slug}`} className="button">打开案卷 <span>→</span></Link>
      </aside>}
    </section>

    <section className="actionStrip" aria-labelledby="action-now"><div><p className="eyebrow">立即可做</p><h2 id="action-now">别把判断留在阅读里</h2></div><p>从一个低风险的真实任务开始，明确成功阈值和人工复核点。</p><Link href="/actions" className="button buttonDark">打开行动中心 <span>→</span></Link></section>
  </div>;
}
