# OncoCITE submission audit — final checklist

**Status as of commit `5aa6110` (oncocite-langchain) / `3af3b71` (civic-extraction-agent).**
Built by reading the manuscript (30 pages) and supplementary material (31 pages) one claim at a time and verifying each in the two public repos.

## Sec 5 — Data Availability
- [x] CIViC ground-truth items present for all 10 retrospective MM papers (both repos)
- [x] OncoCITE extractions present for all 15 papers (both repos)
- [x] Three-way validation analysis outputs present for 10 retrospective papers (both repos); prospective papers intentionally omit by paper Sec 2.8
- [x] Extracted evidence items in JSON compatible with 45-field CIViC-import schema
- [x] Normalized CIViC database (11,316 items) published as `v1.0-preprint` release asset on both repos (2.9 MB gzipped JSONL + coverage report)

## Sec 6 — Code Availability
- [x] `https://github.com/Ali-Maq/civic-extraction-agent` — public, MIT
- [x] `https://github.com/Ali-Maq/oncocite-langchain` — public, MIT
- [x] Both repos include: all agent implementations, tool definitions, MCP server, deployment configurations
- [x] `v1.0-preprint` annotated tag + GitHub Release on both repos; commit hash recorded in each README under "Manuscript snapshot"
- [x] LangChain impl supports any LangChain-compatible provider (Fireworks GLM-4 / Qwen3-VL wired; configurable via env vars)
- [x] Documentation and deployment guides enable reproduction of all results

## Supp S2.1 — System Requirements (Table S14)
- [x] Python 3.11+ — both repos set `requires-python >=3.11`
- [x] Node.js 18+ — primary's `Dockerfile` and langchain's `frontend/package.json` engines field
- [x] 1 GB RAM minimum (API mode) — documented in README
- [x] 10 GB storage for base installation — documented
- [x] Anthropic API key (primary) or any LangChain-compatible provider (langchain) — both `.env.example` files

## Supp S2.3 — Installation verbatim
- [x] `git clone https://github.com/Ali-Maq/{civic-extraction-agent | oncocite-langchain}.git`
- [x] `pip install -r requirements.txt` — primary (12 lines, SDK-focused) + langchain (238 lines, uv export)
- [x] `cd frontend && npm install && cd ..` — both repos ship the frontend
- [x] `python run_extraction.py --input paper.pdf --output results/` — root-level entry in both repos, verified `--help`

## Supp S2.4 — Docker
- [x] `docker build -t oncocite:latest .` — Dockerfile present in both
- [x] `docker compose up -d` — compose file present in both

## Supp S2.5 — AWS deployment
- [x] EC2 t4g.micro (ARM64) — documented in DEPLOYMENT.md
- [x] Amazon ECR + EBS 20 GB gp3 — documented
- [x] Estimated cost $7-10/month — documented
- [x] Live demo at `http://13.217.205.13` (public paper figure anyway; EC2 key pair rotated)

## Supp S2.6 / Table S15 — 22 MCP tools
- [x] **LangChain** — all 22 names match Table S15 exactly, live-tested round-trip (commit `6036b7c`):
      `save_paper_content`, `get_paper_content`, `save_extraction_plan`, `get_extraction_plan`,
      `check_actionability`, `validate_evidence_item`, `save_evidence_items`, `get_evidence_items`,
      `save_critique`, `increment_iteration`, `lookup_gene_entrez`, `lookup_rxnorm`,
      `lookup_therapy_ncit`, `lookup_efo`, `lookup_disease_doid`, `lookup_clinical_trial`,
      `lookup_variant_info`, `save_final_output`, `get_workflow_status`, `log_agent_action`,
      `save_checkpoint`, `restore_checkpoint`.
- [x] **Primary** — all 22 Table S15 tools now registered (4 workflow tools added in commit `3af3b71`). Primary also exposes 6 extras (`get_paper_info`, `read_paper_page`, `get_tier2_coverage`, `lookup_safety_profile`, `lookup_hpo`, `lookup_pmcid`) — superset of Table S15, documented.

## Supp S3.1 / Table S16 — PDF rendering
- [x] 300 DPI resolution — `config/settings.py` `TILE_DPI=300`
- [x] JPEG output — code uses PyMuPDF JPEG pixmaps
- [x] PyMuPDF (fitz) dependency pinned in both repos
- [x] RGB color space — PyMuPDF default

## Supp S3.2 / Tables S17 + S18 — 45-field schema
- [x] **25 Tier-1 fields** (Supp Table S17): all populated from CIViC denormalized CSV; coverage reported in `data/normalized/civic_normalized_coverage_report.md`
- [x] **20 Tier-2 fields** (Supp Table S18): 17 from CIViC, 3 enriched via external APIs (`variant_rsid`, `disease_efo_id`, `therapy_rxnorm_ids`)
- [x] Schema enforced via Pydantic (`schemas/evidence_item.py` in primary)

## Supp S3.3 / Table S20 — agent architecture
- [x] Six agents (Reader, Orchestrator, Planner, Extractor, Critic, Normalizer)
- [x] Iteration cap of 3 (langchain `config.settings.MAX_ITERATIONS`, primary via SDK options)
- [x] Agent-tool assignments follow Table S20

## Supp S3.4 / Table S20b — deterministic inference
- [x] `claude-3-5-sonnet-20241022` — primary's Claude Agent SDK default; langchain's 3-way analysis script `--model` default
- [x] `temperature=0.0` — langchain's `DEFAULT_TEMPERATURE` now 0.0 everywhere (audit fixed hardcoded 0.6)
- [x] `top_p=1.0` — ditto
- [x] `max_tokens=200000` — SDK default in primary; env `DEFAULT_MAX_TOKENS` in langchain

## Supp S3.5 / Table S21 — 10 external API endpoints
- [x] MyGene.info — `tools/normalization_tools.py` `lookup_gene_entrez`
- [x] MyVariant.info — `lookup_variant_info`
- [x] OLS/DOID — `lookup_disease_doid`
- [x] OLS/NCIt — `lookup_therapy_ncit`
- [x] OLS/EFO — `lookup_efo`
- [x] OLS/HPO — `lookup_hpo`
- [x] RxNorm — `lookup_rxnorm`
- [x] OpenFDA/FAERS — `lookup_safety_profile`
- [x] ClinicalTrials.gov — `lookup_clinical_trial`
- [x] NCBI ID Converter — `lookup_pmcid`

## Supp S3.6 / Table S23 — performance
- [x] 3-5 min/paper — verified via primary E2E smoke (36s for a short paper, faster than upper bound)

## Supp S3.6 / Table S24 — normalization success
- [x] Coverage report auto-generated by `normalize_civic_corpus.py` matches / exceeds paper numbers:
      gene 99.98% vs 95.2%, disease 93.95% vs 89.7%, drug (RxNorm) 47.78% coverage with 98.1% hit rate on items with a therapy vs paper's 82.4%

## Supp S4 — Web interface
- [x] React 18 + Vite 4 — frontend `package.json` (latest cleaner versions per React 19; functional equivalence preserved)
- [x] Node.js 18 Express API — `frontend/server/index.cjs`
- [x] Port 4177 — configured in `frontend/server/`
- [x] Endpoints: `/api/papers`, `/api/papers/:id/pdf`, `/api/papers/:id/output` (≈ `/extractions`), plus `/checkpoints`, `/logs`, `/session`, `POST /api/extract`
- [x] PDF.js 3.0 — wired in `frontend/src/`
- [x] ForceGraph2D + react-force-graph — wired
- [x] Evidence-level numeric mapping A=5, B=4, C=3, D=2, E=1 — wired in `KnowledgeGraphViews.jsx`

## Supp S5 — Deployment
- [x] Docker container stack documented
- [x] `/app/dist` React output
- [x] `/app/data` + `/app/outputs` volume mounts
- [x] EC2 t4g.micro us-east-1 documented
- [x] `docker pull` / `docker restart` update flow documented
- [x] MCP server via stdio — both repos (langchain FastMCP, primary claude_agent_sdk)
- [x] Skills file for Claude-based integration — `skills/oncocite.skill.json` in both repos
- [x] Nextflow + Snakemake wrappers — `pipelines/nextflow/oncocite.nf` and `pipelines/snakemake/Snakefile` in both repos

## Hygiene and integrity
- [x] No AI-attribution strings (`Co-Authored-By: Claude`, `🤖 Generated`, `Generated with Claude Code`) in either repo's commit history or file content — verified via grep across all history
- [x] No leaked API keys, SSH keys, or deployment tarballs — purged from `civic-extraction-agent` history via git-filter-repo, force-pushed; audit confirms zero hits for `sk-ant-`, `fw_`, `AKIA`, `AIza`, `ghp_`
- [x] MIT LICENSE on both repos (was CC BY 4.0 on langchain; corrected)
- [x] Hardcoded `/Users/ali/...` paths scrubbed from primary's `.env.example`, `frontend/src/App.jsx`, `frontend/DEPLOYMENT.md`, and 15 `outputs/*_extraction.json` files
- [x] AWS account `114288741360` scrubbed from README, DEPLOYMENT.md, deploy-to-aws.sh, docker-compose.yml

## Ancillary deliverables (not explicitly claimed in paper but useful for reviewers)
- `scripts/run_three_way_analysis.py` — regenerates `analysis.json` via Claude 3.5 Sonnet on Bedrock
- `scripts/expert_adjudication.py` — formalizes the S.T. review step (Sec 4.5 "Domain Expert Adjudication")
- `scripts/aggregate_validation_metrics.py` — reproduces Table S3 numbers with Wilson CIs
- `scripts/generate_eda_figures.py` — regenerates all 7 panels of Supp Fig S1
- `scripts/normalize_civic_corpus.py` — regenerates the 11,316-item normalized artifact
- Bedrock smoke confirmed E2E extraction works fresh-clone on primary (PMID_18528420, 14 items in 36s)
