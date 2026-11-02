"""Synthetic demo data. Loaded only on request in DEMO_MODE; every row is flagged is_demo.

Names are fictional ("Northwind Pay" is a placeholder product), IDs are local-only and the
project is labelled "(synthetic demo)" everywhere it appears.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import (
    Folder, Incident, Project, ProjectMetadata, Release, Requirement, RequirementTestCase,
    TestCase, TestSet, TestSetTestCase, TestStep,
)

DEMO_EXTERNAL_ID = "demo-1"


def seed(db: Session) -> Project:
    existing = db.query(Project).filter_by(external_id=DEMO_EXTERNAL_ID, is_demo=True).one_or_none()
    if existing:
        return existing
    now = utcnow()
    p = Project(platform="spira", external_id=DEMO_EXTERNAL_ID, name="Northwind Pay (synthetic demo)",
                description="Synthetic project for exploring TouQA AI. No data comes from a real system.",
                template_id=None, is_demo=True, last_synced_at=now, settings={}, raw={"synthetic": True})
    db.add(p)
    db.flush()

    meta = {
        "incident_priority": [("1", "1 - Critical"), ("2", "2 - High"), ("3", "3 - Medium"), ("4", "4 - Low")],
        "incident_severity": [("1", "1 - Critical"), ("2", "2 - High"), ("3", "3 - Medium"), ("4", "4 - Low")],
        "incident_type": [("1", "Bug"), ("2", "Enhancement"), ("3", "Issue")],
        "incident_status": [("1", "New"), ("2", "Open"), ("3", "Assigned"), ("4", "Resolved"), ("5", "Closed")],
        "incident_status_default": [("1", "New")], "incident_type_default": [("1", "Bug")],
        "test_case_priority": [("1", "1 - Critical"), ("2", "2 - High"), ("3", "3 - Medium"), ("4", "4 - Low")],
        "test_case_status": [("1", "Draft"), ("2", "Ready for Review"), ("3", "Approved")],
        "test_case_type": [("1", "Functional"), ("2", "Regression"), ("3", "Integration")],
        "user": [("1", "Demo Tester"), ("2", "Demo Developer"), ("3", "Demo Product Owner")],
        "component": [("1", "Checkout"), ("2", "Payments API"), ("3", "Refunds")],
    }
    for kind, values in meta.items():
        for ext, name in values:
            db.add(ProjectMetadata(project_id=p.id, kind=kind, external_id=ext, name=name, data={}))

    releases = [("1", "Release 3.4", "3.4", "AAA", False), ("2", "Sprint 3.4.1", "3.4.1", "AAAAAA", True),
                ("3", "Release 3.5", "3.5", "AAB", False)]
    for ext, name, ver, indent, it in releases:
        db.add(Release(project_id=p.id, external_id=ext, name=name, version_number=ver, indent_level=indent,
                       is_iteration=it, type_name="Iteration" if it else "Major Release", status_name="In Progress",
                       start_date=now - timedelta(days=30), end_date=now + timedelta(days=30), raw={}))

    reqs = [
        ("100", "Payments", None, "AAA", True, ""),
        ("101", "Pay with a saved card", "100", "AAAAAA", False,
         "As a returning customer I want to pay with a saved card so that checkout is faster.\n\n"
         "Acceptance criteria:\n- The customer must be able to select one of their saved cards at checkout.\n"
         "- The CVV must be re-entered for every payment.\n- Expired saved cards should not be selectable.\n"
         "- When the payment is approved the order confirmation page is shown within 5 seconds."),
        ("102", "Reject declined and expired cards", "100", "AAAAAB", False,
         "The system must reject payments with expired or declined cards and display a clear error.\n\n"
         "Acceptance criteria:\n- When the card is expired the payment must be rejected before it is sent to the processor.\n"
         "- When the processor declines the card the customer should see the decline reason.\n"
         "- The order must remain unpaid and the cart must be preserved.\n- Errors should be user friendly."),
        ("103", "Idempotent payment submission", "100", "AAAAAC", False,
         "Duplicate payment requests (double click, network retry) must not charge the customer twice.\n\n"
         "Acceptance criteria:\n- Requests with the same idempotency key within 24 hours must return the original result.\n"
         "- Only one charge may be created per idempotency key.\n- A request with a reused key but different amount must be rejected with HTTP 422."),
        ("200", "Refunds", None, "AAB", True, ""),
        ("201", "Partial refunds", "200", "AABAAA", False,
         "Support agents can refund part of a captured payment.\n\nAcceptance criteria:\n"
         "- The refund amount must be greater than 0 and not exceed the remaining captured amount.\n"
         "- Only users with the Refund role can issue refunds.\n- The customer should receive a refund email."),
    ]
    ids: dict[str, Requirement] = {}
    for ext, name, parent, indent, summary, desc in reqs:
        r = Requirement(project_id=p.id, external_id=ext, name=name, description_text=desc or None,
                        description_html=None, indent_level=indent, is_summary=summary,
                        status_name="Developed" if ext in ("101", "102") else "Accepted", type_name="Feature" if summary else "User Story",
                        importance_name="2 - High", owner_name="Demo Product Owner", release_external_id="1",
                        release_version="3.4", parent_id=ids[parent].id if parent else None, raw={}, steps=[], coverage={})
        db.add(r)
        db.flush()
        ids[ext] = r

    db.add(Folder(project_id=p.id, folder_type="test_case", external_id="10", name="Checkout", indent_level="AAA", raw={}))
    db.add(Folder(project_id=p.id, folder_type="test_case", external_id="11", name="Saved cards", parent_external_id="10", indent_level="AAAAAA", raw={}))
    db.add(Folder(project_id=p.id, folder_type="test_case", external_id="12", name="Refunds", indent_level="AAB", raw={}))
    db.add(Folder(project_id=p.id, folder_type="test_set", external_id="20", name="Regression", indent_level="AAA", raw={}))

    tcs = [
        ("500", "Pay with saved Visa card", "11", "101",
         [("Log in as a customer with a saved Visa card", "Customer dashboard is displayed"),
          ("Add an item to the cart and open checkout", "Checkout shows saved cards"),
          ("Select the saved Visa card and enter CVV 123", "Pay button becomes enabled"),
          ("Click Pay", "Order confirmation page is displayed")]),
        ("501", "Expired card is rejected", "10", "102",
         [("Open checkout with an item in the cart", "Payment form is displayed"),
          ("Enter card 4000 0000 0000 0069 with expiry 01/20", "Card details are accepted by the form"),
          ("Click Pay", "Error 'Your card has expired' is displayed and the order stays unpaid")]),
    ]
    for ext, name, folder, req_ext, steps in tcs:
        tc = TestCase(project_id=p.id, external_id=ext, name=name, folder_external_id=folder, status_name="Approved",
                      type_name="Functional", priority_name="2 - High", owner_name="Demo Tester", raw={})
        for i, (a, e) in enumerate(steps, 1):
            tc.steps.append(TestStep(external_id=f"{ext}{i}", position=i, description=a, expected_result=e))
        db.add(tc)
        db.add(RequirementTestCase(project_id=p.id, requirement_external_id=req_ext, test_case_external_id=ext))
    ts = TestSet(project_id=p.id, external_id="700", name="Checkout regression", folder_external_id="20",
                 status_name="In Progress", release_external_id="1", release_version="3.4", counts={"Passed": 1, "Failed": 1}, raw={})
    db.add(ts)
    db.flush()
    db.add(TestSetTestCase(test_set_id=ts.id, external_id="7001", test_case_external_id="500", position=1))
    db.add(TestSetTestCase(test_set_id=ts.id, external_id="7002", test_case_external_id="501", position=2))
    db.add(Incident(project_id=p.id, platform="spira", external_id="900", name="Spinner never stops when card is declined",
                    description_text="Submitting a payment with a declined card shows a loading spinner indefinitely (RQ:102).",
                    status_name="Open", is_open=True, type_name="Bug", priority_name="2 - High", severity_name="2 - High",
                    owner_name="Demo Developer", detected_release_external_id="1", detected_release_version="3.4", raw={}))
    db.add(Incident(project_id=p.id, platform="spira", external_id="901", name="Refund email not sent for partial refunds",
                    description_text="Customers do not receive an email after a partial refund.", status_name="Resolved",
                    is_open=False, type_name="Bug", priority_name="3 - Medium", severity_name="3 - Medium", raw={}))
    db.commit()
    db.refresh(p)
    return p
