import { PricingTable } from "@/components/pricing/PricingTable";

export const metadata = {
  title: "Pricing",
  description:
    "Free weekly digest, Pro daily alerts at ₹199/month, and Thekedar instant tender alerts at ₹499/month.",
};

const FAQ = [
  {
    q: "Is the free plan really free?",
    a: "Yes. The full web feed, search, filters and a weekly email digest cost nothing, forever. Paid plans add frequency, WhatsApp delivery and contractor filters.",
  },
  {
    q: "How accurate are the summaries?",
    a: "Every summary is AI-generated from the official notification, and low-confidence ones are reviewed by a human before publishing. We always link the original — confirm details there before you apply or bid.",
  },
  {
    q: "How fast are instant tender alerts?",
    a: "Thekedar-plan alerts go out within about five minutes of a matching tender being approved on our feed, which is usually within the hour of it appearing on the portal.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Cancel from your Razorpay subscription page and you'll stay on your paid plan until the current period ends, then drop back to Free.",
  },
  {
    q: "Do you cover my state?",
    a: "Central sources cover all of India. State-level procurement and recruitment portals are being added continuously — Rajasthan, UP, Maharashtra, MP, Gujarat and Bihar are in progress.",
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <header className="text-center">
        <h1 className="text-4xl font-extrabold tracking-tight">
          Simple pricing
        </h1>
        <p className="mx-auto mt-3 max-w-lg text-sm leading-relaxed text-muted">
          Start free. Upgrade when you want the updates to come to you instead of
          the other way round.
        </p>
      </header>

      <PricingTable />

      <section className="mx-auto mt-20 max-w-2xl">
        <h2 className="text-center text-2xl font-bold">Questions</h2>
        <dl className="mt-8 space-y-4">
          {FAQ.map((item) => (
            <div
              key={item.q}
              className="rounded-2xl border border-border bg-card p-5"
            >
              <dt className="font-semibold text-ink">{item.q}</dt>
              <dd className="mt-2 text-sm leading-relaxed text-muted">{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
