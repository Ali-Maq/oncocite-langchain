import { useEffect, useMemo, useState, Component } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import "./App.css";
import {
  normalizeEvidenceItems,
  getSignificanceColor,
  getNodeColor,
  calculateEvidenceWeight
} from "./utils/normalize";
import { ResearchContext, TierFieldExplainer, TraceabilityBadge } from "./ResearchContext";
import { buildKnowledgeGraphs } from "./knowledgeGraph";
import { ClinicalMapView, MatrixView } from "./KnowledgeGraphViews";
import LandingPage from "./LandingPage";

// Paper ID → human-readable citation. Raw folder IDs (DOIs, lab-named slugs)
// are unreadable for reviewers; this maps them to "Author et al., Year
// (Venue)" form. PMID folders are rendered as "PMID 12345678".
const PAPER_CITATIONS = {
  "s41591-023-02491-5":               { author: "Da Vià et al.",    year: 2023, venue: "Nature Medicine" },
  "s43018-023-00625-9":               { author: "Derrien et al.",   year: 2023, venue: "Nature Cancer" },
  "Dutta_et_al-2024-Blood_Neoplasia": { author: "Dutta et al.",     year: 2024, venue: "Blood Neoplasia" },
  "Restrepo_et_al_selinexor":         { author: "Restrepo et al.",  year: 2022, venue: "JCO Precision Oncology" },
  "Elnaggar_et_al":                   { author: "Elnaggar et al.",  year: 2022, venue: "J Hematol Oncol" },
};

const formatPaperTitle = (id) => {
  if (!id) return "";
  if (id.startsWith("PMID_")) return id.replace("PMID_", "PMID ");
  const c = PAPER_CITATIONS[id];
  return c ? `${c.author}, ${c.year}` : id;
};

const formatPaperVenue = (id) => {
  if (!id) return "";
  if (id.startsWith("PMID_")) return null;
  const c = PAPER_CITATIONS[id];
  return c ? c.venue : null;
};

// Error Boundary Component — graceful fallback instead of a scary red banner
// when the PDF viewer or a child component throws transiently (common during
// React 19 concurrent double-renders while the PDF.js worker is initializing).
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null, errorInfo: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    console.error("Error caught by boundary:", error, errorInfo);
    this.setState({ error, errorInfo });
  }

  render() {
    if (this.state.hasError) {
      const fallbackUrl = this.props.fallbackUrl;
      return (
        <div style={{
          padding: "18px 16px",
          background: "#fff8f1",
          border: "1px solid #f3d9bf",
          borderRadius: "8px",
          margin: "8px",
          fontSize: "13px",
          lineHeight: "1.5",
          color: "#3f2e1a",
        }}>
          <div style={{ fontWeight: 600, marginBottom: "6px" }}>
            PDF viewer hiccup
          </div>
          <div className="muted small" style={{ marginBottom: "10px" }}>
            This component recovered from a transient render error (often a React
            concurrent double-render while PDF.js is initializing). The paper and
            the extracted evidence are still available.
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            {fallbackUrl && (
              <a className="pill link-pill" href={fallbackUrl} target="_blank" rel="noreferrer">
                Open PDF in new tab
              </a>
            )}
            <button
              className="pill"
              onClick={() => this.setState({ hasError: false, error: null, errorInfo: null })}
            >
              Retry
            </button>
            <button
              className="pill"
              onClick={() => window.location.reload()}
            >
              Reload workspace
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

// Configure PDF.js worker the Vite way - let Vite resolve the worker from pdfjs-dist
// This is more reliable than serving from /public
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url
).toString();
console.log("[PDF] Worker configured:", pdfjs.GlobalWorkerOptions.workerSrc);
console.log("[PDF] pdfjs version:", pdfjs.version);

// Use relative URLs for API calls (works with Nginx proxy in production)
// In dev, Vite proxy will forward to localhost:4177
const API_BASE = import.meta.env.VITE_API_BASE || "";
async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function parseTrials(nctRaw) {
  if (!nctRaw) return [];
  const toList = Array.isArray(nctRaw)
    ? nctRaw
    : typeof nctRaw === "string"
      ? nctRaw.split(/[\n;,|]/)
      : [];
  return toList
    .map((v) => (typeof v === "string" ? v.trim() : String(v).trim()))
    .filter(Boolean)
    .map((line) => {
      const m = line.match(/(NCT\d{4,10})(.*)/i);
      const id = m ? m[1].toUpperCase() : line;
      const rest = m ? m[2].trim() : "";
      const desc = rest.replace(/^[\s:–-]+/, "").trim();
      return { id, desc };
    });
}

export const Pill = ({ children, kind = "default" }) => (
  <span className={`pill ${kind}`}>{children}</span>
);

const SectionHeader = ({ title, right }) => (
  <div className="panel-header">
    <h3>{title}</h3>
    <div className="panel-actions">{right}</div>
  </div>
);

function EvidenceTable({ items }) {
  if (!items?.length) {
    return <div className="muted">No evidence items found.</div>;
  }

  return (
    <div className="evidence-grid">
      {items.map((item, idx) => (
        <div key={idx} className="evidence-item">
          <div className="evidence-header">
            <div className="evidence-main">
              <span className="gene-badge">{(item.feature_names || []).join(", ") || "—"}</span>
              <span className="variant-badge">{(item.variant_names || []).join(", ") || "—"}</span>
              {item.therapy_names && item.therapy_names.length > 0 && (
                <span className="therapy-badge">{item.therapy_names.join(", ")}</span>
              )}
            </div>
            <div className="evidence-tags">
              <Pill kind={item.evidence_direction === "SUPPORTS" ? "success" : "warning"}>
                {item.evidence_type || "—"} • Level {item.evidence_level || "—"}
              </Pill>
              {item.evidence_significance && (
                <Pill kind={
                  item.evidence_significance.includes("SENSITIVITY") || item.evidence_significance.includes("BETTER")
                    ? "success"
                    : item.evidence_significance.includes("RESISTANCE") || item.evidence_significance.includes("POOR")
                    ? "error"
                    : "default"
                }>
                  {item.evidence_significance}
                </Pill>
              )}
            </div>
          </div>

          <div className="evidence-body">
            <div className="evidence-row">
              <div className="evidence-col">
                <span className="label-sm">Disease</span>
                <span className="value-sm">{item.disease_name || "—"}</span>
              </div>
              {item.cohort_size && (
                <div className="evidence-col">
                  <span className="label-sm">Cohort</span>
                  <span className="value-sm">{item.cohort_size} patients</span>
                </div>
              )}
              {item.extraction_confidence && (
                <div className="evidence-col">
                  <span className="label-sm">Confidence</span>
                  <span className="value-sm">
                    {typeof item.extraction_confidence === "number"
                      ? `${Math.round(item.extraction_confidence * 100)}%`
                      : item.extraction_confidence}
                  </span>
                </div>
              )}
              {item.source_page_numbers && (
                <div className="evidence-col">
                  <span className="label-sm">Pages</span>
                  <span className="value-sm">{item.source_page_numbers}</span>
                </div>
              )}
            </div>

            {item.verbatim_quote && (
              <div className="evidence-quote">
                <span className="quote-icon">💬</span>
                <span className="quote-text">"{item.verbatim_quote}"</span>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function PdfViewer({ url, onError }) {
  const [numPages, setNumPages] = useState(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [scale, setScale] = useState(1.0);
  const [workerReady, setWorkerReady] = useState(false);

  // Ensure worker is initialized before rendering Document
  useEffect(() => {
    console.log("[PdfViewer] Component mounted, checking worker...");
    console.log("[PdfViewer] URL:", url);

    const checkWorker = async () => {
      try {
        // Verify worker is configured
        if (!pdfjs.GlobalWorkerOptions.workerSrc) {
          console.error("[PDF] Worker not configured!");
          setError("PDF worker not configured");
          return;
        }

        console.log("[PDF] Worker ready:", pdfjs.GlobalWorkerOptions.workerSrc);
        console.log("[PDF] pdfjs version:", pdfjs.version);
        setWorkerReady(true);
      } catch (err) {
        console.error("[PDF] Worker initialization error:", err);
        setError("Failed to initialize PDF worker");
      }
    };

    // Small delay to ensure worker script is loaded
    const timer = setTimeout(checkWorker, 100);
    return () => clearTimeout(timer);
  }, [url]);

  if (!url) return <div className="muted">PDF not available.</div>;
  if (!workerReady) return <div className="muted">Initializing PDF viewer...</div>;
  if (error) {
    if (onError) onError(error);
    return (
      <div style={{ padding: "20px", background: "#fee", border: "1px solid #f00", borderRadius: "8px" }}>
        <p><strong>PDF Error:</strong> {error}</p>
        <p className="small">The PDF viewer encountered an error. You can:</p>
        <ul className="small">
          <li>Try opening the PDF in a new tab using the link below</li>
          <li>Check browser console for detailed error messages</li>
        </ul>
        <a className="pill link-pill" href={url} target="_blank" rel="noreferrer" style={{ marginTop: "8px", display: "inline-block" }}>
          Open PDF in new tab
        </a>
      </div>
    );
  }

  const next = () => setPage((p) => Math.min((numPages || p), p + 1));
  const prev = () => setPage((p) => Math.max(1, p - 1));
  const zoomIn = () => setScale((s) => Math.min(s + 0.2, 2.0));
  const zoomOut = () => setScale((s) => Math.max(s - 0.2, 0.5));

  return (
    <div className="pdf-viewer">
      <div className="pdf-controls">
        <button className="pill" onClick={prev} disabled={page <= 1}>
          ◀ Prev
        </button>
        <span className="muted small">
          Page {page} {numPages ? `of ${numPages}` : ""}
        </span>
        <button className="pill" onClick={next} disabled={numPages ? page >= numPages : false}>
          Next ▶
        </button>
        <button className="pill" onClick={zoomOut} disabled={scale <= 0.5}>
          Zoom -
        </button>
        <span className="muted small">{Math.round(scale * 100)}%</span>
        <button className="pill" onClick={zoomIn} disabled={scale >= 2.0}>
          Zoom +
        </button>
        <a className="pill link-pill" href={url} target="_blank" rel="noreferrer">
          Open in new tab
        </a>
      </div>
      <div className="pdf-canvas">
        <ErrorBoundary key={url} fallbackUrl={url}>
          <Document
            key={url}
            file={{ url, httpHeaders: { Accept: "application/pdf" }, withCredentials: false }}
            onLoadSuccess={({ numPages: n }) => {
              console.log("[PDF] Loaded successfully, pages:", n);
              setNumPages(n);
              setError("");
            }}
            onLoadError={(err) => {
              console.error("[PDF] Load error:", err);
              setError(err?.message || "Failed to load PDF");
            }}
            loading={<div className="muted">Loading PDF...</div>}
            error={
              <div className="muted" style={{ padding: "20px", background: "#fee", border: "1px solid #f00" }}>
                <p>Failed to load PDF</p>
                <p className="small">The PDF worker may not be initialized correctly.</p>
                <p className="small">Try opening the PDF in a new tab using the button above.</p>
              </div>
            }
          >
            <Page
              pageNumber={page}
              scale={scale}
              renderAnnotationLayer={false}
              renderTextLayer={false}
              onLoadError={(err) => {
                console.error("[PDF] Page load error:", err);
                setError("Failed to render PDF page. Try opening in a new tab.");
              }}
              onRenderError={(err) => {
                console.error("[PDF] Page render error:", err);
                setError("Failed to render PDF page. Try opening in a new tab.");
              }}
            />
          </Document>
        </ErrorBoundary>
      </div>
    </div>
  );
}

function EvidenceCards({ items }) {
  if (!items?.length) return <div className="muted">No evidence items found.</div>;
  const normalize = (item) => ({
    ...item,
    therapies: item.therapies || [],
    therapy_names: item.therapy_names || (item.therapies ? item.therapies.map((t) => t.name) : []),
    variant_hgvs_descriptions: item.variant_hgvs_descriptions || item.variant_hgvs || [],
    clinical_trial_nct_ids: item.clinical_trial_nct_ids || [],
  });
  return (
    <div className="card-grid">
      {items.map((raw, idx) => {
        const it = normalize(raw);
        return (
          <div className="card evidence-card" key={idx}>
            <div className="card-title">{(it.feature_names && it.feature_names.join?.(", ")) || "—"}</div>
            <div className="muted small strong">{(it.variant_names && it.variant_names.join?.(", ")) || "—"}</div>
            <div className="pill-row">
              <Pill>{it.evidence_type || "—"}</Pill>
              <Pill>{it.evidence_level || "—"}</Pill>
              <Pill>{it.evidence_direction || "—"}</Pill>
              <Pill>{it.evidence_significance || "—"}</Pill>
            </div>
            <div className="kv">
              <span className="label">Disease</span>
              <span>{it.disease_name || "—"}</span>
            </div>
            <div className="kv">
              <span className="label">Therapy</span>
              <span>{(it.therapy_names && it.therapy_names.join?.(", ")) || "—"}</span>
            </div>
            <div className="kv">
              <span className="label">Trials</span>
              <span>{it.clinical_trial_nct_ids.length ? it.clinical_trial_nct_ids.join(", ") : "—"}</span>
            </div>
            <div className="kv">
              <span className="label">Coords</span>
              <span>
                {it.reference_build || "—"} · {it.chromosome || "—"}:{it.start_position || "—"}-{it.stop_position || "—"}
              </span>
            </div>
            <div className="kv">
              <span className="label">HGVS</span>
              <span>{it.variant_hgvs_descriptions.length ? it.variant_hgvs_descriptions.join(", ") : "—"}</span>
            </div>
            <div className="kv">
              <span className="label">CCF / Cohort</span>
              <span>
                {it.cancer_cell_fraction || "—"} / {it.cohort_size || "—"}
              </span>
            </div>
            <div className="kv">
              <span className="label">Source</span>
              <span>
                {it.source_title || "—"} ({it.source_journal || "—"}, {it.source_publication_year || "—"},{" "}
                {it.source_page_numbers || "—"})
              </span>
            </div>
            <div className="quote-block">
              <div className="label tiny">Quote</div>
              <div className="muted tiny ellipsis" title={it.verbatim_quote || ""}>
                “{it.verbatim_quote || "No quote"}”
              </div>
            </div>
            <div className="quote-block">
              <div className="label tiny">Reasoning</div>
              <div className="muted tiny">{it.extraction_reasoning || "No reasoning"}</div>
            </div>
            <div className="muted tiny">
              Confidence:{" "}
              {typeof it.extraction_confidence === "number"
                ? `${Math.round(it.extraction_confidence * 100)}%`
                : it.extraction_confidence || "—"}
            </div>
          </div>
        );
      })}
    </div>
  );
}
function Collapse({ title, summary, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card">
      <div className="collapse-header" onClick={() => setOpen((o) => !o)}>
        <div>
          <div className="card-title">{title}</div>
          {summary && <div className="muted small">{summary}</div>}
        </div>
        <div className="muted">{open ? "▲" : "▼"}</div>
      </div>
      {open && <div className="collapse-body">{children}</div>}
    </div>
  );
}

// Phase summaries/details replaced by CheckpointDeck for richer structured view.

function Timeline({ events }) {
  if (!events?.length) return <div className="muted">No timeline events.</div>;
  const recent = events.slice(-200);
  const grouped = recent.reduce((acc, ev) => {
    const key = ev.hook || ev.event || "other";
    acc[key] = acc[key] || [];
    acc[key].push(ev);
    return acc;
  }, {});
  return (
    <div className="timeline">
      {Object.entries(grouped).map(([hook, list]) => (
        <div className="timeline-group" key={hook}>
          <div className="timeline-group-header">
            <span className="pill">{hook}</span>
            <span className="muted small">{list.length} events</span>
                </div>
          {list.map((ev, idx) => (
            <div className="timeline-item" key={`${hook}-${idx}`}>
              <div className="timeline-meta">
                <span className="muted small">{ev.ts}</span>
                <span className="muted tiny">{ev.tool || "—"}</span>
              </div>
              <div className="timeline-body">
                <div className="muted small">input: {ev.input_keys?.join(", ") || "—"}</div>
                {ev.output_summary && <div className="muted small">result: {ev.output_summary}</div>}
                {ev.text && <div className="muted small">msg: {ev.text}</div>}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function TagList({ items, hrefBuilder, title }) {
  if (!items?.length) return <span className="muted">—</span>;
  return (
    <div className="tag-row" title={title}>
      {items.map((it) => (
        <a
          key={it}
          className="pill link-pill"
          href={hrefBuilder ? hrefBuilder(it) : undefined}
          target={hrefBuilder ? "_blank" : undefined}
          rel="noreferrer"
        >
          {it}
        </a>
        ))}
    </div>
    );
}

function PlanPanel({ plan }) {
  if (!plan) return null;
  return (
    <div className="panel">
      <SectionHeader title="Extraction Plan" />
      <div className="plan-grid">
        <div className="card">
          <div className="muted small">Expected items</div>
          <div className="big">{plan.expected_items ?? "—"}</div>
          <div className="muted small">{plan.paper_type || "Paper type unknown"}</div>
        </div>
        <div className="card">
          <div className="card-title">Key variants</div>
          <pre className="pre small">{plan.key_variants || "—"}</pre>
        </div>
        <div className="card">
          <div className="card-title">Key therapies</div>
          <pre className="pre small">{plan.key_therapies || "—"}</pre>
        </div>
        <div className="card">
          <div className="card-title">Key diseases</div>
          <pre className="pre small">{plan.key_diseases || "—"}</pre>
        </div>
      </div>
      <div className="card">
        <div className="card-title">Focus sections</div>
        <pre className="pre small">{plan.focus_sections || "—"}</pre>
      </div>
      <div className="card">
        <div className="card-title">Extraction notes</div>
        <pre className="pre small">{plan.extraction_notes || "—"}</pre>
      </div>
    </div>
  );
}

function CritiquePanel({ critique }) {
  if (!critique) return null;
  return (
    <div className="panel">
      <SectionHeader
        title="Final Critique"
        right={<Pill kind={critique.overall_assessment === "APPROVE" ? "success" : "warning"}>{critique.overall_assessment}</Pill>}
      />
      <div className="critique-grid">
        <Collapse title="Summary" defaultOpen>
          <pre className="pre small">{critique.summary || "No summary"}</pre>
      </Collapse>
        <Collapse title="Item feedback">
          <pre className="pre small">{critique.item_feedback || "No item feedback"}</pre>
      </Collapse>
        <Collapse title="Missing items">
          <pre className="pre small">{critique.missing_items || "No missing items"}</pre>
        </Collapse>
        <Collapse title="Extra items">
          <pre className="pre small">{critique.extra_items || "No extra items"}</pre>
        </Collapse>
      </div>
    </div>
  );
}

function StatsGrid({ evidence, defaultCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  if (!evidence?.length) return null;

  const geneCounts = {};
  const therapyCounts = {};
  const typeCounts = {};
  const directionCounts = {};
  evidence.forEach((item) => {
    (item.feature_names || []).forEach((g) => {
      geneCounts[g] = (geneCounts[g] || 0) + 1;
    });
    (item.therapy_names || []).forEach((t) => {
      therapyCounts[t] = (therapyCounts[t] || 0) + 1;
    });
    if (item.evidence_type) typeCounts[item.evidence_type] = (typeCounts[item.evidence_type] || 0) + 1;
    if (item.evidence_direction) directionCounts[item.evidence_direction] = (directionCounts[item.evidence_direction] || 0) + 1;
  });

  const top = (obj, n = 3) =>
    Object.entries(obj)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n);

  return (
    <div className="stats-section">
      <div className="stats-header" onClick={() => setCollapsed(!collapsed)}>
        <h4>Quick Stats</h4>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="muted small">
            {evidence.length} items · {Object.keys(geneCounts).length} genes · {Object.keys(therapyCounts).length} therapies
          </span>
          <button className="collapse-icon" onClick={(e) => { e.stopPropagation(); setCollapsed(!collapsed); }}>
            {collapsed ? "▼" : "▲"}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="stats-grid-dense">
          <div className="card">
            <div className="card-title">Top genes</div>
            <div className="tag-row">
              {top(geneCounts).map(([g, c]) => (
                <span key={g} className="pill">
                  {g} · {c}
                </span>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-title">Top therapies</div>
            <div className="tag-row">
              {top(therapyCounts).map(([t, c]) => (
                <span key={t} className="pill">
                  {t} · {c}
                </span>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-title">Types</div>
            <div className="tag-row">
              {Object.entries(typeCounts).map(([k, v]) => (
                <span key={k} className="pill">
                  {k} · {v}
                </span>
              ))}
            </div>
          </div>
          <div className="card">
            <div className="card-title">Directions</div>
            <div className="tag-row">
              {Object.entries(directionCounts).map(([k, v]) => (
                <span key={k} className="pill">
                  {k} · {v}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function CheckpointDeck({ phases, pdfUrl, onOpenRaw }) {
  console.log("[CheckpointDeck] Rendering with phases:", phases);

  const reader = phases?.reader;
  const planner = phases?.planner?.plan;
  const extractorItems = phases?.extractor?.items || [];
  const critic = phases?.critic?.critique;
  const normalizerItems = phases?.normalizer?.items || [];

  const topList = (items) => (items || []).slice(0, 3);

  // Check if we have any phase data
  const hasAnyData = reader || planner || extractorItems.length > 0 || critic || normalizerItems.length > 0;

  console.log("[CheckpointDeck] Has data?", hasAnyData, {
    reader: !!reader,
    planner: !!planner,
    extractor: extractorItems.length,
    critic: !!critic,
    normalizer: normalizerItems.length
  });

  if (!hasAnyData) {
    console.log("[CheckpointDeck] No data, showing fallback message");
    return (
      <div className="muted" style={{ padding: "20px", textAlign: "center" }}>
        <p>No checkpoint data available for this paper.</p>
        <p className="small">Checkpoints are created during the extraction process.</p>
      </div>
    );
  }

  console.log("[CheckpointDeck] Rendering checkpoint cards");

  return (
    <div className="deck-grid">
      <div className="card">
        <div className="card-title">Reader (01)</div>
        <div className="muted small">{reader?.content?.title || "—"}</div>
            <div className="muted small">
          {reader?.content?.journal || "—"} · {reader?.content?.year || "—"} · pgs {reader?.content?.num_pages || "—"}
            </div>
        <div className="muted small">Type: {reader?.content?.paper_type || "—"}</div>
            <div className="muted small">
          Sections: {
            Array.isArray(reader?.content?.sections)
              ? reader.content.sections.map((s) => s.name).join(", ")
              : typeof reader?.content?.sections === "string"
              ? "Available"
              : "—"
          }
            </div>
        <div className="muted small">
          NCT IDs: {reader?.content?.nct_ids ? JSON.stringify(reader.content.nct_ids) : "—"}
        </div>
        {pdfUrl && (
          <a className="pill link-pill" href={pdfUrl} target="_blank" rel="noreferrer">
            Open PDF
          </a>
        )}
        {onOpenRaw && (
          <button className="pill" onClick={() => onOpenRaw("Reader (01)", phases.reader)}>
            Raw Reader
          </button>
        )}
      </div>

      <div className="card">
        <div className="card-title">Planner (02)</div>
        <div className="muted small">Expected items: {planner?.expected_items ?? "—"}</div>
        <div className="muted small">Key variants: {planner?.key_variants || "—"}</div>
        <div className="muted small">Key therapies: {planner?.key_therapies || "—"}</div>
        <div className="muted small">Key diseases: {planner?.key_diseases || "—"}</div>
        <div className="muted small">Focus sections: {planner?.focus_sections || "—"}</div>
        {onOpenRaw && (
          <button className="pill" onClick={() => onOpenRaw("Planner (02)", phases.planner)}>
            Raw Planner
          </button>
        )}
      </div>

      <div className="card">
        <div className="card-title">Extractor (03)</div>
        <div className="muted small">Draft items: {extractorItems.length}</div>
        <ul className="plain-list small">
          {topList(extractorItems).map((it, idx) => (
            <li key={idx}>
              <strong>{it.feature_names?.join?.(", ") || "—"}</strong> · {it.variant_names?.join?.(", ") || "—"} ·{" "}
              {it.therapy_names?.join?.(", ") || "—"} · {it.disease_name || "—"} ({it.evidence_direction || "—"})
            </li>
          ))}
        </ul>
        {onOpenRaw && (
          <button className="pill" onClick={() => onOpenRaw("Extractor (03)", phases.extractor)}>
            Raw Extractor
          </button>
        )}
      </div>

      <div className="card">
        <div className="card-title">Critic (03b)</div>
        <div className="pill-row">
          <Pill kind={critic?.overall_assessment === "APPROVE" ? "success" : "warning"}>
            {critic?.overall_assessment || "—"}
          </Pill>
        </div>
        <div className="muted small">
          Missing: {critic?.missing_items ? critic.missing_items.length : 0} · Extra:{" "}
          {critic?.extra_items ? critic.extra_items.length : 0}
        </div>
        <div className="muted tiny ellipsis" title={critic?.summary || ""}>
          {critic?.summary || "No summary"}
        </div>
        {onOpenRaw && (
          <button className="pill" onClick={() => onOpenRaw("Critic (03b)", phases.critic)}>
            Raw Critic
          </button>
        )}
      </div>

      <div className="card">
        <div className="card-title">Normalizer (04)</div>
        <div className="muted small">Final items: {normalizerItems.length}</div>
        <ul className="plain-list small">
          {topList(normalizerItems).map((it, idx) => (
            <li key={idx}>
              <strong>{it.feature_names?.join?.(", ") || "—"}</strong> · {it.variant_names?.join?.(", ") || "—"} ·{" "}
              {it.therapy_names?.join?.(", ") || "—"} ({it.evidence_significance || "—"})
            </li>
          ))}
        </ul>
        {onOpenRaw && (
          <button className="pill" onClick={() => onOpenRaw("Normalizer (04)", phases.normalizer)}>
            Raw Normalizer
          </button>
        )}
      </div>
    </div>
  );
}

function JsonModal({ open, title, data, onClose }) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="card-title">{title}</div>
          <button className="pill" onClick={onClose}>
            Close
          </button>
          </div>
        <pre className="pre small modal-pre">{JSON.stringify(data, null, 2)}</pre>
            </div>
          </div>
  );
}

function CheckpointCards({ phases }) {
  const entries = [
    {
      key: "reader",
      title: "Reader (01)",
      summary: phases.reader?.summary,
      detail: phases.reader?.content?.title || "No title",
      meta: phases.reader?.content?.authors,
    },
    {
      key: "planner",
      title: "Planner (02)",
      summary: phases.planner?.summary,
      detail: phases.planner?.plan?.expected_items ? `Expected: ${phases.planner.plan.expected_items}` : "No plan",
      meta: phases.planner?.plan?.key_variants,
    },
    {
      key: "extractor",
      title: "Extractor (03)",
      summary: phases.extractor?.summary,
      detail: phases.extractor?.items ? `Draft items: ${phases.extractor.items.length}` : "No items",
      meta: phases.extractor?.items?.[0]?.disease_name,
    },
    {
      key: "critic",
      title: "Critic (03b)",
      summary: phases.critic?.summary,
      detail: phases.critic?.critique?.overall_assessment || "No critique",
      meta: phases.critic?.critique?.missing_items?.length
        ? `Missing: ${phases.critic.critique.missing_items.length}`
        : "",
    },
    {
      key: "normalizer",
      title: "Normalizer (04)",
      summary: phases.normalizer?.summary,
      detail: phases.normalizer?.items ? `Final items: ${phases.normalizer.items.length}` : "No items",
      meta: phases.normalizer?.items?.[0]?.therapy_names?.join(", "),
    },
  ];

  return (
    <div className="cp-card-grid">
      {entries.map((e) => (
        <div key={e.key} className="card cp-card">
          <div className="card-title">{e.title}</div>
          {e.summary && <div className="muted small">{e.summary}</div>}
          <div className="muted small">{e.detail || "—"}</div>
          {e.meta && <div className="muted tiny">{e.meta}</div>}
        </div>
      ))}
    </div>
  );
}

// Clinical Evidence Row Component
function ClinicalEvidenceRow({ item, onClick, selected }) {
  const gene = (item.feature_names || []).join(", ") || "—";
  const variant = (item.variant_names || []).join(", ") || "—";
  const therapy = (item.therapy_names || []).join(", ") || "—";
  const effect = item.evidence_significance || item.evidence_direction || "—";
  const level = item.evidence_level || "—";
  const confidence = typeof item.extraction_confidence === "number"
    ? `${Math.round(item.extraction_confidence * 100)}%`
    : item.extraction_confidence || "—";

  const getEffectClass = (effect) => {
    const effectUpper = String(effect).toUpperCase();
    if (effectUpper.includes("SENSITIVITY") || effectUpper.includes("BETTER") || effectUpper.includes("RESPONSE")) {
      return "sensitivity";
    }
    if (effectUpper.includes("RESISTANCE") || effectUpper.includes("POOR")) {
      return "resistance";
    }
    return "default";
  };

  return (
    <div
      className={`clinical-row ${selected ? "selected" : ""}`}
      onClick={() => onClick(item)}
    >
      <div className="clinical-row-main">
        <span className="gene-badge-compact">{gene}</span>
        <span className="variant-badge-compact">{variant}</span>
        {therapy && therapy !== "—" && (
          <>
            <span className="arrow">→</span>
            <span className="therapy-badge-compact">{therapy}</span>
          </>
        )}
        <span className="arrow">→</span>
        <span className={`effect-badge ${getEffectClass(effect)}`}>{effect}</span>
      </div>

      <div className="clinical-row-meta">
        <span className="muted small">{item.disease_name || "—"}</span>
        <span className="separator">•</span>
        <Pill kind="compact">Level {level}</Pill>
        <span className="separator">•</span>
        <Pill kind="compact">{confidence} confidence</Pill>
      </div>

      <div className="clinical-row-prov">
        {item.source_page_numbers && (
          <span className="muted tiny">📄 p.{item.source_page_numbers}</span>
        )}
        {item.pmid && (
          <span className="muted tiny">PMID:{item.pmid}</span>
        )}
      </div>
    </div>
  );
}

// Detail Field Component
function DetailField({ label, value, ids, hgvs, rxnorm, ncit, efo, norm }) {
  return (
    <div className="detail-field">
      <div className="detail-field-label">{label}</div>
      <div className="detail-field-value">{value || "—"}</div>
      {norm && norm !== value && (
        <div className="detail-field-ids">Normalized: {norm}</div>
      )}
      {ids && ids.length > 0 && (
        <div className="detail-field-ids">IDs: {ids.join(", ")}</div>
      )}
      {hgvs && hgvs.length > 0 && (
        <div className="detail-field-ids">HGVS: {hgvs.join(", ")}</div>
      )}
      {rxnorm && rxnorm.length > 0 && (
        <div className="detail-field-ids">RxNorm: {rxnorm.join(", ")}</div>
      )}
      {ncit && ncit.length > 0 && (
        <div className="detail-field-ids">NCIt: {ncit.join(", ")}</div>
      )}
      {efo && (
        <div className="detail-field-ids">EFO: {efo}</div>
      )}
    </div>
  );
}

// Evidence Detail Panel Component
// The 25 Tier-1 + 20 Tier-2 fields defined in Supp Tables S17 and S18.
// Every one of these must be surfaced on the detail panel (populated
// values shown verbatim, unpopulated values shown as "—") so a reviewer
// can see the 45-field schema is complete, not just the subset that
// happens to be non-empty for the selected item.
const TIER1_SECTIONS = [
  { title: "Core assertion (Tier-1 · 8)", fields: [
    { key: "feature_names",          label: "Gene(s)" },
    { key: "variant_names",          label: "Variant(s)" },
    { key: "disease_name",           label: "Disease" },
    { key: "evidence_type",          label: "Evidence type" },
    { key: "evidence_level",         label: "Evidence level" },
    { key: "evidence_direction",     label: "Evidence direction" },
    { key: "evidence_significance",  label: "Significance" },
    { key: "evidence_description",   label: "Description", long: true },
  ]},
  { title: "Variant (Tier-1 · 6)", fields: [
    { key: "variant_origin",               label: "Variant origin" },
    { key: "variant_type_names",           label: "Variant type" },
    { key: "variant_hgvs_descriptions",    label: "HGVS" },
    { key: "molecular_profile_name",       label: "Molecular profile" },
    { key: "fusion_five_prime_gene_names", label: "Fusion — 5′ partner" },
    { key: "fusion_three_prime_gene_names",label: "Fusion — 3′ partner" },
  ]},
  { title: "Feature (Tier-1 · 2)", fields: [
    { key: "feature_full_names", label: "Feature full name" },
    { key: "feature_types",      label: "Feature type" },
  ]},
  { title: "Disease, therapy, clinical trial, phenotype (Tier-1 · 6)", fields: [
    { key: "disease_display_name",     label: "Disease (display name)" },
    { key: "therapy_names",            label: "Therapy" },
    { key: "therapy_interaction_type", label: "Therapy interaction type" },
    { key: "clinical_trial_nct_ids",   label: "Clinical trial NCT ID(s)" },
    { key: "clinical_trial_names",     label: "Clinical trial name(s)" },
    { key: "phenotype_names",          label: "Phenotype(s)" },
  ]},
  { title: "Source (Tier-1 · 3)", fields: [
    { key: "source_title",            label: "Source title", long: true },
    { key: "source_publication_year", label: "Year" },
    { key: "source_journal",          label: "Journal" },
  ]},
];

const TIER2_SECTIONS = [
  { title: "Ontology identifiers (Tier-2 · 5)", fields: [
    { key: "disease_doid",        label: "DOID" },
    { key: "gene_entrez_ids",     label: "Entrez gene ID(s)" },
    { key: "therapy_ncit_ids",    label: "Therapy NCIt ID(s)" },
    { key: "factor_ncit_ids",     label: "Factor NCIt ID(s)" },
    { key: "variant_type_soids",  label: "Variant type SO ID(s)" },
  ]},
  { title: "Variant identifiers (Tier-2 · 4)", fields: [
    { key: "variant_clinvar_ids",            label: "ClinVar accession" },
    { key: "variant_allele_registry_ids",    label: "Allele registry ID" },
    { key: "variant_mane_select_transcripts",label: "MANE Select transcript" },
    { key: "variant_rsid",                   label: "dbSNP rsID" },
  ]},
  { title: "Phenotype identifiers (Tier-2 · 2)", fields: [
    { key: "phenotype_ids",     label: "Phenotype ID(s)" },
    { key: "phenotype_hpo_ids", label: "HPO ID(s)" },
  ]},
  { title: "Source identifiers (Tier-2 · 2)", fields: [
    { key: "source_citation_id", label: "PMID",  aliases: ["pmid", "source_pmid"] },
    { key: "source_pmcid",       label: "PMCID", aliases: ["pmcid"] },
  ]},
  { title: "Genomic coordinates (Tier-2 · 7)", fields: [
    { key: "chromosome",               label: "Chromosome" },
    { key: "start_position",           label: "Start position" },
    { key: "stop_position",            label: "Stop position" },
    { key: "reference_build",          label: "Reference build" },
    { key: "representative_transcript",label: "Representative transcript" },
    { key: "reference_bases",          label: "Reference bases" },
    { key: "variant_bases",            label: "Variant bases" },
  ]},
];

function renderFieldValue(item, field) {
  const candidates = [field.key, ...(field.aliases || [])];
  let v;
  for (const k of candidates) {
    if (item[k] !== undefined && item[k] !== null && item[k] !== "") { v = item[k]; break; }
  }
  if (v === undefined || v === null || v === "") return null;
  if (Array.isArray(v)) {
    const cleaned = v.filter(x => x !== null && x !== undefined && x !== "");
    return cleaned.length ? cleaned.join(", ") : null;
  }
  return String(v);
}

function populatedCount(item, sections) {
  let total = 0, filled = 0;
  for (const s of sections) {
    for (const f of s.fields) {
      total += 1;
      if (renderFieldValue(item, f) !== null) filled += 1;
    }
  }
  return { filled, total };
}

function FieldRow({ label, value }) {
  return (
    <div className="id-row" style={{ padding: "4px 0" }}>
      <span className="label-tiny" style={{ minWidth: 190 }}>{label}:</span>
      <span className="value-tiny" style={{ color: value === null ? "#94a3b8" : "#1f2937" }}>
        {value === null ? "—" : value}
      </span>
    </div>
  );
}

function SchemaSection({ item, section }) {
  return (
    <div className="detail-section">
      <h4>{section.title}</h4>
      <div className="id-list">
        {section.fields.map((f) => {
          const v = renderFieldValue(item, f);
          return <FieldRow key={f.key} label={f.label} value={v} />;
        })}
      </div>
    </div>
  );
}

function EvidenceDetailPanel({ item }) {
  const renderStars = (rating) => {
    if (!rating) return null;
    return "★".repeat(rating) + "☆".repeat(5 - rating);
  };

  const t1 = populatedCount(item, TIER1_SECTIONS);
  const t2 = populatedCount(item, TIER2_SECTIONS);

  return (
    <div className="detail-panel">
      {/* Evidence Summary with Rating */}
      {item.evidence_description && (
        <div className="detail-section" style={{ background: '#f8fafc', padding: '14px', borderRadius: '8px', marginBottom: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h4 style={{ margin: 0 }}>Evidence summary</h4>
            {item.evidence_rating && (
              <div style={{ color: '#f59e0b', fontSize: '16px', letterSpacing: '2px' }}>
                {renderStars(item.evidence_rating)}
              </div>
            )}
          </div>
          <div style={{ fontSize: '0.9375rem', lineHeight: '1.6', color: '#334155' }}>
            {item.evidence_description}
          </div>
        </div>
      )}

      {/* 45-field schema coverage pill strip */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '14px', flexWrap: 'wrap' }}>
        <Pill kind="default">Tier-1: {t1.filled}/{t1.total} fields populated</Pill>
        <Pill kind="default">Tier-2: {t2.filled}/{t2.total} fields populated</Pill>
        {typeof item.extraction_confidence === 'number' && (
          <Pill kind={item.extraction_confidence >= 0.9 ? 'success' : item.extraction_confidence >= 0.75 ? 'default' : 'warning'}>
            Confidence: {Math.round(item.extraction_confidence * 100)}%
          </Pill>
        )}
      </div>

      {/* Verbatim Quote — grounding evidence */}
      <div className="detail-section">
        <h4>Verbatim quote from source</h4>
        <div className="quote-box">
          "{item.verbatim_quote || "No quote available"}"
        </div>
        {item.source_page_numbers && (
          <div className="muted tiny" style={{ marginTop: '6px' }}>Source location: {item.source_page_numbers}</div>
        )}
      </div>

      {/* Extraction Reasoning (system-level, not in S17/S18) */}
      {item.extraction_reasoning && (
        <div className="detail-section">
          <h4>Extraction reasoning</h4>
          <p className="muted small" style={{ lineHeight: '1.6' }}>
            {item.extraction_reasoning}
          </p>
        </div>
      )}

      {/* 25 Tier-1 fields per Supp Table S17 */}
      <div style={{ background: '#f0f9ff', padding: '8px 10px', borderRadius: '6px', marginBottom: '8px' }}>
        <strong style={{ fontSize: '0.8125rem', color: '#0369a1' }}>
          Tier-1 · extraction fields (Supplementary Table S17) — {t1.filled}/{t1.total} populated
        </strong>
      </div>
      {TIER1_SECTIONS.map((s) => <SchemaSection key={s.title} item={item} section={s} />)}

      {/* 20 Tier-2 fields per Supp Table S18 */}
      <div style={{ background: '#f0fdf4', padding: '8px 10px', borderRadius: '6px', marginTop: '12px', marginBottom: '8px' }}>
        <strong style={{ fontSize: '0.8125rem', color: '#15803d' }}>
          Tier-2 · normalization fields (Supplementary Table S18) — {t2.filled}/{t2.total} populated
        </strong>
      </div>
      {TIER2_SECTIONS.map((s) => <SchemaSection key={s.title} item={item} section={s} />)}
    </div>
  );
}

// Evidence Split-Pane Component
function EvidenceSplitPane({ items, pdfUrl, filters, onFilterChange }) {
  // Default to first evidence item selected and PDF context pane open, so a
  // reviewer landing on the page sees the full system in one view without
  // needing to click through multiple UI states.
  const [selectedEvidence, setSelectedEvidence] = useState(null);
  const [showPdfPane, setShowPdfPane] = useState(true);
  useEffect(() => {
    if (!selectedEvidence && items && items.length > 0) {
      setSelectedEvidence(items[0]);
    }
  }, [items, selectedEvidence]);

  return (
    <div className="split-pane-container">
      <div className="evidence-list-pane">
        <div className="pane-header">
          <h4>Evidence Items ({items.length})</h4>
          <div style={{ display: 'flex', gap: '8px' }}>
            {filters}
            {pdfUrl && (
              <button
                className="pill"
                onClick={() => setShowPdfPane(!showPdfPane)}
                style={{ padding: '4px 10px', fontSize: '11px' }}
              >
                {showPdfPane ? "Hide" : "Show"} PDF
              </button>
            )}
          </div>
        </div>
        <div className="evidence-list-scroll">
          {items.length > 0 ? (
            items.map((item, idx) => (
              <ClinicalEvidenceRow
                key={idx}
                item={item}
                selected={selectedEvidence === item}
                onClick={setSelectedEvidence}
              />
            ))
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">🔍</div>
              <div>No evidence items found</div>
              <div className="muted tiny">Try adjusting your filters</div>
            </div>
          )}
        </div>
      </div>

      <div className="evidence-detail-pane">
        {selectedEvidence ? (
          <EvidenceDetailPanel item={selectedEvidence} />
        ) : (
          <div className="empty-state">
            <div className="empty-state-icon">👈</div>
            <div>Select an evidence item to view details</div>
            <div className="muted tiny">Click on any row in the list</div>
          </div>
        )}
      </div>

      {showPdfPane && pdfUrl && (
        <div className="pdf-context-pane">
          <div className="pane-header">
            <h4>PDF Context</h4>
            <button className="pill" onClick={() => setShowPdfPane(false)} style={{ padding: '4px 8px', fontSize: '11px' }}>✕</button>
          </div>
          <div style={{ height: 'calc(100% - 45px)', overflow: 'auto' }}>
            <PdfViewer
              url={pdfUrl}
              onError={(err) => console.error("PDF error:", err)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function App() {
  // Landing page is shown first so reviewers clicking the paper's demo URL
  // see the OncoCITE title card (paper, authors, DOI) before entering the
  // workspace. A single click on "Get Started" takes them to the three-pane
  // view with a paper pre-selected, PDF pane already open, and the first
  // evidence item highlighted — so the workspace is fully loaded on arrival.
  const [showLanding, setShowLanding] = useState(true);
  const [papers, setPapers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [output, setOutput] = useState(null);
  const [checkpoints, setCheckpoints] = useState([]);
  const [phases, setPhases] = useState({});
  const [sessionEvents, setSessionEvents] = useState([]);
  const [allEvidence, setAllEvidence] = useState([]);
  const [researchContextCollapsed, setResearchContextCollapsed] = useState(true);
  const [graphFilters, setGraphFilters] = useState({
    type: "ALL",
    direction: "ALL",
    search: "",
    diseaseScope: "MM_ONLY",
    minWeight: 0,
  });
  const [graphNode, setGraphNode] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [jsonModal, setJsonModal] = useState({ open: false, title: "", data: null });
  const [activeTab, setActiveTab] = useState("insights");
  // Default to the Evidence sub-tab so reviewers land on the split-pane view
  // (evidence list + PDF context side-by-side) — the canonical "see everything"
  // state shown in the paper's Supplementary Figure S3.
  const [insightsSubTab, setInsightsSubTab] = useState("evidence");
  const [kgView, setKgView] = useState("clinical"); // clinical, matrix
  const [viewMode, setViewMode] = useState("table");
  const [evidenceTypeFilter, setEvidenceTypeFilter] = useState("ALL");
  const [directionFilter, setDirectionFilter] = useState("ALL");
  const [searchTerm, setSearchTerm] = useState("");
  const [pdfStatus, setPdfStatus] = useState({ checked: false, available: false, error: "" });
  const [graphFullscreen, setGraphFullscreen] = useState(false);

  function parseCheckpoints(raw) {
    const phases = { reader: null, planner: null, extractor: null, critic: null, normalizer: null };
    for (const cp of raw || []) {
      if (!cp?.name) continue;
      const name = cp.name.toLowerCase();
      const data = cp.data || {};
      if (name.startsWith("01")) {
        const nct =
          data.paper_content?.clinical_trial_nct_ids ||
          data.paper_content?.clinical_trial_nct ||
          data.paper_content?.clinical_trials;
        phases.reader = {
          summary: data.paper_content?.title || "Reader output",
          content: {
            title: data.paper_content?.title,
            authors: data.paper_content?.authors,
            journal: data.paper_content?.journal,
            year: data.paper_content?.year,
            paper_type: data.paper_content?.paper_type,
            num_pages: data.paper_content?.num_pages,
            abstract: data.paper_content?.abstract,
            sections: data.paper_content?.sections?.slice?.(0, 2),
            nct_ids: nct,
          },
        };
      } else if (name.startsWith("02")) {
        phases.planner = {
          summary: data.plan ? `Planned: ${data.plan.expected_items || "?"}` : "Planner plan",
          plan: data.plan,
        };
      } else if (name.startsWith("03_critic") || name.startsWith("03-critic") || (name.includes("critic") && name.includes("03"))) {
        phases.critic = {
          summary: (data.critique && data.critique.overall_assessment) || "Critic feedback",
          critique: data.critique,
        };
      } else if (name.startsWith("03")) {
        const items = data.extraction?.draft_extractions || [];
        phases.extractor = {
          summary: `Draft items: ${items.length}`,
          items,
          raw: items,
        };
      } else if (name.startsWith("04")) {
        const items = data.final_extractions || data.extraction?.final_extractions || [];
        phases.normalizer = {
          summary: `Final: ${items.length}`,
          items,
          raw: items,
        };
      }
    }
    return phases;
  }

  useEffect(() => {
    fetchJson(`${API_BASE}/api/papers`)
      .then((data) => {
        const paperList = data.papers || [];
        setPapers(paperList);

        // Try to restore last selected paper from localStorage
        const savedPaper = localStorage.getItem('selectedPaper');
        if (savedPaper && paperList.some(p => p.id === savedPaper)) {
          console.log("[App] Restoring selected paper from localStorage:", savedPaper);
          setSelected(savedPaper);
        } else if (paperList.length > 0 && !selected) {
          // Only auto-select first paper if no saved selection
          console.log("[App] Auto-selecting first paper:", paperList[0].id);
          setSelected(paperList[0].id);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  // Save selected paper to localStorage whenever it changes
  useEffect(() => {
    if (selected) {
      console.log("[App] Saving selected paper to localStorage:", selected);
      localStorage.setItem('selectedPaper', selected);
    }
  }, [selected]);

  useEffect(() => {
    let canceled = false;
    const loadAll = async () => {
      try {
        const outputs = await Promise.all(
          (papers || [])
            .filter((p) => p.hasOutput)
            .map((p) =>
              fetchJson(`${API_BASE}/api/papers/${p.id}/output`)
                .then((res) => ({ id: p.id, evidence: res?.output?.extraction?.evidence_items || [] }))
                .catch(() => ({ id: p.id, evidence: [] }))
            )
        );
        if (canceled) return;
        const merged = outputs.flatMap((o) =>
          (o.evidence || []).map((ev, idx) => ({
            ...ev,
            __paperId: o.id,
            __evidenceId: `${o.id}__${idx}`,
          }))
        );
        // Normalize evidence items
        const normalized = normalizeEvidenceItems(merged);
        setAllEvidence(normalized);
      } catch (err) {
        if (!canceled) setError(err.message);
      }
    };
    if (papers?.length) loadAll();
    return () => {
      canceled = true;
    };
  }, [papers]);

  useEffect(() => {
    let canceled = false;
    if (!selected) return;
    // defer setState to avoid synchronous setState warning
    setTimeout(() => {
      if (canceled) return;
    setLoading(true);
    setError("");
    }, 0);
    Promise.all([
      fetchJson(`${API_BASE}/api/papers/${selected}/output`).catch(() => null),
      fetchJson(`${API_BASE}/api/papers/${selected}/checkpoints`).catch(() => ({ checkpoints: [] })),
      fetchJson(`${API_BASE}/api/papers/${selected}/session`).catch(() => ({ events: [] })),
    ])
      .then(([out, cps, ses]) => {
        if (canceled) return;
        try {
          console.log("[Data Load] Paper:", selected);
          console.log("[Data Load] Output:", out ? "✓" : "✗");
          console.log("[Data Load] Checkpoints:", cps?.checkpoints?.length || 0);
          console.log("[Data Load] Session events:", ses?.events?.length || 0);

          setOutput(out?.output || null);
          const sortedCheckpoints = (cps?.checkpoints || []).slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
          setCheckpoints(sortedCheckpoints);

          const parsedPhases = parseCheckpoints(sortedCheckpoints);
          console.log("[Data Load] Parsed phases:", Object.keys(parsedPhases).filter(k => parsedPhases[k]));
          setPhases(parsedPhases);

          setSessionEvents(ses?.events || []);
        } catch (error) {
          console.error("[Data Load] Error processing data:", error);
          if (!canceled) setError(error.message);
        }
      })
      .catch((err) => {
        console.error("[Data Load] Fetch error:", err);
        if (!canceled) setError(err.message);
      })
      .finally(() => {
        if (!canceled) setLoading(false);
      });
    return () => {
      canceled = true;
    };
  }, [selected]);

  const pdfUrl = useMemo(() => {
    if (!selected) return null;
    return `${API_BASE}/api/papers/${selected}/pdf`;
  }, [selected]);

  useEffect(() => {
    let canceled = false;
    if (!pdfUrl) {
      setTimeout(() => {
        if (!canceled) setPdfStatus({ checked: false, available: false, error: "" });
      }, 0);
      return;
    }
    setTimeout(() => {
      if (!canceled) setPdfStatus({ checked: false, available: false, error: "" });
    }, 0);
    fetch(pdfUrl, { method: "HEAD" })
      .then((res) => {
        if (canceled) return;
        setPdfStatus({ checked: true, available: res.ok, error: res.ok ? "" : "PDF not reachable" });
      })
      .catch(() => {
        if (canceled) return;
        setPdfStatus({ checked: true, available: false, error: "PDF not reachable" });
      });
    return () => {
      canceled = true;
    };
  }, [pdfUrl]);

  const trials = useMemo(() => parseTrials(phases.reader?.content?.nct_ids), [phases]);
  const clean = (v) => (v && v !== "Unknown" ? v : "—");
  const formatSeconds = (timing) => {
    if (!timing?.seconds) return "—";
    const secs = Number(timing.seconds);
    if (Number.isNaN(secs)) return "—";
    const minutes = Math.floor(secs / 60);
    const remain = Math.round(secs % 60);
    return minutes ? `${minutes}m ${remain}s` : `${remain}s`;
  };
  const evidenceMeta = useMemo(() => {
    const items = output?.extraction?.evidence_items || [];
    const firstPmid = items.find((it) => it.pmid)?.pmid || output?.paper_info?.pmid;
    const firstPmcid = items.find((it) => it.pmcid)?.pmcid || output?.paper_info?.pmcid;
    return { pmid: firstPmid, pmcid: firstPmcid };
  }, [output]);

  const openJson = (title, data) => setJsonModal({ open: true, title, data });
  const closeJson = () => setJsonModal({ open: false, title: "", data: null });
  const downloadJson = (data, filename) => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };
  const copyText = (text) => {
    if (!text) return;
    navigator.clipboard?.writeText(text).catch(() => {});
  };

  const paperTitle = phases.reader?.content?.title || output?.paper_info?.title || selected;
  const paperAuthors = phases.reader?.content?.authors || output?.paper_info?.author || "—";
  const paperJournal = phases.reader?.content?.journal || output?.paper_info?.journal || "—";
  const paperYear = phases.reader?.content?.year || output?.paper_info?.year || "—";
  const paperPages = phases.reader?.content?.num_pages || output?.paper_info?.num_pages || "—";
  const paperType = phases.reader?.content?.paper_type || output?.paper_info?.paper_type || "—";
  const currentPaper = papers.find((p) => p.id === selected);
  const evidenceItems = useMemo(() => output?.extraction?.evidence_items || [], [output]);
  const filteredEvidence = useMemo(() => {
    return evidenceItems.filter((item) => {
      const matchesType = evidenceTypeFilter === "ALL" || item.evidence_type === evidenceTypeFilter;
      const matchesDir = directionFilter === "ALL" || item.evidence_direction === directionFilter;
      const haystack = JSON.stringify(item).toLowerCase();
      const matchesSearch = !searchTerm.trim() || haystack.includes(searchTerm.toLowerCase());
      return matchesType && matchesDir && matchesSearch;
    });
  }, [evidenceItems, evidenceTypeFilter, directionFilter, searchTerm]);
  const evidenceTypes = Array.from(new Set(evidenceItems.map((i) => i.evidence_type).filter(Boolean)));
  const directions = Array.from(new Set(evidenceItems.map((i) => i.evidence_direction).filter(Boolean)));
  const graphTypes = Array.from(new Set(allEvidence.map((i) => i.evidence_type).filter(Boolean)));
  const graphDirections = Array.from(new Set(allEvidence.map((i) => i.evidence_direction).filter(Boolean)));

  // Build knowledge graphs from all evidence across all papers
  const knowledgeGraphs = useMemo(() => {
    if (!allEvidence || allEvidence.length === 0) {
      return {
        evidenceGraph: { nodes: [], links: [] },
        clinicalGraph: { nodes: [], links: [], assertions: [] },
        paperGraph: { nodes: [], links: [] },
        stats: {}
      };
    }
    return buildKnowledgeGraphs(allEvidence);
  }, [allEvidence]);

  const groundTruthPath =
    selected && selected.startsWith("PMID_")
      ? `/api/papers/${selected}/ground-truth`
      : null;
  const graphEvidence = useMemo(() => {
    const term = graphFilters.search.trim().toLowerCase();
    return (allEvidence || []).filter((item) => {
      const matchesType = graphFilters.type === "ALL" || item.evidence_type === graphFilters.type;
      const matchesDir = graphFilters.direction === "ALL" || item.evidence_direction === graphFilters.direction;
      const matchesDisease =
        graphFilters.diseaseScope === "ALL" ||
        item.disease_efo_id === "EFO_0001378" ||
        item.disease_name?.toLowerCase()?.includes("myeloma");
      const haystack = JSON.stringify(item).toLowerCase();
      const matchesSearch = !term || haystack.includes(term);
      return matchesType && matchesDir && matchesDisease && matchesSearch;
    });
  }, [allEvidence, graphFilters]);


  const graphData = useMemo(() => {
    const nodes = new Map();
    const links = [];

    const addNode = (id, label, kind, meta = {}) => {
      if (!id) return;
      if (!nodes.has(id)) {
        nodes.set(id, {
          id,
          label,
          kind,
          color: getNodeColor(kind),
          ...meta
        });
      }
    };

    graphEvidence.forEach((ev) => {
      const evidId = ev.evidence_item_uid || ev.__evidenceId;
      const diseaseId = ev.disease_efo_id || ev.disease_name || "Disease";
      const outcome = ev.evidence_significance_norm || ev.evidence_significance || ev.evidence_type || "Outcome";
      const weight = calculateEvidenceWeight(ev);
      const sigColor = getSignificanceColor(ev.evidence_significance_norm || ev.evidence_significance);

      // Create EvidenceItem node (first-class citizen)
      addNode(`evidence:${evidId}`,
        `${ev.feature_names?.join?.(", ") || "Evidence"} → ${outcome}`,
        "evidence",
        {
          paper: ev.__paperId,
          weight,
          sig: ev.evidence_significance_norm || ev.evidence_significance,
          level: ev.evidence_level_norm || ev.evidence_level,
          type: ev.evidence_type,
          variantType: ev.variant_type,
          confidence: ev.extraction_confidence,
          cohortSize: ev.cohort_size,
          quote: ev.verbatim_quote,
          description: ev.evidence_description,
          fullEvidence: ev
        }
      );

      // Create entity nodes
      addNode(`paper:${ev.__paperId}`, ev.__paperId, "paper");
      addNode(`disease:${diseaseId}`, ev.disease_name || diseaseId, "disease", {
        efoId: ev.disease_efo_id
      });

      (ev.feature_names || []).forEach((g) =>
        addNode(`gene:${g}`, g, "gene", {
          entrezIds: ev.feature_entrez_ids || []
        })
      );

      (ev.variant_names || []).forEach((v) =>
        addNode(`variant:${v}`, v, "variant", {
          type: ev.variant_type,
          hgvs: ev.variant_hgvs_descriptions || []
        })
      );

      (ev.therapy_names || []).forEach((t) =>
        addNode(`therapy:${t}`, t, "therapy", {
          rxnormIds: ev.therapy_rxnorm_ids || [],
          ncitIds: ev.therapy_ncit_ids || []
        })
      );

      addNode(`outcome:${outcome}`, outcome, "outcome");

      // Create edges from EvidenceItem to entities
      links.push({
        source: `paper:${ev.__paperId}`,
        target: `evidence:${evidId}`,
        kind: "CITED_FROM",
        weight,
        color: sigColor
      });

      links.push({
        source: `evidence:${evidId}`,
        target: `disease:${diseaseId}`,
        kind: "IN_DISEASE",
        weight,
        color: sigColor
      });

      (ev.feature_names || []).forEach((g) =>
        links.push({
          source: `evidence:${evidId}`,
          target: `gene:${g}`,
          kind: "ABOUT_GENE",
          weight,
          color: sigColor
        })
      );

      (ev.variant_names || []).forEach((v) =>
        links.push({
          source: `evidence:${evidId}`,
          target: `variant:${v}`,
          kind: "ABOUT_VARIANT",
          weight,
          color: sigColor
        })
      );

      (ev.therapy_names || []).forEach((t) =>
        links.push({
          source: `evidence:${evidId}`,
          target: `therapy:${t}`,
          kind: "INVOLVES_THERAPY",
          weight,
          color: sigColor
        })
      );

      links.push({
        source: `evidence:${evidId}`,
        target: `outcome:${outcome}`,
        kind: "HAS_SIGNIFICANCE",
        weight,
        color: sigColor
      });
    });

    return { nodes: Array.from(nodes.values()), links };
  }, [graphEvidence]);

  const graphDrillEvidence = useMemo(() => {
    if (!graphNode) return [];
    const id = graphNode.id;

    if (id.startsWith("gene:")) {
      const name = id.replace("gene:", "");
      return graphEvidence.filter((ev) => ev.feature_names?.includes(name));
    }
    if (id.startsWith("variant:")) {
      const name = id.replace("variant:", "");
      return graphEvidence.filter((ev) => ev.variant_names?.includes(name));
    }
    if (id.startsWith("therapy:")) {
      const name = id.replace("therapy:", "");
      return graphEvidence.filter((ev) => ev.therapy_names?.includes(name));
    }
    if (id.startsWith("disease:")) {
      const name = id.replace("disease:", "");
      return graphEvidence.filter((ev) => (ev.disease_efo_id || ev.disease_name) === name);
    }
    if (id.startsWith("outcome:")) {
      const name = id.replace("outcome:", "");
      const norm = name.toUpperCase();
      return graphEvidence.filter((ev) =>
        (ev.evidence_significance_norm || ev.evidence_significance || ev.evidence_type || "").toUpperCase() === norm
      );
    }
    if (id.startsWith("evidence:")) {
      const evidId = id.replace("evidence:", "");
      return graphEvidence.filter((ev) => (ev.evidence_item_uid || ev.__evidenceId) === evidId);
    }
    if (id.startsWith("paper:")) {
      const paperId = id.replace("paper:", "");
      return graphEvidence.filter((ev) => ev.__paperId === paperId);
    }

    return [];
  }, [graphNode, graphEvidence]);
  const exportEvidenceCsv = () => {
    if (!filteredEvidence.length) return;
    const headers = [
      "feature_names",
      "variant_names",
      "variant_origin",
      "disease_name",
      "therapy_names",
      "evidence_type",
      "evidence_level",
      "evidence_direction",
      "evidence_significance",
      "clinical_trial_nct_ids",
      "chromosome",
      "reference_build",
      "start_position",
      "stop_position",
      "variant_hgvs_descriptions",
      "cancer_cell_fraction",
      "cohort_size",
      "source_title",
      "source_publication_year",
      "source_journal",
      "source_page_numbers",
      "verbatim_quote",
      "extraction_confidence",
      "extraction_reasoning",
    ];
    const rows = filteredEvidence.map((item) =>
      headers
        .map((key) => {
          const val = item[key];
          if (Array.isArray(val)) return `"${val.join("; ").replace(/"/g, '""')}"`;
          if (val === undefined || val === null) return "";
          return `"${String(val).replace(/"/g, '""')}"`;
        })
        .join(",")
    );
    const csv = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selected || "evidence"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (showLanding) {
    return <LandingPage onGetStarted={() => setShowLanding(false)} />;
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        {/* Research context overview - always visible */}
        <div className="research-context-container sidebar-version">
          <div className="research-context-header" onClick={() => setResearchContextCollapsed(!researchContextCollapsed)}>
            <h3>Research Overview</h3>
            <button
              className="collapse-btn-small"
              title={researchContextCollapsed ? "Expand" : "Collapse"}
            >
              {researchContextCollapsed ? "▼" : "▲"}
            </button>
          </div>
          {!researchContextCollapsed && (
            <ResearchContext
              papers={papers}
              allEvidence={allEvidence}
              selected={selected}
              output={output}
              phases={phases}
            />
          )}
        </div>

        <h2>Corpus</h2>
        <div className="paper-list">
          {papers.filter((p) => p.id.startsWith("PMID_")).length > 0 && (
            <div className="section-label">Retrospective — CIViC curated</div>
          )}
          {papers
            .filter((p) => p.id.startsWith("PMID_"))
            .map((p) => (
              <button
                key={p.id}
                className={`paper-btn ${selected === p.id ? "active" : ""}`}
                onClick={() => { console.log("[Paper] Selected:", p.id); setSelected(p.id); }}
              >
                <div className="paper-title">{formatPaperTitle(p.id)}</div>
                <div className="paper-meta">
                  CIViC · {p.hasOutput ? "✅ Output" : "…"} · {p.hasCheckpoints ? "💾 Checkpoints" : "…"}
                </div>
              </button>
            ))}
          {papers.filter((p) => !p.id.startsWith("PMID_")).length > 0 && (
            <div className="section-label">Prospective — recent literature</div>
          )}
          {papers
            .filter((p) => !p.id.startsWith("PMID_"))
            .map((p) => {
              const venue = formatPaperVenue(p.id);
              return (
                <button
                  key={p.id}
                  className={`paper-btn ${selected === p.id ? "active" : ""}`}
                  onClick={() => { console.log("[Paper] Selected:", p.id); setSelected(p.id); }}
                >
                  <div className="paper-title">{formatPaperTitle(p.id)}</div>
                  <div className="paper-meta">
                    {venue ? `${venue} · ` : ""}{p.hasOutput ? "✅ Output" : "…"} · {p.hasCheckpoints ? "💾 Checkpoints" : "…"}
                  </div>
                </button>
              );
            })}
          {!papers.length && <div className="muted">No papers found.</div>}
        </div>
      </aside>

      <main className="main">
        <header className="header">
          <div>
            <h1>OncoCITE — Clinical genomic evidence extraction</h1>
            <p className="muted">
              Multiple myeloma validation corpus: 10 CIViC-curated papers (retrospective)
              and 5 recent papers (prospective).
            </p>
          </div>
          <div className="header-pills">
            {loading && <Pill>Loading…</Pill>}
            {error && <Pill kind="error">{error}</Pill>}
          </div>
        </header>

        {!selected && <div className="muted" style={{ padding: "20px 24px" }}>Select a paper from the sidebar to view detailed phase outputs and PDF artifacts.</div>}

        {selected && (
          <div className="content">
            <div className="tab-bar">
              <button className={`tab-btn ${activeTab === "pdf" ? "active" : ""}`} onClick={() => { console.log("[Tab] Switching to: pdf"); setActiveTab("pdf"); }}>
                📄 Source PDF
              </button>
              <button className={`tab-btn ${activeTab === "insights" ? "active" : ""}`} onClick={() => { console.log("[Tab] Switching to: insights"); setActiveTab("insights"); }}>
                📊 Extracted evidence
              </button>
            </div>

            {activeTab === "pdf" && (
              <div className="pane">
                <SectionHeader title="Source PDF" />
                {currentPaper?.pdfPath && (
                  <div className="muted small">Resolved path: {currentPaper.pdfPath}</div>
                )}
                <PdfViewer url={pdfUrl} onError={(err) => setError(err)} />
              </div>
            )}

            {activeTab === "insights" && (
              <div className="pane">
                <div className="sub-tab-bar">
                  <button className={`sub-tab-btn ${insightsSubTab === "overview" ? "active" : ""}`}
                          onClick={() => setInsightsSubTab("overview")}>Summary</button>
                  <button className={`sub-tab-btn ${insightsSubTab === "evidence" ? "active" : ""}`}
                          onClick={() => setInsightsSubTab("evidence")}>Evidence items</button>
                  <button className={`sub-tab-btn ${insightsSubTab === "matrix" ? "active" : ""}`}
                          onClick={() => setInsightsSubTab("matrix")}>Knowledge graph</button>
                  <button className={`sub-tab-btn ${insightsSubTab === "provenance" ? "active" : ""}`}
                          onClick={() => setInsightsSubTab("provenance")}>Provenance</button>
                </div>

                {insightsSubTab === "overview" && (
                  <div style={{ padding: "16px 20px", overflow: "auto", maxHeight: "calc(100vh - 250px)" }}>
                    <StatsGrid evidence={filteredEvidence} defaultCollapsed={false} />
                    {output?.plan && <PlanPanel plan={output.plan} />}
                    {output?.final_critique && <CritiquePanel critique={output.final_critique} />}
                  </div>
                )}

                {insightsSubTab === "evidence" && (
              <div style={{ height: "100%" }}>
                {output ? (
                  <EvidenceSplitPane
                    items={filteredEvidence}
                    pdfUrl={pdfUrl}
                    filters={
                      <>
                        <select
                          value={evidenceTypeFilter}
                          onChange={(e) => setEvidenceTypeFilter(e.target.value)}
                          style={{ padding: '4px 8px', fontSize: '12px', borderRadius: '4px', border: '1px solid #e3e8f0' }}
                        >
                          <option value="ALL">All Types</option>
                          {evidenceTypes.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                        <select
                          value={directionFilter}
                          onChange={(e) => setDirectionFilter(e.target.value)}
                          style={{ padding: '4px 8px', fontSize: '12px', borderRadius: '4px', border: '1px solid #e3e8f0' }}
                        >
                          <option value="ALL">All Directions</option>
                          {directions.map((d) => (
                            <option key={d} value={d}>{d}</option>
                          ))}
                        </select>
                        <input
                          type="text"
                          value={searchTerm}
                          onChange={(e) => setSearchTerm(e.target.value)}
                          placeholder="Search..."
                          style={{ padding: '4px 8px', fontSize: '12px', borderRadius: '4px', border: '1px solid #e3e8f0', width: '150px' }}
                        />
                        <button
                          className="pill"
                          onClick={exportEvidenceCsv}
                          disabled={!filteredEvidence.length}
                          style={{ padding: '4px 10px', fontSize: '11px' }}
                        >
                          Export CSV
                        </button>
                      </>
                    }
                  />
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-icon">📊</div>
                    <div>No extraction output available</div>
                    <div className="muted tiny">Run the extraction first to see evidence items</div>
                  </div>
                )}
              </div>
            )}

            {insightsSubTab === "matrix" && (
              <div>
                {/* Knowledge Graph View Switcher */}
                <div className="kg-view-switcher">
                  <button
                    className={`kg-view-btn ${kgView === 'clinical' ? 'active' : ''}`}
                    onClick={() => setKgView('clinical')}
                  >
                    🔬 Entity graph
                  </button>
                  <button
                    className={`kg-view-btn ${kgView === 'matrix' ? 'active' : ''}`}
                    onClick={() => setKgView('matrix')}
                  >
                    📊 Feature × therapy matrix
                  </button>

                  {/* Stats summary */}
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <div className="pill muted small">
                      {knowledgeGraphs.stats.total_papers || 0} papers
                    </div>
                    <div className="pill muted small">
                      {knowledgeGraphs.stats.total_evidence_items || 0} evidence items
                    </div>
                    <div className="pill muted small">
                      {knowledgeGraphs.stats.total_assertions || 0} assertions
                    </div>
                  </div>
                </div>

                {/* Render appropriate view */}
                <div style={{ padding: '16px 20px', overflow: 'auto', minHeight: '800px' }}>
                  {allEvidence.length === 0 ? (
                    <div className="empty-state">
                      <div className="empty-state-icon">🔍</div>
                      <div>No evidence data available</div>
                      <div className="muted tiny">Load papers with extraction outputs to see the knowledge graph</div>
                    </div>
                  ) : (
                    <>
                      {kgView === 'clinical' && (
                        <ClinicalMapView
                          clinicalGraph={knowledgeGraphs.clinicalGraph}
                          onAssertionClick={(assertion) => {
                            // Could open a modal or jump to evidence tab
                            console.log('Assertion clicked:', assertion);
                          }}
                        />
                      )}

                      {kgView === 'matrix' && (
                        <MatrixView clinicalGraph={knowledgeGraphs.clinicalGraph} />
                      )}
                    </>
                  )}
                </div>
              </div>
            )}

            {insightsSubTab === "provenance" && (
              <div style={{ padding: "16px 20px", overflow: "auto", maxHeight: "calc(100vh - 250px)" }}>
                <CheckpointDeck phases={phases} pdfUrl={pdfUrl} onOpenRaw={(title, data) => openJson(title, data)} />
                {sessionEvents.length > 0 && (
                  <div style={{ marginTop: "20px" }}>
                    <h4>Timeline Events</h4>
                    <Timeline events={sessionEvents} />
                  </div>
                )}
              </div>
            )}
          </div>
        )}

            {activeTab === "plan" && (
              <div className="pane">
                <div className="plan-crit-grid">
                  <div className="panel">
                    <SectionHeader title="Plan" />
                    {output?.plan ? <PlanPanel plan={output.plan} /> : <div className="muted">No plan available.</div>}
                    </div>
                  <div className="panel">
                    <SectionHeader title="Critique" />
                    {output?.final_critique ? <CritiquePanel critique={output.final_critique} /> : <div className="muted">No critique available.</div>}
                  </div>
                </div>
              </div>
            )}

            {activeTab === "graph" && (
              <div className={`pane ${graphFullscreen ? "fullscreen-pane" : ""}`}>
                <SectionHeader
                  title="Knowledge Graph (all papers)"
                  right={
                    <div className="tag-row">
                      <div className="pill muted small">
                        {graphData.nodes.length} nodes · {graphData.links.length} edges
                      </div>
                      <button className="pill" onClick={() => setGraphFullscreen(!graphFullscreen)}>
                        {graphFullscreen ? "Exit Fullscreen" : "Fullscreen"}
                      </button>
                    </div>
                  }
                />

                {/* Trust UI - Quality Indicators */}
                {selected && phases.planner && phases.critic && (
                  <div className="trust-ui">
                    <div className="trust-card">
                      <div className="muted tiny">EXPECTED</div>
                      <div className="big">{phases.planner?.plan?.expected_items ?? '?'}</div>
                      <div className="muted tiny">items</div>
                    </div>
                    <div className="trust-card">
                      <div className="muted tiny">EXTRACTED</div>
                      <div className="big">{output?.extraction?.items ?? '?'}</div>
                      <div className="muted tiny">items</div>
                    </div>
                    <div className="trust-card">
                      <Pill kind={phases.critic?.critique?.overall_assessment === 'APPROVE' ? 'success' : 'warning'}>
                        {phases.critic?.critique?.overall_assessment || '—'}
                      </Pill>
                      <div className="muted tiny">Quality Assessment</div>
                    </div>
                    <div className="trust-card">
                      <div className="muted tiny">PAPER TYPE</div>
                      <div className="small strong">{phases.planner?.plan?.paper_type || output?.paper_info?.paper_type || '—'}</div>
                    </div>
                  </div>
                )}

                <div className="filters">
                  <div className="filter-group">
                    <label>Disease scope</label>
                    <select
                      value={graphFilters.diseaseScope}
                      onChange={(e) => setGraphFilters((s) => ({ ...s, diseaseScope: e.target.value }))}
                    >
                      <option value="MM_ONLY">Multiple Myeloma</option>
                      <option value="ALL">All diseases</option>
                    </select>
                  </div>
                  <div className="filter-group">
                    <label>Evidence type</label>
                    <select value={graphFilters.type} onChange={(e) => setGraphFilters((s) => ({ ...s, type: e.target.value }))}>
                      <option value="ALL">All</option>
                      {graphTypes.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-group">
                    <label>Direction</label>
                    <select value={graphFilters.direction} onChange={(e) => setGraphFilters((s) => ({ ...s, direction: e.target.value }))}>
                      <option value="ALL">All</option>
                      {graphDirections.map((d) => (
                        <option key={d} value={d}>
                          {d}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="filter-group">
                    <label>Search</label>
                    <input
                      type="text"
                      value={graphFilters.search}
                      onChange={(e) => setGraphFilters((s) => ({ ...s, search: e.target.value }))}
                      placeholder="Filter nodes/evidence"
                    />
                  </div>
                  <div className="filter-group">
                    <label>Min weight</label>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.1"
                      value={graphFilters.minWeight}
                      onChange={(e) => setGraphFilters((s) => ({ ...s, minWeight: Number(e.target.value) }))}
                    />
                    <div className="muted tiny">{graphFilters.minWeight.toFixed(1)}</div>
                  </div>
                  <div className="pill muted small">{graphEvidence.length} evidence items</div>
                </div>

                {graphData.nodes.length ? (
                  <div className={graphFullscreen ? "graph-fullscreen-grid" : "graph-grid"}>
                    <div className="graph-box">
                      <ForceGraph2D
                        graphData={{
                          nodes: graphData.nodes,
                          links: graphData.links.filter((l) => l.weight >= graphFilters.minWeight),
                        }}
                        width={graphFullscreen ? window.innerWidth * 0.65 : undefined}
                        height={graphFullscreen ? window.innerHeight - 250 : 600}
                        nodeLabel={(n) => {
                          const parts = [`${n.label} (${n.kind})`];
                          if (n.paper) parts.push(`Paper: ${n.paper}`);
                          if (n.level) parts.push(`Level: ${n.level}`);
                          if (n.sig) parts.push(`Sig: ${n.sig}`);
                          if (n.confidence) parts.push(`Conf: ${typeof n.confidence === 'number' ? Math.round(n.confidence * 100) + '%' : n.confidence}`);
                          return parts.join(' · ');
                        }}
                        nodeColor={(n) => n.color || getNodeColor(n.kind)}
                        nodeRelSize={7}
                        nodeVal={(n) => n.kind === 'evidence' ? (n.weight || 1) * 8 : n.kind === 'gene' ? 6 : 4}
                        linkColor={(l) => l.color || "#94a3b8"}
                        linkWidth={(l) => Math.max(1, (l.weight || 0.5) * 3)}
                        linkDirectionalParticles={(l) => l.weight > 0.5 ? 3 : 1}
                        linkDirectionalParticleWidth={(l) => l.weight * 2}
                        linkLabel={(l) => l.kind}
                        onNodeClick={(node) => setGraphNode(node)}
                        onNodeHover={(node) => node ? document.body.style.cursor = 'pointer' : document.body.style.cursor = 'default'}
                        cooldownTicks={100}
                        onEngineStop={() => {}}
                      />
                    </div>
                    <div className="graph-side">
                      <div className="card">
                        <div className="card-title">Node details</div>
                        {graphNode ? (
                          <>
                            <div className="muted small"><strong>Label:</strong> {graphNode.label}</div>
                            <div className="muted small"><strong>Type:</strong> {graphNode.kind}</div>

                            {graphNode.kind === 'evidence' && graphNode.fullEvidence && (
                              <>
                                <div className="pill-row" style={{marginTop: '8px'}}>
                                  <Pill kind={graphNode.type === 'PREDICTIVE' ? 'success' : 'default'}>
                                    {graphNode.type || '—'}
                                  </Pill>
                                  <Pill>{graphNode.level || '—'}</Pill>
                                  <Pill>{graphNode.sig || '—'}</Pill>
                                </div>
                                {graphNode.description && (
                                  <div className="muted small" style={{marginTop: '8px'}}>
                                    <strong>Description:</strong> {graphNode.description}
                                  </div>
                                )}
                                {graphNode.quote && (
                                  <div className="quote-block" style={{marginTop: '8px'}}>
                                    <div className="label tiny">Quote</div>
                                    <div className="muted tiny">"{graphNode.quote}"</div>
                                  </div>
                                )}
                                {graphNode.confidence && (
                                  <div className="muted small">
                                    <strong>Confidence:</strong> {typeof graphNode.confidence === 'number' ? Math.round(graphNode.confidence * 100) + '%' : graphNode.confidence}
                                  </div>
                                )}
                                {graphNode.cohortSize && (
                                  <div className="muted small">
                                    <strong>Cohort:</strong> {graphNode.cohortSize}
                                  </div>
                                )}
                                {graphNode.variantType && (
                                  <div className="muted small">
                                    <strong>Variant Type:</strong> {graphNode.variantType}
                                  </div>
                                )}
                              </>
                            )}

                            {graphNode.kind === 'gene' && graphNode.entrezIds?.length > 0 && (
                              <div className="muted small"><strong>Entrez IDs:</strong> {graphNode.entrezIds.join(', ')}</div>
                            )}

                            {graphNode.kind === 'disease' && graphNode.efoId && (
                              <div className="muted small"><strong>EFO ID:</strong> {graphNode.efoId}</div>
                            )}

                            {graphNode.kind === 'therapy' && (
                              <>
                                {graphNode.rxnormIds?.length > 0 && (
                                  <div className="muted small"><strong>RxNorm IDs:</strong> {graphNode.rxnormIds.join(', ')}</div>
                                )}
                                {graphNode.ncitIds?.length > 0 && (
                                  <div className="muted small"><strong>NCIt IDs:</strong> {graphNode.ncitIds.join(', ')}</div>
                                )}
                              </>
                            )}

                            {graphNode.kind === 'variant' && (
                              <>
                                <div className="muted small"><strong>Type:</strong> {graphNode.type || '—'}</div>
                                {graphNode.hgvs?.length > 0 && (
                                  <div className="muted small"><strong>HGVS:</strong> {graphNode.hgvs.join(', ')}</div>
                                )}
                              </>
                            )}

                            {graphNode.paper && <div className="muted small"><strong>Paper:</strong> {graphNode.paper}</div>}
                            {graphNode.weight && (
                              <div className="muted small"><strong>Weight:</strong> {graphNode.weight.toFixed?.(2) || graphNode.weight}</div>
                            )}
                  </>
                ) : (
                          <div className="muted small">Click a node to see details and related evidence.</div>
                        )}
                      </div>
                      <div className="card">
                        <div className="card-title">Related evidence ({graphDrillEvidence.length})</div>
                        {graphDrillEvidence.length ? (
                          <div className="drill-list">
                            {graphDrillEvidence.slice(0, 50).map((ev) => (
                              <div key={ev.__evidenceId} className="drill-item">
                                <div className="muted tiny">{ev.__paperId}</div>
                                <div className="muted small strong">{ev.feature_names?.join?.(", ") || "—"}</div>
                                <div className="muted tiny">{ev.variant_names?.join?.(", ") || "—"}</div>
                                <div className="muted tiny">{ev.therapy_names?.join?.(", ") || "—"}</div>
                                <div className="pill-row">
                                  <Pill>{ev.evidence_type || "—"}</Pill>
                                  <Pill>{ev.evidence_direction || "—"}</Pill>
                    </div>
                                <div className="muted tiny ellipsis" title={ev.verbatim_quote || ""}>
                                  "{ev.verbatim_quote || "No quote"}"
                                </div>
                            {ev.source_page_numbers && (
                              <div className="muted tiny">Pages: {ev.source_page_numbers}</div>
                            )}
                            {ev.cohort_size && <div className="muted tiny">Cohort: {ev.cohort_size}</div>}
                            {ev.extraction_confidence && (
                              <div className="muted tiny">
                                Confidence:{" "}
                                {typeof ev.extraction_confidence === "number"
                                  ? `${Math.round(ev.extraction_confidence * 100)}%`
                                  : ev.extraction_confidence}
                              </div>
                            )}
                              </div>
                            ))}
                            {graphDrillEvidence.length > 50 && (
                              <div className="muted tiny">Showing 50 of {graphDrillEvidence.length}</div>
                            )}
                          </div>
                        ) : (
                          <div className="muted small">No related evidence.</div>
                )}
              </div>
            </div>
                  </div>
                ) : (
                  <div className="muted">
                    Knowledge graph is empty. Ensure outputs are available on the API (http://localhost:4177) and reload.
                  </div>
                )}
              </div>
            )}

            {activeTab === "checkpoints" && (
            <div className="panel">
                <SectionHeader
                  title="Agent Checkpoints (01–04)"
                  right={
                    checkpoints.length ? (
                      <div className="tag-row">
                        {checkpoints.map((cp, idx) => (
                          <button
                            key={idx}
                            className="pill"
                            onClick={() => openJson(cp.name || `Checkpoint ${idx + 1}`, cp.data)}
                          >
                            Raw {cp.name || `Checkpoint ${idx + 1}`}
                          </button>
                        ))}
              </div>
                    ) : null
                  }
                />
                <CheckpointDeck phases={phases} pdfUrl={pdfUrl} onOpenRaw={(title, data) => openJson(title, data)} />
            </div>
            )}

            {activeTab === "timeline" && (
            <div className="panel">
                <SectionHeader title="Timeline (tool calls & hooks)" />
              <Timeline events={sessionEvents} />
            </div>
            )}
          </div>
        )}
      </main>

      <JsonModal open={jsonModal.open} title={jsonModal.title} data={jsonModal.data} onClose={closeJson} />
    </div>
  );
}

function AppWithErrorBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}

export default AppWithErrorBoundary;
