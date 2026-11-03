/** Small shadcn/ui-style component kit built on Tailwind tokens. */
import { forwardRef, useEffect, type ButtonHTMLAttributes, type HTMLAttributes, type InputHTMLAttributes, type ReactNode,
  type SelectHTMLAttributes, type TextareaHTMLAttributes, type TdHTMLAttributes } from "react";
import { Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";

type Variant = "default" | "secondary" | "outline" | "ghost" | "destructive";
type Size = "sm" | "md" | "lg" | "icon";

const variants: Record<Variant, string> = {
  default: "bg-primary text-primary-foreground hover:opacity-90 shadow-sm",
  secondary: "bg-muted text-foreground hover:bg-muted/70",
  outline: "border border-input bg-card hover:bg-muted",
  ghost: "hover:bg-muted",
  destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-9 px-4 text-sm gap-2",
  lg: "h-10 px-5 text-sm gap-2",
  icon: "h-9 w-9",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "md", loading, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        variants[variant], sizes[size], className,
      )}
      {...props}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";

const field =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm placeholder:text-muted-foreground " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(field, "h-9", className)} {...p} />
));
Input.displayName = "Input";

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn(field, "min-h-[80px] resize-y", className)} {...p} />
));
Textarea.displayName = "Textarea";

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, ...p }, ref) => (
  <select ref={ref} className={cn(field, "h-9 py-1 pr-8", className)} {...p} />
));
Select.displayName = "Select";

export function Label({ children, className, htmlFor }: { children: ReactNode; className?: string; htmlFor?: string }) {
  return <label htmlFor={htmlFor} className={cn("mb-1.5 block text-xs font-medium text-muted-foreground", className)}>{children}</label>;
}

export function Field({ label, error, hint, children, className }: {
  label: string; error?: string; hint?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={className}>
      <Label>{label}</Label>
      {children}
      {error ? <p className="mt-1 text-xs text-destructive">{error}</p> : hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border bg-card text-card-foreground shadow-sm", className)} {...p} />;
}
export function CardHeader({ title, description, actions, className }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 border-b px-4 py-3", className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold">{title}</h3>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...p} />;
}

type Tone = "neutral" | "blue" | "green" | "amber" | "red" | "violet";
const tones: Record<Tone, string> = {
  neutral: "bg-muted text-muted-foreground",
  blue: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  green: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  amber: "bg-amber-500/15 text-amber-800 dark:text-amber-300",
  red: "bg-red-500/10 text-red-700 dark:text-red-300",
  violet: "bg-violet-500/10 text-violet-700 dark:text-violet-300",
};
export function Badge({ children, tone = "neutral", className, title }: { children: ReactNode; tone?: Tone; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium", tones[tone], className)}>
      {children}
    </span>
  );
}

export function statusTone(s?: string | null): Tone {
  const v = (s ?? "").toLowerCase();
  if (/(succeed|created|approved|pass|complete|connected|ok|closed|done)/.test(v)) return "green";
  if (/(fail|error|reject|blocked|unknown_outcome|disconnected)/.test(v)) return "red";
  if (/(running|queued|pending|submitting|progress)/.test(v)) return "blue";
  if (/(review|warn|partial|attention|caution|draft)/.test(v)) return "amber";
  return "neutral";
}
export function StatusBadge({ status }: { status?: string | null }) {
  return <Badge tone={statusTone(status)}>{status ? status.replace(/_/g, " ") : "—"}</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-muted-foreground", className)} />;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
      <Spinner /> {label}
    </div>
  );
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icon && <div className="mb-3 rounded-full bg-muted p-3 text-muted-foreground">{icon}</div>}
      <p className="text-sm font-medium">{title}</p>
      {description && <p className="mt-1 max-w-md text-xs text-muted-foreground">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorBox({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className={cn("rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive", className)}>{msg}</div>;
}

export function Notice({ tone = "blue", children, className }: { tone?: "blue" | "amber" | "red" | "green"; children: ReactNode; className?: string }) {
  const map = {
    blue: "border-blue-500/30 bg-blue-500/5 text-blue-800 dark:text-blue-200",
    amber: "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-200",
    red: "border-red-500/30 bg-red-500/5 text-red-800 dark:text-red-200",
    green: "border-emerald-500/30 bg-emerald-500/5 text-emerald-800 dark:text-emerald-200",
  };
  return <div className={cn("rounded-md border px-3 py-2 text-xs leading-relaxed", map[tone], className)}>{children}</div>;
}

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}>
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs, className }: {
  value: T; onChange: (v: T) => void; tabs: { value: T; label: ReactNode }[]; className?: string;
}) {
  return (
    <div className={cn("inline-flex rounded-md bg-muted p-0.5", className)} role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          role="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
          className={cn("rounded px-3 py-1 text-xs font-medium transition-colors",
            value === t.value ? "bg-card shadow-sm" : "text-muted-foreground hover:text-foreground")}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Dialog({ open, onClose, title, description, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 pt-[8vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        className={cn("w-full rounded-lg border bg-card shadow-xl", wide ? "max-w-4xl" : "max-w-lg")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b px-5 py-4">
          <div>
            <h2 className="text-base font-semibold">{title}</h2>
            {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
          </div>
          <button onClick={onClose} className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="Close"><X className="h-4 w-4" /></button>
        </div>
        <div className="max-h-[65vh] overflow-y-auto px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, icon }: { label: string; value: ReactNode; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto", className)}>
      <table className="w-full text-sm">{children}</table>
    </div>
  );
}
export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th className={cn("border-b px-3 py-2 text-left text-xs font-medium text-muted-foreground", className)}>{children}</th>;
}
export function Td({ children, className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b px-3 py-2 align-top", className)} {...p}>{children}</td>;
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between px-3 py-2 text-xs text-muted-foreground">
      <span>{total.toLocaleString()} total</span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span>Page {page} of {pages}</span>
        <Button size="sm" variant="outline" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </div>
  );
}

export function Checkbox({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("inline-flex cursor-pointer items-center gap-2 text-sm", disabled && "cursor-not-allowed opacity-60")}>
      <input type="checkbox" className="h-4 w-4 rounded border-input accent-[hsl(var(--primary))]" checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function KV({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right">{children ?? "—"}</span>
    </div>
  );
}
