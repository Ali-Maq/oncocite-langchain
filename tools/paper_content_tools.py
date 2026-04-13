"""
Paper Content Tools
===================

Tools for the Reader-first architecture.
Migrated from Claude Agent SDK to LangChain format.

These tools allow the Reader agent to save extracted paper content,
and other agents to retrieve it.
"""

from typing import Any, Dict, List, Optional
import json
from langchain_core.tools import tool

from .context import get_context


def _normalize_authors_list(authors: Any) -> List[str]:
    """Coerce authors into a clean list of strings."""
    if not authors:
        return []
    if isinstance(authors, list):
        return [str(a).strip() for a in authors if str(a).strip()]
    # If a single string, split on commas/semicolons
    if isinstance(authors, str):
        parts = [p.strip() for p in authors.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(authors).strip()]


def _normalize_sections_data(sections: Any) -> List[Dict[str, Any]]:
    """
    Ensure sections are a list of dicts with name/content/page_numbers.
    Handles legacy cases where the Reader returned a single string blob.
    """
    if not sections:
        return []

    normalized = []

    # Already in expected format
    if isinstance(sections, list):
        for idx, sec in enumerate(sections):
            if isinstance(sec, dict):
                normalized.append(
                    {
                        "name": sec.get("name") or f"Section {idx+1}",
                        "page_numbers": sec.get("page_numbers", []),
                        "content": sec.get("content", ""),
                    }
                )
            else:
                # Plain string inside a list
                normalized.append(
                    {
                        "name": f"Section {idx+1}",
                        "page_numbers": [],
                        "content": str(sec),
                    }
                )
        return normalized

    # Single string blob from legacy Reader output
    if isinstance(sections, str):
        return [
            {
                "name": "Full Text",
                "page_numbers": [],
                "content": sections,
            }
        ]

    # Fallback: wrap unknown type
    return [
        {
            "name": "Section",
            "page_numbers": [],
            "content": str(sections),
        }
    ]


def _generate_paper_context_text(content: dict) -> str:
    """
    Generate formatted text context from paper content.

    This text is passed to Planner/Extractor/Critic agents
    so they can work from the extracted content without reading images.

    CRITICAL: This generates the FULL text context (~10-50KB).
    Do NOT truncate or summarize this output.
    """
    if not isinstance(content, dict):
        return f"Error: Paper content is not a dictionary. Got {type(content)}: {content}"

    lines = [
        "=" * 80,
        "PAPER CONTENT (Extracted by Reader Agent)",
        "=" * 80,
        "",
        f"TITLE: {content.get('title', 'Unknown')}",
        f"AUTHORS: {', '.join(_normalize_authors_list(content.get('authors')))}",
        f"JOURNAL: {content.get('journal', 'Unknown')} ({content.get('year', '?')})",
        f"PAPER TYPE: {content.get('paper_type', 'Unknown')}",
    ]

    # Key entities section
    if any([content.get('genes'), content.get('variants'), content.get('diseases'), content.get('therapies')]):
        lines.extend([
            "",
            "-" * 40,
            "KEY ENTITIES IDENTIFIED",
            "-" * 40,
        ])
        if content.get('genes'):
            genes = content['genes'] if isinstance(content['genes'], list) else [str(content['genes'])]
            lines.append(f"GENES: {', '.join(str(g) for g in genes)}")
        if content.get('variants'):
            variants = content['variants'] if isinstance(content['variants'], list) else [str(content['variants'])]
            lines.append(f"VARIANTS: {', '.join(str(v) for v in variants)}")
        if content.get('diseases'):
            diseases = content['diseases'] if isinstance(content['diseases'], list) else [str(content['diseases'])]
            lines.append(f"DISEASES: {', '.join(str(d) for d in diseases)}")
        if content.get('therapies'):
            therapies = content['therapies'] if isinstance(content['therapies'], list) else [str(content['therapies'])]
            lines.append(f"THERAPIES: {', '.join(str(t) for t in therapies)}")

    # Clinical trials
    if content.get('clinical_trials'):
        lines.extend([
            "",
            "-" * 40,
            "CLINICAL TRIALS",
            "-" * 40,
        ])
        trials = content['clinical_trials'] if isinstance(content['clinical_trials'], list) else []
        for trial in trials:
            if isinstance(trial, dict):
                trial_str = f"  - {trial.get('name', 'Unknown')}"
                if trial.get('nct_id'):
                    trial_str += f" ({trial['nct_id']})"
                if trial.get('phase'):
                    trial_str += f" Phase {trial['phase']}"
                lines.append(trial_str)
            else:
                lines.append(f"  - {str(trial)}")

    # Abstract
    lines.extend([
        "",
        "-" * 40,
        "ABSTRACT",
        "-" * 40,
        content.get('abstract', ''),
    ])

    # Tables (CRITICAL - contain most important data)
    if content.get('tables'):
        lines.extend([
            "",
            "=" * 40,
            "TABLES (Key Data Source)",
            "=" * 40,
        ])
        tables = content['tables'] if isinstance(content['tables'], list) else []
        for table in tables:
            if not isinstance(table, dict):
                lines.append(f"\n[Malformed Table Data]: {str(table)}")
                continue

            lines.append(f"\n### {table.get('table_id', 'Table')} (Page {table.get('page_number', '?')})")
            lines.append(f"Caption: {table.get('caption', '')}")

            # Format as markdown table
            if table.get('headers'):
                headers = table['headers'] if isinstance(table['headers'], list) else []
                lines.append("")
                lines.append("| " + " | ".join(str(h) for h in headers) + " |")
                lines.append("|" + "|".join(["---"] * len(headers)) + "|")

            rows = table.get('rows', [])
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, list):
                        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
                    else:
                        lines.append(f"| {str(row)} |")

            if table.get('footnotes'):
                lines.append(f"\nFootnotes: {table['footnotes']}")

    # Figures
    if content.get('figures'):
        lines.extend([
            "",
            "=" * 40,
            "FIGURES",
            "=" * 40,
        ])
        figures = content['figures'] if isinstance(content['figures'], list) else []
        for fig in figures:
            if not isinstance(fig, dict):
                lines.append(f"\n[Malformed Figure Data]: {str(fig)}")
                continue

            lines.append(f"\n### {fig.get('figure_id', 'Figure')} (Page {fig.get('page_number', '?')})")
            lines.append(f"Type: {fig.get('figure_type', 'Unknown')}")
            lines.append(f"Caption: {fig.get('caption', '')}")
            lines.append(f"Description: {fig.get('description', '')}")
            if fig.get('statistics'):
                stats = fig['statistics'] if isinstance(fig['statistics'], list) else [str(fig['statistics'])]
                lines.append(f"Statistics visible: {', '.join(str(s) for s in stats)}")

    # Key Statistics (extracted for quick reference)
    if content.get('statistics'):
        lines.extend([
            "",
            "=" * 40,
            "KEY STATISTICS EXTRACTED",
            "=" * 40,
            "(Use these for evidence extraction)",
        ])
        statistics = content['statistics'] if isinstance(content['statistics'], list) else []
        for stat in statistics:
            if not isinstance(stat, dict):
                lines.append(f"* {str(stat)}")
                continue

            stat_parts = [f"* {stat.get('value', '')}"]
            if stat.get('confidence_interval'):
                stat_parts.append(f"({stat['confidence_interval']})")
            if stat.get('p_value'):
                stat_parts.append(stat['p_value'])
            if stat.get('sample_size'):
                stat_parts.append(stat['sample_size'])

            stat_str = " ".join(stat_parts)
            stat_str += f" - {stat.get('context', '')}"
            stat_str += f" [Page {stat.get('page_number', '?')}, {stat.get('source_location', '')}]"
            lines.append(stat_str)

    # Sections (full text)
    normalized_sections = _normalize_sections_data(content.get('sections'))
    if normalized_sections:
        lines.extend([
            "",
            "=" * 40,
            "FULL SECTION CONTENT",
            "=" * 40,
        ])
        for section in normalized_sections:
            page_nums = section.get('page_numbers', [])
            page_str = ", ".join(str(p) for p in page_nums) if isinstance(page_nums, list) else str(page_nums)
            lines.extend([
                "",
                f"### {section.get('name', 'Section')} (Pages: {page_str})",
                "-" * 30,
                section.get('content', ''),
            ])

    return "\n".join(lines)


@tool
def save_paper_content(
    title: str,
    authors: List[str],
    journal: str,
    year: int,
    paper_type: str,
    abstract: str,
    sections: Optional[List[Dict[str, Any]]] = None,
    tables: Optional[List[Dict[str, Any]]] = None,
    figures: Optional[List[Dict[str, Any]]] = None,
    statistics: Optional[List[Dict[str, Any]]] = None,
    genes: Optional[List[str]] = None,
    variants: Optional[List[str]] = None,
    diseases: Optional[List[str]] = None,
    therapies: Optional[List[str]] = None,
    clinical_trials: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Save complete extracted paper content. Called by Reader agent after reading all pages.

    This becomes the SINGLE SOURCE OF TRUTH for all downstream agents.

    Args:
        title: Exact paper title
        authors: List of author names
        journal: Journal name
        year: Publication year
        paper_type: Paper classification (PRIMARY, REVIEW, META_ANALYSIS, CASE_REPORT)
        abstract: Full abstract text
        sections: Paper sections with content
        tables: All tables extracted from paper
        figures: All figures extracted from paper
        statistics: All statistics extracted from paper
        genes: All genes mentioned in paper
        variants: All variants mentioned in paper
        diseases: All diseases mentioned in paper
        therapies: All therapies mentioned in paper
        clinical_trials: Clinical trial information

    Returns:
        JSON string with save status and summary
    """
    ctx = get_context()

    # Normalize inputs
    normalized_authors = _normalize_authors_list(authors)
    normalized_sections = _normalize_sections_data(sections or [])

    # Store in context
    ctx.paper_content = {
        "title": title,
        "authors": normalized_authors,
        "journal": journal,
        "year": year,
        "paper_type": paper_type,
        "abstract": abstract,
        "sections": normalized_sections,
        "tables": tables or [],
        "figures": figures or [],
        "statistics": statistics or [],
        "genes": genes or [],
        "variants": variants or [],
        "diseases": diseases or [],
        "therapies": therapies or [],
        "clinical_trials": clinical_trials or [],
    }

    # Sync basic metadata
    if normalized_authors:
        ctx.author = ", ".join(normalized_authors)
    if year:
        ctx.year = str(year)
    if paper_type:
        ctx.paper_type = paper_type

    # Generate text context for other agents
    ctx.paper_content_text = _generate_paper_context_text(ctx.paper_content)

    result = {
        "status": "saved",
        "title": title,
        "paper_type": paper_type,
        "tables_count": len(tables or []),
        "figures_count": len(figures or []),
        "statistics_count": len(statistics or []),
        "genes": genes or [],
        "variants": variants or [],
        "diseases": diseases or [],
        "therapies": therapies or [],
        "context_text_length": len(ctx.paper_content_text),
    }

    return json.dumps(result, indent=2)


@tool
def get_paper_content() -> str:
    """
    Get the extracted paper content.

    Used by Planner, Extractor, and Critic agents to access
    the paper content extracted by the Reader.

    CRITICAL: Returns the FULL text context (~10-50KB).
    This is intentionally large to preserve all paper information.

    Returns:
        Full formatted text of paper content, or error if not yet extracted
    """
    ctx = get_context()

    if not ctx.paper_content:
        return json.dumps({
            "error": "Paper content not yet extracted. Reader agent must run first.",
            "hint": "Delegate to 'reader' agent first to extract paper content."
        })

    # Return the FULL text representation
    # This is intentionally large - do NOT truncate
    return ctx.paper_content_text


@tool
def get_paper_content_json() -> str:
    """
    Get the structured paper content as JSON (the exact object saved by Reader).

    Use this when you need programmatic access to sections, tables, figures, and
    the statistics list, rather than parsing the large text dump.

    Returns:
        JSON string of the structured paper_content dict
    """
    ctx = get_context()
    if not ctx.paper_content:
        return json.dumps({
            "error": "Paper content not yet extracted. Reader agent must run first.",
            "hint": "Delegate to 'reader' agent first to extract paper content."
        })
    return json.dumps(ctx.paper_content, indent=2)
