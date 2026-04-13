# Claude Agent SDK vs LangGraph Migration - Side-by-Side Comparison

## FIXES IMPLEMENTED (2026-01-12)

| Issue | Original Status | Current Status | Fix Applied |
|-------|-----------------|----------------|-------------|
| **MAX_PAGES** | 4 pages only | ✅ 20 pages | Updated `config/settings.py` |
| **Page Chunking** | All at once | ✅ 2 pages per chunk | Updated `reader_graph.py` with acknowledgment protocol |
| **Thinking Tokens** | Not explicit | ✅ Qwen3-VL-thinking model | Using `-thinking` model variant with recommended params |
| **Full Context** | ✓ Works | ✓ Works | No change needed |

### Latest Test Run (2026-01-12)
```
Paper: PMID_11050000 (6 pages)
Chunks processed: 3 (pages 1-2, 3-4, 5-6)
Paper content extracted: 30,010 chars
Final extractions: 2 evidence items
Pipeline: Planner → Extractor → Critic → Normalizer ✅
```

---

## Executive Summary of Original Issues

| Issue | Claude Agent SDK | LangGraph Migration | Impact |
|-------|-----------------|---------------------|--------|
| **Thinking Tokens** | Uses `ThinkingBlock` (Claude native) | ✅ Using Qwen3-VL-thinking | Fixed - model has reasoning |
| **Reader Page Processing** | Chunks 2 pages at a time | ✅ Chunks 2 pages (CHUNK_SIZE=2) | Fixed - matches original |
| **MAX_PAGES** | 20 pages | ✅ 20 pages | Fixed - increased from 4 |
| **Orchestrator Pattern** | Uses `Task` tool to delegate | Direct node execution | Different but functional |
| **Subagent Architecture** | True subagents via `AgentDefinition` | Separate graph nodes | Different but functional |
| **Context Passing** | Via MCP Server shared tools | Via ToolContext thread-local | Should work the same |
| **Full Text Passing** | ✓ FULL `paper_content_text` | ✓ FULL `paper_content_text` | OK - Same pattern |

---

## 1. ARCHITECTURE COMPARISON

### Original: Claude Agent SDK
```
┌──────────────────────────────────────────────────────────────────┐
│                     PHASE 1: READER                               │
│                                                                   │
│   PDF → Images (2 per chunk) → Claude Vision                     │
│                                  │                                │
│                                  ▼                                │
│                          save_paper_content                       │
│                                  │                                │
│                                  ▼                                │
│                         CIViCContext.paper_content                │
└──────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                   PHASE 2: ORCHESTRATOR                           │
│                                                                   │
│   Orchestrator (Root Agent)                                       │
│        │                                                          │
│        │ uses Task tool to delegate                               │
│        │                                                          │
│        ├───▶ Task(subagent_type="planner") ───▶ PLANNER          │
│        │                                                          │
│        ├───▶ Task(subagent_type="extractor") ──▶ EXTRACTOR       │
│        │                                                          │
│        ├───▶ Task(subagent_type="critic") ────▶ CRITIC           │
│        │                                                          │
│        └───▶ Task(subagent_type="normalizer") ─▶ NORMALIZER      │
│                                                                   │
│   Each subagent:                                                  │
│   - Has its OWN AgentDefinition with prompt + tools               │
│   - Runs in a separate context                                    │
│   - Returns result to Orchestrator                                │
└──────────────────────────────────────────────────────────────────┘
```

### LangGraph Migration (UPDATED)
```
┌──────────────────────────────────────────────────────────────────┐
│                     READER GRAPH (StateGraph)                     │
│                                                                   │
│   PDF → Images (up to 20 pages) → Qwen3-VL-Thinking Vision       │
│                                  │                                │
│                                  ▼                                │
│                    ┌─────────────────────────┐                   │
│                    │ CHUNK 1 (pages 1-2)     │                   │
│                    │ "Read, DO NOT extract"  │                   │
│                    │ LLM: "ACKNOWLEDGED"     │                   │
│                    └────────────┬────────────┘                   │
│                                 ▼                                 │
│                    ┌─────────────────────────┐                   │
│                    │ CHUNK 2 (pages 3-4)     │                   │
│                    │ "Read, DO NOT extract"  │                   │
│                    │ LLM: "ACKNOWLEDGED"     │                   │
│                    └────────────┬────────────┘                   │
│                                 ▼                                 │
│                    ┌─────────────────────────┐                   │
│                    │ CHUNK N (last pages)    │                   │
│                    │ "Extract ALL now"       │                   │
│                    │ LLM: save_paper_content │                   │
│                    └────────────┬────────────┘                   │
│                                 ▼                                 │
│                         state["paper_content"]                    │
└──────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────┐
│                 EXTRACTION GRAPH (StateGraph)                     │
│                                                                   │
│   START ──▶ planner_node ──▶ extractor_node ──▶ critic_node      │
│                                                       │           │
│                                    ┌──────────────────┤           │
│                                    │                  │           │
│                                    ▼                  ▼           │
│                              extractor_node    normalizer_node    │
│                              (if NEEDS_REV)         │             │
│                                                     │             │
│                                                     ▼             │
│                                                    END            │
│                                                                   │
│   Each node:                                                      │
│   - Is a Python function                                          │
│   - Has its own LLM instance + tools                              │
│   - Updates shared state directly                                 │
│   - NO orchestrator delegation                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. READER PHASE COMPARISON

| Aspect | Claude Agent SDK | LangGraph Migration | Status |
|--------|-----------------|---------------------|--------|
| **Model** | Claude Vision (Anthropic) | Qwen3-VL-235B-thinking (Fireworks) | Different model, both vision capable |
| **Page Chunking** | 2 pages per turn with acknowledgment | ✅ 2 pages per turn (CHUNK_SIZE=2) | ✅ FIXED |
| **Max Pages** | 20 pages | ✅ 20 pages (MAX_PAGES=20) | ✅ FIXED |
| **Thinking/Reasoning** | ThinkingBlock (Claude native) | ✅ Qwen3-VL-thinking model | ✅ FIXED |
| **Chunk Protocol** | "Received Part N" acknowledgment | ✅ "ACKNOWLEDGED" response | ✅ FIXED |
| **Image Format** | `{"type": "image", "source": {"type": "base64"}}` | `{"type": "image_url", "image_url": {"url": "data:..."}}` | Format difference (both work) |

### Claude Agent SDK Reader (Original)
```python
# client.py lines 457-517
CHUNK_SIZE = 2

for i in range(0, len(images), CHUNK_SIZE):
    chunk = images[i:i+CHUNK_SIZE]
    is_last_chunk = (i + CHUNK_SIZE) >= len(images)

    if i == 0:
        # First chunk: "Read but DO NOT extract yet"
        text = f"Part {i//CHUNK_SIZE + 1}. Read these pages but DO NOT extract yet."
    elif not is_last_chunk:
        # Middle chunk: "Read but DO NOT extract yet"
        text = f"Part {i//CHUNK_SIZE + 1}. Read these pages but DO NOT extract yet."
    else:
        # Last chunk: "Now extract ALL"
        text = "Now you have all pages. Extract ALL and call save_paper_content IMMEDIATELY."

    # Send chunk and wait for acknowledgment
    await client.query(message_generator())
    async for message in client.receive_response():
        await self._process_message(message, "Reader")
```

### LangGraph Reader (Migration)
```python
# reader_graph.py
def reader_node(state: ExtractionGraphState) -> Dict[str, Any]:
    llm = get_reader_llm()  # Qwen3-VL
    tools = get_reader_tools()

    # Get page images from state (ALL AT ONCE)
    page_images = state.get("page_images", [])

    # Build message with ALL images
    message_content = [{"type": "text", "text": "Extract content from these pages..."}]
    message_content.extend(page_images)  # ALL images at once

    # Single invocation
    response = llm.invoke(messages)  # No chunking!
```

**ISSUE**: LangGraph sends all pages at once instead of chunking 2 at a time.

---

## 3. THINKING TOKENS COMPARISON

| Aspect | Claude Agent SDK | LangGraph Migration | Issue? |
|--------|-----------------|---------------------|--------|
| **Thinking Support** | Native `ThinkingBlock` | NOT implemented | **MISSING** |
| **How it works** | Claude outputs `<thinking>` blocks | GLM-4 needs explicit `enable_thinking=True` | Need to enable |

### Claude Agent SDK (Original)
```python
# client.py line 548
elif isinstance(block, ThinkingBlock):
    if block.thinking:
        logger.info(f"[{phase}] [THINKING] {block.thinking[:300]}...")
```

Claude automatically produces thinking blocks for complex reasoning.

### LangGraph Migration - NOT USING THINKING
```python
# llm.py - Current implementation
def get_llm(...) -> BaseChatModel:
    return ChatOpenAI(
        api_key=FIREWORKS_API_KEY,
        base_url=FIREWORKS_BASE_URL,
        model=FIREWORKS_MODEL_NAME,  # GLM-4
        # NO thinking parameter!
    )
```

**ISSUE**: GLM-4 via Fireworks may support `enable_thinking=True` but we're not using it.

---

## 4. ORCHESTRATOR / DELEGATION COMPARISON

| Aspect | Claude Agent SDK | LangGraph Migration | Issue? |
|--------|-----------------|---------------------|--------|
| **Pattern** | Orchestrator delegates via `Task` tool | Direct graph edges | Different flow |
| **Subagents** | True `AgentDefinition` objects | Python functions | No delegation |
| **Decision Making** | Orchestrator decides next step | `route_after_critic()` function | Hardcoded routing |
| **Dynamic Routing** | Orchestrator can choose any agent | Fixed: Planner→Extractor→Critic→Normalizer | Less flexible |

### Claude Agent SDK (Original)
```python
# client.py lines 76-108
ORCHESTRATOR_SYSTEM_PROMPT = """You are the Orchestrator coordinating evidence extraction.

### Step 1: PLANNER
Delegate to "planner":
- Planner calls get_paper_content
- Planner creates extraction strategy

### Step 2: EXTRACTOR
Delegate to "extractor":
...

### Iteration
If NEEDS_REVISION: increment_iteration → Extractor → Critic
"""

# Orchestrator uses Task tool to delegate
options = ClaudeAgentOptions(
    agents={
        "planner": PLANNER_AGENT,
        "extractor": EXTRACTOR_AGENT,
        "critic": CRITIC_AGENT,
        "normalizer": NORMALIZER_AGENT,
    },
    allowed_tools=["Task", ...],  # Task tool for delegation!
)
```

### LangGraph Migration
```python
# extraction_graph.py
def build_extraction_graph():
    graph = StateGraph(ExtractionGraphState)

    # No orchestrator - direct edges
    graph.add_edge(START, "planner")  # Fixed order
    graph.add_edge("planner", "extractor")
    graph.add_edge("extractor", "critic")
    graph.add_conditional_edges("critic", route_after_critic)
    graph.add_edge("normalizer", END)
```

**DIFFERENCE**: Original has dynamic Orchestrator that decides. LangGraph has fixed graph edges.

---

## 5. TOOLS PER AGENT - EXACT COMPARISON

### Reader Tools
| Tool | Claude SDK | LangGraph | Match? |
|------|------------|-----------|--------|
| `save_paper_content` | ✓ | ✓ | ✓ |
| `get_paper_info` | ✓ | ✓ | ✓ |
| `read_paper_page` | ✓ | ✓ | ✓ |
| **Total** | **3** | **3** | ✓ |

### Planner Tools
| Tool | Claude SDK | LangGraph | Match? |
|------|------------|-----------|--------|
| `get_paper_info` | ✓ | ✓ | ✓ |
| `get_paper_content` | ✓ | ✓ | ✓ |
| `save_extraction_plan` | ✓ | ✓ | ✓ |
| **Total** | **3** | **3** | ✓ |

### Extractor Tools
| Tool | Claude SDK | LangGraph | Match? |
|------|------------|-----------|--------|
| `get_paper_info` | ✓ | ✓ | ✓ |
| `get_paper_content` | ✓ | ✓ | ✓ |
| `get_extraction_plan` | ✓ | ✓ | ✓ |
| `get_draft_extractions` | ✓ | ✓ | ✓ |
| `check_actionability` | ✓ | ✓ | ✓ |
| `validate_evidence_item` | ✓ | ✓ | ✓ |
| `save_evidence_items` | ✓ | ✓ | ✓ |
| **Total** | **7** | **7** | ✓ |

### Critic Tools
| Tool | Claude SDK | LangGraph | Match? |
|------|------------|-----------|--------|
| `get_paper_info` | ✓ | ✓ | ✓ |
| `get_paper_content` | ✓ | ✓ | ✓ |
| `get_extraction_plan` | ✓ | ✓ | ✓ |
| `get_draft_extractions` | ✓ | ✓ | ✓ |
| `check_actionability` | ✓ | ✓ | ✓ |
| `validate_evidence_item` | ✓ | ✓ | ✓ |
| `save_critique` | ✓ | ✓ | ✓ |
| `increment_iteration` | ✓ | ✓ | ✓ |
| **Total** | **8** | **8** | ✓ |

### Normalizer Tools
| Tool | Claude SDK | LangGraph | Match? |
|------|------------|-----------|--------|
| `get_draft_extractions` | ✓ | ✓ | ✓ |
| `save_evidence_items` | ✓ | ✓ | ✓ |
| `finalize_extraction` | ✓ | ✓ | ✓ |
| `lookup_rxnorm` | ✓ | ✓ | ✓ |
| `lookup_efo` | ✓ | ✓ | ✓ |
| `lookup_safety_profile` | ✓ | ✓ | ✓ |
| `lookup_gene_entrez` | ✓ | ✓ | ✓ |
| `lookup_variant_info` | ✓ | ✓ | ✓ |
| `lookup_therapy_ncit` | ✓ | ✓ | ✓ |
| `lookup_disease_doid` | ✓ | ✓ | ✓ |
| `lookup_clinical_trial` | ✓ | ✓ | ✓ |
| `lookup_hpo` | ✓ | ✓ | ✓ |
| `lookup_pmcid` | ✓ | ✓ | ✓ |
| **Total** | **13** | **13** | ✓ |

**TOOLS MATCH** ✓

---

## 6. CONTEXT PASSING COMPARISON

| Aspect | Claude SDK | LangGraph | Match? |
|--------|------------|-----------|--------|
| **Full paper_content_text** | ✓ Returns full ~10-50KB | ✓ Returns full text | ✓ |
| **Storage** | `CIViCContext.paper_content_text` | `state["paper_content_text"]` | ✓ |
| **Access Pattern** | `get_current_context()` | `get_context()` (thread-local) | Similar |

### Claude SDK Context (Original)
```python
# context/civic_context.py
class CIViCContext:
    paper_content: dict = None
    paper_content_text: str = ""  # FULL text
    extraction_plan: dict = None
    draft_extractions: list = []
    critique: dict = None
```

### LangGraph Context (Migration)
```python
# tools/context.py
class ToolContext:
    paper_id: str = ""
    paper_content: dict = {}
    paper_content_text: str = ""  # FULL text
    extraction_plan: dict = {}
    draft_extractions: list = []
    critique: dict = {}
```

**CONTEXT PATTERN MATCHES** ✓ - Both pass full text.

---

## 7. POTENTIAL CAUSES OF REDUCED EXTRACTION (2 items vs ?)

### Issue 1: Reader Not Extracting All Content
| Cause | Evidence | Fix |
|-------|----------|-----|
| Only 4 pages processed | `MAX_PAGES = 4` due to timeout | Increase or chunk pages |
| Vision model difference | Qwen3-VL vs Claude Vision | Different extraction quality |
| No chunking protocol | All images at once | Implement 2-page chunking |

### Issue 2: No Thinking Tokens
| Cause | Evidence | Fix |
|-------|----------|-----|
| GLM-4 not "thinking" | No `ThinkingBlock` equivalent | Enable `enable_thinking=True` if supported |
| Less reasoning | Model may not analyze deeply | Use thinking parameter |

### Issue 3: Planner Not Saving Plan
| Cause | Evidence | Fix |
|-------|----------|-----|
| Model outputs plan as text | `extraction_plan: {}` in results | Already added explicit prompt |
| XML parsing incomplete | May miss some tool calls | Check XML patterns |

### Issue 4: Missing Orchestrator Intelligence
| Cause | Evidence | Fix |
|-------|----------|-----|
| No Orchestrator agent | Fixed graph flow | Orchestrator could make smarter decisions |
| No dynamic routing | Can't skip agents | Add Orchestrator node |

---

## 8. PROMPTS COMPARISON

### Reader Prompt
**Claude SDK (Original)**: `READER_SYSTEM_PROMPT` in client.py lines 40-73
**LangGraph**: Copied exactly to `prompts.py`
**Match**: ✓ YES

### Planner Prompt
**Claude SDK (Original)**: `PLANNER_AGENT.prompt` in client.py lines 159-180
**LangGraph**: Copied to `prompts.py` + added mandatory tool instruction
**Match**: ✓ YES (with addition)

### Extractor Prompt
**Claude SDK (Original)**: `EXTRACTOR_AGENT.prompt` in client.py lines 191-237
**LangGraph**: Copied to `prompts.py` + added mandatory tool instruction
**Match**: ✓ YES (with addition)

### Critic Prompt
**Claude SDK (Original)**: `CRITIC_AGENT.prompt` in client.py lines 253-288
**LangGraph**: Copied to `prompts.py`
**Match**: ✓ YES

### Normalizer Prompt
**Claude SDK (Original)**: `NORMALIZER_AGENT.prompt` in client.py lines 113-137
**LangGraph**: Copied to `prompts.py`
**Match**: ✓ YES

---

## 9. RECOMMENDED FIXES

### Priority 1: Enable Page Chunking in Reader
```python
# reader_graph.py - PROPOSED FIX
async def reader_node(state):
    page_images = state["page_images"]
    CHUNK_SIZE = 2

    for i in range(0, len(page_images), CHUNK_SIZE):
        chunk = page_images[i:i+CHUNK_SIZE]
        is_last = (i + CHUNK_SIZE) >= len(page_images)

        if is_last:
            prompt = "Final pages. Now extract ALL content and call save_paper_content."
        else:
            prompt = f"Part {i//CHUNK_SIZE + 1}. Read and acknowledge."

        response = llm.invoke([...chunk...])
```

### Priority 2: Enable GLM-4 Thinking (if supported)
```python
# llm.py - PROPOSED FIX
def get_llm(...):
    return ChatOpenAI(
        ...
        model_kwargs={"enable_thinking": True}  # If Fireworks supports
    )
```

### Priority 3: Increase MAX_PAGES
```python
# settings.py
MAX_PAGES = 10  # Increase from 4
```

### Priority 4: Add Orchestrator Node (Optional)
```python
# extraction_graph.py - PROPOSED FIX
def orchestrator_node(state):
    """Smart routing based on state."""
    if not state.get("extraction_plan"):
        return {"next": "planner"}
    elif not state.get("draft_extractions"):
        return {"next": "extractor"}
    elif not state.get("critique"):
        return {"next": "critic"}
    else:
        return {"next": "normalizer"}
```

---

## 10. FILES COMPARISON TABLE

| Component | Claude SDK Path | LangGraph Path | Status |
|-----------|----------------|----------------|--------|
| Main Client | `client.py` | `langgraph_migration/client.py` | Different architecture |
| Tool Registry | `tool_registry.py` | `langgraph_migration/tools/tool_registry.py` | ✓ Migrated |
| Paper Tools | `tools/paper_tools.py` | `langgraph_migration/tools/paper_tools.py` | ✓ Migrated |
| Paper Content Tools | `tools/paper_content_tools.py` | `langgraph_migration/tools/paper_content_tools.py` | ✓ Migrated |
| Extraction Tools | `tools/extraction_tools.py` | `langgraph_migration/tools/extraction_tools.py` | ✓ Migrated |
| Validation Tools | `tools/validation_tools.py` | `langgraph_migration/tools/validation_tools.py` | ✓ Migrated |
| Normalization Tools | `tools/normalization_tools.py` | `langgraph_migration/tools/normalization_tools.py` | ✓ Migrated |
| Context | `context/civic_context.py` | `langgraph_migration/tools/context.py` | ✓ Migrated |
| State | `context/state.py` | `langgraph_migration/graphs/state.py` | ✓ Migrated |
| Prompts | (in client.py) | `langgraph_migration/graphs/prompts.py` | ✓ Extracted |
| Reader Graph | (embedded in client.py) | `langgraph_migration/graphs/reader_graph.py` | **NEW** |
| Extraction Graph | (embedded in client.py) | `langgraph_migration/graphs/extraction_graph.py` | **NEW** |
| LLM Factory | (uses ClaudeSDKClient) | `langgraph_migration/runtime/llm.py` | **NEW** |
| Checkpointing | (uses Claude SDK) | `langgraph_migration/runtime/checkpointing.py` | **NEW** |
| Hooks/Callbacks | `hooks/logging_hooks.py` | `langgraph_migration/hooks/logging_callbacks.py` | ✓ Migrated |

---

## Summary

**What's Working:**
- ✓ Tool assignments match (3, 3, 7, 8, 13)
- ✓ Prompts are preserved
- ✓ Full context passing
- ✓ XML tool call parsing for GLM-4
- ✓ Normalization lookups

**What's Different/Issues:**
1. **Reader chunking** - Original chunks 2 pages at a time, we send all at once
2. **Thinking tokens** - Not using GLM-4's thinking capability
3. **Orchestrator pattern** - No Task-based delegation
4. **MAX_PAGES** - Limited to 4 due to timeout
5. **Model capabilities** - Qwen3-VL vs Claude Vision for reading

**Root Cause of 2 Items (likely):**
The Reader is only processing 4 pages (vs up to 20), so it may be missing content from later pages. Additionally, without thinking tokens, the model may not reason as deeply about what constitutes evidence.
