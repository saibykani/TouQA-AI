import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { canWrite, useAuth } from "@/lib/auth";
import { useProject } from "@/lib/project";
import { humanize } from "@/lib/utils";
import { Badge, Button, Card, CardBody, CardHeader, ErrorBox, Field, Input, Loading, Notice, PageHeader, Select, Table, Td, Th } from "@/components/ui";
import NoProject from "@/components/NoProject";

function ProjectSettings() {
  const { project } = useProject();
  const { user } = useAuth();
  const qc = useQueryClient();
  const meta = useQuery({ queryKey: ["metadata", project!.id], queryFn: () => api.get<Record<string, any[]>>(`/projects/${project!.id}/metadata`) });
  const [v, setV] = useState({ acceptance_criteria_field: "", default_test_case_status_id: "", default_test_case_type_id: "" });
  useEffect(() => {
    const s = project?.settings ?? {};
    setV({ acceptance_criteria_field: s.acceptance_criteria_field ?? "", default_test_case_status_id: s.default_test_case_status_id ?? "", default_test_case_type_id: s.default_test_case_type_id ?? "" });
  }, [project]);
  const save = useMutation({
    mutationFn: () => api.put(`/projects/${project!.id}/settings`, {
      acceptance_criteria_field: v.acceptance_criteria_field || null,
      default_test_case_status_id: v.default_test_case_status_id || null,
      default_test_case_type_id: v.default_test_case_type_id || null,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); toast.success("Project settings saved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const m = meta.data ?? {};
  const customFields: any[] = m.custom_property_definition ?? m.custom_property ?? [];
  return (
    <Card>
      <CardHeader title="Project settings" description={project!.name} />
      <CardBody className="space-y-3">
        <fieldset disabled={!canWrite(user)} className="grid gap-3 md:grid-cols-3">
          <Field label="Acceptance criteria field" hint="Spira custom field holding acceptance criteria. Leave empty to read them from the description.">
            {customFields.length ? (
              <Select value={v.acceptance_criteria_field} onChange={(e) => setV({ ...v, acceptance_criteria_field: e.target.value })}>
                <option value="">Description text</option>
                {customFields.map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
              </Select>
            ) : <Input value={v.acceptance_criteria_field} onChange={(e) => setV({ ...v, acceptance_criteria_field: e.target.value })} placeholder="e.g. Acceptance Criteria" />}
          </Field>
          <Field label="Default test case status">
            <Select value={v.default_test_case_status_id} onChange={(e) => setV({ ...v, default_test_case_status_id: e.target.value })}>
              <option value="">(Spira default)</option>{(m.test_case_status ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </Select>
          </Field>
          <Field label="Default test case type">
            <Select value={v.default_test_case_type_id} onChange={(e) => setV({ ...v, default_test_case_type_id: e.target.value })}>
              <option value="">(Spira default)</option>{(m.test_case_type ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </Select>
          </Field>
        </fieldset>
        {canWrite(user) && <Button loading={save.isPending} onClick={() => save.mutate()}>Save settings</Button>}
      </CardBody>
    </Card>
  );
}

function Mappings() {
  const { project } = useProject();
  const { user } = useAuth();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["mappings", project!.id], queryFn: () => api.get<any>(`/projects/${project!.id}/mappings`) });
  const save = useMutation({
    mutationFn: (b: { field: string; canonical_value: string; external_value_id: string; external_value_name: string }) =>
      api.put(`/projects/${project!.id}/mappings`, { platform: "spira", ...b }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mappings", project!.id] }); toast.success("Mapping saved"); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const fields = q.data.spira_fields as Record<string, { allowed: { id: string; name: string }[]; resolution: Record<string, any> }>;
  return (
    <Card>
      <CardHeader title="Field mapping" description="How TouQA's priority/severity levels map to your Spira project's values. Unresolved values are left empty rather than guessed." />
      <CardBody className="space-y-5">
        {Object.entries(fields).map(([field, f]) => (
          <div key={field}>
            <div className="mb-2 text-sm font-medium">{humanize(field)}</div>
            {!f.allowed.length ? <Notice tone="amber">No Spira values synced for this field. Run a metadata sync.</Notice> : (
              <Table className="rounded-md border">
                <thead><tr><Th>TouQA value</Th><Th>Spira value</Th><Th>Source</Th></tr></thead>
                <tbody>
                  {Object.entries(f.resolution).map(([canonical, r]) => (
                    <tr key={canonical}>
                      <Td className="capitalize">{canonical}</Td>
                      <Td>
                        <Select className="h-8 max-w-xs text-xs" disabled={!canWrite(user)} value={r.id ?? ""}
                          onChange={(e) => {
                            const opt = f.allowed.find((a) => a.id === e.target.value);
                            if (opt) save.mutate({ field, canonical_value: canonical, external_value_id: opt.id, external_value_name: opt.name });
                          }}>
                          <option value="">(unresolved)</option>
                          {f.allowed.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </Select>
                      </Td>
                      <Td><Badge tone={r.source === "mapping" ? "green" : r.source === "name_match" ? "blue" : "amber"}>{humanize(r.source)}</Badge></Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </div>
        ))}
      </CardBody>
    </Card>
  );
}

export default function Settings() {
  const { project } = useProject();
  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Settings & Mapping" description="Per-project defaults used when creating records in Spira." />
      <div className="space-y-4">
        <ProjectSettings />
        <Mappings />
      </div>
    </>
  );
}
