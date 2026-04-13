"""
Map-Reduce for Parallel Normalization
======================================

Provides parallel processing for entity normalization while:
- Preserving item ordering
- Avoiding race conditions
- Handling failures gracefully

The Map-Reduce pattern:
1. MAP: Split items into independent normalization tasks
2. PROCESS: Run lookups in parallel (with concurrency limits)
3. REDUCE: Collect results maintaining original order

Usage:
    from runtime.map_reduce import normalize_items_parallel

    # Normalize evidence items in parallel
    normalized = await normalize_items_parallel(
        items=draft_extractions,
        max_concurrency=5,
    )
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import functools

logger = logging.getLogger("civic.map_reduce")


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_MAX_CONCURRENCY = 5  # Max parallel API calls
DEFAULT_TIMEOUT = 30.0  # Timeout per lookup (seconds)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class NormalizationTask:
    """A single normalization task for an entity."""
    item_index: int  # Original position in the list (for ordering)
    item_id: str  # Unique identifier for the item
    entity_type: str  # "gene", "variant", "disease", "therapy", etc.
    entity_name: str  # The name to normalize
    lookup_function: str  # Name of lookup function to call


@dataclass
class NormalizationResult:
    """Result of a normalization task."""
    item_index: int
    item_id: str
    entity_type: str
    entity_name: str
    normalized_id: Optional[str] = None
    normalized_name: Optional[str] = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class MapReduceStats:
    """Statistics from a map-reduce operation."""
    total_items: int
    total_tasks: int
    successful_tasks: int
    failed_tasks: int
    total_duration_ms: float
    tasks_per_second: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_items": self.total_items,
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "total_duration_ms": self.total_duration_ms,
            "tasks_per_second": self.tasks_per_second,
        }


# =============================================================================
# ORDERED TASK QUEUE
# =============================================================================

class OrderedTaskQueue:
    """
    A task queue that preserves ordering of results.

    Uses asyncio.Semaphore for concurrency control and
    stores results in a dict keyed by index for ordering.
    """

    def __init__(self, max_concurrency: int = DEFAULT_MAX_CONCURRENCY):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.results: Dict[int, NormalizationResult] = {}
        self.lock = asyncio.Lock()

    async def submit(
        self,
        task: NormalizationTask,
        executor: Callable[[NormalizationTask], NormalizationResult],
    ) -> NormalizationResult:
        """
        Submit a task for execution with concurrency control.

        Args:
            task: The normalization task
            executor: Function to execute the task

        Returns:
            NormalizationResult
        """
        async with self.semaphore:
            result = await asyncio.get_event_loop().run_in_executor(
                None,  # Use default executor
                executor,
                task,
            )

            async with self.lock:
                self.results[task.item_index] = result

            return result

    def get_ordered_results(self) -> List[NormalizationResult]:
        """Get results in original order."""
        return [
            self.results[i]
            for i in sorted(self.results.keys())
        ]


# =============================================================================
# LOOKUP FUNCTION MAPPING
# =============================================================================

def _get_lookup_function(lookup_name: str) -> Optional[Callable]:
    """
    Get the lookup function by name.

    This lazy-imports to avoid circular dependencies.
    """
    try:
        if lookup_name == "lookup_gene_entrez":
            from tools.normalization_tools import lookup_gene_entrez
            return lookup_gene_entrez

        elif lookup_name == "lookup_disease_doid":
            from tools.normalization_tools import lookup_disease_doid_tool
            return lookup_disease_doid_tool

        elif lookup_name == "lookup_therapy_ncit":
            from tools.normalization_tools import lookup_therapy_ncit
            return lookup_therapy_ncit

        elif lookup_name == "lookup_variant_info":
            from tools.normalization_tools import lookup_variant_info_tool
            return lookup_variant_info_tool

        elif lookup_name == "lookup_rxnorm":
            from tools.normalization_tools import lookup_rxnorm
            return lookup_rxnorm

        elif lookup_name == "lookup_efo":
            from tools.normalization_tools import lookup_efo
            return lookup_efo

        elif lookup_name == "lookup_hpo":
            from tools.normalization_tools import lookup_hpo
            return lookup_hpo

        elif lookup_name == "lookup_clinical_trial":
            from tools.normalization_tools import lookup_clinical_trial
            return lookup_clinical_trial

        elif lookup_name == "lookup_pmcid":
            from tools.normalization_tools import lookup_pmcid
            return lookup_pmcid

        else:
            logger.warning(f"Unknown lookup function: {lookup_name}")
            return None

    except ImportError as e:
        logger.error(f"Failed to import {lookup_name}: {e}")
        return None


def _execute_lookup(task: NormalizationTask) -> NormalizationResult:
    """
    Execute a single lookup task.

    This is the worker function called by the thread pool.
    """
    start_time = datetime.now()

    try:
        lookup_fn = _get_lookup_function(task.lookup_function)

        if lookup_fn is None:
            return NormalizationResult(
                item_index=task.item_index,
                item_id=task.item_id,
                entity_type=task.entity_type,
                entity_name=task.entity_name,
                success=False,
                error=f"Unknown lookup function: {task.lookup_function}",
                duration_ms=(datetime.now() - start_time).total_seconds() * 1000,
            )

        # Call the lookup function
        result = lookup_fn.invoke({"name": task.entity_name})

        # Parse the result
        normalized_id = None
        normalized_name = None

        if isinstance(result, str):
            # Try to parse as JSON or extract ID
            import json
            try:
                data = json.loads(result)
                normalized_id = data.get("id") or data.get("entrez_id") or data.get("doid")
                normalized_name = data.get("name") or data.get("symbol")
            except json.JSONDecodeError:
                # Assume result is the ID directly
                normalized_id = result if result and result != "Not found" else None
        elif isinstance(result, dict):
            normalized_id = result.get("id") or result.get("entrez_id") or result.get("doid")
            normalized_name = result.get("name") or result.get("symbol")

        return NormalizationResult(
            item_index=task.item_index,
            item_id=task.item_id,
            entity_type=task.entity_type,
            entity_name=task.entity_name,
            normalized_id=normalized_id,
            normalized_name=normalized_name,
            success=normalized_id is not None,
            duration_ms=(datetime.now() - start_time).total_seconds() * 1000,
        )

    except Exception as e:
        logger.error(f"Lookup failed for {task.entity_type}:{task.entity_name}: {e}")
        return NormalizationResult(
            item_index=task.item_index,
            item_id=task.item_id,
            entity_type=task.entity_type,
            entity_name=task.entity_name,
            success=False,
            error=str(e),
            duration_ms=(datetime.now() - start_time).total_seconds() * 1000,
        )


# =============================================================================
# MAP PHASE: Extract Normalization Tasks
# =============================================================================

def extract_normalization_tasks(items: List[Dict[str, Any]]) -> List[NormalizationTask]:
    """
    Extract normalization tasks from evidence items.

    For each item, creates tasks for:
    - Genes (feature_names → gene_entrez_ids)
    - Diseases (disease_name → disease_doid)
    - Therapies (therapy_names → therapy_ncit_ids)
    - Variants (variant_names → variant_id)

    Args:
        items: List of evidence items

    Returns:
        List of NormalizationTask objects
    """
    tasks = []

    for idx, item in enumerate(items):
        item_id = item.get("id", f"item_{idx}")

        # Gene normalization
        genes = item.get("feature_names") or ""
        if genes:
            for gene in genes.split(","):
                gene = gene.strip()
                if gene and not item.get("gene_entrez_ids"):
                    tasks.append(NormalizationTask(
                        item_index=idx,
                        item_id=item_id,
                        entity_type="gene",
                        entity_name=gene,
                        lookup_function="lookup_gene_entrez",
                    ))

        # Disease normalization
        disease = item.get("disease_name") or ""
        if disease and not item.get("disease_doid"):
            tasks.append(NormalizationTask(
                item_index=idx,
                item_id=item_id,
                entity_type="disease",
                entity_name=disease,
                lookup_function="lookup_disease_doid",
            ))

        # Therapy normalization
        therapies = item.get("therapy_names") or ""
        if therapies:
            for therapy in therapies.split(","):
                therapy = therapy.strip()
                if therapy and not item.get("therapy_ncit_ids"):
                    tasks.append(NormalizationTask(
                        item_index=idx,
                        item_id=item_id,
                        entity_type="therapy",
                        entity_name=therapy,
                        lookup_function="lookup_therapy_ncit",
                    ))

        # Variant normalization
        variants = item.get("variant_names") or ""
        if variants:
            for variant in variants.split(","):
                variant = variant.strip()
                if variant:
                    tasks.append(NormalizationTask(
                        item_index=idx,
                        item_id=item_id,
                        entity_type="variant",
                        entity_name=variant,
                        lookup_function="lookup_variant_info",
                    ))

    logger.info(f"Extracted {len(tasks)} normalization tasks from {len(items)} items")
    return tasks


# =============================================================================
# REDUCE PHASE: Apply Results to Items
# =============================================================================

def apply_normalization_results(
    items: List[Dict[str, Any]],
    results: List[NormalizationResult],
) -> List[Dict[str, Any]]:
    """
    Apply normalization results back to items.

    Maintains original item order and only updates fields
    where normalization succeeded.

    Args:
        items: Original evidence items
        results: Normalization results

    Returns:
        Updated items with normalized IDs
    """
    # Group results by item index
    results_by_item: Dict[int, List[NormalizationResult]] = {}
    for result in results:
        if result.item_index not in results_by_item:
            results_by_item[result.item_index] = []
        results_by_item[result.item_index].append(result)

    # Apply results to items (maintaining order)
    normalized_items = []
    for idx, item in enumerate(items):
        item_copy = dict(item)  # Don't modify original

        item_results = results_by_item.get(idx, [])
        for result in item_results:
            if result.success and result.normalized_id:
                if result.entity_type == "gene":
                    existing = item_copy.get("gene_entrez_ids") or ""
                    if existing:
                        item_copy["gene_entrez_ids"] = f"{existing},{result.normalized_id}"
                    else:
                        item_copy["gene_entrez_ids"] = result.normalized_id

                elif result.entity_type == "disease":
                    item_copy["disease_doid"] = result.normalized_id

                elif result.entity_type == "therapy":
                    existing = item_copy.get("therapy_ncit_ids") or ""
                    if existing:
                        item_copy["therapy_ncit_ids"] = f"{existing},{result.normalized_id}"
                    else:
                        item_copy["therapy_ncit_ids"] = result.normalized_id

                elif result.entity_type == "variant":
                    # Variant normalization may return multiple fields
                    if result.normalized_id:
                        item_copy["variant_id"] = result.normalized_id

        normalized_items.append(item_copy)

    return normalized_items


# =============================================================================
# MAIN PARALLEL NORMALIZATION FUNCTION
# =============================================================================

async def normalize_items_parallel(
    items: List[Dict[str, Any]],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> Tuple[List[Dict[str, Any]], MapReduceStats]:
    """
    Normalize evidence items in parallel.

    This is the main entry point for parallel normalization.
    It uses the map-reduce pattern:
    1. MAP: Extract normalization tasks from items
    2. PROCESS: Execute lookups in parallel
    3. REDUCE: Apply results back to items

    Args:
        items: List of evidence items to normalize
        max_concurrency: Maximum parallel API calls

    Returns:
        Tuple of (normalized_items, stats)

    Example:
        >>> normalized, stats = await normalize_items_parallel(
        ...     items=draft_extractions,
        ...     max_concurrency=5,
        ... )
        >>> print(f"Normalized {len(normalized)} items in {stats.total_duration_ms:.0f}ms")
    """
    start_time = datetime.now()

    # MAP: Extract tasks
    tasks = extract_normalization_tasks(items)

    if not tasks:
        logger.info("No normalization tasks to execute")
        return items, MapReduceStats(
            total_items=len(items),
            total_tasks=0,
            successful_tasks=0,
            failed_tasks=0,
            total_duration_ms=0,
            tasks_per_second=0,
        )

    # PROCESS: Execute in parallel with ordering
    queue = OrderedTaskQueue(max_concurrency=max_concurrency)

    # Create all tasks
    async_tasks = [
        queue.submit(task, _execute_lookup)
        for task in tasks
    ]

    # Wait for all to complete
    await asyncio.gather(*async_tasks)

    # Get ordered results
    results = queue.get_ordered_results()

    # REDUCE: Apply results
    normalized_items = apply_normalization_results(items, results)

    # Calculate stats
    total_duration = (datetime.now() - start_time).total_seconds() * 1000
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    stats = MapReduceStats(
        total_items=len(items),
        total_tasks=len(tasks),
        successful_tasks=successful,
        failed_tasks=failed,
        total_duration_ms=total_duration,
        tasks_per_second=len(tasks) / (total_duration / 1000) if total_duration > 0 else 0,
    )

    logger.info(
        f"Map-Reduce complete: {successful}/{len(tasks)} tasks succeeded "
        f"in {total_duration:.0f}ms ({stats.tasks_per_second:.1f} tasks/sec)"
    )

    return normalized_items, stats


def normalize_items_sync(
    items: List[Dict[str, Any]],
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> Tuple[List[Dict[str, Any]], MapReduceStats]:
    """
    Synchronous wrapper for normalize_items_parallel.

    Use this when you're not in an async context.

    Args:
        items: List of evidence items to normalize
        max_concurrency: Maximum parallel API calls

    Returns:
        Tuple of (normalized_items, stats)
    """
    return asyncio.run(normalize_items_parallel(items, max_concurrency))


# =============================================================================
# INTEGRATION WITH NORMALIZER NODE (COMMENTED OUT)
# =============================================================================
#
# To integrate map-reduce into the normalizer_node:
#
# Replace the current normalizer_node with:
#
# async def normalizer_node_with_map_reduce(state: ExtractionGraphState) -> Dict[str, Any]:
#     """
#     Normalizer agent with parallel Map-Reduce processing.
#     """
#     logger.info("=== NORMALIZER NODE START (MAP-REDUCE) ===")
#
#     # Get items to normalize
#     draft_extractions = state.get("draft_extractions", [])
#
#     if not draft_extractions:
#         logger.warning("No items to normalize")
#         return {
#             "is_complete": True,
#             "current_phase": "normalizer_complete",
#         }
#
#     # Run parallel normalization
#     normalized_items, stats = await normalize_items_parallel(
#         items=draft_extractions,
#         max_concurrency=5,
#     )
#
#     logger.info(f"Normalization stats: {stats.to_dict()}")
#
#     return {
#         "draft_extractions": normalized_items,
#         "final_extractions": normalized_items,
#         "is_complete": True,
#         "current_phase": "normalizer_complete",
#     }


if __name__ == "__main__":
    # Quick test
    import asyncio

    test_items = [
        {
            "id": "1",
            "feature_names": "BRAF",
            "variant_names": "V600E",
            "disease_name": "Melanoma",
            "therapy_names": "Vemurafenib",
        },
        {
            "id": "2",
            "feature_names": "EGFR",
            "variant_names": "L858R",
            "disease_name": "Lung Cancer",
            "therapy_names": "Erlotinib",
        },
    ]

    async def test():
        print("Testing parallel normalization...")
        normalized, stats = await normalize_items_parallel(test_items, max_concurrency=3)
        print(f"Stats: {stats.to_dict()}")
        for item in normalized:
            print(f"  Item: {item}")

    asyncio.run(test())
