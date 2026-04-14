/**
 * Knowledge Graph Module for CIViC Evidence Extraction
 *
 * Implements three-graph architecture:
 * - Graph A: Evidence Graph (auditability)
 * - Graph B: Clinical Assertion Graph (clinically meaningful)
 * - Graph C: Paper Similarity Graph (shows how papers relate)
 */

// ============================================================================
// 1. ID CANONICALIZATION
// ============================================================================

/**
 * Canonicalize gene/feature identifiers
 */
export function canonicalizeGene(item) {
  const entrezIds = item.gene_entrez_ids || item.feature_entrez_ids || [];
  const names = item.gene_names || item.feature_names || [];

  // Use first Entrez ID as canonical, fallback to first name
  const canonical = entrezIds[0] || names[0] || 'UNKNOWN';

  return {
    id: canonical,
    entrez_ids: entrezIds,
    names: names,
    primary_name: names[0] || canonical
  };
}

/**
 * Canonicalize variant identifiers
 */
export function canonicalizeVariant(item) {
  const names = item.variant_names || [];
  const hgvs = item.hgvs_expressions || [];

  // Use first HGVS or variant name as canonical
  const canonical = hgvs[0] || names[0] || 'UNKNOWN';

  return {
    id: canonical,
    hgvs: hgvs,
    names: names,
    primary_name: names[0] || canonical,
    origin: item.variant_origin
  };
}

/**
 * Canonicalize therapy identifiers
 */
export function canonicalizeTherapy(item) {
  const rxcuis = item.therapy_rxcui || [];
  const ncit = item.therapy_ncit_id ? [item.therapy_ncit_id] : [];
  const names = item.therapy_names || [];

  // Use first RxCUI or NCIt or name as canonical
  const canonical = rxcuis[0] || ncit[0] || names[0] || 'UNKNOWN';

  return {
    id: canonical,
    rxcuis: rxcuis,
    ncit_ids: ncit,
    names: names,
    primary_name: names[0] || canonical
  };
}

/**
 * Canonicalize disease identifiers
 */
export function canonicalizeDisease(item) {
  const efoIds = item.disease_efo_id ? [item.disease_efo_id] : [];
  const related = item.related_disease_efo_id || [];
  const name = item.disease_name || 'UNKNOWN';

  // Use first EFO ID or disease name
  const canonical = efoIds[0] || name;

  return {
    id: canonical,
    efo_ids: [...efoIds, ...related],
    name: name,
    state: inferDiseaseState(name) // MGUS, MM, extramedullary, etc.
  };
}

/**
 * Infer disease state from name
 */
function inferDiseaseState(diseaseName) {
  const lower = (diseaseName || '').toLowerCase();

  if (lower.includes('mgus')) return 'MGUS';
  if (lower.includes('extramedullary')) return 'extramedullary';
  if (lower.includes('relapsed') || lower.includes('refractory') || lower.includes('rrmm')) return 'RRMM';
  if (lower.includes('multiple myeloma') || lower.includes('myeloma')) return 'MM';

  return 'other';
}

// ============================================================================
// 2. CLINICAL ASSERTION EXTRACTION
// ============================================================================

/**
 * Generate a unique key for a clinical assertion
 * Format: disease_state|biomarker|therapy|evidence_type|significance
 */
export function generateAssertionKey(item) {
  const disease = canonicalizeDisease(item);
  const gene = canonicalizeGene(item);
  const variant = canonicalizeVariant(item);
  const therapy = canonicalizeTherapy(item);

  // Biomarker = gene + variant
  const biomarker = variant.id !== 'UNKNOWN'
    ? `${gene.primary_name}:${variant.primary_name}`
    : gene.primary_name;

  const evidenceType = item.evidence_type || 'UNKNOWN';
  const significance = item.evidence_significance || item.evidence_direction || 'UNKNOWN';

  // For therapies, include therapy name; for prognostic/diagnostic, use "outcome"
  const therapyPart = therapy.id !== 'UNKNOWN' ? therapy.primary_name : 'outcome';

  return `${disease.state}|${biomarker}|${therapyPart}|${evidenceType}|${significance}`;
}

/**
 * Extract clinical assertion from evidence item
 */
export function extractClinicalAssertion(item) {
  const key = generateAssertionKey(item);

  const disease = canonicalizeDisease(item);
  const gene = canonicalizeGene(item);
  const variant = canonicalizeVariant(item);
  const therapy = canonicalizeTherapy(item);

  const biomarker = variant.id !== 'UNKNOWN'
    ? `${gene.primary_name}:${variant.primary_name}`
    : gene.primary_name;

  return {
    key: key,
    disease_state: disease.state,
    disease_name: disease.name,
    biomarker: biomarker,
    biomarker_gene: gene.primary_name,
    biomarker_variant: variant.primary_name !== 'UNKNOWN' ? variant.primary_name : null,
    therapy: therapy.primary_name !== 'UNKNOWN' ? therapy.primary_name : null,
    evidence_type: item.evidence_type || 'UNKNOWN',
    significance: item.evidence_significance || item.evidence_direction || 'UNKNOWN',
    evidence_level: item.evidence_level || 'E',

    // Readable summary
    summary: generateAssertionSummary(biomarker, therapy.primary_name, item.evidence_significance || item.evidence_direction, disease.state),

    // Supporting evidence items (will be aggregated)
    supporting_evidence: []
  };
}

/**
 * Generate human-readable assertion summary
 */
function generateAssertionSummary(biomarker, therapy, significance, diseaseState) {
  const therapyPart = therapy !== 'UNKNOWN' ? `→ ${therapy}` : '';
  const diseasePart = diseaseState !== 'other' ? ` in ${diseaseState}` : '';

  return `${biomarker} ${therapyPart} → ${significance}${diseasePart}`;
}

// ============================================================================
// 3. EVIDENCE STRENGTH SCORING
// ============================================================================

/**
 * Calculate evidence strength score
 * Higher score = stronger evidence
 */
export function calculateEvidenceStrength(item) {
  let score = 0;

  // 1. Evidence level weight (A=100, B=75, C=50, D=25, E=10)
  const levelWeights = { 'A': 100, 'B': 75, 'C': 50, 'D': 25, 'E': 10 };
  const level = item.evidence_level || 'E';
  score += levelWeights[level] || 10;

  // 2. Cohort size weight (log scale, max +50)
  const cohortSize = item.cohort_size || 0;
  if (cohortSize > 0) {
    score += Math.min(50, Math.log10(cohortSize) * 15);
  }

  // 3. Extraction confidence weight (0-20)
  const confidence = item.extraction_confidence || 0;
  score += confidence * 20;

  // 4. Evidence rating weight (0-25)
  const rating = item.evidence_rating || 0;
  score += rating * 5;

  // 5. Has clinical trial NCT ID (+10)
  if (item.clinical_trial_nct_ids && item.clinical_trial_nct_ids.length > 0) {
    score += 10;
  }

  // 6. Has genomic coordinates (+5, indicates precision)
  if (item.chromosome || item.start_position) {
    score += 5;
  }

  return Math.round(score);
}

/**
 * Aggregate evidence strength from multiple items
 */
export function aggregateEvidenceStrength(items) {
  if (items.length === 0) return 0;

  // Sum of individual strengths, with diminishing returns for redundancy
  const scores = items.map(calculateEvidenceStrength);
  const maxScore = Math.max(...scores);
  const sumScore = scores.reduce((a, b) => a + b, 0);

  // Formula: max + 30% of sum (to reward multiple papers but not linearly)
  return Math.round(maxScore + (sumScore - maxScore) * 0.3);
}

// ============================================================================
// 4. GRAPH A: EVIDENCE GRAPH (Auditability)
// ============================================================================

/**
 * Build evidence graph (node per evidence item)
 * This is for provenance and drill-down
 */
export function buildEvidenceGraph(allEvidenceItems) {
  const nodes = [];
  const links = [];
  const nodeMap = new Map();

  allEvidenceItems.forEach((item, idx) => {
    const gene = canonicalizeGene(item);
    const variant = canonicalizeVariant(item);
    const therapy = canonicalizeTherapy(item);
    const disease = canonicalizeDisease(item);

    // Evidence node
    const paperId = item.__paperId || item.pmid || 'UNKNOWN';
    const evidenceId = `evidence_${paperId}_${idx}`;
    nodes.push({
      id: evidenceId,
      kind: 'evidence',
      label: `${gene.primary_name} evidence`,
      pmid: item.pmid,
      paperId: paperId,
      page: item.source_page_numbers,
      level: item.evidence_level,
      strength: calculateEvidenceStrength(item),
      item: item // Keep reference for drill-down
    });

    // Gene node
    if (!nodeMap.has(gene.id)) {
      nodeMap.set(gene.id, {
        id: gene.id,
        kind: 'gene',
        label: gene.primary_name,
        entrez_ids: gene.entrez_ids
      });
    }

    // Variant node
    if (variant.id !== 'UNKNOWN' && !nodeMap.has(variant.id)) {
      nodeMap.set(variant.id, {
        id: variant.id,
        kind: 'variant',
        label: variant.primary_name,
        hgvs: variant.hgvs,
        origin: variant.origin
      });
    }

    // Therapy node
    if (therapy.id !== 'UNKNOWN' && !nodeMap.has(therapy.id)) {
      nodeMap.set(therapy.id, {
        id: therapy.id,
        kind: 'therapy',
        label: therapy.primary_name,
        rxcuis: therapy.rxcuis
      });
    }

    // Disease node
    if (!nodeMap.has(disease.id)) {
      nodeMap.set(disease.id, {
        id: disease.id,
        kind: 'disease',
        label: disease.name,
        state: disease.state,
        efo_ids: disease.efo_ids
      });
    }

    // Links
    links.push({ source: evidenceId, target: gene.id, weight: 1.0, type: 'involves_gene' });

    if (variant.id !== 'UNKNOWN') {
      links.push({ source: gene.id, target: variant.id, weight: 1.0, type: 'has_variant' });
      links.push({ source: evidenceId, target: variant.id, weight: 0.8, type: 'involves_variant' });
    }

    if (therapy.id !== 'UNKNOWN') {
      links.push({ source: evidenceId, target: therapy.id, weight: 0.9, type: 'involves_therapy' });
    }

    links.push({ source: evidenceId, target: disease.id, weight: 0.9, type: 'involves_disease' });
  });

  // Add all entity nodes
  nodes.push(...Array.from(nodeMap.values()));

  return { nodes, links };
}

// ============================================================================
// 5. GRAPH B: CLINICAL ASSERTION GRAPH (Clinically Meaningful)
// ============================================================================

/**
 * Build clinical assertion graph (aggregated, one node per unique assertion)
 */
export function buildClinicalAssertionGraph(allEvidenceItems) {
  const assertionMap = new Map();
  const biomarkerNodes = new Map();
  const therapyNodes = new Map();
  const diseaseNodes = new Map();
  const links = [];

  // 1. Group evidence items by assertion
  allEvidenceItems.forEach(item => {
    const assertion = extractClinicalAssertion(item);

    if (!assertionMap.has(assertion.key)) {
      assertionMap.set(assertion.key, assertion);
    }

    // Add this item to supporting evidence
    assertionMap.get(assertion.key).supporting_evidence.push(item);
  });

  // 2. Build nodes and links
  assertionMap.forEach(assertion => {
    const strength = aggregateEvidenceStrength(assertion.supporting_evidence);
    const numPapers = new Set(assertion.supporting_evidence.map(e => e.pmid)).size;
    const totalCohort = assertion.supporting_evidence.reduce((sum, e) => sum + (e.cohort_size || 0), 0);

    // Biomarker node
    if (!biomarkerNodes.has(assertion.biomarker)) {
      biomarkerNodes.set(assertion.biomarker, {
        id: `biomarker_${assertion.biomarker}`,
        kind: 'biomarker',
        label: assertion.biomarker,
        gene: assertion.biomarker_gene,
        variant: assertion.biomarker_variant
      });
    }

    // Therapy node (or outcome)
    const therapyId = assertion.therapy || 'outcome';
    if (!therapyNodes.has(therapyId)) {
      therapyNodes.set(therapyId, {
        id: `therapy_${therapyId}`,
        kind: assertion.therapy ? 'therapy' : 'outcome',
        label: therapyId
      });
    }

    // Disease state node
    if (!diseaseNodes.has(assertion.disease_state)) {
      diseaseNodes.set(assertion.disease_state, {
        id: `disease_${assertion.disease_state}`,
        kind: 'disease_state',
        label: assertion.disease_state
      });
    }

    // Link: biomarker → therapy/outcome
    links.push({
      source: `biomarker_${assertion.biomarker}`,
      target: `therapy_${therapyId}`,
      weight: strength / 200, // Normalize to 0-1 range
      type: assertion.significance,
      evidence_level: assertion.evidence_level,
      num_papers: numPapers,
      total_cohort: totalCohort,
      strength: strength,
      assertion: assertion // Keep reference for drill-down
    });

    // Link: disease → biomarker
    links.push({
      source: `disease_${assertion.disease_state}`,
      target: `biomarker_${assertion.biomarker}`,
      weight: 0.5,
      type: 'has_biomarker'
    });
  });

  const nodes = [
    ...Array.from(biomarkerNodes.values()),
    ...Array.from(therapyNodes.values()),
    ...Array.from(diseaseNodes.values())
  ];

  return { nodes, links, assertions: Array.from(assertionMap.values()) };
}

// ============================================================================
// 6. GRAPH C: PAPER SIMILARITY GRAPH
// ============================================================================

/**
 * Calculate similarity between two papers based on shared assertions
 */
function calculatePaperSimilarity(paper1Items, paper2Items) {
  const assertions1 = new Set(paper1Items.map(item => generateAssertionKey(item)));
  const assertions2 = new Set(paper2Items.map(item => generateAssertionKey(item)));

  // Count shared assertions
  let shared = 0;
  assertions1.forEach(key => {
    if (assertions2.has(key)) shared++;
  });

  // Jaccard similarity
  const union = assertions1.size + assertions2.size - shared;
  return union > 0 ? shared / union : 0;
}

/**
 * Extract topics/themes from a paper
 */
function extractPaperTopics(items) {
  const topics = new Set();

  items.forEach(item => {
    const gene = canonicalizeGene(item);
    const therapy = canonicalizeTherapy(item);
    const disease = canonicalizeDisease(item);

    // Add biomarker topics
    topics.add(`biomarker:${gene.primary_name}`);

    // Add therapy topics
    if (therapy.primary_name !== 'UNKNOWN') {
      topics.add(`therapy:${therapy.primary_name}`);
    }

    // Add disease state topics
    topics.add(`disease:${disease.state}`);

    // Add significance topics
    const sig = item.evidence_significance || item.evidence_direction;
    if (sig) {
      topics.add(`significance:${sig}`);
    }
  });

  return Array.from(topics);
}

/**
 * Build paper similarity graph
 */
export function buildPaperSimilarityGraph(allEvidenceItems) {
  // Group by paper ID (use __paperId which is the full paper identifier like "PMID_18528420")
  const paperMap = new Map();
  allEvidenceItems.forEach(item => {
    const paperId = item.__paperId || item.pmid || 'UNKNOWN';
    if (!paperMap.has(paperId)) {
      paperMap.set(paperId, []);
    }
    paperMap.get(paperId).push(item);
  });

  const papers = Array.from(paperMap.keys());
  const nodes = [];
  const links = [];

  // Create paper nodes
  papers.forEach(paperId => {
    const items = paperMap.get(paperId);
    const topics = extractPaperTopics(items);

    // Determine primary topic for coloring
    const biomarkerTopics = topics.filter(t => t.startsWith('biomarker:'));
    const primaryTopic = biomarkerTopics.length > 0
      ? biomarkerTopics[0].split(':')[1]
      : 'other';

    // Extract PMID from paperId (e.g., "PMID_18528420" -> "18528420")
    const pmid = paperId.replace('PMID_', '').replace('PMID', '');

    nodes.push({
      id: `paper_${paperId}`,
      kind: 'paper',
      label: paperId,
      pmid: pmid,
      paperId: paperId,
      num_items: items.length,
      topics: topics,
      primary_topic: primaryTopic,
      title: items[0].source_title || paperId
    });
  });

  // Create similarity links (only if similarity > threshold)
  const threshold = 0.1;
  for (let i = 0; i < papers.length; i++) {
    for (let j = i + 1; j < papers.length; j++) {
      const pmid1 = papers[i];
      const pmid2 = papers[j];
      const similarity = calculatePaperSimilarity(paperMap.get(pmid1), paperMap.get(pmid2));

      if (similarity > threshold) {
        links.push({
          source: `paper_${pmid1}`,
          target: `paper_${pmid2}`,
          weight: similarity,
          type: 'similar'
        });
      }
    }
  }

  return { nodes, links };
}

// ============================================================================
// 7. MASTER GRAPH BUILDER
// ============================================================================

/**
 * Build all three graphs from evidence items
 */
export function buildKnowledgeGraphs(allEvidenceItems) {
  const evidenceGraph = buildEvidenceGraph(allEvidenceItems);
  const clinicalGraph = buildClinicalAssertionGraph(allEvidenceItems);
  const paperGraph = buildPaperSimilarityGraph(allEvidenceItems);

  return {
    evidenceGraph,
    clinicalGraph,
    paperGraph,
    stats: {
      total_evidence_items: allEvidenceItems.length,
      total_papers: new Set(allEvidenceItems.map(e => e.__paperId || e.pmid)).size,
      total_assertions: clinicalGraph.assertions.length,
      total_biomarkers: new Set(clinicalGraph.assertions.map(a => a.biomarker)).size,
      total_therapies: new Set(clinicalGraph.assertions.map(a => a.therapy).filter(t => t)).size
    }
  };
}

// ============================================================================
// 8. UTILITY FUNCTIONS
// ============================================================================

/**
 * Get node color by kind
 */
export function getNodeColor(kind) {
  const colors = {
    gene: '#3b82f6',      // blue
    variant: '#8b5cf6',   // purple
    therapy: '#10b981',   // green
    disease: '#ef4444',   // red
    evidence: '#f59e0b',  // amber
    biomarker: '#6366f1', // indigo
    outcome: '#ec4899',   // pink
    disease_state: '#f97316', // orange
    paper: '#14b8a6'      // teal
  };
  return colors[kind] || '#64748b';
}

/**
 * Get evidence level color
 */
export function getEvidenceLevelColor(level) {
  const colors = {
    'A': '#10b981', // green
    'B': '#3b82f6', // blue
    'C': '#f59e0b', // amber
    'D': '#ef4444', // red
    'E': '#6b7280'  // gray
  };
  return colors[level] || '#6b7280';
}

/**
 * Format evidence strength as label
 */
export function formatStrength(strength) {
  if (strength > 150) return 'Very Strong';
  if (strength > 100) return 'Strong';
  if (strength > 50) return 'Moderate';
  if (strength > 20) return 'Weak';
  return 'Very Weak';
}
