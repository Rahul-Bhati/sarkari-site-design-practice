import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface Props {
  children: ReactNode;
  /** Any CSS color. Renders as tinted background + matching text. */
  color?: string;
  className?: string;
}

export function Badge({ children, color, className }: Props) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold",
        !color && "bg-border text-muted",
        className,
      )}
      style={
        color
          ? { backgroundColor: `${color}22`, color, border: `1px solid ${color}44` }
          : undefined
      }
    >
      {children}
    </span>
  );
}
