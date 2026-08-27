import type { MetadataRoute } from "next";
import { api } from "@/lib/api";
import { CATEGORIES, STATES } from "@/lib/constants";

const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "https://sarkarisaar.com";
const MAX_ENTRIES = 5000;

export const revalidate = 3600;

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: SITE, changeFrequency: "hourly", priority: 1 },
    { url: `${SITE}/feed`, changeFrequency: "hourly", priority: 0.9 },
    { url: `${SITE}/pricing`, changeFrequency: "monthly", priority: 0.5 },
  ];

  // Category and state landing pages (PRD Milestone 13).
  for (const c of CATEGORIES) {
    if (c.id === "all") continue;
    staticRoutes.push({
      url: `${SITE}/feed?category=${c.id}`,
      changeFrequency: "daily",
      priority: 0.7,
    });
  }
  for (const s of STATES) {
    if (s.code === "ALL") continue;
    staticRoutes.push({
      url: `${SITE}/feed?state=${s.code}`,
      changeFrequency: "daily",
      priority: 0.6,
    });
  }

  try {
    const entries: MetadataRoute.Sitemap = [];
    let page = 1;

    while (entries.length < MAX_ENTRIES) {
      const data = await api.entries({ page, limit: 50 }, 3600);
      entries.push(
        ...data.entries.map((e) => ({
          url: `${SITE}/entry/${e.id}`,
          lastModified: e.published_at ? new Date(e.published_at) : undefined,
          changeFrequency: "weekly" as const,
          priority: 0.8,
        })),
      );
      if (!data.has_more) break;
      page += 1;
    }

    return [...staticRoutes, ...entries];
  } catch {
    // A sitemap missing entry URLs still beats a 500.
    return staticRoutes;
  }
}
