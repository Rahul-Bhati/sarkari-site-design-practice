import { daysUntil, deadlineLabel, deadlineTone, formatDate } from "@/lib/utils";

const TONE_STYLES = {
  red: "bg-rule/15 text-rule border-rule/40",
  yellow: "bg-tender/15 text-tender border-tender/40",
  green: "bg-secondary/15 text-secondary border-secondary/40",
} as const;

interface Props {
  deadline: string | null | undefined;
  showDate?: boolean;
}

export function DeadlineBadge({ deadline, showDate = false }: Props) {
  const days = daysUntil(deadline);
  if (days === null) return null;

  if (days < 0) {
    return (
      <span className="inline-flex items-center rounded-md border border-border bg-border/40 px-2 py-0.5 text-[11px] font-semibold text-faint">
        Closed
      </span>
    );
  }

  const tone = deadlineTone(days);
  return (
    <span
      className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-semibold ${TONE_STYLES[tone]}`}
      title={deadline ? `Last date: ${formatDate(deadline)}` : undefined}
    >
      ⏰ {deadlineLabel(days)}
      {showDate && deadline && (
        <span className="ml-1 font-normal opacity-80">· {formatDate(deadline)}</span>
      )}
    </span>
  );
}
