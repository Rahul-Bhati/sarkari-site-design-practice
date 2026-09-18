import Link from "next/link";
import { Badge } from "@/components/ui/Badge";
import { DeadlineBadge } from "./DeadlineBadge";
import {
  categoryMeta,
  formatBudget,
  formatDate,
  isNew,
  relativeTime,
  stateLabel,
  truncate,
} from "@/lib/utils";
import type { Entry } from "@/types";

interface Props {
  entry: Entry;
  showHindi?: boolean;
}

/**
 * What a card shows before the plain-language summary exists.
 *
 * Entries from trusted portals go live as soon as they are scraped, so the
 * summary can lag by hours when the AI provider's daily quota runs out. The
 * facts below are the portal's own — title, department, dates — so the entry is
 * still useful, and the card says plainly that the summary is still coming
 * rather than looking like an empty record.
 */
function PendingSummary({ entry }: { entry: Entry }) {
  const facts = [
    entry.department,
    entry.published_date ? `Published ${formatDate(entry.published_date)}` : null,
    entry.deadline ? `Last date ${formatDate(entry.deadline)}` : null,
  ].filter(Boolean) as string[];

  return (
    <div className="mt-2">
      {facts.length > 0 && (
        <p className="text-sm leading-relaxed text-muted">{facts.join(" · ")}</p>
      )}
      <p className="mt-1 text-xs text-faint">
        Plain-language summary is still being written. The official notice is linked below.
      </p>
    </div>
  );
}

export function FeedCard({ entry, showHindi = false }: Props) {
  const category = categoryMeta(entry.category);
  const budget = formatBudget(entry.budget_amount);
  const vacancies = entry.key_details?.vacancies;

  return (
    <article className="rounded-2xl border border-border bg-card p-5 transition-colors hover:border-border-hover">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge color={category.color}>
          <span aria-hidden>{category.icon}</span>
          {category.label}
        </Badge>
        <Badge>{stateLabel(entry.state)}</Badge>
        {isNew(entry.published_at) && (
          <Badge color="#FF6B35">NEW</Badge>
        )}
        <span className="grow" />
        <DeadlineBadge deadline={entry.deadline} />
      </div>

      <h3 className="text-[17px] font-bold leading-snug text-ink">
        <Link href={`/entry/${entry.id}`} className="hover:text-primary">
          {entry.title}
        </Link>
      </h3>

      {entry.summary_en ? (
        <p className="mt-2 text-sm leading-relaxed text-muted">
          {truncate(entry.summary_en, 240)}
        </p>
      ) : (
        <PendingSummary entry={entry} />
      )}

      {showHindi && entry.summary_hi && (
        <p className="mt-2 text-sm leading-relaxed text-muted/80">
          {truncate(entry.summary_hi, 240)}
        </p>
      )}

      {(budget || vacancies) && (
        <div className="mt-3 flex flex-wrap gap-4 text-xs">
          {budget && (
            <span className="text-tender">
              <span className="text-faint">Est. cost </span>
              <span className="font-semibold">{budget}</span>
            </span>
          )}
          {typeof vacancies === "number" && (
            <span className="text-secondary">
              <span className="text-faint">Vacancies </span>
              <span className="font-semibold">{vacancies.toLocaleString("en-IN")}</span>
            </span>
          )}
        </div>
      )}

      <footer className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-xs text-faint">
        <span>{entry.source?.name ?? entry.department ?? "Government portal"}</span>
        {entry.published_at && (
          <>
            <span aria-hidden>·</span>
            <span>{relativeTime(entry.published_at)}</span>
          </>
        )}
        <span className="grow" />
        <a
          href={entry.original_url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="font-semibold text-primary hover:underline"
        >
          View Original →
        </a>
      </footer>
    </article>
  );
}
