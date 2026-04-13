"""
OncoCITE MCP server.

Implements the 22-tool Model Context Protocol server described in
Supplementary Note S5 and Supplementary Table S15 of the manuscript. The
server registers every tool listed in Table S15 and exposes them over MCP
stdio transport, so any MCP-compatible client (Claude Desktop, the MCP
inspector, or another LLM agent) can drive the full CIViC extraction
pipeline end-to-end against the same codebase the paper uses.

The underlying implementations are the LangChain `@tool` functions in
`oncocite_langchain.tools.*`; this module is a thin adapter that wraps
each LangChain tool into an MCP tool with a matching signature and
docstring. Tool names match Table S15 exactly.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from tools.extraction_tools import (
    get_draft_extractions as _get_draft_extractions,
    get_extraction_plan as _get_extraction_plan,
    increment_iteration as _increment_iteration,
    save_critique as _save_critique,
    save_evidence_items as _save_evidence_items,
    save_extraction_plan as _save_extraction_plan,
)
from tools.normalization_tools import (
    finalize_extraction as _finalize_extraction,
    lookup_clinical_trial as _lookup_clinical_trial,
    lookup_disease_doid as _lookup_disease_doid,
    lookup_efo as _lookup_efo,
    lookup_gene_entrez as _lookup_gene_entrez,
    lookup_rxnorm as _lookup_rxnorm,
    lookup_therapy_ncit as _lookup_therapy_ncit,
    lookup_variant_info as _lookup_variant_info,
)
from tools.paper_content_tools import (
    get_paper_content as _get_paper_content,
    save_paper_content as _save_paper_content,
)
from tools.validation_tools import (
    check_actionability as _check_actionability,
    validate_evidence_item as _validate_evidence_item,
)

logger = logging.getLogger(__name__)


_WORKFLOW_STATE: Dict[str, Any] = {
    "current_phase": "idle",
    "iteration": 0,
    "last_update": None,
    "paper_id": None,
    "checkpoints": {},
    "agent_log": [],
}


def _invoke(langchain_tool, **kwargs: Any) -> Any:
    """Invoke a LangChain @tool and return its raw output."""
    return langchain_tool.invoke(kwargs)


def build_server() -> FastMCP:
    server = FastMCP(
        "oncocite-langchain",
        instructions=(
            "OncoCITE CIViC evidence extraction over MCP. Exposes the 22 "
            "tools from Supplementary Table S15 of the manuscript."
        ),
    )

    # ----- Paper content (Reader) -----

    @server.tool(name="save_paper_content", description="Persist Reader-extracted paper content.")
    def save_paper_content(
        title: str,
        authors: List[str],
        journal: str,
        year: int,
        abstract: str,
        sections: List[Dict[str, Any]],
        genes: Optional[List[str]] = None,
        variants: Optional[List[str]] = None,
        diseases: Optional[List[str]] = None,
        therapies: Optional[List[str]] = None,
    ) -> str:
        return _invoke(
            _save_paper_content,
            title=title,
            authors=authors,
            journal=journal,
            year=year,
            abstract=abstract,
            sections=sections,
            genes=genes or [],
            variants=variants or [],
            diseases=diseases or [],
            therapies=therapies or [],
        )

    @server.tool(name="get_paper_content", description="Retrieve the full structured paper content.")
    def get_paper_content() -> str:
        return _invoke(_get_paper_content)

    # ----- Planner -----

    @server.tool(name="save_extraction_plan", description="Save the Planner's extraction strategy.")
    def save_extraction_plan(
        disease_focus: str,
        target_evidence_types: List[str],
        priority_sections: List[str],
        extraction_strategy: str,
    ) -> str:
        return _invoke(
            _save_extraction_plan,
            disease_focus=disease_focus,
            target_evidence_types=target_evidence_types,
            priority_sections=priority_sections,
            extraction_strategy=extraction_strategy,
        )

    @server.tool(name="get_extraction_plan", description="Retrieve the stored extraction strategy.")
    def get_extraction_plan() -> str:
        return _invoke(_get_extraction_plan)

    # ----- Extractor / Critic -----

    @server.tool(name="check_actionability", description="Check whether a claim is clinically actionable.")
    def check_actionability(claim: str) -> str:
        return _invoke(_check_actionability, claim=claim)

    @server.tool(
        name="validate_evidence_item",
        description="Validate a draft evidence item against the CIViC schema.",
    )
    def validate_evidence_item(item: Dict[str, Any]) -> str:
        return _invoke(_validate_evidence_item, item=item)

    @server.tool(name="save_evidence_items", description="Persist validated evidence items.")
    def save_evidence_items(items: List[Dict[str, Any]]) -> str:
        return _invoke(_save_evidence_items, items=items)

    @server.tool(
        name="get_evidence_items",
        description="Retrieve the current draft evidence items (alias: get_draft_extractions).",
    )
    def get_evidence_items() -> str:
        return _invoke(_get_draft_extractions)

    @server.tool(name="save_critique", description="Persist the Critic's validation results.")
    def save_critique(
        status: str,
        feedback: str,
        specific_issues: Optional[List[str]] = None,
    ) -> str:
        return _invoke(
            _save_critique,
            status=status,
            feedback=feedback,
            specific_issues=specific_issues or [],
        )

    @server.tool(
        name="increment_iteration",
        description="Increment the Extractor-Critic refinement counter.",
    )
    def increment_iteration() -> str:
        _WORKFLOW_STATE["iteration"] += 1
        return _invoke(_increment_iteration)

    # ----- Normalizer (ontology lookups) -----

    @server.tool(name="lookup_gene_entrez", description="Resolve a gene symbol to its NCBI Entrez Gene ID.")
    def lookup_gene_entrez(symbol: str) -> str:
        return _invoke(_lookup_gene_entrez, symbol=symbol)

    @server.tool(name="lookup_rxnorm", description="Resolve a drug name to its RxNorm concept identifier.")
    def lookup_rxnorm(name: str) -> str:
        return _invoke(_lookup_rxnorm, name=name)

    @server.tool(
        name="lookup_therapy_ncit",
        description="Resolve a therapy name to its NCI Thesaurus (NCIt) code via OLS.",
    )
    def lookup_therapy_ncit(name: str) -> str:
        return _invoke(_lookup_therapy_ncit, name=name)

    @server.tool(
        name="lookup_efo",
        description="Resolve a disease name to an Experimental Factor Ontology (EFO) ID via OLS.",
    )
    def lookup_efo(name: str) -> str:
        return _invoke(_lookup_efo, name=name)

    @server.tool(
        name="lookup_disease_doid",
        description="Resolve a disease name to a Disease Ontology (DOID) identifier via OLS.",
    )
    def lookup_disease_doid(name: str) -> str:
        return _invoke(_lookup_disease_doid, name=name)

    @server.tool(
        name="lookup_clinical_trial",
        description="Verify a ClinicalTrials.gov NCT identifier.",
    )
    def lookup_clinical_trial(nct_id: str) -> str:
        return _invoke(_lookup_clinical_trial, nct_id=nct_id)

    @server.tool(
        name="lookup_variant_info",
        description=(
            "Look up genomic coordinates, ClinVar accession, and HGVS for a variant via MyVariant.info."
        ),
    )
    def lookup_variant_info(query: str) -> str:
        return _invoke(_lookup_variant_info, query=query)

    # ----- Orchestrator / workflow management -----

    @server.tool(
        name="save_final_output",
        description="Finalize the extraction run and save the enriched evidence items.",
    )
    def save_final_output() -> str:
        _WORKFLOW_STATE["current_phase"] = "done"
        return _invoke(_finalize_extraction)

    @server.tool(
        name="get_workflow_status",
        description="Retrieve the current phase, iteration, and paper_id of the extraction run.",
    )
    def get_workflow_status() -> str:
        return json.dumps(
            {
                "current_phase": _WORKFLOW_STATE["current_phase"],
                "iteration": _WORKFLOW_STATE["iteration"],
                "last_update": _WORKFLOW_STATE["last_update"],
                "paper_id": _WORKFLOW_STATE["paper_id"],
                "checkpoints": sorted(_WORKFLOW_STATE["checkpoints"].keys()),
            }
        )

    @server.tool(
        name="log_agent_action",
        description="Append an entry to the audit trail of agent actions.",
    )
    def log_agent_action(agent: str, action: str, detail: Optional[str] = None) -> str:
        entry = {"agent": agent, "action": action, "detail": detail}
        _WORKFLOW_STATE["agent_log"].append(entry)
        return json.dumps({"logged": True, "entries": len(_WORKFLOW_STATE["agent_log"])})

    @server.tool(
        name="save_checkpoint",
        description="Save an intermediate LangGraph checkpoint under the given label.",
    )
    def save_checkpoint(label: str, state: Dict[str, Any]) -> str:
        _WORKFLOW_STATE["checkpoints"][label] = state
        return json.dumps({"saved": True, "label": label})

    @server.tool(
        name="restore_checkpoint",
        description="Restore a previously saved checkpoint by label.",
    )
    def restore_checkpoint(label: str) -> str:
        if label not in _WORKFLOW_STATE["checkpoints"]:
            return json.dumps({"restored": False, "reason": f"no checkpoint named {label!r}"})
        return json.dumps(
            {"restored": True, "label": label, "state": _WORKFLOW_STATE["checkpoints"][label]}
        )

    return server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    build_server().run()


if __name__ == "__main__":
    main()
