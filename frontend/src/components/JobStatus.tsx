import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { isTerminal } from "@/lib/jobs";
import type { Job } from "@/lib/types";
import { Button, Notice, Progress, Spinner, StatusBadge } from "./ui";

/** Inline progress row for a background job, with cancel. */
export default function JobStatus({ job, label }: { job: Job | null; label?: string }) {
  const cancel = useMutation({
    mutationFn: () => api.post(`/jobs/${job!.id}/cancel`),
    onSuccess: () => toast.message("Cancellation requested"),
    onError: (e) => toast.error(errorMessage(e)),
  });
  if (!job) return null;
  const active = !isTerminal(job.status);
  return (
    <div className="space-y-2 rounded-md border bg-muted/40 p-3">
      <div className="flex items-center gap-2 text-sm">
        {active && <Spinner />}
        <span className="flex-1 truncate">{job.message ?? label ?? job.kind}</span>
        <StatusBadge status={job.status} />
        {active && !job.cancel_requested && (
          <Button size="sm" variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel</Button>
        )}
      </div>
      {active && <Progress value={job.progress} />}
      {job.error && <Notice tone="red">{job.error}</Notice>}
    </div>
  );
}
