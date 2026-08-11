import type { Metadata } from "next";
import Link from "next/link";
import { PageIntro } from "../../components/atlas";
export const metadata: Metadata = { title: "设置" };
const options = [["当前目标", "开发、搭建可控工作流、降低模型成本。"], ["阅读预算", "每次雷达默认保留 10 分钟，完成后显示结束状态。"], ["证据阈值", "默认展示 A 到 C；D 级仅显示为待核线索。"], ["通知节奏", "仅当你关注的条件出现实质证据增量时发送。"]] as const;
export default function SettingsPage() { return <div className="contentPage"><PageIntro eyebrow="SETTINGS / LOCAL BETA" title="你的阅读与判断偏好">个性化只改变排序和解释，不改变共享事件、证据等级或更正记录。</PageIntro><section className="formLayout">{options.map(([title, body], index) => <div className="settingsRow" key={title}><div><h3>{title}</h3><p>{body}</p>{index === 0 && <Link href="/for-you" className="textLink">查看为你页面 <span>→</span></Link>}</div><input className="toggle" type="checkbox" defaultChecked={index !== 0} aria-label={`启用 ${title}`} /></div>)}</section><div className="dataNote"><span aria-hidden="true">⊙</span><p>公共 Beta 使用演示偏好。登录与云端同步将在正式版提供。</p></div></div>; }
