import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DataModeNotice, DataNote, PageIntro, Signal, Waveform } from "../../../components/atlas";
import { claimsForEvent } from "../../../data/radar";
import { getEventBySlug, getRadarDataset } from "../../../data/server";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const event = await getEventBySlug((await params).slug);
  return { title: event?.title ?? "事件未找到" };
}

export default async function EventPage({
  params
}: {
  params: Promise<{ slug: string }>;
}) {
  const dataset = await getRadarDataset();
  const event = await getEventBySlug((await params).slug);
  if (!event) notFound();
  const claims = claimsForEvent(event);

  return (
    <div className="contentPage">
      <DataModeNotice mode={dataset.mode} />
      <PageIntro
        eyebrow={`LIVE EVENT / ${event.kind}`}
        title={event.title}
        aside={
          <>
            <Signal grade={event.confidence} state={event.evidence} />
            <br />最后变化 {event.time} · 北京时间
          </>
        }
      >
        {event.summary}
      </PageIntro>

      <div className="splitContent">
        <article className="prose">
          <section>
            <p className="eyebrow">本次事实增量</p>
            <h2>{event.delta}</h2>
            <Waveform values={event.waveform} active />
            <p>
              这是一个活事件，而不是一次性文章。以下区分可直接核对的事实、当前解释，以及尚不足以下结论的部分。
            </p>
          </section>

          <section aria-labelledby="claim-ledger-title">
            <p className="eyebrow">CLAIM LEDGER / VERSION 1</p>
            <h2 id="claim-ledger-title">主张与证据</h2>
            <div className="claimLedger">
              {claims.map((claim, index) => (
                <article className="claimRow" id={claim.id} key={claim.id}>
                  <span className="claimNumber">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <h3>{claim.text}</h3>
                    {claim.evidenceHref ? <a href={claim.evidenceHref} target="_blank" rel="noreferrer">{claim.evidenceLabel} <span aria-hidden="true">↗</span></a> : <span className="evidenceMissing">{claim.evidenceLabel}</span>}
                  </div>
                  <strong data-state={claim.status}>{claim.status}</strong>
                  <a className="claimAnchor" href={`#${claim.id}`} aria-label={`复制主张 ${index + 1} 的链接`}>
                    #
                  </a>
                </article>
              ))}
            </div>
          </section>

          <section>
            <h2>目前可以确定什么</h2>
            <p>
              {event.sources.length ? "原始材料已经发布并可追溯" : "当前事件没有返回可公开跳转的原始材料"}；本案卷将 <strong>{event.evidence}</strong> 与行业冲击分开呈现。评分 <strong>{event.score}/100</strong> 表示它可能改变的范围，不表示所有效果已被独立复现。
            </p>
            <DataNote>厂商提供的基准和性能主张均视为第一方证据，不自动等同于独立验证。</DataNote>
          </section>

          <section>
            <h2>为什么值得关注</h2>
            <p>
              影响不在于单一发布本身，而在于它可能改变团队今天可以实验、迁移或暂缓采购的边界。对受影响人群而言，下一步应该是一个小范围可回滚的对照，而非直接替换生产系统。
            </p>
          </section>

          <section>
            <h2>现在的未知项</h2>
            <ul>{event.unknowns.map((unknown) => <li key={unknown}>{unknown}</li>)}</ul>
          </section>

          <section id="next-check">
            <h2>接下来盯什么</h2>
            <p>
              我们将在 24 小时、7 天和 30 天窗口检查可用性、第三方复现、价格或采用信号；若结论变化，会在本案卷留下版本记录。
            </p>
          </section>
        </article>

        <aside className="marginNote">
          <h3>案卷字段</h3>
          <dl className="factRail">
            <div><dt>震幅</dt><dd>{event.score} / 100</dd></div>
            <div><dt>证据</dt><dd><Signal grade={event.confidence} state={event.evidence} /></dd></div>
            <div><dt>谁需要关心</dt><dd>{event.affected.join("、") || "尚待明确"}</dd></div>
            <div><dt>建议行动</dt><dd><Link href={event.actionSlug ? `/action/${event.actionSlug}` : "/actions"}>{event.action} →</Link></dd></div>
          </dl>
          <h3 id="sources">原始来源</h3>
          <ul className="sourceList">
            {event.sources.map((item) => (
              <li key={item.id ?? item.href}>
                <a href={item.href} target="_blank" rel="noreferrer">{item.name} ↗</a>
                <span>{item.kind}</span>
              </li>
            ))}
            {!event.sources.length && <li><span>当前 API 没有返回公开 Evidence URL。</span></li>}
          </ul>
        </aside>
      </div>
    </div>
  );
}
