export type Category =
  | "yojana"
  | "naukri"
  | "tender"
  | "rule"
  | "auction"
  | "notice";

export type Urgency = "low" | "medium" | "high" | "critical";
export type EntryStatus = "pending" | "approved" | "rejected" | "expired";
export type PlanId = "free" | "pro" | "thekedar";

export interface Source {
  id: number;
  name: string;
  url: string;
}

export interface KeyDetails {
  application_link?: string | null;
  helpline?: string | null;
  vacancies?: number | null;
  emd_amount?: number | null;
  tender_id?: string | null;
  [key: string]: unknown;
}

export interface Entry {
  id: string;
  source_id: number | null;
  source: Source | null;

  title: string;
  summary_en: string;
  summary_hi: string | null;

  category: Category;
  state: string;
  district: string | null;
  department: string | null;

  original_url: string;
  pdf_url: string | null;

  deadline: string | null;
  published_date: string | null;

  /** In paisa. Divide by 100 for rupees. */
  budget_amount: number | null;
  eligibility: Record<string, unknown> | null;
  key_details: KeyDetails;

  ai_confidence: number;
  urgency: Urgency;
  status: EntryStatus;

  published_at: string | null;
  created_at: string | null;
}

export interface EntriesResponse {
  entries: Entry[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface StatsResponse {
  total_entries: number;
  entries_today: number;
  states_covered: number;
  sources_active: number;
  categories: Partial<Record<Category, number>>;
}

export interface EntryFilters {
  category?: string;
  state?: string;
  search?: string;
  urgency?: string;
  deadline_before?: string;
  sort?: "published_at" | "deadline" | "created_at";
  page?: number;
  limit?: number;
}

export interface SubscribePayload {
  email?: string;
  phone?: string;
  channel: "email" | "whatsapp" | "both";
  frequency: "instant" | "daily" | "weekly";
  categories: Category[];
  states: string[];
}

export interface ScraperSource {
  id: number;
  name: string;
  url: string;
  scraper_key: string;
  is_active: boolean;
  registered: boolean;
  health: "green" | "yellow" | "red";
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  consecutive_failures: number;
  total_entries_scraped: number;
  last_run: {
    status: string;
    entries_found: number;
    entries_new: number;
    entries_duplicate: number;
    started_at: string;
  } | null;
}
