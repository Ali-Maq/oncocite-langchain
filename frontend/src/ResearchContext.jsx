import { Pill } from './App';

/**
 * Research Context Component
 * Displays study metadata, architecture overview, and key findings
 */
export function ResearchContext({ papers, allEvidence, selected, output, phases }) {
  const totalPapers = papers?.length || 0;
  const totalEvidence = allEvidence?.length || 0;
  const civicBaseline = 33; // From paper: 10 papers, 33 manual items
  const automatedTotal = 60; // From paper: 10 papers, 60 automated items
  const superiority = ((automatedTotal - civicBaseline) / civicBaseline * 100).toFixed(1);

  return (
    <div className="research-context">
      <div className="research-header">
        <h2>Reader-First Multi-Agent Evidence Extraction System</h2>
        <p className="muted">
          Automated extraction achieving <strong>{superiority}% superiority</strong> over manual curation
          (60 vs 33 items, p&lt;0.001, Cohen's d=1.31)
        </p>
      </div>

      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-value">{totalPapers}</div>
          <div className="metric-label">Papers Processed</div>
          <div className="muted tiny">Multiple Myeloma validation set</div>
        </div>

        <div className="metric-card">
          <div className="metric-value">{totalEvidence}</div>
          <div className="metric-label">Evidence Items</div>
          <div className="muted tiny">Normalized & traceable</div>
        </div>

        <div className="metric-card highlight">
          <div className="metric-value">{superiority}%</div>
          <div className="metric-label">Superiority</div>
          <div className="muted tiny">vs CIViC manual baseline</div>
        </div>

        <div className="metric-card">
          <div className="metric-value">100%</div>
          <div className="metric-label">Completeness</div>
          <div className="muted tiny">Zero false negatives</div>
        </div>
      </div>

      <div className="architecture-overview">
        <h3>Four-Phase Architecture</h3>
        <div className="phase-grid">
          <div className="phase-card">
            <div className="phase-number">01</div>
            <div className="phase-name">Reader</div>
            <div className="phase-desc">Vision-based PDF → Structured Markdown</div>
            <div className="phase-benefit">✓ Preserves tables & figures</div>
          </div>

          <div className="phase-card">
            <div className="phase-number">02</div>
            <div className="phase-name">Planner</div>
            <div className="phase-desc">Strategy & Expected Items</div>
            <div className="phase-benefit">✓ Eliminates yield bias</div>
          </div>

          <div className="phase-card">
            <div className="phase-number">03</div>
            <div className="phase-name">Extractor-Critic</div>
            <div className="phase-desc">Evidence Extraction + Verification</div>
            <div className="phase-benefit">✓ Self-correction loop</div>
          </div>

          <div className="phase-card">
            <div className="phase-number">04</div>
            <div className="phase-name">Normalizer</div>
            <div className="phase-desc">Tier 2 Enrichment (IDs, HGVS)</div>
            <div className="phase-benefit">✓ Computable knowledge graph</div>
          </div>
        </div>
      </div>

      {selected && output && (
        <div className="paper-context">
          <h3>Current Paper Analysis</h3>
          <div className="context-grid">
            <div className="context-item">
              <div className="label">Paper Category</div>
              <div className="value">
                {getPaperCategory(output.extraction?.items || 0)}
              </div>
            </div>
            <div className="context-item">
              <div className="label">Expected Items</div>
              <div className="value">{phases.planner?.plan?.expected_items || '—'}</div>
            </div>
            <div className="context-item">
              <div className="label">Extracted Items</div>
              <div className="value">{output.extraction?.items || '—'}</div>
            </div>
            <div className="context-item">
              <div className="label">Quality Assessment</div>
              <div className="value">
                <Pill kind={phases.critic?.critique?.overall_assessment === 'APPROVE' ? 'success' : 'warning'}>
                  {phases.critic?.critique?.overall_assessment || '—'}
                </Pill>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="key-advantages">
        <h3>Key Advantages Over Manual Curation</h3>
        <div className="advantages-grid">
          <div className="advantage-item">
            <div className="advantage-icon">🎯</div>
            <div className="advantage-title">+225% in LOW-yield papers</div>
            <div className="advantage-desc">Eliminates satisficing bias</div>
          </div>
          <div className="advantage-item">
            <div className="advantage-icon">📊</div>
            <div className="advantage-title">Multivariate statistics</div>
            <div className="advantage-desc">Captures HRs, CIs, covariates</div>
          </div>
          <div className="advantage-item">
            <div className="advantage-icon">🔗</div>
            <div className="advantage-title">100% Tier 2 coverage</div>
            <div className="advantage-desc">93% gene IDs, 80% disease IDs</div>
          </div>
          <div className="advantage-item">
            <div className="advantage-icon">📝</div>
            <div className="advantage-title">Complete traceability</div>
            <div className="advantage-desc">Quotes, pages, confidence</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function getPaperCategory(itemCount) {
  if (itemCount >= 5) return 'HIGH YIELD (5-6 items)';
  if (itemCount === 4) return 'MEDIUM YIELD (4 items)';
  return 'LOW YIELD (1-2 items)';
}

/**
 * Tier 1 vs Tier 2 Field Explainer
 */
export function TierFieldExplainer() {
  return (
    <div className="tier-explainer">
      <h4>Data Normalization Tiers</h4>
      <div className="tier-grid">
        <div className="tier-section">
          <div className="tier-badge tier1">Tier 1</div>
          <div className="tier-title">Text Descriptions</div>
          <ul className="tier-list">
            <li>Gene symbols (e.g., "FGFR3")</li>
            <li>Variant names (e.g., "S249C")</li>
            <li>Disease names (e.g., "Multiple Myeloma")</li>
            <li>Evidence descriptions</li>
          </ul>
          <div className="tier-coverage">
            <strong>Manual curation:</strong> 100% coverage
          </div>
        </div>

        <div className="tier-section">
          <div className="tier-badge tier2">Tier 2</div>
          <div className="tier-title">Computational Identifiers</div>
          <ul className="tier-list">
            <li>Gene Entrez IDs (e.g., "2261")</li>
            <li>Disease EFO IDs (e.g., "EFO:0001378")</li>
            <li>Variant HGVS (e.g., "p.Ser249Cys")</li>
            <li>Variant origin (SOMATIC/GERMLINE)</li>
          </ul>
          <div className="tier-coverage">
            <strong>Manual curation:</strong> 0% coverage<br/>
            <strong>Our system:</strong> 93% gene IDs, 80% disease IDs
          </div>
        </div>
      </div>

      <div className="tier-impact">
        <strong>Clinical Impact:</strong> Tier 2 normalization enables direct EHR integration,
        variant calling pipeline matching, and automated clinical decision support—impossible with text-only data.
      </div>
    </div>
  );
}

/**
 * Traceability Features Display
 */
export function TraceabilityBadge({ item }) {
  const hasQuote = !!item.verbatim_quote;
  const hasPages = !!item.source_page_numbers;
  const hasConfidence = item.extraction_confidence !== undefined && item.extraction_confidence !== null;
  const traceabilityScore = [hasQuote, hasPages, hasConfidence].filter(Boolean).length;

  return (
    <div className="traceability-badge">
      <div className="traceability-label">Traceability Score</div>
      <div className="traceability-score">{traceabilityScore}/3</div>
      <div className="traceability-features">
        <span className={hasQuote ? 'feature-yes' : 'feature-no'}>
          {hasQuote ? '✓' : '✗'} Quote
        </span>
        <span className={hasPages ? 'feature-yes' : 'feature-no'}>
          {hasPages ? '✓' : '✗'} Pages
        </span>
        <span className={hasConfidence ? 'feature-yes' : 'feature-no'}>
          {hasConfidence ? '✓' : '✗'} Confidence
        </span>
      </div>
      <div className="muted tiny">
        Manual curation: 0/3 (0% traceability)
      </div>
    </div>
  );
}
