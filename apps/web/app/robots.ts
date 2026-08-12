import type { MetadataRoute } from "next";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const baseUrl = (process.env.RADAR_PUBLIC_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/admin", "/teams/"] },
    sitemap: `${baseUrl}/sitemap.xml`
  };
}
