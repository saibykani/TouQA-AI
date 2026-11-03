import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, HelpCircle, Pencil, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import type { AcceptanceCriterion, Analysis, AnalysisContent, Statement } from "@/lib/types";
import { cn, fmtDate, humanize } from "@/lib/utils";
import { Badge, Button, Notice, StatusBadge, Textarea } from "./ui";

function BasisTag({ basis, source }: { basis: string; source?: string }) {
  return basis === "grounded"
    ? <Badge tone="green" title={source ? `From ${source}` : undefined}>grounded</Badge>
    : <Badge tone="amber" title="AI inference — verify before relying on it">inference</Badge>;
}

const clarityTone = { clear: "green", ambiguous: "amber", contradictory: "red", untestable: "red" } as const;

function Section({ title, children, count }: { title: string; children: React.ReactNode; count?: number }) {
  return (
    <details open className="group border-b last:border-0">
      <summary className="flex cursor-pointer list-none items-center justify-between py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {title} {count != null && <span className="font-normal normal-case">{count}</span>}
      </summary>
      <div className="pb-3">{children}</div>
    </details>
  );
}

function Statements({ items }: { items: Statement[] }) {
  if (!items?.length) return <p className="text-xs italic text-muted-foreground">None identified.</p>;
  return (
    <ul className="space-y-1.5">
      {items.map((s, i) => (
        <li key={i} className="flex items-start gap-2 text-sm"><span className="flex-1">{s.text}</span><BasisTag basis={s.basis} source={s.source_field} /></li>
      ))}
    </ul>
  );
}

export default function AnalysisView({ analysis, editable }: { analysis: Analysis; editable: boolean }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const [text, setText] = useState("");
  const c = analysis.content as AnalysisContent;
  const refresh = () => qc.invalidateQueries({ queryKey: ["analyses", analysis.requirement_id] });

  const save = useMutation({
    mutationFn: (content: AnalysisContent) => api.put(`/analyses/${analysis.id}`, { content }),
    onSuccess: () => { refresh(); setEditing(null); toast.success("Analysis updated"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const approve = useMutation({
    mutationFn: () => api.post(`/analyses/${analysis.id}/approve`),
    onSuccess: () => { refresh(); toast.success("Analysis approved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!c) return <Notice tone="amber">This analysis has no content.</Notice>;

  const updateCriterion = (i: number, patch: Partial<AcceptanceCriterion>) => {
    const acs = c.acceptance_criteria.map((a, j) => (j === i ? { ...a, ...patch } : a));
    save.mutate({ ...c, acceptance_criteria: acs });
  };
  const removeCriterion = (i: number) => save.mutate({ ...c, acceptance_criteria: c.acceptance_criteria.filter((_, j) => j !== i) });

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StatusBadge status={analysis.status} />
        {analysis.is_simulated && <Badge tone="violet">simulated AI</Badge>}
        {analysis.is_edited && <Badge>edited</Badge>}
        <span className="text-xs text-muted-foreground">{analysis.provider} · {analysis.model} · {fmtDate(analysis.created_at)}</span>
        <div className="ml-auto flex gap-1">
          <a href={api.url(`/analyses/${analysis.id}/export?format=markdown`)} target="_blank" rel="noreferrer">
            <Button size="sm" variant="ghost"><Download className="h-3.5 w-3.5" />Export</Button>
          </a>
          {editable && analysis.status !== "approved" && (
            <Button size="sm" variant="outline" loading={approve.isPending} onClick={() => approve.mutate()}><CheckCircle2 className="h-3.5 w-3.5" />Approve</Button>
          )}
        </div>
      </div>
      {analysis.is_simulated && <Notice tone="amber" className="mb-3">Simulated output for demonstration. Configure an AI provider for real analysis.</Notice>}

      <p className="mb-3 text-sm leading-relaxed">{c.summary}</p>
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        <Badge tone="blue">Testability: {c.testability}</Badge>
        <Badge>Complexity: {c.complexity}</Badge>
      </div>

      <Section title="Acceptance criteria" count={c.acceptance_criteria.length}>
        <ul className="space-y-2">
          {c.acceptance_criteria.map((a, i) => (
            <li key={a.id} className={cn("rounded-md border p-2 text-sm", a.origin === "proposed" && "border-dashed")}>
              <div className="mb-1 flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] font-semibold">{a.id}</span>
                <Badge tone={a.origin === "imported" ? "green" : "violet"} title={a.origin === "proposed" ? "Suggested by AI — not in the source record" : `From ${a.source_field}`}>{a.origin}</Badge>
                <Badge tone={clarityTone[a.clarity]}>{a.clarity}</Badge>
                {editable && editing !== i && (
                  <span className="ml-auto flex gap-1">
                    <button className="rounded p-1 text-muted-foreground hover:bg-muted" onClick={() => { setEditing(i); setText(a.text); }} aria-label="Edit criterion"><Pencil className="h-3 w-3" /></button>
                    {a.origin === "proposed" && <button className="rounded px-1 text-[11px] text-muted-foreground hover:bg-muted" onClick={() => removeCriterion(i)}>Remove</button>}
                  </span>
                )}
              </div>
              {editing === i ? (
                <div className="space-y-2">
                  <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-[60px]" />
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                    <Button size="sm" loading={save.isPending} onClick={() => updateCriterion(i, { text })}>Save</Button>
                  </div>
                </div>
              ) : <p>{a.text}</p>}
              {a.source_quote && <p className="mt-1 border-l-2 pl-2 text-xs italic text-muted-foreground">“{a.source_quote}”</p>}
              {a.notes && <p className="mt-1 text-xs text-muted-foreground">{a.notes}</p>}
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Gaps & clarifications" count={c.gaps.length + c.clarification_questions.length}>
        <ul className="space-y-2">
          {c.gaps.map((g, i) => (
            <li key={i} className="rounded-md bg-amber-500/5 p-2 text-sm">
              <div className="flex items-center gap-1.5"><HelpCircle className="h-3.5 w-3.5 text-amber-600" /><b className="text-xs">{humanize(g.category)}</b></div>
              <p className="mt-1">{g.description}</p>
              {g.suggested_question && <p className="mt-1 text-xs text-muted-foreground">Ask: {g.suggested_question}</p>}
            </li>
          ))}
          {c.clarification_questions.map((q, i) => <li key={`q${i}`} className="text-sm">• {q}</li>)}
          {!c.gaps.length && !c.clarification_questions.length && <p className="text-xs italic text-muted-foreground">No gaps found.</p>}
        </ul>
      </Section>

      <Section title="Risks" count={c.risks.length}>
        <ul className="space-y-1.5">
          {c.risks.map((r, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              <ShieldAlert className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", r.severity === "high" ? "text-red-500" : r.severity === "medium" ? "text-amber-500" : "text-muted-foreground")} />
              <span className="flex-1">{r.description}</span>
              <Badge>{humanize(r.kind)}</Badge>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Coverage" count={c.coverage_matrix.length}>
        <ul className="space-y-1 text-sm">
          {c.coverage_matrix.map((m) => (
            <li key={m.criterion_id} className="flex items-center gap-2">
              <span className="w-12 font-mono text-[11px]">{m.criterion_id}</span>
              <StatusBadge status={m.status} />
              <span className="truncate text-xs text-muted-foreground">{m.existing_test_case_ids.map((x) => `TC:${x}`).join(", ") || m.rationale}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Behaviour & rules">
        <div className="space-y-3">
          <div><div className="mb-1 text-xs text-muted-foreground">Business objective</div><Statements items={[c.business_objective]} /></div>
          <div><div className="mb-1 text-xs text-muted-foreground">Functional behaviour</div><Statements items={c.functional_behavior} /></div>
          <div><div className="mb-1 text-xs text-muted-foreground">Business rules</div><Statements items={c.business_rules} /></div>
          <div><div className="mb-1 text-xs text-muted-foreground">Preconditions</div><Statements items={c.preconditions} /></div>
          <div><div className="mb-1 text-xs text-muted-foreground">Failure modes</div><Statements items={c.failure_modes} /></div>
        </div>
      </Section>

      {c.assumptions.length > 0 && (
        <Section title="Assumptions" count={c.assumptions.length}>
          <ul className="list-disc space-y-1 pl-5 text-sm">{c.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </Section>
      )}
    </div>
  );
}
