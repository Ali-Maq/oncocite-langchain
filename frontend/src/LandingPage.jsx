import React from 'react';
import './LandingPage.css';

export default function LandingPage({ onGetStarted }) {
  return (
    <div className="landing-page">
      {/* Hero Section */}
      <section className="hero-section">
        <div className="hero-content">
          <h1 className="hero-title">OncoCITE</h1>
          <h2 className="hero-subtitle">Multi-Agent Genomic Evidence Extraction Pipeline</h2>
          <p className="hero-description">
            An AI-powered system that automatically extracts, validates, and normalizes
            clinical genomic evidence from scientific literature using advanced multi-agent
            orchestration and vision-language models.
          </p>
          <button className="cta-button" onClick={onGetStarted}>
            Get Started
          </button>
        </div>
      </section>

      {/* System Overview */}
      <section className="system-overview">
        <h2 className="section-title">System Architecture</h2>
        <p className="section-description">
          OncoCITE employs a two-phase pipeline that processes scientific PDFs and extracts
          structured genomic evidence with high accuracy.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_a_v2.png"
            alt="OncoCITE Pipeline Overview"
            className="panel-image"
          />
        </div>
      </section>

      {/* Phase 1: Reader */}
      <section className="phase-section">
        <div className="phase-header">
          <div className="phase-badge reader-badge">Phase 1</div>
          <h2 className="phase-title">Reader: PDF Processing & Content Extraction</h2>
        </div>
        <p className="phase-description">
          The Reader agent processes PDF documents using vision-language models to extract
          structured content including metadata, document structure, entities, and clinical information.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_b_v2.png"
            alt="Reader Phase Pipeline"
            className="panel-image"
          />
        </div>
        <div className="feature-grid">
          <div className="feature-card">
            <div className="feature-icon">📄</div>
            <h3>PDF Processing</h3>
            <p>Converts PDFs to high-resolution images and chunks them for efficient processing</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">🔍</div>
            <h3>Vision-Language Model</h3>
            <p>Uses Claude SDK for iterative page-by-page content extraction</p>
          </div>
          <div className="feature-card">
            <div className="feature-icon">📊</div>
            <h3>Structured Output</h3>
            <p>Extracts metadata, structure, entities, and clinical information systematically</p>
          </div>
        </div>
      </section>

      {/* Phase 2: Orchestrator */}
      <section className="phase-section orchestrator-section">
        <div className="phase-header">
          <div className="phase-badge orchestrator-badge">Phase 2</div>
          <h2 className="phase-title">Orchestrator: Multi-Agent Evidence Extraction</h2>
        </div>
        <p className="phase-description">
          The Orchestrator coordinates four specialized agents that work together to plan, extract,
          validate, and normalize genomic evidence with iterative refinement.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_c_v2.png"
            alt="Orchestrator Architecture"
            className="panel-image"
          />
        </div>
        <div className="agent-grid">
          <div className="agent-card planner-card">
            <h3>🎯 Planner</h3>
            <p>Develops extraction strategy and identifies key entities in the paper</p>
          </div>
          <div className="agent-card extractor-card">
            <h3>⚡ Extractor</h3>
            <p>Extracts 25 Tier-1 fields for each evidence item from the paper content</p>
          </div>
          <div className="agent-card critic-card">
            <h3>✓ Critic</h3>
            <p>Validates extracted evidence and provides feedback for refinement</p>
          </div>
          <div className="agent-card normalizer-card">
            <h3>✂ Normalizer</h3>
            <p>Maps entities to standardized ontology IDs using external APIs</p>
          </div>
        </div>
      </section>

      {/* Validation System */}
      <section className="feature-section">
        <h2 className="section-title">Schema Validation System</h2>
        <p className="section-description">
          Robust validation ensures data quality and consistency through field definitions,
          actionability checks, and Pydantic schema enforcement.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_d_v2.png"
            alt="Schema Validation System"
            className="panel-image"
          />
        </div>
      </section>

      {/* API Integration */}
      <section className="feature-section alt-bg">
        <h2 className="section-title">External API Integration</h2>
        <p className="section-description">
          The Normalizer agent integrates with multiple ontology APIs to ensure standardized,
          interoperable genomic annotations.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_e_v2.png"
            alt="API Integration Architecture"
            className="panel-image"
          />
        </div>
        <div className="api-grid">
          <div className="api-card">
            <h3>🧬 Gene/Variant APIs</h3>
            <p>Ensembl, MyVariant.info for genomic coordinates</p>
          </div>
          <div className="api-card">
            <h3>💊 Drug/Safety APIs</h3>
            <p>DrugBank, FDA for therapeutic normalization</p>
          </div>
          <div className="api-card">
            <h3>📚 Clinical/Publication</h3>
            <p>ClinVar, PubMed for clinical data</p>
          </div>
        </div>
      </section>

      {/* Checkpoint System */}
      <section className="feature-section">
        <h2 className="section-title">Checkpoint System & Logging</h2>
        <p className="section-description">
          Resume logic and comprehensive logging ensure reliability and enable debugging
          across all pipeline phases.
        </p>
        <div className="panel-container">
          <img
            src="/panels/panel_f_v2.png"
            alt="Checkpoint and Logging Architecture"
            className="panel-image"
          />
        </div>
      </section>

      {/* Key Features */}
      <section className="features-highlight">
        <h2 className="section-title">Key Features</h2>
        <div className="highlight-grid">
          <div className="highlight-card">
            <div className="highlight-number">81.8%</div>
            <p>Agreement with manual CIViC curation (Cohen's d=1.31)</p>
          </div>
          <div className="highlight-card">
            <div className="highlight-number">25</div>
            <p>Tier-1 fields extracted per evidence item</p>
          </div>
          <div className="highlight-card">
            <div className="highlight-number">3x</div>
            <p>Iterative revision loops for quality assurance</p>
          </div>
          <div className="highlight-card">
            <div className="highlight-number">100%</div>
            <p>Automated with checkpoint-based resume capability</p>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <h2>Ready to Explore?</h2>
        <p>Start extracting genomic evidence from scientific literature</p>
        <button className="cta-button-large" onClick={onGetStarted}>
          Launch Application
        </button>
      </section>

      {/* Footer */}
      <footer className="landing-footer">
        <p>OncoCITE: Multi-Agent Genomic Evidence Extraction System</p>
      </footer>
    </div>
  );
}
