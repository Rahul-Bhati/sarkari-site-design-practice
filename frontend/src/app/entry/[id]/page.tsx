import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { FeedCard } from "@/components/feed/FeedCard";
import { DeadlineBadge } from "@/components/feed/DeadlineBadge";
import { ShareButtons } from "@/components/entry/ShareButtons";
import { FollowButton } from "@/components/entry/FollowButton";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import {
  categoryMeta,
  formatBudget,
  formatDate,
  stateLabel,
  truncate,
} from "@/lib/utils";
import type { Entry } from "@/types";

export const revalidate = 300;

type Params = Promise<{ id: string }>;

async function loadEntry(id: string): Promise<Entry | null> {
  try {
    return await api.entry(id, 300);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

export async function generateMetadata({
  params,
}: {
  params: Params;
}): Promise<Metadata> {
  const { id } = await params;
  const entry = await loadEntry(id).catch(() => null);
  if (!entry) return { title: "Update not found" };

  const description = truncate(entry.summary_en, 155);
  return {
    title: entry.title,
    description,
    alternates: { canonical: `/entry/${entry.id}` },
    openGraph: {
      title: entry.title,
      description,
      type: "article",
      url: `/entry/${entry.id}`,
      publishedTime: entry.published_at ?? undefined,
    },
    twitter: { card: "summary", title: entry.title, description },
  };
}

export default async function EntryPage({ params }: { params: Params }) {
  const { id } = await params;
  const entry = await loadEntry(id);
  if (!entry) notFound();

  const [related] = await Promise.all([
    api.relatedEntries(id, 300).catch(() => [] as Entry[]),
  ]);

  const category = categoryMeta(entry.category);
  const budget = formatBudget(entry.budget_amount);
  const details = entry.key_details ?? {};
  const eligibility =
    entry.eligibility && typeof entry.eligibility === "object"
      ? (entry.eligibility as { text?: string }).text
      : null;

  return (
    <article className="mx-auto max-w-3xl px-4 py-8">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData(entry)) }}
      />

      <Link
        href={`/feed?category=${entry.category}`}
        className="text-xs font-semibold text-muted hover:text-ink"
      >
        ← Back to {category.label}
      </Link>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Badge color={category.color}>
          <span aria-hidden>{category.icon}</span>
          {category.label}
        </Badge>
        <Badge>{stateLabel(entry.state)}</Badge>
        {entry.department && <Badge>{entry.department}</Badge>}
        <DeadlineBadge deadline={entry.deadline} showDate />
      </div>

      <h1 className="mt-4 text-3xl font-extrabold leading-tight tracking-tight">
        {entry.title}
      </h1>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
        {entry.published_date && <span>Published {formatDate(entry.published_date)}</span>}
        {entry.source && <span>Source: {entry.source.name}</span>}
      </div>

      <section className="mt-8 rounded-2xl border border-border bg-card p-6">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-primary">
          In short
        </h2>
        <p className="mt-3 text-[15px] leading-relaxed text-ink">{entry.summary_en}</p>

        {entry.summary_hi && (
          <>
            <h2 className="mt-6 text-xs font-semibold uppercase tracking-wide text-primary">
              हिंदी में
            </h2>
            <p className="mt-3 text-[15px] leading-relaxed text-ink" lang="hi">
              {entry.summary_hi}
            </p>
          </>
        )}
      </section>

      {(budget || eligibility || Object.keys(details).length > 0) && (
        <section className="mt-6 rounded-2xl border border-border bg-card p-6">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Key details
          </h2>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2">
            {typeof details.post === "string" && <Detail label="Post" value={details.post} />}
            {typeof details.vacancies === "number" && (
              <Detail label="Vacancies" value={details.vacancies.toLocaleString("en-IN")} />
            )}
            {typeof details.pay === "string" && <Detail label="Pay" value={details.pay} />}
            {typeof details.age === "string" && <Detail label="Age" value={details.age} />}
            {typeof details.qualification === "string" && (
              <Detail label="Qualification" value={details.qualification} />
            )}
            {typeof details.fee === "string" && <Detail label="Fee" value={details.fee} />}
            {typeof details.benefit === "string" && (
              <Detail label="What you get" value={details.benefit} />
            )}
            {budget && <Detail label="Estimated value" value={budget} />}
            {typeof details.emd_amount === "number" && (
              <Detail label="EMD" value={`₹${details.emd_amount.toLocaleString("en-IN")}`} />
            )}
            {entry.deadline && <Detail label="Last date" value={formatDate(entry.deadline)} />}
            {typeof details.tender_id === "string" && (
              <Detail label="Tender ID" value={details.tender_id} />
            )}
            {typeof details.helpline === "string" && (
              <Detail label="Helpline" value={details.helpline} />
            )}
            {typeof details.important_dates === "string" && (
              <div className="sm:col-span-2">
                <Detail label="Important dates" value={details.important_dates} />
              </div>
            )}
            {eligibility && (
              <div className="sm:col-span-2">
                <Detail label="Who is eligible" value={eligibility} />
              </div>
            )}
            {typeof details.how_to_apply === "string" && (
              <div className="sm:col-span-2">
                <Detail label="How to apply" value={details.how_to_apply} />
              </div>
            )}
          </dl>
        </section>
      )}

      {details.pdf_unreadable && (
        <p className="mt-6 text-sm text-muted">
          This notice could not be read from the file. Use the official link below.
        </p>
      )}

      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <a
          href={entry.original_url}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="grow rounded-xl bg-primary px-6 py-3.5 text-center text-sm font-bold text-white transition-colors hover:bg-primary-dim"
        >
          View original on {entry.source?.name ?? "the official portal"} →
        </a>
        {typeof details.application_link === "string" && (
          <a
            href={details.application_link}
            target="_blank"
            rel="noopener noreferrer nofollow"
            className="rounded-xl border border-secondary/50 bg-secondary/10 px-6 py-3.5 text-center text-sm font-bold text-secondary hover:bg-secondary/20"
          >
            Apply
          </a>
        )}
      </div>

      <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <FollowButton entryId={entry.id} hasDeadline={Boolean(entry.deadline)} />
      </div>

      <ShareButtons
        title={entry.title}
        entryId={entry.id}
        deadline={entry.deadline}
        vacancies={typeof details.vacancies === "number" ? details.vacancies : null}
      />

      <p className="mt-6 rounded-xl border border-border bg-surface/50 p-4 text-xs leading-relaxed text-faint">
        This summary was generated by AI from a public government notification.
        Always confirm the details on the official source before applying or
        bidding.
      </p>

      {related.length > 0 && (
        <section className="mt-12">
          <h2 className="mb-4 text-lg font-bold">
            More {category.label.toLowerCase()} in {stateLabel(entry.state)}
          </h2>
          <div className="space-y-4">
            {related.map((item) => (
              <FeedCard key={item.id} entry={item} />
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold text-ink">{value}</dd>
    </div>
  );
}

/** JSON-LD so job postings and schemes can surface in Google rich results. */
function structuredData(entry: Entry) {
  const base = {
    "@context": "https://schema.org",
    name: entry.title,
    description: entry.summary_en,
    url: entry.original_url,
  };

  if (entry.category === "naukri") {
    return {
      ...base,
      "@type": "JobPosting",
      title: entry.title,
      datePosted: entry.published_date ?? undefined,
      validThrough: entry.deadline ?? undefined,
      employmentType: "FULL_TIME",
      hiringOrganization: {
        "@type": "Organization",
        name: entry.department ?? "Government of India",
      },
      jobLocation: {
        "@type": "Place",
        address: { "@type": "PostalAddress", addressRegion: stateLabel(entry.state), addressCountry: "IN" },
      },
    };
  }

  return {
    ...base,
    "@type": "GovernmentService",
    serviceType: entry.category,
    provider: {
      "@type": "GovernmentOrganization",
      name: entry.department ?? "Government of India",
    },
    areaServed: stateLabel(entry.state),
  };
}
