/**
 * Knowledge Graph Views Components - REDESIGNED
 *
 * Four coordinated views with proper D3 force simulation and visual hierarchy:
 * 1. Atlas Overview (Paper clusters with radial layout)
 * 2. Clinical Evidence Map (Assertion-first, biomarker → therapy)
 * 3. Evidence Matrix (biomarker × therapy grid)
 * 4. Disease Evolution Storyline (MGUS → MM → extramedullary)
 * 
 * KEY FIXES:
 * - Proper D3 force simulation with collision detection
 * - Node labels rendered on canvas
 * - Better visual hierarchy with sized nodes
 * - Configurable force parameters
 * - Responsive layouts
 */

import React, { useState, useMemo, useRef, useCallback, useEffect } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import * as d3Force from 'd3-force';
import {
  getNodeColor,
  getEvidenceLevelColor,
  formatStrength
} from './knowledgeGraph.js';
import './KnowledgeGraph.css';

// ============================================================================
// SHARED COMPONENTS & UTILITIES
// ============================================================================

const NODE_COLORS = {
  gene: '#3b82f6',
  biomarker: '#8b5cf6',
  variant: '#a855f7',
  therapy: '#10b981',
  outcome: '#f59e0b',
  disease: '#ef4444',
  disease_state: '#f97316',
  paper: '#06b6d4',
  evidence: '#64748b'
};

const EDGE_COLORS = {
  SENSITIVITY: '#10b981',
  BETTER_OUTCOME: '#10b981',
  RESPONSE: '#22c55e',
  RESISTANCE: '#ef4444',
  POOR_OUTCOME: '#ef4444',
  NO_BENEFIT: '#f59e0b',
  has_biomarker: '#cbd5e1',
  default: '#94a3b8'
};

function getEdgeColor(type, strength) {
  if (type === 'has_biomarker') return '#e2e8f0';
  if (EDGE_COLORS[type]) return EDGE_COLORS[type];
  if (strength > 150) return '#10b981';
  if (strength > 100) return '#3b82f6';
  if (strength > 50) return '#f59e0b';
  return '#94a3b8';
}

function GraphStats({ nodes, links, assertions }) {
  return (
    <div className="kg-stats-bar">
      <div className="kg-stat">
        <span className="kg-stat-value">{nodes?.length || 0}</span>
        <span className="kg-stat-label">Nodes</span>
      </div>
      <div className="kg-stat">
        <span className="kg-stat-value">{links?.length || 0}</span>
        <span className="kg-stat-label">Edges</span>
      </div>
      {assertions && (
        <div className="kg-stat">
          <span className="kg-stat-value">{assertions.length}</span>
          <span className="kg-stat-label">Assertions</span>
        </div>
      )}
    </div>
  );
}

function GraphLegend({ items }) {
  return (
    <div className="kg-legend">
      {items.map((item, idx) => (
        <div key={idx} className="kg-legend-item">
          <div 
            className="kg-legend-dot" 
            style={{ 
              background: item.color,
              borderRadius: item.shape === 'square' ? '2px' : '50%',
              width: item.shape === 'line' ? '20px' : '10px',
              height: item.shape === 'line' ? '3px' : '10px'
            }} 
          />
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ message }) {
  return (
    <div className="kg-empty-state">
      <div className="kg-empty-icon">📊</div>
      <div className="kg-empty-text">{message || 'No data available'}</div>
    </div>
  );
}

// ============================================================================
// VIEW 1: ATLAS OVERVIEW (Paper Clusters)
// ============================================================================

export function AtlasView({ paperGraph, onPaperClick }) {
  const fgRef = useRef();
  const [selectedPaper, setSelectedPaper] = useState(null);
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [highlightNodes, setHighlightNodes] = useState(new Set());

  const clusters = useMemo(() => {
    if (!paperGraph?.nodes) return [];
    const clusterMap = new Map();

    paperGraph.nodes.forEach(node => {
      const topic = node.primary_topic || 'other';
      if (!clusterMap.has(topic)) {
        clusterMap.set(topic, {
          topic,
          papers: [],
          biomarkers: new Set(),
          therapies: new Set(),
          totalItems: 0
        });
      }

      const cluster = clusterMap.get(topic);
      cluster.papers.push(node);
      cluster.totalItems += node.num_items || 0;

      (node.topics || []).forEach(t => {
        if (t.startsWith('biomarker:')) cluster.biomarkers.add(t.split(':')[1]);
        if (t.startsWith('therapy:')) cluster.therapies.add(t.split(':')[1]);
      });
    });

    return Array.from(clusterMap.values())
      .sort((a, b) => b.papers.length - a.papers.length);
  }, [paperGraph]);

  useEffect(() => {
    if (fgRef.current) {
      fgRef.current.d3Force('charge').strength(-300).distanceMax(400);
      fgRef.current.d3Force('link').distance(link => 80 + (1 - (link.weight || 0)) * 100);
      fgRef.current.d3Force('center').strength(0.05);
      fgRef.current.d3Force('collision', 
        d3Force.forceCollide().radius(node => 15 + (node.num_items || 1) * 3)
      );
      
      // Zoom to fit after simulation settles
      setTimeout(() => {
        fgRef.current?.zoomToFit(400, 40);
      }, 500);
    }
  }, [paperGraph]);

  const handleNodeClick = useCallback((node) => {
    setSelectedPaper(node);
    if (onPaperClick) onPaperClick(node);
    if (fgRef.current) {
      fgRef.current.centerAt(node.x, node.y, 500);
      fgRef.current.zoom(2, 500);
    }
  }, [onPaperClick]);

  const handleClusterClick = useCallback((cluster) => {
    setSelectedCluster(cluster);
    setHighlightNodes(new Set(cluster.papers.map(p => p.id)));
  }, []);

  const paintNode = useCallback((node, ctx, globalScale) => {
    const isHighlighted = highlightNodes.size === 0 || highlightNodes.has(node.id);
    const size = 6 + (node.num_items || 1) * 2;
    const fontSize = Math.max(10 / globalScale, 3);
    
    ctx.beginPath();
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
    ctx.fillStyle = isHighlighted ? NODE_COLORS.paper : '#cbd5e1';
    ctx.fill();
    
    if (selectedPaper?.id === node.id) {
      ctx.strokeStyle = '#1e40af';
      ctx.lineWidth = 3;
      ctx.stroke();
    }
    
    if (globalScale > 0.8) {
      const label = node.paperId?.replace('PMID_', '').replace('Elnaggar_et_al', 'Elnaggar') || node.label?.slice(0, 12);
      ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillStyle = isHighlighted ? '#0f172a' : '#94a3b8';
      ctx.fillText(label, node.x, node.y + size + 2);
    }
  }, [highlightNodes, selectedPaper]);

  if (!paperGraph?.nodes?.length) {
    return <EmptyState message="No papers to display" />;
  }

  return (
    <div className="kg-atlas-container">
      <div className="kg-atlas-graph">
        <div className="kg-graph-header">
          <h4>Paper Similarity Network</h4>
          <GraphStats nodes={paperGraph.nodes} links={paperGraph.links} />
        </div>
        
        <GraphLegend items={[
          { color: NODE_COLORS.paper, label: 'Paper', shape: 'circle' },
          { color: '#cbd5e1', label: 'Similar', shape: 'line' }
        ]} />
        
        <div className="kg-graph-canvas">
          <ForceGraph2D
            ref={fgRef}
            graphData={paperGraph}
            width={600}
            height={500}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.beginPath();
              ctx.arc(node.x, node.y, 10 + (node.num_items || 1) * 2, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkColor={() => '#e2e8f0'}
            linkWidth={link => Math.max(1, (link.weight || 0) * 4)}
            linkLineDash={[2, 2]}
            onNodeClick={handleNodeClick}
            onNodeHover={node => document.body.style.cursor = node ? 'pointer' : 'default'}
            onEngineStop={() => {
              if (fgRef.current) {
                fgRef.current.zoomToFit(300, 40);
              }
            }}
            cooldownTicks={200}
            warmupTicks={50}
            d3AlphaDecay={0.02}
            d3VelocityDecay={0.3}
          />
        </div>
      </div>

      <div className="kg-atlas-sidebar">
        <div className="kg-sidebar-section">
          <h5>Clusters by Topic ({clusters.length})</h5>
          <div className="kg-cluster-list">
            {clusters.map(cluster => (
              <div
                key={cluster.topic}
                className={`kg-cluster-card ${selectedCluster?.topic === cluster.topic ? 'selected' : ''}`}
                onClick={() => handleClusterClick(cluster)}
              >
                <div className="kg-cluster-header">
                  <span className="kg-cluster-topic">{cluster.topic}</span>
                  <span className="kg-cluster-count">{cluster.papers.length}</span>
                </div>
                <div className="kg-cluster-meta">
                  <span>{cluster.biomarkers.size} biomarkers</span>
                  <span>·</span>
                  <span>{cluster.totalItems} items</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {selectedPaper && (
          <div className="kg-sidebar-section">
            <h5>Selected Paper</h5>
            <div className="kg-paper-detail">
              <div className="kg-paper-id">{selectedPaper.paperId || selectedPaper.label}</div>
              <div className="kg-paper-title">{selectedPaper.title}</div>
              <div className="kg-paper-stats">
                <span className="kg-stat-pill">{selectedPaper.num_items} items</span>
              </div>
              <div className="kg-paper-topics">
                {(selectedPaper.topics || []).slice(0, 8).map((t, i) => (
                  <span key={i} className="kg-topic-tag">{t.split(':')[1] || t}</span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// VIEW 2: CLINICAL EVIDENCE MAP
// ============================================================================

export function ClinicalMapView({ clinicalGraph, onAssertionClick }) {
  const fgRef = useRef();
  const canvasRef = useRef();
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  // Bumped default from 30 → 50 so the first render is less crowded for
  // papers with a dense biomarker × therapy fan-out.
  const [minStrength, setMinStrength] = useState(50);
  const [showLabels, setShowLabels] = useState(true);
  // Responsive canvas size — drives ForceGraph2D width/height from the
  // container's measured bounds instead of a hardcoded 1200×700.
  const [canvasSize, setCanvasSize] = useState({ w: 960, h: 640 });
  useEffect(() => {
    if (!canvasRef.current) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        setCanvasSize({ w: Math.floor(width), h: Math.max(520, Math.floor(height)) });
      }
    });
    ro.observe(canvasRef.current);
    return () => ro.disconnect();
  }, []);

  const filteredData = useMemo(() => {
    if (!clinicalGraph?.links) return { nodes: [], links: [] };
    
    const filteredLinks = clinicalGraph.links.filter(link => {
      if (link.type === 'has_biomarker') return true;
      return (link.strength || 0) >= minStrength;
    });

    const connectedNodeIds = new Set();
    filteredLinks.forEach(link => {
      connectedNodeIds.add(typeof link.source === 'object' ? link.source.id : link.source);
      connectedNodeIds.add(typeof link.target === 'object' ? link.target.id : link.target);
    });

    const filteredNodes = (clinicalGraph.nodes || []).filter(n => connectedNodeIds.has(n.id));
    return { nodes: filteredNodes, links: filteredLinks };
  }, [clinicalGraph, minStrength]);

  // Configure forces and zoom to fit when data changes.
  // Layout tuning per the first-principles audit: the previous settings
  // caused a center-pile-up when the biomarker hub attracted many therapy
  // nodes. Stronger repulsion, label-aware collision, weaker center pull,
  // and a gentle axis force give each entity breathing room.
  useEffect(() => {
    if (fgRef.current && filteredData.nodes.length) {
      const fg = fgRef.current;
      fg.d3Force('charge').strength(-700).distanceMax(700);
      fg.d3Force('link')
        .distance(link => {
          if (link.type === 'has_biomarker') return 90;
          return 140 + (200 - Math.min(link.strength || 0, 150)) * 0.6;
        })
        .strength(link => link.type === 'has_biomarker' ? 0.25 : 0.5);
      fg.d3Force('center', d3Force.forceCenter(0, 0).strength(0.03));
      fg.d3Force('collision', d3Force.forceCollide()
        .radius(node => {
          const base = node.kind === 'biomarker' ? 34 : node.kind === 'therapy' ? 28 : 24;
          const labelPad = showLabels ? Math.min((node.label || node.id || '').length, 18) * 3 : 0;
          return base + labelPad;
        })
        .strength(1)
        .iterations(2));
      fg.d3Force('x', d3Force.forceX().strength(0.02));
      fg.d3Force('y', d3Force.forceY().strength(0.02));

      setTimeout(() => {
        fg.zoomToFit(500, 80);
      }, 1200);
    }
  }, [filteredData, showLabels]);

  const paintNode = useCallback((node, ctx, globalScale) => {
    const isSelected = selectedNode?.id === node.id;
    const baseSize = node.kind === 'biomarker' ? 12 : node.kind === 'therapy' ? 10 : 8;
    const size = isSelected ? baseSize * 1.3 : baseSize;
    
    if (isSelected) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, size + 4, 0, 2 * Math.PI);
      ctx.fillStyle = 'rgba(37, 99, 235, 0.2)';
      ctx.fill();
    }
    
    ctx.beginPath();
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
    ctx.fillStyle = NODE_COLORS[node.kind] || '#64748b';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();
    
    if (isSelected) {
      ctx.strokeStyle = '#1e40af';
      ctx.lineWidth = 3;
      ctx.stroke();
    }
    
    if (showLabels && globalScale > 0.5) {
      const label = node.label.length > 20 ? node.label.slice(0, 18) + '...' : node.label;
      const fontSize = Math.max(11 / globalScale, 4);
      ctx.font = `600 ${fontSize}px Inter, system-ui, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      
      const textWidth = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.fillRect(node.x - textWidth/2 - 2, node.y + size + 2, textWidth + 4, fontSize + 2);
      
      ctx.fillStyle = '#1e293b';
      ctx.fillText(label, node.x, node.y + size + 3);
    }
  }, [selectedNode, showLabels]);

  const paintLink = useCallback((link, ctx) => {
    const start = link.source;
    const end = link.target;
    if (!start.x || !end.x) return;
    
    const color = getEdgeColor(link.type, link.strength);
    const width = link.type === 'has_biomarker' ? 1 : Math.max(2, (link.strength || 0) / 40);
    
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    
    if (link.type === 'has_biomarker') {
      ctx.setLineDash([3, 3]);
    } else {
      ctx.setLineDash([]);
    }
    ctx.stroke();
    ctx.setLineDash([]);
    
    if (link.type !== 'has_biomarker') {
      const angle = Math.atan2(end.y - start.y, end.x - start.x);
      const arrowLen = 8;
      const endX = end.x - Math.cos(angle) * 12;
      const endY = end.y - Math.sin(angle) * 12;
      
      ctx.beginPath();
      ctx.moveTo(endX, endY);
      ctx.lineTo(endX - arrowLen * Math.cos(angle - Math.PI/6), endY - arrowLen * Math.sin(angle - Math.PI/6));
      ctx.lineTo(endX - arrowLen * Math.cos(angle + Math.PI/6), endY - arrowLen * Math.sin(angle + Math.PI/6));
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    }
  }, []);

  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node);
    setSelectedEdge(null);
  }, []);

  const handleLinkClick = useCallback((link) => {
    setSelectedEdge(link);
    setSelectedNode(null);
    if (onAssertionClick && link.assertion) {
      onAssertionClick(link.assertion);
    }
  }, [onAssertionClick]);

  if (!clinicalGraph?.nodes?.length) {
    return <EmptyState message="No clinical assertions to display" />;
  }

  return (
    <div className="kg-clinical-container">
      <div className="kg-clinical-graph">
        <div className="kg-graph-header">
          <h4>Clinical Assertion Map</h4>
          <div className="kg-graph-controls">
            <label className="kg-control">
              <span>Min Strength</span>
              <input
                type="range"
                min="0"
                max="150"
                step="10"
                value={minStrength}
                onChange={(e) => setMinStrength(parseInt(e.target.value))}
              />
              <span className="kg-control-value">{minStrength}</span>
            </label>
            <label className="kg-control-checkbox">
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
              />
              <span>Labels</span>
            </label>
          </div>
        </div>

        <GraphLegend items={[
          { color: NODE_COLORS.biomarker, label: 'Biomarker', shape: 'circle' },
          { color: NODE_COLORS.therapy, label: 'Therapy', shape: 'circle' },
          { color: NODE_COLORS.disease_state, label: 'Disease State', shape: 'circle' },
          { color: EDGE_COLORS.SENSITIVITY, label: 'Sensitivity', shape: 'line' },
          { color: EDGE_COLORS.RESISTANCE, label: 'Resistance', shape: 'line' },
        ]} />

        <div className="kg-graph-canvas" ref={canvasRef}>
          <ForceGraph2D
            ref={fgRef}
            graphData={filteredData}
            width={canvasSize.w}
            height={canvasSize.h}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              ctx.beginPath();
              ctx.arc(node.x, node.y, 20, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkCanvasObject={paintLink}
            linkPointerAreaPaint={(link, color, ctx) => {
              const start = link.source;
              const end = link.target;
              if (!start.x || !end.x) return;
              ctx.beginPath();
              ctx.moveTo(start.x, start.y);
              ctx.lineTo(end.x, end.y);
              ctx.strokeStyle = color;
              ctx.lineWidth = 10;
              ctx.stroke();
            }}
            onNodeClick={handleNodeClick}
            onLinkClick={handleLinkClick}
            onNodeHover={node => document.body.style.cursor = node ? 'pointer' : 'default'}
            onLinkHover={link => document.body.style.cursor = link ? 'pointer' : 'default'}
            onEngineStop={() => {
              // Auto-fit the view when simulation settles
              if (fgRef.current) {
                fgRef.current.zoomToFit(300, 50);
              }
            }}
            cooldownTicks={400}
            warmupTicks={100}
            d3AlphaDecay={0.0228}
            d3VelocityDecay={0.4}
            minZoom={0.2}
            maxZoom={6}
          />
        </div>
      </div>

      <div className="kg-clinical-sidebar">
        {selectedEdge && selectedEdge.assertion && (
          <div className="kg-detail-card">
            <h5>Assertion</h5>
            <div className="kg-assertion-summary">{selectedEdge.assertion.summary}</div>
            
            <div className="kg-assertion-meta">
              <span className={`kg-sig-badge ${selectedEdge.type?.toLowerCase()}`}>
                {selectedEdge.type}
              </span>
              <span className="kg-level-badge" style={{ background: getEvidenceLevelColor(selectedEdge.evidence_level) }}>
                Level {selectedEdge.evidence_level}
              </span>
              <span className="kg-strength-badge">{formatStrength(selectedEdge.strength)}</span>
            </div>

            <div className="kg-assertion-stats">
              <div className="kg-stat-item">
                <span className="kg-stat-num">{selectedEdge.num_papers || 0}</span>
                <span className="kg-stat-label">Papers</span>
              </div>
              <div className="kg-stat-item">
                <span className="kg-stat-num">{selectedEdge.total_cohort || 0}</span>
                <span className="kg-stat-label">Patients</span>
              </div>
              <div className="kg-stat-item">
                <span className="kg-stat-num">{selectedEdge.strength || 0}</span>
                <span className="kg-stat-label">Strength</span>
              </div>
            </div>

            {selectedEdge.assertion.supporting_evidence?.length > 0 && (
              <div className="kg-evidence-list">
                <h6>Supporting Evidence ({selectedEdge.assertion.supporting_evidence.length})</h6>
                {selectedEdge.assertion.supporting_evidence.slice(0, 5).map((ev, idx) => (
                  <div key={idx} className="kg-evidence-item">
                    <div className="kg-evidence-header">
                      <span className="kg-pmid">PMID {ev.pmid || ev.__paperId}</span>
                      {ev.cohort_size > 0 && <span className="kg-cohort">n={ev.cohort_size}</span>}
                    </div>
                    {ev.verbatim_quote && (
                      <div className="kg-evidence-quote">"{ev.verbatim_quote.slice(0, 120)}..."</div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {selectedNode && (
          <div className="kg-detail-card">
            <h5>{selectedNode.kind.charAt(0).toUpperCase() + selectedNode.kind.slice(1)}</h5>
            <div className="kg-node-name">{selectedNode.label}</div>
            {selectedNode.gene && <div className="kg-node-detail">Gene: {selectedNode.gene}</div>}
            {selectedNode.variant && <div className="kg-node-detail">Variant: {selectedNode.variant}</div>}
          </div>
        )}

        {!selectedEdge && !selectedNode && (
          <div className="kg-placeholder">
            <div className="kg-placeholder-icon">🎯</div>
            <div className="kg-placeholder-text">Click a node or edge to see details</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// VIEW 3: EVIDENCE MATRIX
// ============================================================================

export function MatrixView({ clinicalGraph }) {
  const [selectedCell, setSelectedCell] = useState(null);
  const [sortBy, setSortBy] = useState('strength');

  const { biomarkers, therapies, matrix, maxStrength } = useMemo(() => {
    if (!clinicalGraph?.assertions) return { biomarkers: [], therapies: [], matrix: new Map(), maxStrength: 1 };
    
    const biomarkerMap = new Map();
    const therapySet = new Set();
    const matrixMap = new Map();
    let max = 1;

    clinicalGraph.assertions.forEach(assertion => {
      if (!assertion.therapy) return;
      
      if (!biomarkerMap.has(assertion.biomarker)) {
        biomarkerMap.set(assertion.biomarker, { name: assertion.biomarker, totalStrength: 0, count: 0 });
      }
      const bm = biomarkerMap.get(assertion.biomarker);
      bm.totalStrength += assertion.supporting_evidence?.reduce((sum, e) => sum + (e.cohort_size || 0), 0) || 0;
      bm.count++;

      therapySet.add(assertion.therapy);

      const key = `${assertion.biomarker}|${assertion.therapy}`;
      if (!matrixMap.has(key)) {
        matrixMap.set(key, { 
          biomarker: assertion.biomarker, 
          therapy: assertion.therapy,
          assertions: [],
          strength: 0,
          significance: assertion.significance
        });
      }
      const cell = matrixMap.get(key);
      cell.assertions.push(assertion);
      const linkStrength = clinicalGraph.links?.find(l => l.assertion?.key === assertion.key)?.strength || 0;
      cell.strength = Math.max(cell.strength, linkStrength);
      if (cell.strength > max) max = cell.strength;
    });

    const sortedBiomarkers = Array.from(biomarkerMap.values())
      .sort((a, b) => sortBy === 'strength' ? b.totalStrength - a.totalStrength : b.count - a.count)
      .map(b => b.name);

    return { 
      biomarkers: sortedBiomarkers, 
      therapies: Array.from(therapySet).sort(), 
      matrix: matrixMap,
      maxStrength: max
    };
  }, [clinicalGraph, sortBy]);

  const getCellStyle = (strength) => {
    if (strength === 0) return { background: '#f8fafc' };
    const intensity = Math.min(strength / maxStrength, 1);
    return { 
      background: `hsla(145, 70%, ${85 - intensity * 35}%, 1)`,
      fontWeight: intensity > 0.5 ? '600' : '400'
    };
  };

  if (!biomarkers.length || !therapies.length) {
    return <EmptyState message="No biomarker-therapy associations found" />;
  }

  return (
    <div className="kg-matrix-container">
      <div className="kg-matrix-main">
        <div className="kg-matrix-header">
          <h4>Evidence Matrix</h4>
          <div className="kg-matrix-controls">
            <label>
              Sort by:
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
                <option value="strength">Evidence Strength</option>
                <option value="count">Association Count</option>
              </select>
            </label>
          </div>
        </div>

        <div className="kg-matrix-scroll">
          <table className="kg-matrix-table">
            <thead>
              <tr>
                <th className="kg-matrix-corner">Biomarker \ Therapy</th>
                {therapies.map(therapy => (
                  <th key={therapy} className="kg-matrix-therapy-header">
                    <div className="kg-matrix-therapy-label">{therapy}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {biomarkers.map(biomarker => (
                <tr key={biomarker}>
                  <td className="kg-matrix-biomarker">{biomarker}</td>
                  {therapies.map(therapy => {
                    const key = `${biomarker}|${therapy}`;
                    const cell = matrix.get(key);
                    const isSelected = selectedCell?.biomarker === biomarker && selectedCell?.therapy === therapy;
                    
                    return (
                      <td
                        key={therapy}
                        className={`kg-matrix-cell ${isSelected ? 'selected' : ''} ${cell ? 'has-data' : ''}`}
                        style={getCellStyle(cell?.strength || 0)}
                        onClick={() => cell && setSelectedCell({ biomarker, therapy, ...cell })}
                      >
                        {cell && (
                          <div className="kg-matrix-cell-content">
                            <span className={`kg-matrix-sig ${cell.significance?.toLowerCase()}`}>
                              {cell.significance?.slice(0, 3) || '•'}
                            </span>
                            <span className="kg-matrix-count">{cell.assertions.length}</span>
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="kg-matrix-legend">
          <span className="kg-matrix-legend-item">
            <span className="kg-matrix-legend-box" style={{ background: '#dcfce7' }}></span>
            Weak
          </span>
          <span className="kg-matrix-legend-item">
            <span className="kg-matrix-legend-box" style={{ background: '#86efac' }}></span>
            Moderate
          </span>
          <span className="kg-matrix-legend-item">
            <span className="kg-matrix-legend-box" style={{ background: '#22c55e' }}></span>
            Strong
          </span>
        </div>
      </div>

      <div className="kg-matrix-sidebar">
        {selectedCell ? (
          <div className="kg-detail-card">
            <h5>Association Details</h5>
            <div className="kg-association-pair">
              <span className="kg-biomarker-tag">{selectedCell.biomarker}</span>
              <span className="kg-arrow">→</span>
              <span className="kg-therapy-tag">{selectedCell.therapy}</span>
            </div>
            
            <div className="kg-association-sig">
              <span className={`kg-sig-badge ${selectedCell.significance?.toLowerCase()}`}>
                {selectedCell.significance}
              </span>
            </div>

            <div className="kg-assertions-list">
              <h6>{selectedCell.assertions.length} Assertion(s)</h6>
              {selectedCell.assertions.map((assertion, idx) => (
                <div key={idx} className="kg-assertion-item">
                  <div className="kg-assertion-summary-small">{assertion.summary}</div>
                  <div className="kg-assertion-papers">
                    {assertion.supporting_evidence?.length || 0} supporting papers
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="kg-placeholder">
            <div className="kg-placeholder-icon">📋</div>
            <div className="kg-placeholder-text">Click a cell to see association details</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// VIEW 4: DISEASE EVOLUTION
// ============================================================================

export function DiseaseEvolutionView({ clinicalGraph }) {
  const [selectedTransition, setSelectedTransition] = useState(null);
  const [expandedState, setExpandedState] = useState(null);

  const stateOrder = ['MGUS', 'MM', 'RRMM', 'extramedullary'];
  
  const stateData = useMemo(() => {
    if (!clinicalGraph?.assertions) return {};
    
    const states = {};
    stateOrder.forEach(s => {
      states[s] = { biomarkers: new Map(), assertions: [], therapies: new Set() };
    });

    clinicalGraph.assertions.forEach(assertion => {
      const state = assertion.disease_state;
      if (states[state]) {
        states[state].assertions.push(assertion);
        
        if (!states[state].biomarkers.has(assertion.biomarker)) {
          states[state].biomarkers.set(assertion.biomarker, []);
        }
        states[state].biomarkers.get(assertion.biomarker).push(assertion);
        
        if (assertion.therapy) {
          states[state].therapies.add(assertion.therapy);
        }
      }
    });

    return states;
  }, [clinicalGraph]);

  const transitions = useMemo(() => {
    const transitionMap = new Map();
    const allBiomarkers = new Set();

    Object.values(stateData).forEach(state => {
      if (state.biomarkers) {
        state.biomarkers.forEach((_, biomarker) => allBiomarkers.add(biomarker));
      }
    });

    allBiomarkers.forEach(biomarker => {
      const presentIn = stateOrder.filter(state => stateData[state]?.biomarkers?.has(biomarker));
      if (presentIn.length > 1) {
        transitionMap.set(biomarker, presentIn);
      }
    });

    return Array.from(transitionMap.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [stateData]);

  return (
    <div className="kg-evolution-container">
      <div className="kg-evolution-timeline">
        {stateOrder.map((state, idx) => {
          const data = stateData[state] || { assertions: [], biomarkers: new Map(), therapies: new Set() };
          const isExpanded = expandedState === state;
          
          return (
            <React.Fragment key={state}>
              <div 
                className={`kg-evolution-stage ${isExpanded ? 'expanded' : ''}`}
                onClick={() => setExpandedState(isExpanded ? null : state)}
              >
                <div className="kg-stage-header">
                  <span className="kg-stage-name">{state}</span>
                  <span className="kg-stage-count">{data.assertions.length}</span>
                </div>
                <div className="kg-stage-stats">
                  <span>{data.biomarkers.size} biomarkers</span>
                  <span>{data.therapies.size} therapies</span>
                </div>
                
                {isExpanded && (
                  <div className="kg-stage-details">
                    <div className="kg-stage-biomarkers">
                      {Array.from(data.biomarkers.keys()).slice(0, 6).map(b => (
                        <span key={b} className="kg-mini-tag">{b}</span>
                      ))}
                      {data.biomarkers.size > 6 && (
                        <span className="kg-mini-tag more">+{data.biomarkers.size - 6}</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
              
              {idx < stateOrder.length - 1 && (
                <div className="kg-evolution-arrow"><span>→</span></div>
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div className="kg-evolution-content">
        <div className="kg-transitions-panel">
          <h5>Progression Biomarkers ({transitions.length})</h5>
          <p className="kg-transitions-desc">Biomarkers found across multiple disease stages</p>
          
          <div className="kg-transitions-list">
            {transitions.map(([biomarker, states]) => (
              <div
                key={biomarker}
                className={`kg-transition-card ${selectedTransition === biomarker ? 'selected' : ''}`}
                onClick={() => setSelectedTransition(selectedTransition === biomarker ? null : biomarker)}
              >
                <div className="kg-transition-biomarker">{biomarker}</div>
                <div className="kg-transition-states">
                  {states.map((state, idx) => (
                    <React.Fragment key={state}>
                      <span className="kg-transition-state">{state}</span>
                      {idx < states.length - 1 && <span className="kg-transition-arrow">→</span>}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            ))}
            
            {transitions.length === 0 && (
              <div className="kg-no-transitions">No biomarkers span multiple disease states</div>
            )}
          </div>
        </div>

        {selectedTransition && (
          <div className="kg-transition-detail">
            <h5>{selectedTransition} Across Disease States</h5>
            
            <div className="kg-transition-timeline">
              {stateOrder.map(state => {
                const assertions = stateData[state]?.biomarkers?.get(selectedTransition) || [];
                if (assertions.length === 0) return null;
                
                return (
                  <div key={state} className="kg-transition-state-block">
                    <div className="kg-state-label">{state}</div>
                    <div className="kg-state-assertions">
                      {assertions.map((assertion, idx) => (
                        <div key={idx} className="kg-mini-assertion">
                          <span className={`kg-mini-sig ${assertion.significance?.toLowerCase()}`}>
                            {assertion.significance}
                          </span>
                          {assertion.therapy && (
                            <span className="kg-mini-therapy">{assertion.therapy}</span>
                          )}
                          <span className="kg-mini-papers">
                            {assertion.supporting_evidence?.length || 0} papers
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
