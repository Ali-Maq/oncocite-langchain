"""
Normalization Tools
===================

Tools for normalizing evidence items by looking up database IDs.
Migrated from Claude Agent SDK to LangChain format.

Uses public APIs:
- MyGene.info for gene Entrez IDs
- MyVariant.info for variant annotations
- OLS/DOID for disease DOIDs
- OLS/NCIt for therapy NCIt IDs
- RxNorm for drug RxCUIs
- EFO for disease EFO IDs
- ClinicalTrials.gov for trial info
- HPO for phenotype IDs
- NCBI for PMID/PMCID conversion
"""

from typing import Dict, Any, List, Optional
import re
import json
import urllib.parse
import aiohttp
import asyncio
import concurrent.futures
from langchain_core.tools import tool

from .context import get_context
from .schemas import TIER_1_FIELDS


# =============================================================================
# ASYNC HELPER
# =============================================================================

def run_async(coro):
    """
    Run an async coroutine safely, whether or not we're already in an event loop.

    Uses a thread pool executor to run the async code in a new thread with its own
    event loop if we're already in an async context.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - we can use asyncio.run()
        return asyncio.run(coro)

    # Already in an async context - run in a thread pool
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=30)

# =============================================================================
# TIER 2 FIELDS - Fields requiring database lookups
# =============================================================================

TIER_2_FIELDS = [
    "disease_doid",
    "gene_entrez_ids",
    "therapy_ncit_ids",
    "factor_ncit_ids",
    "variant_type_soids",
    "variant_clinvar_ids",
    "variant_allele_registry_ids",
    "variant_mane_select_transcripts",
    "phenotype_ids",
    "phenotype_hpo_ids",
    "source_citation_id",
    "source_pmcid",
    "chromosome",
    "start_position",
    "stop_position",
    "reference_build",
    "representative_transcript",
    "reference_bases",
    "variant_bases",
    "coordinate_type",
]

# =============================================================================
# GENERIC VARIANT TERMS (Cannot be looked up in databases)
# =============================================================================

GENERIC_VARIANT_TERMS = {
    "mutation", "mutations", "mutant", "mutated",
    "wild type", "wild-type", "wildtype", "wt",
    "amplification", "amplified",
    "deletion", "deleted", "del",
    "expression", "overexpression", "underexpression",
    "loss", "loss of function", "lof",
    "gain", "gain of function", "gof",
    "alteration", "altered", "variant", "variants",
    "positive", "negative",
    "high", "low",
    "any", "any mutation", "any variant",
}


def is_specific_variant(variant_name: str) -> bool:
    """Check if a variant name is specific enough to look up."""
    if not variant_name:
        return False

    if isinstance(variant_name, list):
        if not variant_name:
            return False
        variant_name = str(variant_name[0])

    normalized = variant_name.lower().strip()

    if normalized in GENERIC_VARIANT_TERMS:
        return False

    # Check for amino acid change patterns
    aa_pattern = re.compile(r'^p?\.?[A-Z][a-z]{0,2}\d+[A-Z][a-z]{0,2}$', re.IGNORECASE)
    if aa_pattern.match(normalized.replace(" ", "")):
        return True

    # Check for exon patterns
    exon_pattern = re.compile(r'exon\s*\d+', re.IGNORECASE)
    if exon_pattern.search(normalized):
        return True

    # Check for fusion patterns
    fusion_pattern = re.compile(r'^[A-Z0-9]+[-:][:|-][A-Z0-9]+$', re.IGNORECASE)
    if fusion_pattern.match(normalized.replace(" ", "")):
        return True

    # Check for HGVS patterns
    hgvs_pattern = re.compile(r'[cgp]\.\d+', re.IGNORECASE)
    if hgvs_pattern.search(normalized):
        return True

    # Check for rsID
    if normalized.startswith("rs") and normalized[2:].isdigit():
        return True

    # If variant has numbers and letters mixed
    has_numbers = any(c.isdigit() for c in variant_name)
    has_letters = any(c.isalpha() for c in variant_name)
    if has_numbers and has_letters and len(variant_name) < 20:
        return True

    return False


# =============================================================================
# INTERNAL LOOKUP HELPERS (Async)
# =============================================================================

async def _lookup_gene_entrez_internal(gene_symbol: str) -> Dict[str, Any]:
    """Internal helper for gene Entrez ID lookup via MyGene.info."""
    if not gene_symbol:
        return {"found": False, "error": "Empty gene symbol"}

    if isinstance(gene_symbol, list):
        gene_symbol = str(gene_symbol[0]) if gene_symbol else ""

    url = f"https://mygene.info/v3/query?q=symbol:{urllib.parse.quote(gene_symbol)}&species=human&fields=entrezgene,symbol,name"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                hits = data.get("hits", [])
                if hits:
                    hit = hits[0]
                    entrez_id = hit.get("entrezgene")
                    if entrez_id:
                        return {
                            "found": True,
                            "gene_symbol": hit.get("symbol"),
                            "gene_entrez_id": str(entrez_id),
                            "gene_name": hit.get("name"),
                            "source": "MyGene.info"
                        }

                return {"found": False, "error": f"Gene {gene_symbol} not found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_disease_doid_internal(disease_name: str) -> Dict[str, Any]:
    """Internal helper for Disease Ontology ID lookup via OLS."""
    if not disease_name:
        return {"found": False, "error": "Empty disease name"}

    if isinstance(disease_name, list):
        disease_name = str(disease_name[0]) if disease_name else ""

    url = f"https://www.ebi.ac.uk/ols/api/search?q={urllib.parse.quote(disease_name)}&ontology=doid&rows=5"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                docs = data.get("response", {}).get("docs", [])

                if docs:
                    best = docs[0]
                    obo_id = best.get("obo_id", "")
                    doid = obo_id if obo_id.startswith("DOID:") else None

                    return {
                        "found": True,
                        "disease_doid": doid,
                        "disease_label": best.get("label"),
                        "source": "OLS/DOID"
                    }

                return {"found": False, "error": f"Disease '{disease_name}' not found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_therapy_ncit_internal(therapy_name: str) -> Dict[str, Any]:
    """Internal helper for NCI Thesaurus ID lookup via OLS."""
    if not therapy_name:
        return {"found": False, "error": "Empty therapy name"}

    if isinstance(therapy_name, list):
        therapy_name = str(therapy_name[0]) if therapy_name else ""

    search_term = f"*{therapy_name}*" if len(therapy_name) > 4 else therapy_name
    url = f"https://www.ebi.ac.uk/ols/api/search?q={urllib.parse.quote(search_term)}&ontology=ncit&rows=20&exact=false"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                docs = data.get("response", {}).get("docs", [])

                # Try exact match first
                for doc in docs:
                    label = doc.get("label", "").lower()
                    if label == therapy_name.lower():
                        return _format_ncit_result(doc)

                # Use first result
                if docs:
                    return _format_ncit_result(docs[0])

                return {"found": False, "error": f"Therapy '{therapy_name}' not found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


def _format_ncit_result(doc: Dict) -> Dict[str, Any]:
    """Helper to format OLS NCIt result."""
    obo_id = doc.get("obo_id", "")
    ncit_id = None
    if obo_id.startswith("NCIT:"):
        ncit_id = obo_id
    elif "NCIT_" in obo_id:
        ncit_id = "NCIT:" + obo_id.split("NCIT_")[-1]

    if ncit_id:
        return {
            "found": True,
            "therapy_ncit_id": ncit_id,
            "therapy_label": doc.get("label"),
            "source": "OLS/NCIt"
        }
    return {"found": False, "error": "Invalid ID format"}


async def _lookup_rxnorm_internal(drug_name: str) -> Dict[str, Any]:
    """Internal helper for RxNorm lookup."""
    if not drug_name:
        return {"found": False, "error": "Empty drug name"}

    if isinstance(drug_name, list):
        drug_name = str(drug_name[0]) if drug_name else ""

    url = f"https://rxnav.nlm.nih.gov/REST/approximateTerm.json?term={urllib.parse.quote(drug_name)}&maxEntries=1"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                if 'approximateGroup' in data and 'candidate' in data['approximateGroup']:
                    candidates = data['approximateGroup']['candidate']
                    if candidates:
                        best = candidates[0]
                        return {
                            "found": True,
                            "rxcui": best.get('rxcui'),
                            "score": best.get('score'),
                            "source": "RxNorm/NLM"
                        }
                return {"found": False, "error": "Not found in RxNorm"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_efo_internal(disease_name: str) -> Dict[str, Any]:
    """Internal helper for EFO lookup."""
    if not disease_name:
        return {"found": False, "error": "Empty disease name"}

    if isinstance(disease_name, list):
        disease_name = str(disease_name[0]) if disease_name else ""

    search_term = f"*{disease_name}*" if len(disease_name) > 4 else disease_name
    url = f"https://www.ebi.ac.uk/ols/api/search?q={urllib.parse.quote(search_term)}&ontology=efo&rows=5&exact=false"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                docs = data.get("response", {}).get("docs", [])

                if docs:
                    best = docs[0]
                    return {
                        "found": True,
                        "efo_id": best.get('short_form'),
                        "label": best.get('label'),
                        "source": "EFO/OLS"
                    }
                return {"found": False, "error": "Not found in EFO"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_safety_profile_internal(drug_name: str) -> Dict[str, Any]:
    """Internal helper for Safety lookup via OpenFDA."""
    if not drug_name:
        return {"found": False, "error": "Empty drug name"}

    if isinstance(drug_name, list):
        drug_name = str(drug_name[0]) if drug_name else ""

    url = f'https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:"{urllib.parse.quote(drug_name)}"&count=patient.reaction.reactionmeddrapt.exact&limit=5'

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                if 'results' in data:
                    return {
                        "found": True,
                        "top_events": [
                            {"term": item['term'], "count": item['count']}
                            for item in data['results']
                        ],
                        "source": "FAERS/OpenFDA"
                    }
                return {"found": False, "error": "No safety data found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_clinical_trial_internal(nct_id: str) -> Dict[str, Any]:
    """Internal helper for ClinicalTrials.gov lookup."""
    if not nct_id:
        return {"found": False, "error": "Empty NCT ID"}

    nct_id = nct_id.strip()
    if not nct_id.startswith("NCT"):
        return {"found": False, "error": "Invalid format (must start with NCT)"}

    url = f"https://clinicaltrials.gov/api/v2/studies/{nct_id}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                protocol = data.get("protocolSection", {})
                id_module = protocol.get("identificationModule", {})
                status_module = protocol.get("statusModule", {})

                return {
                    "found": True,
                    "nct_id": id_module.get("nctId"),
                    "title": id_module.get("briefTitle"),
                    "status": status_module.get("overallStatus"),
                    "phases": protocol.get("designModule", {}).get("phases", []),
                    "source": "ClinicalTrials.gov API v2"
                }
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_hpo_internal(phenotype_name: str) -> Dict[str, Any]:
    """Internal helper for HPO lookup."""
    if not phenotype_name:
        return {"found": False, "error": "Empty phenotype"}

    url = f"https://www.ebi.ac.uk/ols/api/search?q={urllib.parse.quote(phenotype_name)}&ontology=hp&rows=1&exact=false"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                docs = data.get("response", {}).get("docs", [])

                if docs:
                    best = docs[0]
                    return {
                        "found": True,
                        "hpo_id": best.get("obo_id"),
                        "label": best.get("label"),
                        "source": "EBI OLS (HPO)"
                    }
                return {"found": False, "error": "Not found in HPO"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_pmcid_internal(pmid: str) -> Dict[str, Any]:
    """Internal helper to convert PMID to PMCID."""
    if not pmid:
        return {"found": False, "error": "Empty PMID"}

    pmid_clean = pmid.replace("PMID:", "").strip()
    url = f"https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/?tool=civic_agent&email=civic_agent@example.com&ids={pmid_clean}&format=json"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                records = data.get("records", [])
                if records:
                    record = records[0]
                    pmcid = record.get("pmcid")
                    if pmcid:
                        return {"found": True, "pmcid": pmcid, "source": "NCBI ID Converter"}

                return {"found": False, "error": "No PMCID found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


async def _lookup_variant_info_internal(gene_symbol: str, variant_name: str) -> Dict[str, Any]:
    """Internal helper for variant lookup via MyVariant.info."""
    if not is_specific_variant(variant_name):
        return {
            "found": False,
            "error": f"'{variant_name}' is a generic term, not a specific variant. Cannot lookup.",
            "skipped": True
        }

    # Build query for MyVariant.info
    query = f"{gene_symbol}:{variant_name}".replace(" ", "")
    url = f"https://myvariant.info/v1/query?q={urllib.parse.quote(query)}&fields=cadd,clinvar,dbsnp,dbnsfp&size=1"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return {"found": False, "error": f"HTTP {response.status}"}

                data = await response.json()
                hits = data.get("hits", [])

                if hits:
                    hit = hits[0]
                    return {
                        "found": True,
                        "variant_id": hit.get("_id"),
                        "clinvar_id": hit.get("clinvar", {}).get("rcv", {}).get("accession") if hit.get("clinvar") else None,
                        "rsid": hit.get("dbsnp", {}).get("rsid") if hit.get("dbsnp") else None,
                        "cadd_score": hit.get("cadd", {}).get("phred") if hit.get("cadd") else None,
                        "source": "MyVariant.info"
                    }

                return {"found": False, "error": "Variant not found"}
        except Exception as e:
            return {"found": False, "error": str(e)}


# =============================================================================
# LANGCHAIN TOOLS
# =============================================================================

@tool
def finalize_extraction() -> str:
    """
    Finalize the extraction after approval and normalization.

    This marks the extraction as complete and copies draft items to final.
    Call this as the LAST step after normalization.

    Returns:
        JSON string with finalization status and coverage statistics
    """
    ctx = get_context()

    # Copy draft to final
    ctx.final_extractions = list(ctx.draft_extractions)
    ctx.is_complete = True
    ctx.final_status = "COMPLETE"

    # Calculate coverage statistics
    items_count = len(ctx.final_extractions)
    tier1_coverages = []
    tier2_coverages = []

    for item in ctx.final_extractions:
        tier1_present = sum(1 for f in TIER_1_FIELDS if item.get(f) is not None)
        tier1_coverages.append(tier1_present / len(TIER_1_FIELDS) * 100)

        tier2_present = sum(1 for f in TIER_2_FIELDS if item.get(f) is not None)
        tier2_coverages.append(tier2_present / len(TIER_2_FIELDS) * 100)

    avg_tier1 = round(sum(tier1_coverages) / len(tier1_coverages), 1) if tier1_coverages else 0
    avg_tier2 = round(sum(tier2_coverages) / len(tier2_coverages), 1) if tier2_coverages else 0

    result = {
        "success": True,
        "items_extracted": items_count,
        "iterations_used": ctx.iteration_count,
        "max_iterations": ctx.max_iterations,
        "average_tier1_coverage": avg_tier1,
        "average_tier2_coverage": avg_tier2,
        "message": f"Extraction finalized with {items_count} evidence items."
    }

    return json.dumps(result, indent=2)


@tool
def get_tier2_coverage() -> str:
    """
    Get Tier 2 field coverage statistics for all draft extractions.

    Returns coverage percentage and lists of present/missing Tier 2 fields
    for each evidence item.

    Returns:
        JSON string with coverage statistics per item
    """
    ctx = get_context()

    if not ctx.draft_extractions:
        return json.dumps({
            "items": 0,
            "average_coverage": 0,
            "message": "No draft extractions available"
        })

    item_coverages = []

    for i, item in enumerate(ctx.draft_extractions):
        present = [f for f in TIER_2_FIELDS if item.get(f) is not None]
        missing = [f for f in TIER_2_FIELDS if item.get(f) is None]

        item_coverages.append({
            "item_index": i,
            "gene": item.get("feature_names", "?"),
            "variant": item.get("variant_names", "?"),
            "tier2_fields_present": len(present),
            "tier2_coverage_percent": round(len(present) / len(TIER_2_FIELDS) * 100, 1),
            "missing": missing[:5],
        })

    avg_coverage = round(
        sum(c["tier2_coverage_percent"] for c in item_coverages) / len(item_coverages),
        1
    )

    return json.dumps({
        "items": len(item_coverages),
        "average_tier2_coverage": avg_coverage,
        "per_item_coverage": item_coverages,
        "tier2_fields_total": len(TIER_2_FIELDS),
    }, indent=2)


@tool
def lookup_rxnorm(drug_name: str) -> str:
    """
    Lookup a drug in RxNorm to get its RXCUI and canonical name.

    Args:
        drug_name: Drug/therapy name to look up

    Returns:
        JSON string with RxCUI if found
    """
    result = run_async(_lookup_rxnorm_internal(drug_name))
    return json.dumps(result, indent=2)


@tool
def lookup_efo(disease_name: str) -> str:
    """
    Lookup a disease in EFO (Experimental Factor Ontology) via EBI OLS API.

    Args:
        disease_name: Disease name to look up

    Returns:
        JSON string with EFO ID if found
    """
    result = run_async(_lookup_efo_internal(disease_name))
    return json.dumps(result, indent=2)


@tool
def lookup_safety_profile(drug_name: str) -> str:
    """
    Lookup top adverse events for a drug via OpenFDA (FAERS database).

    Args:
        drug_name: Drug name to look up

    Returns:
        JSON string with top adverse events
    """
    result = run_async(_lookup_safety_profile_internal(drug_name))
    return json.dumps(result, indent=2)


@tool
def lookup_gene_entrez(gene_symbol: str) -> str:
    """
    Lookup Entrez Gene ID for a gene symbol via MyGene.info.

    Args:
        gene_symbol: Gene symbol (e.g., BRAF, EGFR, TP53)

    Returns:
        JSON string with Entrez ID if found
    """
    result = run_async(_lookup_gene_entrez_internal(gene_symbol))
    return json.dumps(result, indent=2)


@tool
def lookup_variant_info(gene_symbol: str, variant_name: str) -> str:
    """
    Lookup variant information from MyVariant.info.

    Returns genomic coordinates, ClinVar IDs, CADD scores, etc.
    Only works for specific variants (V600E, L858R) - not generic terms like "MUTATION".

    Args:
        gene_symbol: Gene symbol (e.g., BRAF)
        variant_name: Specific variant name (e.g., V600E, L858R)

    Returns:
        JSON string with variant annotations if found
    """
    result = run_async(_lookup_variant_info_internal(gene_symbol, variant_name))
    return json.dumps(result, indent=2)


@tool
def lookup_therapy_ncit(therapy_name: str) -> str:
    """
    Lookup NCI Thesaurus ID for a therapy/drug name via OLS.

    Args:
        therapy_name: Single drug/therapy name (e.g., Erlotinib, Pembrolizumab)

    Returns:
        JSON string with NCIt ID if found
    """
    result = run_async(_lookup_therapy_ncit_internal(therapy_name))
    return json.dumps(result, indent=2)


@tool
def lookup_disease_doid(disease_name: str) -> str:
    """
    Lookup Disease Ontology ID (DOID) for a disease name via OLS.

    Args:
        disease_name: Disease name (e.g., Non-Small Cell Lung Carcinoma, Melanoma)

    Returns:
        JSON string with DOID if found
    """
    result = run_async(_lookup_disease_doid_internal(disease_name))
    return json.dumps(result, indent=2)


@tool
def lookup_clinical_trial(nct_id: str) -> str:
    """
    Lookup Clinical Trial details by NCT ID from ClinicalTrials.gov.

    Args:
        nct_id: NCT identifier (e.g., NCT01234567)

    Returns:
        JSON string with trial title, status, and phases
    """
    result = run_async(_lookup_clinical_trial_internal(nct_id))
    return json.dumps(result, indent=2)


@tool
def lookup_hpo(phenotype_name: str) -> str:
    """
    Lookup Human Phenotype Ontology (HPO) ID for a phenotype name.

    Args:
        phenotype_name: Phenotype description to look up

    Returns:
        JSON string with HPO ID if found
    """
    result = run_async(_lookup_hpo_internal(phenotype_name))
    return json.dumps(result, indent=2)


@tool
def lookup_pmcid(pmid: str) -> str:
    """
    Lookup PMCID for a given PMID using NCBI ID Converter.

    Args:
        pmid: PubMed ID to convert

    Returns:
        JSON string with PMCID if found
    """
    result = run_async(_lookup_pmcid_internal(pmid))
    return json.dumps(result, indent=2)
