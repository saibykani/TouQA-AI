import { fmtBytes, humanize, qs } from "@/lib/utils";
import { isTerminal } from "@/lib/jobs";
import { statusTone } from "@/components/ui";

describe("utils", () => {
  it("builds query strings and drops empty values", () => {
    expect(qs({ project_id: 3, q: "", status: null, page: 2 })).toBe("?project_id=3&page=2");
    expect(qs({})).toBe("");
  });
  it("formats bytes and labels", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(humanize("data_integrity")).toBe("Data integrity");
  });
  it("treats only queued/running jobs as active", () => {
    expect(isTerminal("RUNNING")).toBe(false);
    expect(isTerminal("QUEUED")).toBe(false);
    expect(isTerminal("COMPLETED")).toBe(true);
    expect(isTerminal("NEEDS_REVIEW")).toBe(true);
    expect(isTerminal(undefined)).toBe(false);
  });
  it("maps statuses to tones", () => {
    expect(statusTone("COMPLETED")).toBe("green");
    expect(statusTone("FAILED")).toBe("red");
    expect(statusTone("needs_review")).toBe("amber");
  });
});
