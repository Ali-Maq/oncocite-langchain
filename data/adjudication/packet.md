# Expert adjudication packet — OncoCITE three-way validation

Following paper Section 4.5, each candidate below requires an independent domain-expert judgment: **CONFIRMED** (genuine discrepancy), **REJECTED** (acceptable curatorial interpretation), or **UNCERTAIN** (ambiguous). Only CONFIRMED items are reported as ground-truth errors in the manuscript.

## PMID_11050000

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `NRAS|CODON_12|MULTIPLE_MYELOMA|MELPHALAN` | Figure 4 shows N-ras12 provides protection from melphalan-induced apoptosis | ___ | ___ |
| 2 | `ai_improvement` | `TP53|WILD_TYPE|MULTIPLE_MYELOMA|DOXORUBICIN` | Expression of wt p53 significantly suppresses Dox-induced apoptosis (26% vs 55%) | ___ | ___ |
| 3 | `field:PARTIAL_MATCH_OR_UNDER_SPECIFIED` | `KRAS|CODON_12|MULTIPLE_MYELOMA|MELPHALAN` | variant_names flagged as PARTIAL_MATCH_OR_UNDER_SPECIFIED | ___ | ___ |

## PMID_12483530

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `KRAS|CODON 12 MUTATION|Multiple Myeloma|Dexamethasone` | Figure 5 shows KRAS codon 12 mutations protect from dexamethasone-induced apoptosis | ___ | ___ |
| 2 | `ai_improvement` | `KRAS|CODON 12 MUTATION|Multiple Myeloma|Doxorubicin` | Figure 6 shows KRAS codon 12 mutations protect from doxorubicin-induced apoptosis | ___ | ___ |
| 3 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `KRAS|CODON 12 MUTATION|Multiple Myeloma|Dexamethasone` | therapy_names flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 4 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `KRAS|CODON 12 MUTATION|Multiple Myeloma|Doxorubicin` | therapy_names flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 5 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `KRAS|G12D|Multiple Myeloma|Melphalan` | variant_names flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |
| 6 | `field:CONTRADICTS_PAPER` | `KRAS|G12D|Multiple Myeloma|Melphalan` | therapy_names flagged as CONTRADICTS_PAPER | ___ | ___ |

## PMID_15339850

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `missing_from_ai` | `KRAS,NRAS|MUTATION|Multiple Myeloma|Melphalan` | AI extraction focused on prognostic/molecular associations rather than therapy predictions. The paper does not actually discuss melphalan re | ___ | ___ |
| 2 | `ai_improvement` | `KRAS,NRAS|MUTATION|ExPCT|null` | Results section shows RAS mutations in 3/6 extramedullary but 0/13 intramedullary samples from ExPCT patients | ___ | ___ |
| 3 | `ai_improvement` | `KRAS,NRAS|MUTATION + cyclin D1|Multiple Myeloma|null` | Results show significant association between RAS mutations and cyclin D1 expression (P=0.015) | ___ | ___ |
| 4 | `ai_improvement` | `KRAS,NRAS|MUTATION + t(4;14)|Multiple Myeloma|null` | Results show reduced RAS mutation frequency in t(4;14) subset (P=0.055) | ___ | ___ |
| 5 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `KRAS,NRAS|MUTATION|Multiple Myeloma|Melphalan` | variant_names flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |
| 6 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `KRAS,NRAS|MUTATION|Multiple Myeloma|Melphalan` | therapy_names flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |
| 7 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `KRAS,NRAS|MUTATION|Multiple Myeloma|Melphalan` | evidence_type flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |
| 8 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `KRAS,NRAS|MUTATION|Multiple Myeloma|Melphalan` | evidence_significance flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |

## PMID_16091734

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `FGFR3|K650E|Pre-B Cell Lymphoma|Midostaurin` | PKC412 showed significant survival benefit in murine model of FGFR3 TDII (K650E)-induced pre-B cell lymphoma (P=0.0006) | ___ | ___ |
| 2 | `ai_improvement` | `ETV6-FGFR3|Fusion|Myeloproliferative Neoplasm|Midostaurin` | PKC412 showed efficacy against TEL-FGFR3 fusion in myeloproliferative disease model (P<0.0001) | ___ | ___ |
| 3 | `ai_improvement` | `ETV6-FGFR3|Fusion|Peripheral T-cell Lymphoma|Midostaurin` | Paper suggests PKC412 efficacy for t(4;12) TEL-FGFR3-induced peripheral T-cell lymphoma based on preclinical data | ___ | ___ |

## PMID_18528420

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `NRAS|Q61|Multiple Myeloma|` | 64/74 NRAS mutations at codon 61, associated with aggressive disease features but not survival | ___ | ___ |
| 2 | `ai_improvement` | `KRAS,NRAS|MUTATION|Multiple Myeloma|` | RAS mutations associated with malignant transformation from MGUS to MM (7% vs 25% vs 45% in MGUS/new MM/relapsed MM) | ___ | ___ |

## PMID_19381019

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | Figure 5C-E, Figure 7D-E showing efficacy against S249C mutant bladder cancer | ___ | ___ |
| 2 | `ai_improvement` | `FGFR3|EXPRESSION|Bladder Carcinoma|null` | Figure 1A-D showing oncogenic role through knockdown studies | ___ | ___ |
| 3 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | feature_names flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 4 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | variant_names flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 5 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | disease_name flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 6 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | therapy_names flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 7 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | evidence_type flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 8 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | evidence_level flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 9 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | evidence_direction flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |
| 10 | `field:CORRECT_BUT_MISSING_IN_GROUND_TRUTH` | `FGFR3|S249C|Bladder Carcinoma|R3Mab` | evidence_significance flagged as CORRECT_BUT_MISSING_IN_GROUND_TRUTH | ___ | ___ |

## PMID_23480694

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `CRBN|R283K|Multiple Myeloma|IMiDs` | Page 2: 'a Q99* truncating mutation as well as a R283K point mutation were observed in CRBN' | ___ | ___ |
| 2 | `ai_improvement` | `PSMG2|E171K|Multiple Myeloma|Bortezomib` | Page 2: 'nonsynonymous point mutation in proteasome assembly chaperone 2, PSMG2 (E171K)...possibly explaining this patient's bortezomib-refr | ___ | ___ |
| 3 | `ai_improvement` | `NR3C1|G369A|Multiple Myeloma|Dexamethasone` | Page 2: 'NR3C1 (G369A)...has been associated with resistance to steroid therapy, which this patient received and proved refractory' | ___ | ___ |
| 4 | `field:OVER_SPECIFIED_BEYOND_PAPER` | `CRBN|Q99*|Multiple Myeloma|Lenalidomide,Pomalidomide` | variant_names flagged as OVER_SPECIFIED_BEYOND_PAPER | ___ | ___ |
| 5 | `field:PARTIAL_MATCH_OR_UNDER_SPECIFIED` | `CRBN|Q99*|Multiple Myeloma|Lenalidomide,Pomalidomide` | therapy_names flagged as PARTIAL_MATCH_OR_UNDER_SPECIFIED | ___ | ___ |

## PMID_23612012

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `BRAF|V600E|Multiple Myeloma|` | Four of seven BRAF-mutated patients (57%) developed extramedullary disease vs 17% of controls (p=0.02) | ___ | ___ |
| 2 | `ai_improvement` | `BRAF|V600E|Multiple Myeloma|Vemurafenib` | Patient with BRAF V600E achieved partial response to vemurafenib with tumor regression and durable response | ___ | ___ |

## PMID_24997557

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_improvement` | `BRAF|V600E|Multiple Myeloma|` | Discussion section clearly states prognostic significance of BRAF V600E in multiple myeloma with supporting data from referenced study | ___ | ___ |

## PMID_26193344

| # | kind | tuple | reason | judgment | rationale |
|---|---|---|---|---|---|
| 1 | `ai_hallucinated` | `HLA-A|A*0201 POSITIVE STATUS|Multiple Myeloma|NY-ESO-259 TCR T-cells` | While HLA-A*0201 is required for therapy, this is a technical requirement rather than a predictive biomarker finding | ___ | ___ |
| 2 | `ai_improvement` | `CTAG1B|LOSS|Multiple Myeloma|NY-ESO-259 TCR T-cells` | Results section shows antigen loss as resistance mechanism: 'In no cases was an antigen-positive tumor relapse observed in the presence of e | ___ | ___ |
| 3 | `ai_improvement` | `CTAG2|LOSS|Multiple Myeloma|NY-ESO-259 TCR T-cells` | Results section shows LAGE-1 loss correlates with resistance | ___ | ___ |
| 4 | `ai_improvement` | `CTAG1B|EXPRESSION|Multiple Myeloma|` | Introduction states NY-ESO-1 expression correlates with proliferation and high-risk features | ___ | ___ |

