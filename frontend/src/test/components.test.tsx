import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Button, Dialog, StatusBadge } from "@/components/ui";
import DraftEditor from "@/components/DraftEditor";
import type { Draft } from "@/lib/types";

const draft: Draft = {
  id: 7, batch_id: 1, requirement_id: 3, position: 1, status: "draft", is_edited: false, duplicate_decision: null,
  external_test_case_id: null, external_url: null, updated_at: "2026-11-01T00:00:00Z",
  duplicate_info: { checked: true, level: "possible", matches: [{ kind: "test_case", external_id: "55", name: "Login works", score: 0.62, title_only: true, explanation: "title similarity only" }] },
  validation_errors: [{ field: "steps[1].expected_result", severity: "error", message: "Expected result is not verifiable" }],
  content: {
    name: "Login with valid credentials", description: "d", requirement_id: "3", acceptance_criterion_ids: ["AC-1"], category: "positive",
    objective: "o", preconditions: [], test_data: [], expected_outcome: "ok", priority: "high", risk_level: "low",
    automation_suitability: "high", automation_rationale: "", tags: [], assumptions: [], source_references: [], confidence: "high", review_warnings: [],
    steps: [{ step_number: 1, action: "Enter valid user", expected_result: "Works", test_data: "" }],
  },
};

const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

describe("ui kit", () => {
  it("disables a loading button", () => {
    render(<Button loading>Save</Button>);
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });
  it("renders status text without underscores", () => {
    render(<StatusBadge status="NEEDS_REVIEW" />);
    expect(screen.getByText("NEEDS REVIEW")).toBeInTheDocument();
  });
  it("closes a dialog on Escape", () => {
    const onClose = vi.fn();
    render(<Dialog open onClose={onClose} title="T">body</Dialog>);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });
});

describe("DraftEditor", () => {
  it("summarises validation and duplicate state, and blocks approval on errors", () => {
    wrap(<DraftEditor draft={draft} editable selected={false} onSelect={() => {}} />);
    expect(screen.getByText("Login with valid credentials")).toBeInTheDocument();
    expect(screen.getByText(/1 error/)).toBeInTheDocument();
    expect(screen.getByText("possible duplicate")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Login with valid credentials"));
    expect(screen.getByText(/title similarity only\)/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
  });
  it("is read-only once submitted", () => {
    wrap(<DraftEditor draft={{ ...draft, status: "submitted", external_test_case_id: "901" }} editable selected={false} onSelect={() => {}} />);
    expect(screen.queryByRole("checkbox", { name: /select for submission/i })).toBeNull();
    expect(screen.getByText("TC:901")).toBeInTheDocument();
  });
});
