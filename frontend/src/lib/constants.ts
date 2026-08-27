export const CATEGORIES = [
  { id: "all", label: "All", icon: "◉", color: "#FF6B35" },
  { id: "yojana", label: "Yojana", icon: "🏛", color: "#8B5CF6" },
  { id: "naukri", label: "Naukri", icon: "💼", color: "#10B981" },
  { id: "tender", label: "Tender / Theka", icon: "📋", color: "#F59E0B" },
  { id: "rule", label: "Rule Change", icon: "⚖️", color: "#EF4444" },
  { id: "auction", label: "Auction", icon: "🔨", color: "#06B6D4" },
  { id: "notice", label: "Notice / Circular", icon: "📢", color: "#EC4899" },
] as const;

export type CategoryId = (typeof CATEGORIES)[number]["id"];

export const CATEGORY_MAP = Object.fromEntries(
  CATEGORIES.map((c) => [c.id, c]),
) as Record<string, (typeof CATEGORIES)[number]>;

/** 28 states + 8 union territories, plus the ALL bucket for central notices. */
export const STATES = [
  { code: "ALL", label: "All India" },
  { code: "AP", label: "Andhra Pradesh" },
  { code: "AR", label: "Arunachal Pradesh" },
  { code: "AS", label: "Assam" },
  { code: "BR", label: "Bihar" },
  { code: "CG", label: "Chhattisgarh" },
  { code: "GA", label: "Goa" },
  { code: "GJ", label: "Gujarat" },
  { code: "HR", label: "Haryana" },
  { code: "HP", label: "Himachal Pradesh" },
  { code: "JH", label: "Jharkhand" },
  { code: "KA", label: "Karnataka" },
  { code: "KL", label: "Kerala" },
  { code: "MP", label: "Madhya Pradesh" },
  { code: "MH", label: "Maharashtra" },
  { code: "MN", label: "Manipur" },
  { code: "ML", label: "Meghalaya" },
  { code: "MZ", label: "Mizoram" },
  { code: "NL", label: "Nagaland" },
  { code: "OD", label: "Odisha" },
  { code: "PB", label: "Punjab" },
  { code: "RJ", label: "Rajasthan" },
  { code: "SK", label: "Sikkim" },
  { code: "TN", label: "Tamil Nadu" },
  { code: "TS", label: "Telangana" },
  { code: "TR", label: "Tripura" },
  { code: "UK", label: "Uttarakhand" },
  { code: "UP", label: "Uttar Pradesh" },
  { code: "WB", label: "West Bengal" },
  { code: "AN", label: "Andaman & Nicobar Islands" },
  { code: "CH", label: "Chandigarh" },
  { code: "DN", label: "Dadra & Nagar Haveli and Daman & Diu" },
  { code: "DL", label: "Delhi" },
  { code: "JK", label: "Jammu & Kashmir" },
  { code: "LA", label: "Ladakh" },
  { code: "LD", label: "Lakshadweep" },
  { code: "PY", label: "Puducherry" },
] as const;

export const STATE_MAP = Object.fromEntries(
  STATES.map((s) => [s.code, s.label]),
) as Record<string, string>;

export const URGENCY_LABELS: Record<string, string> = {
  critical: "Closing very soon",
  high: "Closing soon",
  medium: "Open",
  low: "Open",
};

export const PLANS = [
  {
    id: "free",
    name: "Free",
    priceMonthly: 0,
    priceYearly: 0,
    tagline: "Stay informed",
    features: [
      "Full web feed with filters",
      "Search across every source",
      "Weekly email digest",
      "Hindi + English summaries",
    ],
    missing: ["Daily updates", "WhatsApp alerts", "Saved entries"],
  },
  {
    id: "pro",
    name: "Pro",
    priceMonthly: 199,
    priceYearly: 1999,
    tagline: "For job seekers and citizens",
    highlight: true,
    features: [
      "Everything in Free",
      "Daily email + WhatsApp digest",
      "Custom category and state filters",
      "Save entries for later",
      "Deadline reminders",
    ],
    missing: ["Instant tender alerts"],
  },
  {
    id: "thekedar",
    name: "Thekedar",
    priceMonthly: 499,
    priceYearly: 4999,
    tagline: "For contractors and bidders",
    features: [
      "Everything in Pro",
      "Instant WhatsApp tender alerts",
      "Budget and department filters",
      "Tender comparison",
      "Priority support",
    ],
    missing: [],
  },
] as const;
