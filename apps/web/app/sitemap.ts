import type { MetadataRoute } from "next";

export const dynamic = "force-dynamic";

const routes = ["/radar", "/events", "/stories", "/actions", "/capabilities", "/for-you", "/search", "/watch", "/corrections", "/methodology/scoring", "/methodology/coverage", "/contribute", "/settings"];
export default function sitemap(): MetadataRoute.Sitemap {
  const baseUrl = (process.env.RADAR_PUBLIC_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
  return routes.map((route) => ({
    url: `${baseUrl}${route}`,
    lastModified: new Date(),
    changeFrequency: "daily",
    priority: route === "/radar" ? 1 : 0.7
  }));
}
