import { CATEGORY_MAP, STATE_MAP } from "./constants";

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/** Days until a deadline. Negative means it has passed. */
export function daysUntil(dateStr: string | null | undefined): number | null {
  if (!dateStr) return null;
  const target = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export type DeadlineTone = "red" | "yellow" | "green";

export function deadlineTone(days: number): DeadlineTone {
  if (days <= 7) return "red";
  if (days <= 30) return "yellow";
  return "green";
}

export function deadlineLabel(days: number): string {
  if (days === 0) return "Last day";
  if (days === 1) return "1 day left";
  return `${days} days left`;
}

/** Paisa to a short Indian-format rupee string. */
export function formatBudget(paisa: number | null | undefined): string | null {
  if (!paisa || paisa <= 0) return null;
  const rupees = paisa / 100;
  if (rupees >= 10_000_000) return `₹${(rupees / 10_000_000).toFixed(2)} Cr`;
  if (rupees >= 100_000) return `₹${(rupees / 100_000).toFixed(2)} L`;
  return `₹${rupees.toLocaleString("en-IN")}`;
}

export function formatINR(rupees: number): string {
  return `₹${rupees.toLocaleString("en-IN")}`;
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function relativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  const then = new Date(dateStr).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((Date.now() - then) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(dateStr);
}

/** Entries published within the last 24 hours get a NEW badge. */
export function isNew(publishedAt: string | null | undefined): boolean {
  if (!publishedAt) return false;
  return Date.now() - new Date(publishedAt).getTime() < 86_400_000;
}

export function categoryMeta(id: string) {
  return CATEGORY_MAP[id] ?? CATEGORY_MAP.notice;
}

export function stateLabel(code: string): string {
  return STATE_MAP[code] ?? code;
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}
