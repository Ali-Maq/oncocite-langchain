# Validation corpus

This directory bundles all 15 papers used for end-to-end validation of
OncoCITE in the manuscript.

## `triplet/` — 10 retrospective Multiple Myeloma papers (CIViC-indexed)

Papers drawn from the CIViC database disease filter for "Multiple Myeloma"
(CIViC v2 API, accessed 2024-12-15). Each paper folder contains:

| File | Purpose |
|---|---|
| `{PMID}.pdf` | Source publication |
| `{PMID}_ground_truth.json` | CIViC curator-labeled evidence items |
| `{PMID}_extraction.json` | OncoCITE system extraction output |
| `analysis.json` | Three-way validation analysis (CIViC × OncoCITE × independent analysis agent) with field-level status, adjudication, and confirmed ground-truth curation errors |

These correspond to **Table S4** in the manuscript (per-paper metrics) and
feed the headline validation numbers reported in Section 2.6: **84.0%
ground-truth recovery**, **97.8% novel-discovery precision**, and **0%
critical-error rate** across 69 extracted items.

## `prospective/` — 5 prospective-application papers (not in CIViC)

Recent high-impact publications (2022–2024) reporting biomarkers for
emerging immunotherapy modalities that have 0% coverage in CIViC as of
December 2024:

| Folder | Publication | Focus |
|---|---|---|
| `s41591-023-02491-5` | Da Vià et al., 2023, Nature Medicine | TNFRSF17 (BCMA) variants and anti-BCMA CAR-T resistance |
| `s43018-023-00625-9` | Derrien et al., 2023, Nature Cancer | GPRC5D resistance mutations to Talquetamab |
| `Dutta_et_al-2024-Blood_Neoplasia` | Dutta et al., 2024, Blood Neoplasia | Venetoclax response biomarkers (BCL2/MCL1, 6-gene signature) |
| `Restrepo_et_al_selinexor` | Restrepo et al., 2022, JCO Precision Oncology | Selinexor response signature |
| `Elnaggar_et_al` | Elnaggar et al., 2022, J Hematol Oncol | Triple MAPK inhibition in BRAF V600E myeloma |

Each folder contains the source PDF, the OncoCITE extraction output
(`*_extraction.json`), and staged pipeline checkpoints (Reader → Planner
→ Extractor → Critic → Normalizer) under `checkpoints/`.

Because these papers are **absent from CIViC**, no curator ground truth
or three-way analysis file exists; Section 2.8 of the manuscript reports
the combined extraction statistics (39 items, 0% critical errors,
96% verbatim grounding on the combined 108-item corpus).

## Reproducing the validation numbers

From the repository root:

```bash
# Single retrospective paper (matches Table S4)
python run_extraction.py \
    --input test_paper/triplet/PMID_18528420/PMID_18528420.pdf \
    --output outputs/

# All 10 retrospective papers
for d in test_paper/triplet/PMID_*; do
    python run_extraction.py --input "$d/$(basename "$d").pdf" --output outputs/
done

# All 5 prospective papers
for d in test_paper/prospective/*; do
    pdf=$(ls "$d"/*.pdf)
    python run_extraction.py --input "$pdf" --output outputs/
done
```

Expected runtime (per Supplementary Table S23): 3–5 minutes per paper on
API-mode inference.
