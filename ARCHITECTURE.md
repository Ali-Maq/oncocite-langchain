# CIViC Extraction Pipeline - LangGraph Architecture

## Overview

This document describes the end-to-end system architecture for the CIViC evidence extraction pipeline migrated from Claude Agent SDK to LangGraph.

---

## 1. HIGH-LEVEL SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CIViC EXTRACTION PIPELINE                             │
│                         (LangGraph Implementation)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   INPUT                           PROCESSING                      OUTPUT    │
│   ─────                           ──────────                      ──────    │
│                                                                              │
│   ┌─────────┐    ┌────────────────────────────────────┐    ┌─────────────┐  │
│   │   PDF   │───▶│         TWO-PHASE PIPELINE         │───▶│  Structured │  │
│   │  Paper  │    │                                    │    │  Evidence   │  │
│   └─────────┘    │  PHASE 1        PHASE 2            │    │   Items     │  │
│                  │  ────────       ────────           │    └─────────────┘  │
│                  │  Reader    →    Extraction         │                      │
│                  │  (Vision)       (Text-based)       │                      │
│                  └────────────────────────────────────┘                      │
│                                                                              │
│   Models Used:                                                               │
│   ┌────────────────────────────────────────────────────────────────────┐    │
│   │  Reader:     Qwen3-VL-235B (Vision Model via Fireworks API)        │    │
│   │  All Others: GLM-4 (Text Model via Fireworks API)                  │    │
│   └────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. TWO-PHASE PIPELINE ARCHITECTURE

### Phase 1: Reader (Vision → Structured Text)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PHASE 1: READER GRAPH                              │
│                         (reader_graph.py)                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────┐                                                          │
│   │  PDF File    │                                                          │
│   │ (6 pages)    │                                                          │
│   └──────┬───────┘                                                          │
│          │                                                                   │
│          ▼                                                                   │
│   ┌──────────────────────────────────────────────┐                          │
│   │     load_images_from_pdf()                    │                          │
│   │     ─────────────────────                     │                          │
│   │  • Opens PDF with PyMuPDF (fitz)             │                          │
│   │  • Renders each page at 1.5x scale (108 DPI) │                          │
│   │  • Converts to JPEG, base64 encoded          │                          │
│   │  • Returns list of image content dicts       │                          │
│   └──────────────────────┬───────────────────────┘                          │
│                          │                                                   │
│                          ▼                                                   │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                         READER NODE                                   │  │
│   │                         (StateGraph Node)                             │  │
│   ├──────────────────────────────────────────────────────────────────────┤  │
│   │                                                                       │  │
│   │  LLM: Qwen3-VL-235B (Vision Model)                                   │  │
│   │  Tools: save_paper_content, get_paper_info, read_paper_page          │  │
│   │                                                                       │  │
│   │  Input:  [System Prompt] + [Page Images (base64)]                    │  │
│   │                                                                       │  │
│   │  Processing:                                                          │  │
│   │  ┌─────────────────────────────────────────────────────────────────┐ │  │
│   │  │  1. LLM receives ALL page images as vision input                │ │  │
│   │  │  2. LLM extracts:                                               │ │  │
│   │  │     • Metadata (title, authors, journal, year)                  │ │  │
│   │  │     • Sections with full text                                   │ │  │
│   │  │     • Tables (structured)                                       │ │  │
│   │  │     • Figures (descriptions)                                    │ │  │
│   │  │     • Statistics and key claims                                 │ │  │
│   │  │  3. LLM calls save_paper_content tool                           │ │  │
│   │  └─────────────────────────────────────────────────────────────────┘ │  │
│   │                                                                       │  │
│   │  Output: state["paper_content"] + state["paper_content_text"]        │  │
│   │          (23,951 characters in test run)                              │  │
│   │                                                                       │  │
│   └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Phase 2: Extraction (Planner → Extractor → Critic → Normalizer)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 2: EXTRACTION GRAPH                             │
│                       (extraction_graph.py)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Input: paper_content_text (full text from Reader)                         │
│                                                                              │
│                          ┌───────────────┐                                  │
│                          │    START      │                                  │
│                          └───────┬───────┘                                  │
│                                  │                                          │
│                                  ▼                                          │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                        PLANNER NODE                                   │  │
│   │                        (3 tools)                                      │  │
│   ├──────────────────────────────────────────────────────────────────────┤  │
│   │  LLM: GLM-4                                                          │  │
│   │  Tools: get_paper_info, get_paper_content, save_extraction_plan      │  │
│   │                                                                       │  │
│   │  Process:                                                             │  │
│   │  1. get_paper_content → receives FULL 23,951 char text               │  │
│   │  2. Analyzes paper type, identifies key claims                       │  │
│   │  3. save_extraction_plan → stores strategy                           │  │
│   │                                                                       │  │
│   │  Output: extraction_plan with paper_type, key_variants, etc.         │  │
│   └──────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼                                      │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                       EXTRACTOR NODE                                  │  │
│   │                       (7 tools)                                       │  │
│   ├──────────────────────────────────────────────────────────────────────┤  │
│   │  LLM: GLM-4                                                          │  │
│   │  Tools: get_paper_info, get_paper_content, get_extraction_plan,      │  │
│   │         get_draft_extractions, check_actionability,                   │  │
│   │         validate_evidence_item, save_evidence_items                   │  │
│   │                                                                       │  │
│   │  Process:                                                             │  │
│   │  1. get_paper_content → FULL text                                    │  │
│   │  2. get_extraction_plan → strategy                                   │  │
│   │  3. For each potential evidence item:                                │  │
│   │     • check_actionability → is this clinically actionable?           │  │
│   │     • validate_evidence_item → are required fields present?          │  │
│   │  4. save_evidence_items → stores draft_extractions                   │  │
│   │                                                                       │  │
│   │  Output: draft_extractions (2 items in test run)                     │  │
│   └──────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼                                      │
│   ┌──────────────────────────────────────────────────────────────────────┐  │
│   │                         CRITIC NODE                                   │  │
│   │                         (8 tools)                                     │  │
│   ├──────────────────────────────────────────────────────────────────────┤  │
│   │  LLM: GLM-4                                                          │  │
│   │  Tools: get_paper_info, get_paper_content, get_extraction_plan,      │  │
│   │         get_draft_extractions, check_actionability,                   │  │
│   │         validate_evidence_item, save_critique, increment_iteration    │  │
│   │                                                                       │  │
│   │  Process:                                                             │  │
│   │  1. get_paper_content → FULL text (to verify quotes)                 │  │
│   │  2. get_draft_extractions → items to validate                        │  │
│   │  3. Validates each item:                                             │  │
│   │     • verbatim_quote exists in paper_content_text?                   │  │
│   │     • Entity grounding (all entities in quote)?                      │  │
│   │     • Required fields present?                                       │  │
│   │  4. save_critique → APPROVE / NEEDS_REVISION / REJECT                │  │
│   │                                                                       │  │
│   │  Output: critique with overall_assessment (APPROVE in test run)      │  │
│   └──────────────────────────────────┬───────────────────────────────────┘  │
│                                      │                                      │
│                                      ▼                                      │
│                          ┌───────────────────────┐                          │
│                          │   ROUTING DECISION    │                          │
│                          │  route_after_critic() │                          │
│                          └───────────┬───────────┘                          │
│                                      │                                      │
│              ┌───────────────────────┴───────────────────────┐              │
│              │                                               │              │
│              ▼                                               ▼              │
│   ┌─────────────────────┐                     ┌─────────────────────────┐  │
│   │  NEEDS_REVISION     │                     │  APPROVE or             │  │
│   │  AND iteration < 3  │                     │  max iterations reached │  │
│   └──────────┬──────────┘                     └────────────┬────────────┘  │
│              │                                              │              │
│              │                                              ▼              │
│              │              ┌────────────────────────────────────────────┐ │
│              │              │                NORMALIZER NODE              │ │
│              │              │                (13 tools)                   │ │
│              │              ├────────────────────────────────────────────┤ │
│              │              │  LLM: GLM-4                                │ │
│              │              │  Tools: get_draft_extractions,             │ │
│              │              │         save_evidence_items,                │ │
│              │              │         finalize_extraction,                │ │
│              │              │         lookup_gene_entrez,                 │ │
│              │              │         lookup_variant_info,                │ │
│              │              │         lookup_disease_doid,                │ │
│              │              │         lookup_efo,                         │ │
│              │              │         lookup_therapy_ncit,                │ │
│              │              │         lookup_rxnorm,                      │ │
│              │              │         lookup_safety_profile,              │ │
│              │              │         lookup_clinical_trial,              │ │
│              │              │         lookup_hpo,                         │ │
│              │              │         lookup_pmcid                        │ │
│              │              │                                             │ │
│              │              │  Process:                                   │ │
│              │              │  1. get_draft_extractions → items           │ │
│              │              │  2. For each entity:                        │ │
│              │              │     • Gene → lookup_gene_entrez             │ │
│              │              │       (p53 → 7157)                          │ │
│              │              │     • Disease → lookup_disease_doid         │ │
│              │              │       (multiple myeloma → DOID:9538)        │ │
│              │              │     • Therapy → lookup_rxnorm + ncit        │ │
│              │              │       (doxorubicin → RxCUI:3639)            │ │
│              │              │  3. save_evidence_items → with IDs          │ │
│              │              │  4. finalize_extraction → complete          │ │
│              │              └────────────────────────────────────────────┘ │
│              │                                              │              │
│              │                                              ▼              │
│              │                                       ┌──────────┐          │
│              └──────────────────────────────────────▶│   END    │          │
│                         (loop back to Extractor)     └──────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. LANGGRAPH STATE ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ExtractionGraphState (TypedDict)                          │
│                         (graphs/state.py)                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  LANGGRAPH CONTROL FIELDS                                            │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  thread_id: str            # For checkpointing (= paper_id)         │   │
│   │  messages: Annotated[list, add_messages]  # Agent messages          │   │
│   │  current_phase: str        # "reader"|"planner"|"extractor"|...     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  PAPER IDENTIFICATION                                                │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  paper_id: str             # "PMID_11050000"                         │   │
│   │  paper_info: PaperInfo     # Metadata dict                           │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  READER INPUT                                                        │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  page_images: list[dict]   # Base64 JPEG images for vision LLM      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  READER OUTPUT (CRITICAL - FULL CONTENT)                             │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  paper_content: dict       # Structured extraction                   │   │
│   │  paper_content_text: str   # FULL text (~23,951 chars)              │   │
│   │                            # INVARIANT: NEVER truncated!             │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  AGENT OUTPUTS (Accumulated through pipeline)                        │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  extraction_plan: ExtractionPlan    # From Planner                   │   │
│   │  draft_extractions: list[dict]      # From Extractor (2 items)       │   │
│   │  critique: CritiqueResult           # From Critic (APPROVE)          │   │
│   │  final_extractions: list[dict]      # From Normalizer (with IDs)     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  ITERATION CONTROL                                                   │   │
│   ├─────────────────────────────────────────────────────────────────────┤   │
│   │  iteration_count: int      # 0 in test (no revisions needed)        │   │
│   │  max_iterations: int       # 3 (default)                             │   │
│   │  is_complete: bool         # True after finalize_extraction          │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. TOOL ARCHITECTURE (Per Agent)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          TOOL SCOPING BY AGENT                               │
│                        (tools/tool_registry.py)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   READER (3 tools)                                                          │
│   ─────────────────                                                         │
│   • save_paper_content    ← Primary output tool                             │
│   • get_paper_info        ← Paper metadata                                  │
│   • read_paper_page       ← Legacy compatibility                            │
│                                                                              │
│   PLANNER (3 tools)                                                         │
│   ─────────────────                                                         │
│   • get_paper_info        ← Metadata                                        │
│   • get_paper_content     ← FULL paper text (23,951 chars)                  │
│   • save_extraction_plan  ← Primary output tool                             │
│                                                                              │
│   EXTRACTOR (7 tools)                                                       │
│   ───────────────────                                                       │
│   • get_paper_info        ← Metadata                                        │
│   • get_paper_content     ← FULL paper text                                 │
│   • get_extraction_plan   ← Planner's strategy                              │
│   • get_draft_extractions ← Previous items (for revision)                   │
│   • check_actionability   ← Is claim clinically actionable?                 │
│   • validate_evidence_item← Are required fields present?                    │
│   • save_evidence_items   ← Primary output tool                             │
│                                                                              │
│   CRITIC (8 tools)                                                          │
│   ────────────────                                                          │
│   • get_paper_info        ← Metadata                                        │
│   • get_paper_content     ← FULL paper text (for quote verification)        │
│   • get_extraction_plan   ← Original strategy                               │
│   • get_draft_extractions ← Items to validate                               │
│   • check_actionability   ← Re-verify actionability                         │
│   • validate_evidence_item← Re-verify structure                             │
│   • save_critique         ← Primary output tool                             │
│   • increment_iteration   ← Bump counter if NEEDS_REVISION                  │
│                                                                              │
│   NORMALIZER (13 tools)                                                     │
│   ─────────────────────                                                     │
│   • get_draft_extractions   ← Items to normalize                            │
│   • save_evidence_items     ← Save with IDs                                 │
│   • finalize_extraction     ← Mark complete                                 │
│   • lookup_gene_entrez      ← Gene → Entrez ID (p53 → 7157)                 │
│   • lookup_variant_info     ← Variant annotation                            │
│   • lookup_disease_doid     ← Disease → DOID (myeloma → DOID:9538)          │
│   • lookup_efo              ← Disease → EFO ID                              │
│   • lookup_therapy_ncit     ← Drug → NCIt ID                                │
│   • lookup_rxnorm           ← Drug → RxCUI (doxorubicin → 3639)             │
│   • lookup_safety_profile   ← Drug → FDA adverse events                     │
│   • lookup_clinical_trial   ← NCT ID lookup                                 │
│   • lookup_hpo              ← Phenotype → HPO ID                            │
│   • lookup_pmcid            ← PMID → PMCID                                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. TOOL CONTEXT PATTERN

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        TOOL CONTEXT PATTERN                                  │
│                       (tools/context.py)                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Problem: LangChain @tool functions can't access LangGraph state directly  │
│                                                                              │
│   Solution: Thread-local ToolContext that holds current state               │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  class ToolContext:                                                  │   │
│   │      """Context object passed to tools via thread-local storage."""  │   │
│   │      paper_id: str                                                   │   │
│   │      paper_content: dict                                             │   │
│   │      paper_content_text: str                                         │   │
│   │      extraction_plan: dict                                           │   │
│   │      draft_extractions: list                                         │   │
│   │      critique: dict                                                  │   │
│   │      iteration_count: int                                            │   │
│   │      is_complete: bool                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Usage in agent nodes:                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  def planner_node(state: ExtractionGraphState):                      │   │
│   │      # Set context BEFORE running LLM with tools                     │   │
│   │      set_context(ToolContext.from_state(state))                      │   │
│   │                                                                       │   │
│   │      # LLM runs, tools access state via get_context()                │   │
│   │      result = llm.invoke(messages, tools=tools)                      │   │
│   │                                                                       │   │
│   │      # Update state from context                                     │   │
│   │      ctx = get_context()                                             │   │
│   │      state["extraction_plan"] = ctx.extraction_plan                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Usage in tool functions:                                                  │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  @tool                                                               │   │
│   │  def get_paper_content() -> str:                                     │   │
│   │      ctx = get_context()                                             │   │
│   │      return ctx.paper_content_text  # Returns FULL 23,951 chars      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. GLM-4 XML TOOL CALL PARSING

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      GLM-4 XML TOOL CALL HANDLING                            │
│                     (_parse_xml_tool_calls in extraction_graph.py)           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Problem: GLM-4 outputs tool calls in XML format, not native function calls│
│                                                                              │
│   GLM-4 Output Format:                                                      │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  <tool_call>get_paper_content</tool_call>                            │   │
│   │  <tool_call>save_evidence_items(items=[{...}, {...}])</tool_call>    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Solution: Parse XML and convert to LangChain tool call format             │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  def _parse_xml_tool_calls(content: str) -> List[Dict]:              │   │
│   │      # Pattern 1: <tool_call>name</tool_call>                        │   │
│   │      # Pattern 2: <tool_call>name(arg=value)</tool_call>             │   │
│   │      # Pattern 3: <tool_call>{"name": "...", "arguments": {}}</tool_call>│
│   │                                                                       │   │
│   │      Returns: [{"name": "tool_name", "args": {...}, "id": "..."}]    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Integration in _run_agent_with_tools():                                   │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  response = llm.invoke(messages)                                     │   │
│   │                                                                       │   │
│   │  # First try native tool_calls                                       │   │
│   │  tool_calls = response.tool_calls                                    │   │
│   │                                                                       │   │
│   │  # If empty, parse XML from content                                  │   │
│   │  if not tool_calls and response.content:                             │   │
│   │      tool_calls = _parse_xml_tool_calls(response.content)            │   │
│   │                                                                       │   │
│   │  # Execute parsed tool calls                                         │   │
│   │  for call in tool_calls:                                             │   │
│   │      result = tool.invoke(call["args"])                              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. ACTUAL TEST RUN FLOW (PMID_11050000)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ACTUAL EXECUTION FLOW (from test results)                 │
│                           Duration: 344.23 seconds                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ═══════════════════════════════════════════════════════════════════════   │
│   PHASE 1: READER                                                            │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│   Input:  PMID_11050000.pdf (6 pages, limited to 4)                         │
│   Model:  Qwen3-VL-235B via Fireworks API                                   │
│                                                                              │
│   [15:50:06] Rendering 4 pages from PDF                                     │
│   [15:50:06] Running Reader graph with 4 images                             │
│   [15:53:41] HTTP POST → 200 OK                                             │
│   [15:53:41] Reader calling tool: save_paper_content                        │
│                                                                              │
│   Output: paper_content_text = 23,951 characters                            │
│                                                                              │
│   ═══════════════════════════════════════════════════════════════════════   │
│   PHASE 2: EXTRACTION                                                        │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  PLANNER                                                             │   │
│   │  [15:53:51] Planner iteration 1                                      │   │
│   │  [15:53:52] Parsed 1 XML tool call: get_paper_content                │   │
│   │  [15:54:16] Planner completed (created extraction_plan)              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  EXTRACTOR                                                           │   │
│   │  [15:54:16] Extractor iteration 1                                    │   │
│   │  [15:54:17] Parsed 2 XML: get_paper_content, get_extraction_plan     │   │
│   │  [15:54:27] check_actionability × 3 calls                            │   │
│   │  [15:54:41] validate_evidence_item × 2 calls                         │   │
│   │  [15:54:47] save_evidence_items → 2 items saved                      │   │
│   │  [15:54:53] Extractor completed                                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  CRITIC                                                              │   │
│   │  [15:54:53] Critic iteration 1                                       │   │
│   │  [15:54:54] Parsed 3 XML: get_paper_content, get_extraction_plan,    │   │
│   │                           get_draft_extractions                       │   │
│   │  [15:55:12] save_critique → APPROVE                                  │   │
│   │  [15:55:16] Critic completed                                         │   │
│   │                                                                       │   │
│   │  Route: assessment=APPROVE → proceed to Normalizer                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                             │                                                │
│                             ▼                                                │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │  NORMALIZER                                                          │   │
│   │  [15:55:16] Normalizer iteration 1                                   │   │
│   │  [15:55:17] get_draft_extractions                                    │   │
│   │  [15:55:20] lookup_gene_entrez × 3 (p53→7157, N-ras→4893, K-ras→3845)│   │
│   │  [15:55:22] lookup_efo, lookup_disease_doid (myeloma→DOID:9538)      │   │
│   │  [15:55:24-34] lookup_rxnorm, lookup_therapy_ncit, lookup_safety_profile│
│   │                × 3 therapies (doxorubicin, melphalan, dexamethasone)  │   │
│   │  [15:55:36-39] lookup_variant_info × 6 calls                         │   │
│   │  [15:55:49] save_evidence_items → 2 items with IDs                   │   │
│   │  [15:55:50] finalize_extraction → is_complete=True                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   ═══════════════════════════════════════════════════════════════════════   │
│   FINAL OUTPUT                                                               │
│   ═══════════════════════════════════════════════════════════════════════   │
│                                                                              │
│   Evidence Items: 2                                                          │
│   Items by Type: {"PREDICTIVE": 2}                                          │
│   Critique: APPROVE                                                          │
│   Iterations Used: 0 (no revisions needed)                                  │
│   Average Tier1 Coverage: 85%                                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 8. FILE STRUCTURE

```
langgraph_migration/
├── pyproject.toml              # uv project config (Python 3.12, LangGraph deps)
├── .env                        # Fireworks API key, model settings
│
├── client.py                   # Main entry point (CivicExtractionClient)
│
├── graphs/
│   ├── __init__.py
│   ├── state.py                # ExtractionGraphState, EvidenceProvenance TypedDicts
│   ├── prompts.py              # System prompts with provenance requirements
│   ├── reader_graph.py         # Phase 1: Vision → Text
│   └── extraction_graph.py     # Phase 2: Planner→Extractor→Critic→Normalizer
│
├── runtime/
│   ├── __init__.py
│   ├── llm.py                  # LLM factory with retry wrapper integration
│   ├── checkpointing.py        # InMemorySaver factory
│   ├── retry.py                # Retry policies + circuit breaker pattern
│   ├── visualization.py        # Mermaid diagrams + state history analytics
│   └── map_reduce.py           # Parallel normalization with ordering preservation
│
├── config/
│   ├── __init__.py
│   └── settings.py             # FIREWORKS_API_KEY, model names, MAX_PAGES
│
├── tools/
│   ├── __init__.py
│   ├── context.py              # ToolContext for state access
│   ├── tool_registry.py        # get_*_tools() functions
│   ├── paper_content_tools.py  # save_paper_content, get_paper_content
│   ├── extraction_tools.py     # save_extraction_plan, save_evidence_items, etc.
│   ├── validation_tools.py     # validate_evidence_item, check_actionability
│   ├── normalization_tools.py  # lookup_* tools for external APIs
│   └── schemas.py              # TIER_1_FIELDS, REQUIRED_FIELDS
│
├── hooks/
│   ├── __init__.py
│   └── logging_callbacks.py    # LangChain BaseCallbackHandler for tool/chain logging
│
├── scripts/
│   └── run_extraction.py       # CLI entry point
│
└── test/
    ├── run_full_pipeline_test.py
    ├── test_e2e_with_new_features.py
    └── e2e_outputs/            # Test run artifacts
```

---

## 9. KEY LANGGRAPH PATTERNS USED

| Pattern | LangGraph Feature | Location |
|---------|------------------|----------|
| State Management | `StateGraph(ExtractionGraphState)` | extraction_graph.py:480 |
| Node Definition | `graph.add_node("planner", planner_node)` | extraction_graph.py:483 |
| Edge Definition | `graph.add_edge(START, "planner")` | extraction_graph.py:489 |
| Conditional Routing | `graph.add_conditional_edges("critic", route_after_critic)` | extraction_graph.py:494 |
| Message Accumulation | `Annotated[list, add_messages]` | state.py:75 |
| Checkpointing | `InMemorySaver()` | checkpointing.py |
| Tool Binding | `llm.bind_tools(tools)` | extraction_graph.py |
| Callbacks | `BaseCallbackHandler` | logging_callbacks.py |

---

## 10. EXTRACTED EVIDENCE ITEMS (Actual Output)

### Item 1: p53 wild-type
```json
{
  "feature_names": ["p53"],
  "variant_names": ["wild-type"],
  "disease_name": "multiple myeloma",
  "evidence_type": "PREDICTIVE",
  "evidence_level": "C",
  "clinical_significance": "Drug resistance",
  "therapy_names": ["doxorubicin", "melphalan"],
  "gene_entrez_ids": ["7157"],
  "disease_doid": "DOID:9538",
  "therapy_rxcuis": ["3639", "6718"]
}
```

### Item 2: N-ras12/K-ras12
```json
{
  "feature_names": ["N-ras", "K-ras"],
  "variant_names": ["N-ras12", "K-ras12"],
  "disease_name": "multiple myeloma",
  "evidence_type": "PREDICTIVE",
  "evidence_level": "C",
  "clinical_significance": "Drug resistance",
  "therapy_names": ["dexamethasone", "doxorubicin", "melphalan"],
  "gene_entrez_ids": ["4893", "3845"],
  "disease_doid": "DOID:9538",
  "therapy_rxcuis": ["3264", "3639", "6718"]
}
```

---

## 11. ENHANCED RUNTIME FEATURES

### 11.1 Retry with Circuit Breaker (runtime/retry.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        RETRY + CIRCUIT BREAKER PATTERN                       │
│                              (runtime/retry.py)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   RETRY POLICIES (Pre-configured)                                           │
│   ───────────────────────────────                                           │
│   • "vision": 3 attempts, 5s→10s→20s delays (for Qwen3-VL)                 │
│   • "llm": 3 attempts, 2s→4s→8s delays (for GLM-4 text)                    │
│   • "normalization": 2 attempts, 1s→2s delays (for API lookups)            │
│                                                                              │
│   CIRCUIT BREAKER STATES                                                    │
│   ─────────────────────────                                                 │
│   ┌──────────┐    5 failures    ┌──────────┐   timeout    ┌────────────┐   │
│   │  CLOSED  │ ───────────────▶ │   OPEN   │ ──────────▶  │ HALF_OPEN  │   │
│   │ (normal) │                  │ (reject) │              │  (test)    │   │
│   └──────────┘                  └──────────┘              └────────────┘   │
│        ▲                                                        │          │
│        │                          success                       │          │
│        └────────────────────────────────────────────────────────┘          │
│                                                                              │
│   USAGE                                                                      │
│   ─────                                                                      │
│   from runtime.llm import get_llm                                           │
│                                                                              │
│   # Retry enabled by default                                                │
│   llm = get_llm(enable_retry=True, retry_policy="llm")                     │
│                                                                              │
│   # Get statistics                                                          │
│   from runtime.llm import get_llm_retry_stats                              │
│   stats = get_llm_retry_stats()                                            │
│   # {"total_calls": 42, "total_retries": 3, "circuit_breaker_trips": 0}    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.2 Graph Visualization (runtime/visualization.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VISUALIZATION FEATURES                                │
│                         (runtime/visualization.py)                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   MERMAID DIAGRAM GENERATION                                                │
│   ──────────────────────────                                                │
│   from runtime.visualization import save_graph_visualization                │
│   from graphs.extraction_graph import build_extraction_graph                │
│                                                                              │
│   graph = build_extraction_graph()                                          │
│   save_graph_visualization(graph, "extraction_graph.md")                    │
│                                                                              │
│   Output:                                                                   │
│   ```mermaid                                                                │
│   graph TD                                                                  │
│       __start__ --> planner                                                 │
│       planner --> extractor                                                 │
│       extractor --> critic                                                  │
│       critic --> normalizer                                                 │
│       critic --> extractor                                                  │
│       normalizer --> __end__                                                │
│   ```                                                                       │
│                                                                              │
│   STATE HISTORY ACCESS                                                      │
│   ────────────────────                                                      │
│   from runtime.visualization import get_state_history, get_execution_analytics│
│                                                                              │
│   history = get_state_history(graph, "paper_123")                          │
│   analytics = get_execution_analytics(history, "paper_123")                │
│                                                                              │
│   # analytics.total_steps, analytics.nodes_visited,                        │
│   # analytics.duration_seconds, analytics.iterations_used                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 11.3 Parallel Normalization (runtime/map_reduce.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MAP-REDUCE NORMALIZATION                              │
│                           (runtime/map_reduce.py)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   PROBLEM: Sequential API calls for entity normalization are slow           │
│   SOLUTION: Parallel lookups with ordering preservation                     │
│                                                                              │
│   WORKFLOW                                                                  │
│   ────────                                                                  │
│   ┌───────────────────────────────────────────────────────────────────┐    │
│   │  MAP PHASE                                                         │    │
│   │  ──────────                                                        │    │
│   │  Extract tasks from evidence items:                                │    │
│   │  Item 0: [gene:BRAF, disease:Melanoma, therapy:Vemurafenib]       │    │
│   │  Item 1: [gene:EGFR, disease:Lung Cancer, therapy:Erlotinib]      │    │
│   └───────────────────────────────────────────────────────────────────┘    │
│                              │                                              │
│                              ▼                                              │
│   ┌───────────────────────────────────────────────────────────────────┐    │
│   │  PROCESS PHASE (Parallel with Semaphore)                          │    │
│   │  ──────────────────────────────────────                           │    │
│   │  max_concurrency=5 (configurable)                                 │    │
│   │                                                                    │    │
│   │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐ │    │
│   │  │lookup_  │  │lookup_  │  │lookup_  │  │lookup_  │  │lookup_  │ │    │
│   │  │gene_    │  │disease_ │  │therapy_ │  │gene_    │  │disease_ │ │    │
│   │  │entrez   │  │doid     │  │ncit     │  │entrez   │  │doid     │ │    │
│   │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └─────────┘ │    │
│   └───────────────────────────────────────────────────────────────────┘    │
│                              │                                              │
│                              ▼                                              │
│   ┌───────────────────────────────────────────────────────────────────┐    │
│   │  REDUCE PHASE                                                      │    │
│   │  ────────────                                                      │    │
│   │  Apply results back to items (ORDER PRESERVED):                   │    │
│   │  Item 0: gene_entrez_ids="673", disease_doid="DOID:1909", ...     │    │
│   │  Item 1: gene_entrez_ids="1956", disease_doid="DOID:1324", ...    │    │
│   └───────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│   USAGE                                                                      │
│   ─────                                                                      │
│   from runtime.map_reduce import normalize_items_parallel                   │
│                                                                              │
│   normalized, stats = await normalize_items_parallel(                       │
│       items=draft_extractions,                                              │
│       max_concurrency=5,                                                    │
│   )                                                                         │
│   # stats: total_tasks=10, successful_tasks=8, tasks_per_second=2.5        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 12. EVIDENCE PROVENANCE (graphs/state.py)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        EvidenceProvenance TypedDict                          │
│                            (graphs/state.py)                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Each evidence item includes provenance metadata for traceability:         │
│                                                                              │
│   class EvidenceProvenance(TypedDict):                                      │
│       # Source Location                                                     │
│       source_pages: list[int]        # [4, 5] - page numbers                │
│       source_section: str            # "Results"                            │
│       figure_table_ref: str          # "Table 2", "Figure 3A"               │
│                                                                              │
│       # Verbatim Quote (CRITICAL)                                           │
│       verbatim_quote: str            # Exact text from paper                │
│       quote_context: str             # Surrounding context                  │
│                                                                              │
│       # Reasoning                                                           │
│       clinical_significance: str     # Why clinically important             │
│       extraction_reasoning: str      # Why included in CIViC                │
│       assumptions: list[str]         # Any interpretations made             │
│                                                                              │
│       # Confidence Assessment                                               │
│       confidence_score: float        # 0.0 to 1.0                           │
│       confidence_level: str          # "low"|"medium"|"high"|"very_high"    │
│       confidence_factors_positive: list[str]  # ["Phase 3 RCT", ...]       │
│       confidence_factors_negative: list[str]  # ["Small sample", ...]      │
│       caveats: list[str]             # Limitations                          │
│                                                                              │
│       # Data Quality                                                        │
│       has_statistics: bool           # p-values, HR, OR present?            │
│       is_direct_statement: bool      # Direct vs inferred                   │
│       sample_size: str               # "675 patients"                       │
│       study_type: str                # "Phase 3 RCT", "case study"          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 13. HUMAN-IN-THE-LOOP (Optional)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        HUMAN-IN-THE-LOOP FEATURE                             │
│                     (extraction_graph.py - COMMENTED OUT)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   LOCATION: graphs/extraction_graph.py (search for "HUMAN-IN-THE-LOOP")    │
│   STATUS: Commented out by default, can be enabled                          │
│                                                                              │
│   HOW IT WORKS                                                              │
│   ────────────                                                              │
│   1. After Critic approves, pipeline pauses                                 │
│   2. Writes review file: {HUMAN_REVIEW_DIR}/{paper_id}_review.json         │
│   3. Waits for human to create: {paper_id}_status.json                     │
│   4. Human sets status to "APPROVED" or "REJECT"                           │
│   5. Pipeline continues or aborts based on status                          │
│                                                                              │
│   TO ENABLE                                                                 │
│   ─────────                                                                 │
│   1. Uncomment the human_review_node function                               │
│   2. Uncomment graph.add_node("human_review", human_review_node)           │
│   3. Modify route_after_critic to route to "human_review"                  │
│                                                                              │
│   ALTERNATIVE: LangGraph interrupt_before/interrupt_after                   │
│   (Also documented in the commented code)                                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

*Generated from actual codebase and test runs. Last updated: 2026-01-12*
