import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

const publicBaseUrl = process.env.RADAR_PUBLIC_BASE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  title: { default: "震幅 · AI Radar", template: "%s · 震幅" },
  description: "可验证、可行动的 AI 行业观测工作台。",
  metadataBase: new URL(publicBaseUrl),
  openGraph: {
    type: "website",
    locale: "zh_CN",
    siteName: "震幅 AI Radar",
    images: [{ url: "/ai-radar-og.png", width: 1200, height: 630, alt: "震幅 AI Radar 信号雷达" }]
  },
  twitter: { card: "summary_large_image", images: ["/ai-radar-og.png"] }
};

const primary = [
  ["/radar", "此刻"], ["/for-you", "为你"], ["/actions", "行动"], ["/stories", "故事线"], ["/events", "全量"]
] as const;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <a className="skip" href="#main">跳到主要内容</a>
        <header className="siteHeader">
          <Link href="/radar" className="brand" aria-label="震幅 AI Radar，前往此刻">
            <span className="brandMark" aria-hidden="true">⌁</span><span>震幅</span><small>AI RADAR <b>β</b></small>
          </Link>
          <nav aria-label="主导航" className="primaryNav">
            {primary.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}
          </nav>
          <div className="headerTools">
            <Link href="/search" aria-label="搜索"><span className="key">⌘</span> 搜索</Link>
            <Link href="/watch" className="watchLink">关注 <span aria-hidden="true">↗</span></Link>
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="siteFooter">
          <span>震幅 AI Radar · 公共 Beta</span>
          <span>事实可追溯，判断可更正。</span>
          <nav aria-label="页脚"><Link href="/corrections">更正</Link><Link href="/methodology/scoring">方法</Link><Link href="/contribute">提交线索</Link><Link href="/settings">设置</Link></nav>
        </footer>
      </body>
    </html>
  );
}
