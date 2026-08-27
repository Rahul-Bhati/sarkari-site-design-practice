import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-24 text-center">
      <div className="text-5xl" aria-hidden>
        🗂️
      </div>
      <h1 className="mt-6 text-2xl font-extrabold">This page doesn&apos;t exist</h1>
      <p className="mt-2 text-sm text-muted">
        The update may have been withdrawn, or the link is wrong.
      </p>
      <Link
        href="/feed"
        className="mt-6 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-white hover:bg-primary-dim"
      >
        Browse the feed
      </Link>
    </div>
  );
}
