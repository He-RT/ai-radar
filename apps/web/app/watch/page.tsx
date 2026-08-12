import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "../../components/atlas";
export const metadata: Metadata = { title: "关注" };
const watches = [["开放权重推理", "只在出现可下载权重、独立复现或显著成本变化时提醒。", "下次检查：8 小时后"], ["Agent 审计与权限", "关注可回放、地域保留和不可逆操作的控制边界。", "下次检查：明天 08:30"], ["视觉模型权利状态", "出现条款更新、诉讼材料或基准修订时才进入收件箱。", "下次检查：3 天后"], ["训练用 GPU", "区域级价格、容量与交付周期发生异常时提醒。", "下次检查：今天 17:00"]] as const;
export default function WatchPage() { return <div className="contentPage"><PageIntro eyebrow="WATCH / CONDITIONS, NOT NOISE" title="关注的是条件，不是关键词">将信号绑到你实际会改变决定的条件；没有新事实时，不推送。</PageIntro><div className="watchGrid">{watches.map(([title, body, when]) => <article className="watchItem" key={title}><small>● 活跃</small><h2>{title}</h2><p>{body}</p><p className="duration">{when}</p><Link href="/settings" className="textLink">调整条件 <span>→</span></Link></article>)}</div></div>; }
