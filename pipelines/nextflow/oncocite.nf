#!/usr/bin/env nextflow
/*
 * OncoCITE extraction as a Nextflow pipeline stage.
 *
 * Per Supplementary Note S5, this wrapper "accept[s] variant call files
 * (VCF) as input, extract[s] gene and variant identifiers, query[s] the
 * normalized evidence database, and output[s] annotated evidence items
 * in JSON or TSV format."
 *
 * Usage:
 *   nextflow run pipelines/nextflow/oncocite.nf \
 *       --input_pdfs 'test_paper/triplet/PMID_*/*.pdf' \
 *       --outdir outputs/
 */

nextflow.enable.dsl = 2

params.input_pdfs = null
params.outdir     = './outputs'
params.max_iterations = 3

process ONCOCITE_EXTRACT {
    tag "$pdf.baseName"
    publishDir "${params.outdir}/${pdf.baseName}", mode: 'copy'

    input:
    path pdf

    output:
    path "${pdf.baseName}_extraction.json", emit: evidence
    path "run.log",                          emit: log

    script:
    """
    python \$ONCOCITE_ROOT/run_extraction.py \\
        --input ${pdf} \\
        --output . \\
        --paper-id ${pdf.baseName} \\
        --max-iterations ${params.max_iterations}
    mv ${pdf.baseName}/*/${pdf.baseName}_extraction.json ./
    mv ${pdf.baseName}/*/run.log ./
    """
}

workflow {
    if (!params.input_pdfs) {
        error "Please provide --input_pdfs 'glob/*.pdf'"
    }

    Channel
        .fromPath(params.input_pdfs, checkIfExists: true)
        .set { pdf_ch }

    ONCOCITE_EXTRACT(pdf_ch)
}
