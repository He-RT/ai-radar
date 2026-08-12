import Link from "next/link";
import type { Route } from "next";
import type { ReactNode } from "react";
import type { EvidenceGrade, RadarEvent } from "../data/radar";

export function Signal({ grade, state }: { grade: EvidenceGrade; state?: string }) {
  return <span className={`signal signal${grade}`} title={`证据等级 ${grade}`}><b>{grade}</b>{state && <em>{state}</em>}</span>;
}

export function Waveform({ values, active = false }: { values: number[]; active?: boolean }) {
  const width = 300;
  const height = 64;
  const step = width / (values.length - 1);
  const path = values.map((value, index) => `${index ? "L" : "M"}${(index * step).toFixed(2)},${(height - value * 0.56).toFixed(2)}`).join(" ");
  const peak = Math.max(...values);
  const peakIndex = values.indexOf(peak);
  return <svg className={`wave ${active ? "waveActive" : ""}`} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="行业震幅波形"><path className="waveGrid" d="M0 54H300M0 32H300M0 10H300" /><path className="waveLine" d={path} /><circle className="wavePeak" cx={peakIndex * step} cy={height - peak * 0.56} r="3" /></svg>;
}

export function Score({ value }: { value: number }) {
  return <span className="score"><strong>{value}</strong><small>/100</small></span>;
}

export function EventRow({ event, rank, compact = false }: { event: RadarEvent; rank?: number; compact?: boolean }) {
  return <article className={`eventRow ${compact ? "eventRowCompact" : ""}`}>
    <div className="eventRank" aria-label={rank ? `排名 ${rank}` : "事件"}>{rank ? String(rank).padStart(2, "0") : "—"}</div>
    <div className="eventBody">
      <div className="eventMeta"><span>{event.kicker}</span><time>{event.timeAgo}</time><Signal grade={event.confidence} state={event.evidence} /></div>
      <h2><Link href={`/event/${event.slug}`}>{event.title}</Link></h2>
      {!compact && <p>{event.summary}</p>}
      <div className="eventDelta"><span>△</span>{event.delta}</div>
    </div>
    <div className="eventInstrument"><Waveform values={event.waveform} /><Score value={event.score} /></div>
    {!compact && <Link className="rowAction" href={event.actionSlug ? `/action/${event.actionSlug}` : "/actions"}>行动 <span>→</span></Link>}
  </article>;
}

export function PageIntro({ eyebrow, title, children, aside }: { eyebrow: string; title: string; children?: ReactNode; aside?: ReactNode }) {
  return <section className="pageIntro"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <div className="introCopy">{children}</div>}</div>{aside && <aside className="introAside">{aside}</aside>}</section>;
}

export function EmptyState({ title, body, href = "/radar", label = "回到此刻" }: { title: string; body: string; href?: Route; label?: string }) {
  return <section className="empty"><p className="eyebrow">NO SIGNAL</p><h1>{title}</h1><p>{body}</p><Link href={href} className="button">{label} <span>→</span></Link></section>;
}

export function DataNote({ children }: { children: ReactNode }) {
  return <aside className="dataNote"><span aria-hidden="true">⊙</span><p>{children}</p></aside>;
}

export function DataModeNotice({ mode }: { mode: "api" | "fixture" }) {
  if (mode !== "fixture") return null;
  return <div className="demoData" role="status"><b>演示数据</b><span>当前页面使用本地示例，不代表实时公共事实。</span></div>;
}
