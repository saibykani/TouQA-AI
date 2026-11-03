export interface User { id: number; email: string; display_name: string; role: string }
export interface SessionInfo { user: User; csrf_token: string | null; auth_enabled: boolean }
export interface PublicConfig {
  app_name: string; auth_enabled: boolean; demo_mode: boolean; demo_allow_external_writes: boolean;
  environment: string; max_upload_bytes: number; allowed_upload_types: string[];
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Project {
  id: number; platform: string; external_id: string; name: string; description: string | null;
  template_id: string | null; is_demo: boolean; last_synced_at: string | null; settings: Record<string, any>;
}

export interface Job {
  id: number; kind: string; status: string; project_id: number | null; progress: number; message: string | null;
  params: Record<string, any>; result: Record<string, any>; error: string | null; cancel_requested: boolean;
  is_demo: boolean; created_at: string; started_at: string | null; finished_at: string | null;
}

export interface Coverage { total?: number | null; passed?: number | null; failed?: number | null; caution?: number | null; blocked?: number | null }
export interface RequirementRow {
  id: number; external_id: string; name: string; status: string | null; type: string | null; importance: string | null;
  owner: string | null; release: string | null; release_external_id: string | null; indent_level: string | null;
  is_summary: boolean; parent_id: number | null; coverage: Coverage | null; updated_at: string | null; is_deleted_externally: boolean;
}
export interface RequirementDetail extends RequirementRow {
  description_html: string | null; description_text: string | null; author: string | null; tags: string | null;
  steps: { position: number; description: string }[]; custom_properties: { name: string; value: any }[];
  created_at: string | null; synced_at: string | null; url: string | null;
  parent: { id: number; external_id: string; name: string } | null; children: RequirementRow[];
  linked_test_cases: { id: number; external_id: string; name: string; status: string | null; execution_status: string | null; step_count: number }[];
  unresolved_test_case_links: string[];
  related_incidents: any[];
  analyses: { id: number; status: string; provider: string; model: string; is_simulated: boolean; created_at: string; approved_at: string | null }[];
}

export type Basis = "grounded" | "inference";
export interface Statement { text: string; basis: Basis; source_field: string }
export interface AcceptanceCriterion {
  id: string; text: string; origin: "imported" | "proposed"; source_field: string; source_quote: string;
  clarity: "clear" | "ambiguous" | "contradictory" | "untestable"; notes: string;
}
export interface AnalysisContent {
  requirement_id: string; requirement_title: string; summary: string; business_objective: Statement;
  actors: Statement[]; dependencies: Statement[]; functional_behavior: Statement[]; inputs: Statement[]; outputs: Statement[];
  business_rules: Statement[]; preconditions: Statement[]; postconditions: Statement[];
  acceptance_criteria: AcceptanceCriterion[];
  gaps: { category: string; description: string; related_criteria: string[]; suggested_question: string }[];
  testability: string; testability_rationale: string; complexity: string; failure_modes: Statement[];
  risks: { description: string; kind: string; severity: string; basis: Basis }[];
  assumptions: string[]; clarification_questions: string[];
  test_objectives: { id: string; objective: string; criterion_ids: string[]; category: string; basis: Basis }[];
  coverage_matrix: { criterion_id: string; status: string; existing_test_case_ids: string[]; proposed_objective_ids: string[]; rationale: string }[];
}
export interface Analysis {
  id: number; requirement_id: number; job_id: number | null; status: string; content: AnalysisContent | null;
  is_edited: boolean; provider: string; model: string; prompt_version: string; is_simulated: boolean;
  approved_at: string | null; created_at: string; updated_at: string;
}

export interface GeneratedStep { step_number: number; action: string; expected_result: string; test_data: string }
export interface TestCaseContent {
  name: string; description: string; requirement_id: string; acceptance_criterion_ids: string[]; category: string;
  objective: string; preconditions: string[]; test_data: string[]; steps: GeneratedStep[]; expected_outcome: string;
  priority: string; risk_level: string; automation_suitability: string; automation_rationale: string; tags: string[];
  assumptions: string[]; source_references: string[]; confidence: string; review_warnings: string[];
}
export interface Issue { field: string; severity: "error" | "warning" | "info"; message: string }
export interface Draft {
  id: number; batch_id: number; requirement_id: number | null; position: number; status: string;
  content: TestCaseContent; is_edited: boolean; duplicate_info: any; duplicate_decision: string | null;
  validation_errors: Issue[]; external_test_case_id: string | null; external_url: string | null; updated_at: string;
}
export interface Batch {
  id: number; project_id: number; job_id: number | null; requirement_ids: number[]; config: any; instructions: string | null;
  provider: string; model: string; is_simulated: boolean; summary: any; created_at: string; drafts: Draft[];
}

export interface FolderNode { id?: number; external_id: string; name: string; children?: FolderNode[]; [k: string]: any }

export interface Attachment {
  id: number; filename: string; content_type: string; size_bytes: number; width: number | null; height: number | null;
  sha256: string; include_in_submission: boolean; analysis: any; upload_results: any; created_at: string; is_image: boolean;
}
export interface IncidentDraft {
  id: number; project_id: number; status: string; title: string | null; raw_notes: string; evidence: any;
  content: any; classification: any; destinations: ("spira" | "jira")[]; ai_provider: string | null; ai_model: string | null;
  is_simulated: boolean; results: Record<string, any> | null; validation: Issue[]; attachments: Attachment[];
  created_at: string; updated_at: string;
}
