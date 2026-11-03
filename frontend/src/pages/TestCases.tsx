import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { fmtDate } from "@/lib/utils";
import { Badge, Button, Dialog, ErrorBox, KV, Loading, PageHeader, Select, StatusBadge, Table, Td, Th } from "@/components/ui";
import RecordTable, { useOpenParam } from "@/components/RecordTable";
import NoProject from "@/components/NoProject";

function TestCaseDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["test-case", id], queryFn: () => api.get<any>(`/test-cases/${id}`) });
  const t = q.data;
  return (
    <Dialog open onClose={onClose} wide title={t ? <><span className="mr-2 font-mono text-xs text-muted-foreground">TC:{t.external_id}</span>{t.name}</> : "Test case"}
      footer={t?.url && <a href={t.url} target="_blank" rel="noreferrer"><Button variant="outline"><ExternalLink className="h-4 w-4" />Open in Spira</Button></a>}>
      {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} /> : t && (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-[1fr_220px]">
            <div>
              <p className="whitespace-pre-wrap text-sm">{t.description_text || <span className="italic text-muted-foreground">No description</span>}</p>
              {t.folder_path?.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Folder: {t.folder_path.join(" / ")}</p>}
            </div>
            <div>
              <KV label="Status"><StatusBadge status={t.status} /></KV>
              <KV label="Execution"><StatusBadge status={t.execution_status} /></KV>
              <KV label="Priority">{t.priority}</KV>
              <KV label="Type">{t.type}</KV>
              <KV label="Owner">{t.owner}</KV>
              <KV label="Origin">{t.origin === "touqa" ? <Badge tone="violet">TouQA</Badge> : "Spira"}</KV>
              <KV label="Synced">{fmtDate(t.synced_at)}</KV>
            </div>
          </div>
          <Table className="rounded-md border">
            <thead><tr><Th className="w-10">#</Th><Th>Action</Th><Th>Expected result</Th><Th>Sample data</Th></tr></thead>
            <tbody>
              {t.steps.length ? t.steps.map((s: any) => (
                <tr key={s.position}>
                  <Td className="text-muted-foreground">{s.position}</Td>
                  <Td className="whitespace-pre-wrap">{s.linked_test_case_external_id ? <i>Calls TC:{s.linked_test_case_external_id}</i> : s.description}</Td>
                  <Td className="whitespace-pre-wrap">{s.expected_result}</Td>
                  <Td className="whitespace-pre-wrap text-xs">{s.sample_data}</Td>
                </tr>
              )) : <tr><Td colSpan={4} className="text-center text-muted-foreground">No steps imported</Td></tr>}
            </tbody>
          </Table>
          <div className="grid gap-4 md:grid-cols-2 text-sm">
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">Covers requirements</div>
              {t.requirements.length ? t.requirements.map((r: any) => (
                <Link key={r.id} to={`/requirements/${r.id}`} className="block truncate hover:underline"><span className="font-mono text-xs text-muted-foreground">RQ:{r.external_id}</span> {r.name}</Link>
              )) : <span className="text-muted-foreground">None</span>}
            </div>
            <div>
              <div className="mb-1 text-xs font-medium text-muted-foreground">In test sets</div>
              {t.test_sets.length ? t.test_sets.map((s: any) => (
                <Link key={s.id} to={`/test-sets?open=${s.id}`} className="block truncate hover:underline"><span className="font-mono text-xs text-muted-foreground">TX:{s.external_id}</span> {s.name}</Link>
              )) : <span className="text-muted-foreground">None</span>}
            </div>
          </div>
        </div>
      )}
    </Dialog>
  );
}

export default function TestCases() {
  const { project } = useProject();
  const [open, close] = useOpenParam();
  const [origin, setOrigin] = useState("");
  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Test Cases" description="Test cases imported from Spira, including ones created through TouQA." />
      <RecordTable<any>
        endpoint="/test-cases" projectId={project.id} placeholder="Search name or TC:id" filters={{ origin }}
        extra={<Select className="h-9 w-40" value={origin} onChange={(e) => setOrigin(e.target.value)}><option value="">All origins</option><option value="spira">From Spira</option><option value="touqa">Created by TouQA</option></Select>}
        columns={[
          { header: "ID", cell: (r) => <span className="font-mono text-xs text-muted-foreground">TC:{r.external_id}</span>, className: "w-24" },
          { header: "Name", cell: (r) => <span className="font-medium">{r.name}</span> },
          { header: "Status", cell: (r) => <StatusBadge status={r.status} /> },
          { header: "Execution", cell: (r) => <StatusBadge status={r.execution_status} /> },
          { header: "Priority", cell: (r) => r.priority ?? "—" },
          { header: "Owner", cell: (r) => r.owner ?? "—" },
          { header: "Origin", cell: (r) => (r.origin === "touqa" ? <Badge tone="violet">TouQA</Badge> : <span className="text-xs text-muted-foreground">Spira</span>) },
        ]}
      />
      {open && <TestCaseDetail id={open} onClose={close} />}
    </>
  );
}
