"""Editorial and operating knowledge, resolved for clients that have no filesystem.

This repository carries a real body of craft guidance: how to tighten a recording
without cutting the breath out of it, what to look at before applying a grade, which
Resolve API calls silently lie. It lives in two places — `.agents/skills/*/SKILL.md`
and `docs/guides` + `docs/kernels` — and until now both were reachable only by an
agent that could open files in this checkout.

Over MCP the client has no checkout. A skill that says "open
`docs/guides/color-decision-guide.md`" is a dead end there: the pointer resolves to
nothing, and the agent operates the tools without ever seeing the reasoning that makes
the operation correct. So this module serves **content, not pointers** — it follows the
in-repo references one level and inlines what they point at.

## One level, deliberately

Following references transitively would turn a 150-line answer into the whole `docs/`
tree. One level is the depth at which a skill's own routing is satisfied: the skill
names the manual, and the manual arrives with it. Anything deeper is a different
question, and the agent can ask it as a separate topic.

## Nothing in the corpus is unreachable

The index is built from the directories themselves, not from a hand-kept list, and a
drift guard asserts every skill and every guide/kernel appears in it. A knowledge file
added later cannot go quietly unserved — which is the failure mode a hand-kept list has
every time.

## An oversized reference is summarised, not truncated

Inlining is capped. Under the cap a referenced document arrives whole; over it, what
arrives is its title, its summary and its section list, plus the topic id to fetch for
the full text. A truncated prefix would be worse than a pointer — it is the first N
lines, which is rarely the part that answers the question.

## Reference documents are terminal

`docs/SKILL.md`, the api ledgers and the release process are exhaustive by design and
cross-link each other freely. Inlining from them doubles a document that was already
complete, so the `reference` category resolves to itself. Skills, guides and kernels —
the documents whose job is to route — still inline.

## Sections are parsed from the primary document only

`get(topic, section=...)` slices the skill's or doc's own headings, never the inlined
material. Slicing across an inline boundary would return a section whose name belongs to
one document and whose body belongs to another. An unknown section is an error that
lists the real ones rather than quietly returning the whole file.
"""

from __future__ import annotations

import difflib
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
GUIDES_DIR = REPO_ROOT / "docs" / "guides"
KERNELS_DIR = REPO_ROOT / "docs" / "kernels"

# Skills about developing *this repository* rather than operating Resolve. Served, but
# categorised apart so an editor asking for craft guidance is not handed our release
# checklist.
_REPO_SKILLS = frozenset({"house-style", "release-check"})

# `docs/kernels/README.md` is a table of contents for its own directory: every entry it
# lists is already an indexed topic, so serving it adds a second, staler index. The
# drift guard skips it for the same reason.
_DOC_SKIPLIST = frozenset({"README.md"})

CATEGORIES = ("workflow", "guide", "kernel", "reference", "repo")

MAX_SUMMARY_CHARS = 320
EXCERPT_RADIUS = 160

# Dropped from search terms. Without this "cut to music" is decided by "to", and the
# longest document in the corpus wins every query that contains a preposition.
_STOPWORDS = frozenset(
    "a an the to of in on for and or is are it its my me we with from at by as be "
    "this that how what when do does can should".split()
)

# Referenced documents longer than this are summarised rather than inlined whole. Set
# so the everyday kernels and guides (100-250 lines) arrive complete, while the two
# outliers — the 2250-line operating reference and the generated api-limitations ledger
# — do not swallow the topic that merely pointed at them.
MAX_INLINE_LINES = 260

# Documents outside `docs/guides` and `docs/kernels` that the corpus points at. Indexed
# explicitly, with stable ids, so an over-budget reference can name a topic to fetch
# instead of dead-ending. (`docs/SKILL.md` as a topic id would read as "a skill".)
_EXTRA_DOCS: Dict[str, str] = {
    "mcp-operating-reference": "docs/SKILL.md",
    "release-process": "docs/process/release-process.md",
    "api-limitations": "docs/reference/api-limitations.md",
    "api-coverage": "docs/reference/api-coverage.md",
}

# Natural phrasings an agent is likely to reach for, mapped to real topic ids. Keys are
# matched after lowercasing and collapsing separators, so "dead air" and "dead_air" both
# land.
_ALIASES: Dict[str, str] = {
    "color": "resolve-color",
    "colour": "resolve-color",
    "grade": "resolve-color",
    "grading": "resolve-color",
    "look": "resolve-color",
    "looks": "resolve-color",
    "lut": "resolve-color",
    "luts": "resolve-color",
    "edit": "resolve-edit",
    "editing": "resolve-edit",
    "cut": "resolve-edit",
    "cutting": "resolve-edit",
    "trim": "resolve-edit",
    "pacing": "resolve-edit",
    "timeline": "resolve-edit",
    "rough cut": "resolve-rough-cut",
    "roughcut": "resolve-rough-cut",
    "assembly": "resolve-rough-cut",
    "selects": "resolve-rough-cut",
    "tighten": "resolve-tighten-recording",
    "tightening": "resolve-tighten-recording",
    "dead air": "resolve-tighten-recording",
    "silence": "resolve-tighten-recording",
    "silences": "resolve-tighten-recording",
    "pauses": "resolve-tighten-recording",
    "audio": "resolve-audio",
    "sound": "resolve-audio",
    "mix": "resolve-audio",
    "mixing": "resolve-audio",
    "fairlight": "resolve-audio",
    "loudness": "resolve-audio",
    "conform": "resolve-conform",
    "conforming": "resolve-conform",
    "online": "resolve-conform",
    "relink": "resolve-conform",
    "aaf": "resolve-conform",
    "delivery": "resolve-delivery",
    "deliver": "resolve-delivery",
    "render": "resolve-delivery",
    "export": "resolve-delivery",
    "fusion": "resolve-fusion",
    "vfx": "resolve-fusion",
    "titles": "resolve-fusion",
    "analysis": "resolve-media-analysis",
    "analyze": "resolve-media-analysis",
    "analyse": "resolve-media-analysis",
    "transcription": "resolve-media-analysis",
    "transcribe": "resolve-media-analysis",
    "media pool": "resolve-media-pool",
    "bins": "resolve-media-pool",
    "ingest": "resolve-media-pool",
    "multicam": "resolve-media-pool",
    "mcp": "resolve-mcp",
    "tools": "resolve-mcp",
    "session": "resolve-session",
    "style": "house-style",
    "release": "release-check",
    "api": "api-coverage",
    "limitations": "api-limitations",
    "api limitations": "api-limitations",
    "skill": "mcp-operating-reference",
    "operating reference": "mcp-operating-reference",
}


class KnowledgeError(Exception):
    """A topic or section that does not exist. Carries the real options."""


# ── corpus parsing ───────────────────────────────────────────────────────────


def _split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Return (frontmatter fields, body). Absent frontmatter yields an empty dict."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        return {}, text
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        key_value = re.match(r"^([a-zA-Z_][\w-]*):\s*(.*)$", line)
        if key_value:
            fields[key_value.group(1)] = key_value.group(2).strip()
    return fields, text[match.end():]


def _first_paragraph(body: str) -> str:
    """The first real paragraph after the H1 — a doc's own one-line summary."""
    lines = body.splitlines()
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("# "):
            start = index + 1
            break
    collected: List[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith(("#", "|", "```", "- ", "* ", ">")):
            if collected:
                break
            continue
        collected.append(stripped)
    summary = " ".join(collected)
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    return summary


def _title_of(body: str, fallback: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


_DOC_REF_RE = re.compile(r"`(docs/[^`\s]+\.md)`|\]\((docs/[^)\s]+\.md)\)")


def _doc_references(body: str) -> List[str]:
    """In-repo doc paths a body points at, in first-appearance order."""
    seen: List[str] = []
    for backticked, linked in _DOC_REF_RE.findall(body):
        path = backticked or linked
        if path not in seen:
            seen.append(path)
    return seen


def _demote_headings(body: str) -> str:
    """Shift every ATX heading one level down so inlined material nests correctly."""
    return re.sub(r"^(#{1,5})(\s)", r"#\1\2", body, flags=re.M)


# ── index ────────────────────────────────────────────────────────────────────


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _build_index() -> Dict[str, Dict[str, Any]]:
    """Topic id → record. Built from the directories, never from a hand-kept list."""
    index: Dict[str, Dict[str, Any]] = {}

    if SKILLS_DIR.is_dir():
        for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
            topic = skill_md.parent.name
            text = _read(skill_md)
            fields, body = _split_frontmatter(text)
            index[topic] = {
                "topic": topic,
                "title": _title_of(body, topic),
                "summary": fields.get("description", "") or _first_paragraph(body),
                "category": "repo" if topic in _REPO_SKILLS else "workflow",
                "path": str(skill_md.relative_to(REPO_ROOT)),
                "body": body.strip(),
            }

    for category, directory in (("guide", GUIDES_DIR), ("kernel", KERNELS_DIR)):
        if not directory.is_dir():
            continue
        for doc in sorted(directory.glob("*.md")):
            if doc.name in _DOC_SKIPLIST:
                continue
            topic = doc.stem
            body = _split_frontmatter(_read(doc))[1]
            index[topic] = {
                "topic": topic,
                "title": _title_of(body, topic),
                "summary": _first_paragraph(body),
                "category": category,
                "path": str(doc.relative_to(REPO_ROOT)),
                "body": body.strip(),
            }

    for topic, reference in _EXTRA_DOCS.items():
        path = REPO_ROOT / reference
        if not path.is_file():
            continue
        body = _split_frontmatter(_read(path))[1]
        index[topic] = {
            "topic": topic,
            "title": _title_of(body, topic),
            "summary": _first_paragraph(body),
            "category": "reference",
            "path": reference,
            "body": body.strip(),
        }

    for record in index.values():
        record["related"] = _related_topics(record, index)
    return index


def _related_topics(record: Dict[str, Any], index: Dict[str, Dict[str, Any]]) -> List[str]:
    """Topics this one points at: linked docs first, then topics named in the body."""
    by_path = {other["path"]: other["topic"] for other in index.values()}
    related: List[str] = []
    for reference in _doc_references(record["body"]):
        topic = by_path.get(reference)
        if topic and topic != record["topic"] and topic not in related:
            related.append(topic)
    for topic in sorted(index):
        if topic == record["topic"] or topic in related:
            continue
        if re.search(rf"\b{re.escape(topic)}\b", record["body"]):
            related.append(topic)
    return related


_INDEX_CACHE: Optional[Dict[str, Dict[str, Any]]] = None


def index(*, refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None or refresh:
        _INDEX_CACHE = _build_index()
    return _INDEX_CACHE


def _normalize(value: str) -> str:
    return re.sub(r"[\s_]+", " ", str(value or "").strip().lower())


def resolve_alias(topic: str) -> Optional[str]:
    """Map a natural phrasing to a topic id, or return the id when it is already one."""
    records = index()
    raw = str(topic or "").strip()
    if raw in records:
        return raw
    normalized = _normalize(raw)
    for candidate in records:
        if _normalize(candidate) == normalized:
            return candidate
    hyphenated = normalized.replace(" ", "-")
    if hyphenated in records:
        return hyphenated
    return _ALIASES.get(normalized)


# ── public surface ───────────────────────────────────────────────────────────


def topics(*, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """The index an agent reads before deciding what to fetch."""
    if category is not None and category not in CATEGORIES:
        raise KnowledgeError(
            f"unknown category '{category}'. Valid categories: {', '.join(CATEGORIES)}"
        )
    listing = []
    for record in index().values():
        if category and record["category"] != category:
            continue
        listing.append(
            {
                "topic": record["topic"],
                "title": record["title"],
                "summary": record["summary"],
                "category": record["category"],
                "source": record["path"],
                "length_lines": len(record["body"].splitlines()),
                "resolved_length_lines": len(_resolve_body(record).splitlines()),
                "sections": [name for name, _, _ in _sections(record["body"])],
                "related": record["related"],
            }
        )
    return sorted(listing, key=lambda item: (item["category"], item["topic"]))


def _sections(body: str) -> List[Tuple[str, int, int]]:
    """(heading text, start line, end line) for every `##` section, in order."""
    lines = body.splitlines()
    starts = [
        (index_, line[3:].strip())
        for index_, line in enumerate(lines)
        if line.startswith("## ")
    ]
    out: List[Tuple[str, int, int]] = []
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        out.append((name, start, end))
    return out


def _resolve_body(record: Dict[str, Any]) -> str:
    """The topic's body with its in-repo references inlined one level deep."""
    body = record["body"]
    if record["category"] == "reference":
        return body
    references = _doc_references(body)
    if not references:
        return body
    by_path = {other["path"]: other["topic"] for other in index().values()}
    parts = [body]
    for reference in references:
        path = REPO_ROOT / reference
        if not path.is_file():
            # A reference to a file that no longer exists is a real defect in the
            # corpus, but it must not take the whole answer down with it.
            parts.append(
                f"\n\n---\n\n## Referenced: `{reference}` (missing from the checkout)\n"
            )
            continue
        referenced = _split_frontmatter(_read(path))[1].strip()
        title = _title_of(referenced, reference)
        header = f"\n\n---\n\n## Referenced: {title}\n\n_Source: `{reference}`_\n\n"
        line_count = len(referenced.splitlines())
        if line_count <= MAX_INLINE_LINES:
            parts.append(header + _demote_headings(referenced))
            continue
        target = by_path.get(reference)
        fetch = (
            f"get(topic=\"{target}\") for the full text, or "
            f"get(topic=\"{target}\", section=...) for one section"
            if target
            else "read it in the repository checkout"
        )
        sections = [name for name, _, _ in _sections(referenced)]
        parts.append(
            header
            + f"_{line_count} lines — summarised here rather than inlined. Call {fetch}._\n\n"
            + f"{_first_paragraph(referenced)}\n\n"
            + "Sections: "
            + (", ".join(sections) if sections else "(none)")
            + "\n"
        )
    return "".join(parts)


def get(topic: str, *, section: Optional[str] = None, inline: bool = True) -> Dict[str, Any]:
    """Resolve one topic to prose.

    `section` slices the primary document's own `##` headings and implies no inlining;
    an unknown section raises rather than quietly returning everything.
    """
    resolved = resolve_alias(topic)
    if resolved is None:
        # Nearest matches, not all 35 ids: a wrong guess is usually a near miss, and a
        # wall of every topic is harder to act on than three plausible ones.
        near = difflib.get_close_matches(_normalize(topic), sorted(index()), n=3, cutoff=0.4)
        hint = f"Did you mean: {', '.join(near)}? " if near else ""
        raise KnowledgeError(
            f"unknown topic '{topic}'. {hint}Call topics() for the full index."
        )
    record = index()[resolved]

    if section is not None:
        available = _sections(record["body"])
        wanted = _normalize(section)
        for name, start, end in available:
            if _normalize(name) == wanted:
                lines = record["body"].splitlines()[start:end]
                return {
                    "topic": resolved,
                    "title": record["title"],
                    "section": name,
                    "category": record["category"],
                    "source": record["path"],
                    "content": "\n".join(lines).strip(),
                    "inlined": [],
                    "related": record["related"],
                }
        raise KnowledgeError(
            f"unknown section '{section}' in topic '{resolved}'. "
            f"Sections: {', '.join(name for name, _, _ in available) or '(none)'}"
        )

    inlining = inline and record["category"] != "reference"
    content = _resolve_body(record) if inlining else record["body"]
    return {
        "topic": resolved,
        "title": record["title"],
        "category": record["category"],
        "source": record["path"],
        "content": content,
        "inlined": _doc_references(record["body"]) if inlining else [],
        "sections": [name for name, _, _ in _sections(record["body"])],
        "related": record["related"],
    }


def _term_count(haystack: str, term: str) -> int:
    """Whole-word occurrences.

    Substring counting looks equivalent and is not: searching "dead air" scored
    `resolve-audio` top because "air" is inside "F-air-light". Every term here is a word
    the user typed, so a word boundary is the honest match.
    """
    return len(re.findall(rf"(?<!\w){re.escape(term)}(?!\w)", haystack))


def search(query: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    """Rank topics against a query. Deterministic term scoring — no embeddings."""
    text_query = str(query or "").strip()
    if not text_query:
        raise KnowledgeError("search requires a non-empty query")
    words = [term for term in re.split(r"\W+", text_query.lower()) if term]
    # A query made only of stopwords still deserves an answer, so fall back to the
    # unfiltered words rather than returning nothing.
    terms = [term for term in words if term not in _STOPWORDS] or words
    phrase = text_query.lower()

    hits: List[Dict[str, Any]] = []
    for record in index().values():
        body = _resolve_body(record)
        haystack = body.lower()
        heading = f"{record['topic']} {record['title']} {record['summary']}".lower()
        # Body hits are normalised by document size. Raw counts make length the ranking
        # signal: the 2250-line operating reference mentions everything at least once.
        weight = math.sqrt(max(1, len(body.splitlines())))
        body_score = sum(_term_count(haystack, term) for term in terms)
        if phrase and phrase in haystack:
            body_score += 5
        score = 10 * body_score / weight
        score += 3 * sum(_term_count(heading, term) for term in terms)
        if phrase and phrase in heading:
            score += 15
        score = round(score, 3)
        if score <= 0:
            continue
        hits.append(
            {
                "topic": record["topic"],
                "title": record["title"],
                "category": record["category"],
                "score": score,
                "excerpt": _excerpt(body, terms, phrase),
            }
        )
    hits.sort(key=lambda hit: (-hit["score"], hit["topic"]))
    return hits[: max(1, int(limit))]


def _excerpt(body: str, terms: List[str], phrase: str) -> str:
    lowered = body.lower()
    position = lowered.find(phrase) if phrase else -1
    if position < 0:
        for term in terms:
            position = lowered.find(term)
            if position >= 0:
                break
    if position < 0:
        position = 0
    start = max(0, position - EXCERPT_RADIUS)
    end = min(len(body), position + EXCERPT_RADIUS)
    snippet = " ".join(body[start:end].split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{snippet}{suffix}"


def capabilities() -> Dict[str, Any]:
    """What this server knows, summarised for a capability probe."""
    records = index()
    by_category: Dict[str, int] = {}
    for record in records.values():
        by_category[record["category"]] = by_category.get(record["category"], 0) + 1
    return {
        "topic_count": len(records),
        "categories": by_category,
        "aliases": len(_ALIASES),
        "corpus": [
            str(SKILLS_DIR.relative_to(REPO_ROOT)),
            str(GUIDES_DIR.relative_to(REPO_ROOT)),
            str(KERNELS_DIR.relative_to(REPO_ROOT)),
        ],
        "note": (
            "Craft and workflow guidance resolved to prose, so a client with no "
            "checkout can read it. Fetch the index with topics(), then get(topic) "
            "before a creative or destructive operation — not after."
        ),
    }
