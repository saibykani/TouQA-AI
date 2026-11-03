import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowDown, ArrowUp, Check, Copy, ExternalLink, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import type { Draft, TestCaseContent } from "@/lib/types";
import { cn, humanize } from "@/lib/utils";
import { Badge, Button, Card, Field, Input, Notice, Select, StatusBadge, Textarea } from "./ui";

const PRIORITIES = ["critical", "high", "medium", "low"];

function ListEditor({ label, items, onChange }: { label: string; items: string[]; onChange: (v: string[]) => void }) {
  return (
    <Field label={label}>
      <Textarea value={items.join("\n")} onChange={(e) => onChange(e.target.value.split("\n"))} className="min-h-[56px]" placeholder="One per line" />
    </Field>
  );
}

export function DuplicateNotice({ draft, editable }: { draft: Draft; editable: boolean }) {
  const qc = useQueryClient();
  const info = draft.duplicate_info;
  const decide = useMutation({
    mutationFn: (d: string) => api.put(`/drafts/${draft.id}`, { duplicate_decision: d }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["batch", draft.batch_id] }),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!info?.checked || info.level === "none" || !info.matches?.length) return null;
  const top = info.matches[0];
  return (
    <Notice tone={info.level === "likely" ? "red" : "amber"} className="space-y-1.5">
      <div className="flex items-center gap-1.5 font-medium"><Copy className="h-3.5 w-3.5" />{humanize(info.level)} duplicate</div>
      <ul className="space-y-0.5">
        {info.matches.slice(0, 3).map((m: any, i: number) => (
          <li key={i}>
            {m.kind === "draft" ? `Draft #${m.draft_id}` : `TC:${m.external_id}`} — {m.name}
            <span className="opacity-70"> ({Math.round(m.score * 100)}%{m.title_only ? ", title similarity only" : ""})</span>
          </li>
        ))}
      </ul>
      {top.explanation && <p className="opacity-80">{top.explanation}</p>}
      {editable && (
        <div className="flex gap-1.5 pt-1">
          {(["keep", "merge", "remove"] as const).map((d) => (
            <Button key={d} size="sm" variant={draft.duplicate_decision === d ? "default" : "outline"} loading={decide.isPending && decide.variables === d}
              onClick={() => decide.mutate(d)}>{d === "keep" ? "Keep both" : d === "merge" ? "Mark for merge" : "Remove draft"}</Button>
          ))}
        </div>
      )}
    </Notice>
  );
}

export default function DraftEditor({ draft, editable, selected, onSelect }: {
  draft: Draft; editable: boolean; selected: boolean; onSelect: (v: boolean) => void;
}) {
  const qc = useQueryClient();
  const [c, setC] = useState<TestCaseContent>(draft.content);
  const [dirty, setDirty] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    setC(draft.content);
    setDirty(false);
  }, [draft.content]);

  const locked = !editable || ["submitted", "submitting"].includes(draft.status);
  const refresh = () => qc.invalidateQueries({ queryKey: ["batch", draft.batch_id] });
  const update = useMutation({
    mutationFn: (body: any) => api.put<Draft>(`/drafts/${draft.id}`, body),
    onSuccess: () => { refresh(); setDirty(false); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/drafts/${draft.id}`),
    onSuccess: () => { refresh(); toast.success("Draft deleted"); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const set = <K extends keyof TestCaseContent>(k: K, v: TestCaseContent[K]) => { setC({ ...c, [k]: v }); setDirty(true); };
  const setStep = (i: number, k: "action" | "expected_result" | "test_data", v: string) =>
    set("steps", c.steps.map((s, j) => (j === i ? { ...s, [k]: v } : s)));
  const moveStep = (i: number, dir: -1 | 1) => {
    const s = [...c.steps];
    [s[i], s[i + dir]] = [s[i + dir], s[i]];
    set("steps", s.map((x, j) => ({ ...x, step_number: j + 1 })));
  };
  const clean = (x: TestCaseContent): TestCaseContent => ({
    ...x,
    preconditions: x.preconditions.map((s) => s.trim()).filter(Boolean),
    test_data: x.test_data.map((s) => s.trim()).filter(Boolean),
    tags: x.tags.map((s) => s.trim()).filter(Boolean),
  });

  const errors = draft.validation_errors?.filter((i) => i.severity === "error") ?? [];
  const warnings = draft.validation_errors?.filter((i) => i.severity !== "error") ?? [];

  return (
    <Card className={cn(draft.status === "rejected" && "opacity-60", selected && "ring-2 ring-primary/50")}>
      <div className="flex items-start gap-2 px-3 py-2.5">
        {!locked && draft.status !== "rejected" && (
          <input type="checkbox" className="mt-1 h-4 w-4 accent-[hsl(var(--primary))]" checked={selected} onChange={(e) => onSelect(e.target.checked)} aria-label="Select for submission" />
        )}
        <button className="min-w-0 flex-1 text-left" onClick={() => setExpanded((e) => !e)}>
          <div className="truncate text-sm font-medium">{c.name || "Untitled test case"}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <StatusBadge status={draft.status} />
            <Badge tone="blue">{humanize(c.category)}</Badge>
            <Badge>{c.priority}</Badge>
            <Badge>{c.steps.length} steps</Badge>
            {c.acceptance_criterion_ids.map((id) => <Badge key={id} tone="green">{id}</Badge>)}
            {errors.length > 0 && <Badge tone="red"><AlertTriangle className="h-3 w-3" />{errors.length} error{errors.length > 1 ? "s" : ""}</Badge>}
            {warnings.length > 0 && <Badge tone="amber">{warnings.length} warning{warnings.length > 1 ? "s" : ""}</Badge>}
            {draft.duplicate_info?.level && draft.duplicate_info.level !== "none" && <Badge tone="amber">possible duplicate</Badge>}
            {c.confidence === "low" && <Badge tone="amber">low confidence</Badge>}
            {draft.is_edited && <Badge>edited</Badge>}
          </div>
        </button>
        {draft.external_test_case_id && (
          draft.external_url
            ? <a href={draft.external_url} target="_blank" rel="noreferrer"><Badge tone="green">TC:{draft.external_test_case_id} <ExternalLink className="h-3 w-3" /></Badge></a>
            : <Badge tone="green">TC:{draft.external_test_case_id}</Badge>
        )}
      </div>

      {expanded && (
        <div className="space-y-3 border-t p-3">
          <DuplicateNotice draft={draft} editable={!locked} />
          {(errors.length > 0 || warnings.length > 0) && (
            <ul className="space-y-1 text-xs">
              {[...errors, ...warnings].map((i, k) => (
                <li key={k} className={i.severity === "error" ? "text-destructive" : "text-amber-700 dark:text-amber-300"}>
                  <b>{i.field}</b>: {i.message}
                </li>
              ))}
            </ul>
          )}
          {c.review_warnings?.length > 0 && <Notice tone="amber">{c.review_warnings.join(" · ")}</Notice>}

          <fieldset disabled={locked} className="space-y-3">
            <Field label="Name"><Input value={c.name} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Description"><Textarea value={c.description} onChange={(e) => set("description", e.target.value)} className="min-h-[56px]" /></Field>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Field label="Priority">
                <Select value={c.priority} onChange={(e) => set("priority", e.target.value)}>{PRIORITIES.map((p) => <option key={p}>{p}</option>)}</Select>
              </Field>
              <Field label="Category"><Input value={humanize(c.category)} disabled /></Field>
              <Field label="Automation"><Input value={humanize(c.automation_suitability)} disabled /></Field>
            </div>
            <ListEditor label="Preconditions" items={c.preconditions} onChange={(v) => set("preconditions", v)} />

            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-xs font-medium text-muted-foreground">Steps</span>
                {!locked && (
                  <Button size="sm" variant="ghost" onClick={() => set("steps", [...c.steps, { step_number: c.steps.length + 1, action: "", expected_result: "", test_data: "" }])}>
                    <Plus className="h-3.5 w-3.5" />Add step
                  </Button>
                )}
              </div>
              <div className="space-y-2">
                {c.steps.map((s, i) => (
                  <div key={i} className="grid grid-cols-[24px_1fr_1fr_auto] gap-2 rounded-md border p-2">
                    <span className="pt-2 text-center text-xs font-semibold text-muted-foreground">{i + 1}</span>
                    <div className="space-y-1">
                      <Textarea placeholder="Action" value={s.action} onChange={(e) => setStep(i, "action", e.target.value)} className="min-h-[52px] text-xs" />
                      <Input placeholder="Test data" value={s.test_data} onChange={(e) => setStep(i, "test_data", e.target.value)} className="h-7 text-xs" />
                    </div>
                    <Textarea placeholder="Expected result" value={s.expected_result} onChange={(e) => setStep(i, "expected_result", e.target.value)} className="min-h-[52px] text-xs" />
                    {!locked && (
                      <div className="flex flex-col gap-0.5">
                        <button disabled={i === 0} onClick={() => moveStep(i, -1)} className="rounded p-1 hover:bg-muted disabled:opacity-30" aria-label="Move up"><ArrowUp className="h-3 w-3" /></button>
                        <button disabled={i === c.steps.length - 1} onClick={() => moveStep(i, 1)} className="rounded p-1 hover:bg-muted disabled:opacity-30" aria-label="Move down"><ArrowDown className="h-3 w-3" /></button>
                        <button onClick={() => set("steps", c.steps.filter((_, j) => j !== i).map((x, j) => ({ ...x, step_number: j + 1 })))} className="rounded p-1 text-destructive hover:bg-muted" aria-label="Delete step"><Trash2 className="h-3 w-3" /></button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
            <Field label="Expected outcome"><Textarea value={c.expected_outcome} onChange={(e) => set("expected_outcome", e.target.value)} className="min-h-[48px]" /></Field>
            <Field label="Tags"><Input value={c.tags.join(", ")} onChange={(e) => set("tags", e.target.value.split(","))} placeholder="comma separated" /></Field>
          </fieldset>
          {c.assumptions?.length > 0 && <p className="text-xs text-muted-foreground"><b>Assumptions:</b> {c.assumptions.join("; ")}</p>}

          {!locked && (
            <div className="flex flex-wrap items-center gap-2 border-t pt-3">
              <Button size="sm" variant="ghost" className="text-destructive" loading={remove.isPending} onClick={() => remove.mutate()}><Trash2 className="h-3.5 w-3.5" />Delete</Button>
              <div className="ml-auto flex gap-2">
                {dirty && <Button size="sm" variant="outline" onClick={() => { setC(draft.content); setDirty(false); }}>Discard</Button>}
                {dirty && <Button size="sm" loading={update.isPending} onClick={() => update.mutate({ content: clean(c) })}>Save changes</Button>}
                {!dirty && draft.status !== "rejected" && (
                  <Button size="sm" variant="outline" onClick={() => update.mutate({ status: "rejected" })}><X className="h-3.5 w-3.5" />Reject</Button>
                )}
                {!dirty && draft.status === "rejected" && <Button size="sm" variant="outline" onClick={() => update.mutate({ status: "draft" })}>Restore</Button>}
                {!dirty && draft.status !== "approved" && draft.status !== "rejected" && (
                  <Button size="sm" disabled={errors.length > 0} title={errors.length ? "Fix validation errors first" : undefined}
                    onClick={() => update.mutate({ status: "approved" })}><Check className="h-3.5 w-3.5" />Approve</Button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
