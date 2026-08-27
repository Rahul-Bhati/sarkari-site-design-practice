export function FeedCardSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="mb-3 flex gap-2">
        <div className="skeleton h-5 w-24 rounded-md" />
        <div className="skeleton h-5 w-16 rounded-md" />
      </div>
      <div className="skeleton mb-2 h-5 w-4/5 rounded" />
      <div className="skeleton mb-3 h-5 w-2/3 rounded" />
      <div className="skeleton mb-1.5 h-3.5 w-full rounded" />
      <div className="skeleton mb-1.5 h-3.5 w-full rounded" />
      <div className="skeleton h-3.5 w-1/2 rounded" />
      <div className="mt-4 border-t border-border pt-3">
        <div className="skeleton h-3 w-40 rounded" />
      </div>
    </div>
  );
}

export function FeedSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading updates">
      {Array.from({ length: count }, (_, i) => (
        <FeedCardSkeleton key={i} />
      ))}
    </div>
  );
}
