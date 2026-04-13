# Pipeline wrappers

Supplementary Note S5 documents "wrapper modules for Nextflow and
Snakemake" that allow OncoCITE to be incorporated as a stage in standard
genomic pipelines. Both wrappers live here:

- [`nextflow/oncocite.nf`](nextflow/oncocite.nf) — DSL2 Nextflow workflow
- [`snakemake/Snakefile`](snakemake/Snakefile) — Snakemake workflow

Both accept a directory or glob of publication PDFs and produce one
`{paper_id}_extraction.json` per input, using the same multi-agent
pipeline documented in the main paper (Section 2.2, Supplementary
Figure S2).

## Nextflow

```bash
export ONCOCITE_ROOT=$(pwd)
nextflow run pipelines/nextflow/oncocite.nf \
    --input_pdfs 'test_paper/triplet/PMID_*/*.pdf' \
    --outdir outputs/
```

## Snakemake

```bash
snakemake --snakefile pipelines/snakemake/Snakefile \
    --cores 4 \
    --config input_dir=test_paper/triplet outdir=outputs
```
