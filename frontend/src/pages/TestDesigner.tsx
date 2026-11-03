import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, FileText, Search, Send, Sparkles, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { canWrite, useAuth } from "@/lib/auth";
import { useJob } from "@/lib/jobs";
import { useProject } from "@/lib/project";
import type { Analysis, Batch, Job, Page, RequirementDetail, RequirementRow } from "@/lib/types";
import { cn, fmtDate, humanize, qs } from "@/lib/utils";
import {
  Badge, Button, Card, CardBody, CardHeader, Checkbox, EmptyState, ErrorBox, Field, Input, Loading, Notice, PageHeader, Select, StatusBadge, Textarea,
} from "@/components/ui";
import NoProject from "@/components/NoProject";
import AnalysisView from "@/components/AnalysisView";
import DraftEditor from "@/components/DraftEditor";
import JobStatus from "@/components/JobStatus";
import SubmitDialog from "@/components/SubmitDialog";

const CATEGORIES = ["positive", "negative", "boundary", "validation", "error_handling", "security", "integration",
  "data_integrity", "regression", "concurrency", "accessibility", "other"];
const DEFAULT_COUNTS: Record<string, number> = { positive: 2, negative: 2, boundary: 1, validation: 1 };

function RequirementPicker({ projectId, value, onChange }: { projectId: number; value: number | null; onChange: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  useEffect(() => { const t = setTimeout(() => setDeb(q), 250); return () => clearTimeout(t); }, [q]);
  const list = useQuery({
    queryKey: ["req-picker", projectId, deb],
    queryFn: () => api.get<Page<RequirementRow>>(`/requirements${qs({ project_id: projectId, q: deb, include_summary: false, page_size: 30 })}`),
  });
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative p-2">
        <Search className="absolute left-4 top-4.5 h-4 w-4 translate-y-[2px] text-muted-foreground" />
        <Input className="pl-8" placeholder="Find requirement or RQ:id" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-1">
        {list.isLoading ? <Loading /> : list.data?.items.length ? list.data.items.map((r) => (
          <button key={r.id} onClick={() => onChange(r.id)}
            className={cn("flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-muted", value === r.id && "bg-accent text-accent-foreground")}>
            <span className="mt-0.5 w-12 shrink-0 font-mono text-[11px] text-muted-foreground">RQ:{r.external_id}</span>
            <span className="line-clamp-2">{r.name}</span>
          </button>
        )) : <EmptyState title="No requirements" description="Sync requirements first." />}
      </div>
    </div>
  );
}

export default function TestDesigner() {
  const { project } = useProject();
  const { user } = useAuth();
  const writer = canWrite(user);
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const reqId = params.get("requirement") ? Number(params.get("requirement")) : null;
  const setReqId = (id: number) => setParams({ requirement: String(id) });

  const [analysisJob, setAnalysisJob] = useState<number | null>(null);
  const [genJob, setGenJob] = useState<number | null>(null);
  const [batchId, setBatchId] = useState<number | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>(DEFAULT_COUNTS);
  const [maxSteps, setMaxSteps] = useState<number | "">("");
  const [instructions, setInstructions] = useState("");
  const [avoidDupes, setAvoidDupes] = useState(true);
  const [requireApproved, setRequireApproved] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "draft" | "approved" | "rejected" | "submitted">("all");

  const req = useQuery({ queryKey: ["requirement", reqId], queryFn: () => api.get<RequirementDetail>(`/requirements/${reqId}`), enabled: !!reqId });
  const analyses = useQuery({ queryKey: ["analyses", reqId], queryFn: () => api.get<Analysis[]>(`/requirements/${reqId}/analyses`), enabled: !!reqId });
  const batches = useQuery({
    queryKey: ["batches", project?.id, reqId],
    queryFn: () => api.get<any[]>(`/generation/batches${qs({ project_id: project!.id, requirement_id: reqId, limit: 10 })}`),
    enabled: !!project && !!reqId,
  });
  const batch = useQuery({ queryKey: ["batch", batchId], queryFn: () => api.get<Batch>(`/generation/batches/${batchId}`), enabled: !!batchId });

  // Reset per-requirement state; open the most recent batch for this requirement.
  useEffect(() => { setBatchId(null); setSelected([]); setAnalysisJob(null); setGenJob(null); }, [reqId]);
  useEffect(() => { if (!batchId && batches.data?.length) setBatchId(batches.data[0].id); }, [batches.data, batchId]);

  const startAnalysis = useMutation({
    mutationFn: () => api.post<Job>(`/requirements/${reqId}/analyses`),
    onSuccess: (j) => setAnalysisJob(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const aJob = useJob(analysisJob, (j) => {
    qc.invalidateQueries({ queryKey: ["analyses", reqId] });
    qc.invalidateQueries({ queryKey: ["requirement", reqId] });
    j.error ? toast.error(j.error) : toast.success("Analysis ready for review");
  });

  const total = Object.values(counts).reduce((a, b) => a + (b || 0), 0);
  const startGen = useMutation({
    mutationFn: () => api.post<Job>("/generation", {
      project_id: project!.id, requirement_ids: [reqId],
      config: { counts, max_steps: maxSteps || null, avoid_existing_duplicates: avoidDupes },
      instructions: instructions.trim() || null, require_approved_analysis: requireApproved,
    }),
    onSuccess: (j) => setGenJob(j.id),
    onError: (e) => toast.error(errorMessage(e)),
  });
  const gJob = useJob(genJob, (j) => {
    qc.invalidateQueries({ queryKey: ["batches", project?.id, reqId] });
    if (j.result?.batch_id) setBatchId(j.result.batch_id);
    else if (j.params?.batch_id) setBatchId(j.params.batch_id);
    j.error ? toast.error(j.error) : toast.success(`${j.result?.draft_count ?? ""} draft test case(s) ready for review`);
  });

  const drafts = useMemo(() => (batch.data?.drafts ?? []).filter((d) => filter === "all" || d.status === filter), [batch.data, filter]);
  const approvedIds = (batch.data?.drafts ?? []).filter((d) => d.status === "approved").map((d) => d.id);

  if (!project) return <NoProject />;
  const latest = analyses.data?.[0];
  const r = req.data;

  return (
    <>
      <PageHeader title="AI Test Designer" description="Analyse a requirement, generate draft test cases, review them, then create them in Spira with your approval." />
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_minmax(0,1.2fr)]">
        {/* Panel 1: requirement context */}
        <Card className="flex max-h-[calc(100vh-170px)] flex-col">
          <CardHeader title="Requirement" />
          {r ? (
            <div className="min-h-0 flex-1 overflow-y-auto p-3 text-sm">
              <div className="mb-2 flex items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">RQ:{r.external_id}</span>
                <StatusBadge status={r.status} />
                <button className="ml-auto text-xs text-primary hover:underline" onClick={() => setParams({})}>Change</button>
              </div>
              <h3 className="mb-2 font-medium">{r.name}</h3>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">{r.description_text || "No description."}</p>
              {r.custom_properties?.filter((c) => c.value).map((c) => (
                <div key={c.name} className="mt-2 text-xs"><b>{c.name}:</b> <span className="whitespace-pre-wrap">{String(c.value)}</span></div>
              ))}
              <div className="mt-3 border-t pt-2">
                <div className="mb-1 text-xs font-medium text-muted-foreground">Existing test cases ({r.linked_test_cases.length})</div>
                {r.linked_test_cases.map((t) => <div key={t.id} className="truncate text-xs"><span className="font-mono text-muted-foreground">TC:{t.external_id}</span> {t.name}</div>)}
              </div>
            </div>
          ) : reqId && req.isLoading ? <Loading /> : <RequirementPicker projectId={project.id} value={reqId} onChange={setReqId} />}
        </Card>

        {/* Panel 2: analysis + generation config */}
        <div className="space-y-4">
          <Card>
            <CardHeader title={<span className="flex items-center gap-1.5"><Brain className="h-4 w-4" />Analysis</span>}
              actions={reqId && writer && (
                <Button size="sm" variant={latest ? "outline" : "default"} loading={startAnalysis.isPending || (!!aJob && !aJob.finished_at)} onClick={() => startAnalysis.mutate()}>
                  <Wand2 className="h-3.5 w-3.5" />{latest ? "Re-analyse" : "Analyse requirement"}
                </Button>
              )} />
            <CardBody className="max-h-[52vh] overflow-y-auto">
              {!reqId ? <EmptyState icon={<FileText className="h-5 w-5" />} title="Pick a requirement" description="Choose a requirement on the left to begin." />
                : aJob && !aJob.finished_at ? <JobStatus job={aJob} />
                : analyses.isLoading ? <Loading />
                : latest ? <AnalysisView analysis={latest} editable={writer} />
                : <EmptyState title="Not analysed yet" description="Analysis extracts acceptance criteria, gaps and risks. It is optional but improves generated tests." />}
            </CardBody>
          </Card>

          {reqId && writer && (
            <Card>
              <CardHeader title={<span className="flex items-center gap-1.5"><Sparkles className="h-4 w-4" />Generate test cases</span>} description={`${total} test case(s) requested`} />
              <CardBody className="space-y-3">
                <div className="grid grid-cols-2 gap-2 2xl:grid-cols-3">
                  {CATEGORIES.map((c) => (
                    <label key={c} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-xs">
                      <span>{humanize(c)}</span>
                      <input type="number" min={0} max={10} value={counts[c] ?? 0}
                        onChange={(e) => setCounts({ ...counts, [c]: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })}
                        className="w-12 rounded border border-input bg-background px-1 py-0.5 text-right tabular-nums" />
                    </label>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Max steps per case"><Input type="number" min={1} max={50} placeholder="Auto" value={maxSteps} onChange={(e) => setMaxSteps(e.target.value ? Number(e.target.value) : "")} /></Field>
                  <div className="space-y-1.5 pt-5">
                    <Checkbox checked={avoidDupes} onChange={setAvoidDupes} label={<span className="text-xs">Avoid existing duplicates</span>} />
                    <Checkbox checked={requireApproved} onChange={setRequireApproved} label={<span className="text-xs">Require approved analysis</span>} />
                  </div>
                </div>
                <Field label="Extra instructions (optional)">
                  <Textarea value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="e.g. Use the staging test account, focus on the mobile layout…" className="min-h-[60px]" />
                </Field>
                {gJob && !gJob.finished_at && <JobStatus job={gJob} />}
                <Button className="w-full" disabled={total === 0 || total > 50} loading={startGen.isPending || (!!gJob && !gJob.finished_at)} onClick={() => startGen.mutate()}>
                  <Sparkles className="h-4 w-4" />Generate {total} draft{total === 1 ? "" : "s"}
                </Button>
                {total > 50 && <p className="text-xs text-destructive">At most 50 per batch.</p>}
              </CardBody>
            </Card>
          )}
        </div>

        {/* Panel 3: drafts */}
        <Card className="flex max-h-[calc(100vh-170px)] flex-col">
          <CardHeader
            title="Draft test cases"
            description={batch.data ? <>Batch #{batch.data.id} · {batch.data.provider} {batch.data.model} · {fmtDate(batch.data.created_at)}</> : "Generated drafts appear here for review"}
            actions={batches.data && batches.data.length > 1 && (
              <Select className="h-8 w-36 text-xs" value={batchId ?? ""} onChange={(e) => { setBatchId(Number(e.target.value)); setSelected([]); }}>
                {batches.data.map((b) => <option key={b.id} value={b.id}>#{b.id} · {b.draft_count} drafts</option>)}
              </Select>
            )}
          />
          {batch.data && (
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
              {(["all", "draft", "approved", "rejected", "submitted"] as const).map((f) => (
                <button key={f} onClick={() => setFilter(f)} className={cn("rounded-full px-2.5 py-0.5 text-xs", filter === f ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground")}>
                  {humanize(f)} {f !== "all" && `(${batch.data.drafts.filter((d) => d.status === f).length})`}
                </button>
              ))}
              {writer && (
                <div className="ml-auto flex gap-2">
                  {approvedIds.length > 0 && selected.length === 0 && <Button size="sm" variant="outline" onClick={() => setSelected(approvedIds)}>Select approved</Button>}
                  <Button size="sm" disabled={!selected.length} onClick={() => setSubmitOpen(true)}><Send className="h-3.5 w-3.5" />Review & submit ({selected.length})</Button>
                </div>
              )}
            </div>
          )}
          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
            {batch.data?.is_simulated && <Notice tone="amber">These drafts come from the simulated AI provider.</Notice>}
            {(batch.data?.summary?.skipped_categories?.length ?? 0) > 0 && (
              <Notice tone="blue">Skipped: {batch.data!.summary.skipped_categories.map((s: any) => `${humanize(s.category)} — ${s.reason}`).join("; ")}</Notice>
            )}
            <ErrorBox error={batch.error} />
            {batch.isLoading ? <Loading /> : drafts.length ? drafts.map((d) => (
              <DraftEditor key={d.id} draft={d} editable={writer} selected={selected.includes(d.id)}
                onSelect={(v) => setSelected((s) => (v ? [...s, d.id] : s.filter((x) => x !== d.id)))} />
            )) : <EmptyState icon={<Sparkles className="h-5 w-5" />} title={batch.data ? "No drafts match this filter" : "No drafts yet"}
              description={batch.data ? undefined : "Configure categories and generate test cases."} />}
          </div>
          {batch.data && (
            <div className="border-t px-3 py-2 text-[11px] text-muted-foreground">
              Drafts stay local until you approve a Spira submission. <Badge>{batch.data.drafts.length} total</Badge>
            </div>
          )}
        </Card>
      </div>

      {project && (
        <SubmitDialog open={submitOpen} onClose={() => setSubmitOpen(false)} projectId={project.id} draftIds={selected}
          onDone={() => { qc.invalidateQueries({ queryKey: ["batch", batchId] }); qc.invalidateQueries({ queryKey: ["requirement", reqId] }); setSelected([]); }} />
      )}
    </>
  );
}
