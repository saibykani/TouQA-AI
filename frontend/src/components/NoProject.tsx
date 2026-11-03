import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderPlus } from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { useProject } from "@/lib/project";
import type { Project } from "@/lib/types";
import { Button, Card, EmptyState, Loading } from "./ui";

/** Shown by project-scoped pages when no project has been imported yet. */
export default function NoProject() {
  const { loading, setProjectId } = useProject();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const seed = useMutation({
    mutationFn: () => api.post<Project>("/projects/demo/seed"),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      setProjectId(p.id);
      toast.success("Demo project loaded");
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (loading) return <Loading />;
  return (
    <Card>
      <EmptyState
        icon={<FolderPlus className="h-6 w-6" />}
        title="No project selected"
        description="Connect Spira and import a project, or load the synthetic demo project to explore TouQA without touching real systems."
        action={
          <div className="flex gap-2">
            <Button onClick={() => navigate("/integrations")}>Connect Spira</Button>
            <Button variant="outline" loading={seed.isPending} onClick={() => seed.mutate()}>Load demo project</Button>
          </div>
        }
      />
    </Card>
  );
}
