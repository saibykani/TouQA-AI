"""Structured output schemas for every AI task.

These Pydantic models are sent to the provider as the JSON output schema and used to
validate the response before anything is displayed or sent to an external system.
Free-form dicts are avoided so schemas stay compatible with strict structured output.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Basis = Literal["grounded", "inference"]

SCENARIO_CATEGORIES = (
    "positive", "negative", "boundary", "validation", "integration", "security",
    "data_integrity", "regression", "error_handling", "concurrency", "accessibility", "other",
)
ScenarioCategory = Literal[
    "positive", "negative", "boundary", "validation", "integration", "security",
    "data_integrity", "regression", "error_handling", "concurrency", "accessibility", "other",
]


# --------------------------------------------------------------------------- analysis
class Statement(BaseModel):
    text: str
    basis: Basis = Field(description="'grounded' if stated in the imported record/project data; 'inference' otherwise")
    source_field: str = Field(description="Record field the statement comes from (e.g. 'description', 'parent', 'custom:Acceptance Criteria'); 'n/a' for inferences")


class AcceptanceCriterion(BaseModel):
    id: str = Field(description="Stable identifier such as AC-1")
    text: str
    origin: Literal["imported", "proposed"] = Field(description="'imported' if present in the source record; 'proposed' if suggested by AI as missing")
    source_field: str
    source_quote: str = Field(description="Verbatim excerpt from the source; empty for proposed criteria")
    clarity: Literal["clear", "ambiguous", "contradictory", "untestable"]
    notes: str


class Gap(BaseModel):
    category: Literal[
        "missing_criterion", "validation_rule", "error_behavior", "boundary_condition",
        "ambiguity", "contradiction", "dependency", "other",
    ]
    description: str
    related_criteria: list[str]
    suggested_question: str


class Risk(BaseModel):
    description: str
    kind: Literal["functional", "security", "authorization", "data_integrity", "performance", "usability", "integration", "other"]
    severity: Literal["low", "medium", "high"]
    basis: Basis


class TestObjective(BaseModel):
    __test__ = False
    id: str = Field(description="Identifier such as TO-1")
    objective: str
    criterion_ids: list[str]
    category: ScenarioCategory
    basis: Basis


class CoverageEntry(BaseModel):
    criterion_id: str
    status: Literal["fully_covered", "partially_covered", "not_covered", "needs_clarification"]
    existing_test_case_ids: list[str] = Field(description="External IDs of existing linked test cases that cover it")
    proposed_objective_ids: list[str]
    rationale: str


class RequirementAnalysisContent(BaseModel):
    requirement_id: str
    requirement_title: str
    summary: str
    business_objective: Statement
    actors: list[Statement]
    dependencies: list[Statement]
    functional_behavior: list[Statement]
    inputs: list[Statement]
    outputs: list[Statement]
    business_rules: list[Statement]
    preconditions: list[Statement]
    postconditions: list[Statement]
    acceptance_criteria: list[AcceptanceCriterion]
    gaps: list[Gap]
    testability: Literal["high", "medium", "low"]
    testability_rationale: str
    complexity: Literal["low", "medium", "high"]
    failure_modes: list[Statement]
    risks: list[Risk]
    assumptions: list[str]
    clarification_questions: list[str]
    test_objectives: list[TestObjective]
    coverage_matrix: list[CoverageEntry]


# -------------------------------------------------------------------------- test cases
class GeneratedStep(BaseModel):
    step_number: int
    action: str
    expected_result: str
    test_data: str = Field(description="Data used in this step, or empty string")


class GeneratedTestCase(BaseModel):
    name: str
    description: str
    requirement_id: str = Field(description="External ID of the requirement this case verifies")
    acceptance_criterion_ids: list[str]
    category: ScenarioCategory
    objective: str
    preconditions: list[str]
    test_data: list[str]
    steps: list[GeneratedStep]
    expected_outcome: str
    priority: Literal["critical", "high", "medium", "low"]
    risk_level: Literal["high", "medium", "low"]
    automation_suitability: Literal["high", "medium", "low", "not_suitable"]
    automation_rationale: str
    tags: list[str]
    assumptions: list[str]
    source_references: list[str]
    confidence: Literal["high", "medium", "low"]
    review_warnings: list[str]


class SkippedCategory(BaseModel):
    category: ScenarioCategory
    reason: str


class GenerationOutput(BaseModel):
    test_cases: list[GeneratedTestCase]
    skipped_categories: list[SkippedCategory]
    notes: str


# --------------------------------------------------------------------------- incidents
class ObservedFact(BaseModel):
    statement: str
    source: Literal["user_notes", "screenshot", "log", "api_details", "environment", "linked_record"]


class Hypothesis(BaseModel):
    statement: str
    rationale: str


class EnvironmentInfo(BaseModel):
    environment: str
    browser: str
    operating_system: str
    device: str
    application_version: str
    release: str


class IncidentDraftContent(BaseModel):
    title: str
    summary: str
    description: str
    environment: EnvironmentInfo
    preconditions: list[str]
    steps_to_reproduce: list[str]
    expected_result: str
    actual_result: str
    reproducibility: Literal["always", "intermittent", "once", "unknown"]
    impact: str
    severity: Literal["critical", "high", "medium", "low", "unknown"]
    priority: Literal["critical", "high", "medium", "low", "unknown"]
    affected_component: str
    observed_facts: list[ObservedFact]
    hypotheses: list[Hypothesis]
    evidence_summary: list[str]
    suggested_diagnostics: list[str]
    missing_information: list[str]
    clarification_questions: list[str]
    related_requirement_ids: list[str]
    related_test_case_ids: list[str]


class ScreenshotAnalysis(BaseModel):
    visible_ui_state: str
    displayed_errors: list[str]
    validation_messages: list[str]
    contextual_details: list[str]
    uncertainty_notes: str
