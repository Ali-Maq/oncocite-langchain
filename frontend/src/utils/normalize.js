/**
 * Normalization utilities for evidence items
 * Handles inconsistent field names and types across different paper JSONs
 */

/**
 * Normalize field names and types
 */
export function normalizeEvidenceItem(rawItem) {
  const normalized = { ...rawItem };

  // A) Normalize disease EFO ID field name
  if (rawItem.efo_id && !rawItem.disease_efo_id) {
    normalized.disease_efo_id = rawItem.efo_id;
  }

  // B) Normalize gene/feature Entrez IDs to always be arrays
  const entrezIds = [];
  if (rawItem.gene_entrez_id) {
    entrezIds.push(...(Array.isArray(rawItem.gene_entrez_id) ? rawItem.gene_entrez_id : [rawItem.gene_entrez_id]));
  }
  if (rawItem.feature_entrez_id) {
    entrezIds.push(...(Array.isArray(rawItem.feature_entrez_id) ? rawItem.feature_entrez_id : [rawItem.feature_entrez_id]));
  }
  if (rawItem.feature_entrez_ids) {
    entrezIds.push(...(Array.isArray(rawItem.feature_entrez_ids) ? rawItem.feature_entrez_ids : [rawItem.feature_entrez_ids]));
  }
  normalized.feature_entrez_ids = [...new Set(entrezIds.filter(Boolean))];

  // C) Normalize therapy IDs
  const rxnormIds = [];
  const ncitIds = [];

  if (rawItem.therapy_rxnorm_id) {
    rxnormIds.push(rawItem.therapy_rxnorm_id);
  }
  if (rawItem.therapy_rxcui) {
    rxnormIds.push(rawItem.therapy_rxcui);
  }
  if (rawItem.therapy_rxcui_ids) {
    rxnormIds.push(...(Array.isArray(rawItem.therapy_rxcui_ids) ? rawItem.therapy_rxcui_ids : [rawItem.therapy_rxcui_ids]));
  }
  if (rawItem.therapy_ncit_id) {
    ncitIds.push(rawItem.therapy_ncit_id);
  }
  if (rawItem.therapy_ncit_ids) {
    ncitIds.push(...(Array.isArray(rawItem.therapy_ncit_ids) ? rawItem.therapy_ncit_ids : [rawItem.therapy_ncit_ids]));
  }

  normalized.therapy_rxnorm_ids = [...new Set(rxnormIds.filter(Boolean))];
  normalized.therapy_ncit_ids = [...new Set(ncitIds.filter(Boolean))];

  // D) Normalize evidence level enum
  normalized.evidence_level_norm = normalizeEvidenceLevel(rawItem.evidence_level);

  // E) Normalize evidence significance enum
  normalized.evidence_significance_norm = normalizeEvidenceSignificance(rawItem.evidence_significance);

  // F) Determine variant type
  normalized.variant_type = determineVariantType(rawItem);

  // G) Normalize safety data field name
  normalized.therapy_safety = rawItem.drug_safety || rawItem.therapy_safety_profile || rawItem.therapy_safety;

  // H) Generate stable UID for this evidence item
  normalized.evidence_item_uid = generateEvidenceUID(rawItem);

  return normalized;
}

/**
 * Normalize evidence level to standard format
 */
function normalizeEvidenceLevel(level) {
  if (!level) return null;

  const levelStr = String(level).toUpperCase();

  // Map LEVEL_X to X
  if (levelStr.startsWith('LEVEL_')) {
    return levelStr.replace('LEVEL_', '');
  }

  // Map CASE_STUDY to D
  if (levelStr === 'CASE_STUDY') {
    return 'D';
  }

  return levelStr;
}

/**
 * Normalize evidence significance to standard format
 */
function normalizeEvidenceSignificance(significance) {
  if (!significance) return null;

  const sigStr = String(significance).toUpperCase();

  // Map SENSITIVITY/RESPONSE to SENSITIVITY_RESPONSE
  if (sigStr === 'SENSITIVITY/RESPONSE' || sigStr === 'SENSITIVITY') {
    return 'SENSITIVITY_RESPONSE';
  }

  // Map RESISTANCE variants
  if (sigStr.includes('RESIST')) {
    return 'RESISTANCE';
  }

  // Map poor outcome variants
  if (sigStr.includes('POOR') && sigStr.includes('OUTCOME')) {
    return 'POOR_OUTCOME';
  }

  return sigStr;
}

/**
 * Determine variant type based on variant names and HGVS presence
 */
function determineVariantType(item) {
  const variantNames = item.variant_names || [];
  const hasHGVS = item.variant_hgvs_c || item.variant_hgvs_p ||
                  (item.variant_hgvs_descriptions && item.variant_hgvs_descriptions.length > 0);

  const variantStr = variantNames.join(' ').toUpperCase();

  if (variantStr.includes('EXPRESSION')) return 'EXPRESSION';
  if (variantStr.includes('LOSS')) return 'LOSS';
  if (variantStr.includes('WILD') && variantStr.includes('TYPE')) return 'WILD_TYPE';
  if (variantStr.includes('WILDTYPE')) return 'WILD_TYPE';
  if (hasHGVS) return 'SNV_INDEL';

  // Default to SNV_INDEL if we have variant names but no clear type
  return variantNames.length > 0 ? 'SNV_INDEL' : 'UNKNOWN';
}

/**
 * Generate stable UID for evidence item based on key fields
 */
function generateEvidenceUID(item) {
  const parts = [
    item.pmid || item.source_pmid || '',
    (item.verbatim_quote || '').substring(0, 100),
    (item.therapy_names || []).sort().join(','),
    (item.feature_names || []).sort().join(','),
    (item.variant_names || []).sort().join(','),
    item.disease_efo_id || item.efo_id || '',
  ];

  // Simple hash function
  const str = parts.join('|');
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash; // Convert to 32bit integer
  }
  return 'ev_' + Math.abs(hash).toString(36);
}

/**
 * Normalize all evidence items in a dataset
 */
export function normalizeEvidenceItems(items) {
  return (items || []).map(normalizeEvidenceItem);
}

/**
 * Get color for evidence significance
 */
export function getSignificanceColor(significance) {
  const sig = (significance || '').toLowerCase();

  if (sig.includes('resist')) return '#ef4444'; // red
  if (sig.includes('response') || sig.includes('sensitivity')) return '#22c55e'; // green
  if (sig.includes('poor') || sig.includes('adverse')) return '#f97316'; // orange
  if (sig.includes('progression') || sig.includes('recurrence')) return '#dc2626'; // dark red

  return '#6366f1'; // default indigo
}

/**
 * Get node color based on node type
 */
export function getNodeColor(nodeType) {
  const colors = {
    gene: '#3b82f6',      // blue
    variant: '#8b5cf6',   // purple
    disease: '#ec4899',   // pink
    therapy: '#10b981',   // green
    evidence: '#f59e0b',  // amber
    outcome: '#6366f1',   // indigo
    paper: '#6b7280',     // gray
  };
  return colors[nodeType] || '#94a3b8';
}

/**
 * Calculate evidence weight for graph visualization
 */
export function calculateEvidenceWeight(evidence) {
  const levelScores = {
    A: 1.2,
    B: 1.0,
    C: 0.9,
    D: 0.7,
    CASE_STUDY: 0.5
  };

  const level = levelScores[evidence.evidence_level_norm || evidence.evidence_level] || 0.4;

  const conf = typeof evidence.extraction_confidence === 'number'
    ? evidence.extraction_confidence
    : evidence.extraction_confidence === 'High' ? 0.9 : 0.6;

  const cohort = evidence.cohort_size
    ? Math.min(Math.log10(evidence.cohort_size + 1) / 3, 1)
    : 0.2;

  return Math.max(0.2, level * (0.5 + conf * 0.4 + cohort * 0.3));
}
