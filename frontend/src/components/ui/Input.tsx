import type { InputHTMLAttributes, SelectHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

const FIELD =
  "w-full bg-surface border border-border rounded-xl px-4 py-2.5 text-sm text-ink " +
  "placeholder:text-faint transition-colors hover:border-border-hover " +
  "focus:border-primary focus:outline-none";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string;
}

export function Input({ label, hint, error, className, id, ...rest }: InputProps) {
  const fieldId = id ?? rest.name;
  return (
    <label className="block" htmlFor={fieldId}>
      {label && (
        <span className="mb-1.5 block text-xs font-semibold text-muted">{label}</span>
      )}
      <input
        id={fieldId}
        aria-invalid={Boolean(error)}
        className={cn(FIELD, error && "border-rule", className)}
        {...rest}
      />
      {(error || hint) && (
        <span className={cn("mt-1.5 block text-xs", error ? "text-rule" : "text-faint")}>
          {error ?? hint}
        </span>
      )}
    </label>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: { value: string; label: string }[];
}

export function Select({ label, options, className, id, ...rest }: SelectProps) {
  const fieldId = id ?? rest.name;
  return (
    <label className="block" htmlFor={fieldId}>
      {label && (
        <span className="mb-1.5 block text-xs font-semibold text-muted">{label}</span>
      )}
      <select id={fieldId} className={cn(FIELD, "cursor-pointer", className)} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value} className="bg-surface">
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
