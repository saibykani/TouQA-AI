"""Minimal Atlassian Document Format (ADF) builder for Jira Cloud v3 descriptions."""
from __future__ import annotations

from typing import Any


def text(value: str, *, bold: bool = False, code: bool = False) -> dict:
    node: dict[str, Any] = {"type": "text", "text": value}
    marks = []
    if bold:
        marks.append({"type": "strong"})
    if code:
        marks.append({"type": "code"})
    if marks:
        node["marks"] = marks
    return node


def paragraph(value: str) -> dict:
    lines = value.split("\n")
    content: list[dict] = []
    for i, line in enumerate(lines):
        if line:
            content.append(text(line))
        if i < len(lines) - 1:
            content.append({"type": "hardBreak"})
    return {"type": "paragraph", "content": content}


def heading(value: str, level: int = 3) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [text(value)]}


def ordered_list(items: list[str]) -> dict:
    return {"type": "orderedList", "content": [
        {"type": "listItem", "content": [paragraph(i)]} for i in items if i.strip()
    ]}


def bullet_list(items: list[str]) -> dict:
    return {"type": "bulletList", "content": [
        {"type": "listItem", "content": [paragraph(i)]} for i in items if i.strip()
    ]}


def code_block(value: str, language: str | None = None) -> dict:
    node: dict[str, Any] = {"type": "codeBlock", "content": [text(value)] if value else []}
    if language:
        node["attrs"] = {"language": language}
    return node


def doc(blocks: list[dict]) -> dict:
    return {"type": "doc", "version": 1, "content": [b for b in blocks if b.get("content") or b["type"] == "codeBlock"]}


def sections_to_adf(sections: list[tuple[str, Any]]) -> dict:
    """sections: list of (heading, value) where value is str, list[str] (ordered) or ('code', str)."""
    blocks: list[dict] = []
    for title, value in sections:
        if value in (None, "", []):
            continue
        blocks.append(heading(title))
        if isinstance(value, list):
            blocks.append(ordered_list([str(v) for v in value]))
        elif isinstance(value, tuple) and value and value[0] == "code":
            blocks.append(code_block(str(value[1])))
        elif isinstance(value, tuple) and value and value[0] == "bullets":
            blocks.append(bullet_list([str(v) for v in value[1]]))
        else:
            for para in str(value).split("\n\n"):
                if para.strip():
                    blocks.append(paragraph(para))
    return doc(blocks)


def sections_to_wiki(sections: list[tuple[str, Any]]) -> str:
    """Plain wiki-markup equivalent for Jira Data Center (REST v2 takes a string description)."""
    out: list[str] = []
    for title, value in sections:
        if value in (None, "", []):
            continue
        out.append(f"h3. {title}")
        if isinstance(value, list):
            out.extend(f"# {v}" for v in value)
        elif isinstance(value, tuple) and value and value[0] == "code":
            out.append("{noformat}\n" + str(value[1]) + "\n{noformat}")
        elif isinstance(value, tuple) and value and value[0] == "bullets":
            out.extend(f"* {v}" for v in value[1])
        else:
            out.append(str(value))
        out.append("")
    return "\n".join(out).strip()


def adf_to_text(node: Any) -> str:
    """Flatten ADF (as returned by Jira Cloud) to plain text for local search and AI context."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    if t == "hardBreak":
        return "\n"
    inner = adf_to_text(node.get("content", []))
    if t in {"paragraph", "heading", "codeBlock", "blockquote"}:
        return inner + "\n\n"
    if t == "listItem":
        return "- " + inner.strip() + "\n"
    return inner
