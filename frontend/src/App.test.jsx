import React from "react";
import "@testing-library/jest-dom";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";

// Helper to mock fetch responses by URL
function createFetchMock() {
  const responses = {
    "/api/papers": {
      papers: [{ id: "s41591-023-02491-5", hasOutput: true, hasCheckpoints: true }],
    },
    "/api/papers/s41591-023-02491-5/output": {
      output: {
        paper_id: "s41591-023-02491-5",
        paper_info: {
          title: "Mechanisms of antigen escape",
          author: "Unknown",
          year: 2023,
          num_pages: 34,
          paper_type: "PRIMARY",
        },
        extraction: {
          items: 1,
          iterations: 1,
          evidence_items: [
            {
              feature_names: ["TNFRSF17"],
              variant_names: ["BIALLELIC DELETION"],
              variant_origin: "SOMATIC",
              disease_name: "Multiple Myeloma",
              therapy_names: ["Teclistamab"],
              therapy_ncit_ids: ["NCIT:C136823"],
              therapy_rxcui_ids: ["2619426"],
              evidence_type: "PREDICTIVE",
              evidence_level: "CASE_STUDY",
              evidence_direction: "SUPPORTS",
              evidence_significance: "RESISTANCE",
              clinical_trial_nct_ids: ["NCT03651128"],
              chromosome: "16",
              reference_build: "GRCh37",
              start_position: 11920001,
              stop_position: 12100000,
              variant_hgvs_descriptions: [],
              cancer_cell_fraction: 0.12,
              cohort_size: 30,
              source_title: "Nature Medicine study",
              source_publication_year: 2023,
              source_journal: "Nature Medicine",
              source_page_numbers: "Abstract",
              verbatim_quote: "In two cases, MM relapse ...",
              extraction_confidence: 0.95,
              extraction_reasoning: "High confidence",
            },
          ],
        },
        plan: {
          expected_items: 15,
          paper_type: "PRIMARY",
          key_variants: "TNFRSF17 biallelic deletions",
          key_therapies: "Teclistamab",
          key_diseases: "Multiple Myeloma",
          focus_sections: "Abstract",
          extraction_notes: "Focus on resistance items",
        },
        final_critique: {
          overall_assessment: "APPROVE",
          summary: "EXCELLENT",
          item_feedback: "All items validated",
          missing_items: "None",
          extra_items: "None",
        },
        timing: { seconds: 10 },
      },
    },
    "/api/papers/s41591-023-02491-5/checkpoints": {
      checkpoints: [
        { name: "01_reader_output.json", data: { paper_content: { title: "Mechanisms of antigen escape" } } },
      ],
    },
    "/api/papers/s41591-023-02491-5/session": { events: [] },
  };

  return vi.fn((url) => {
    const key = url.replace(/^https?:\/\/[^/]+/, ""); // strip host if present
    const body = responses[key];
    if (!body) {
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => body,
    });
  });
}

describe("App frontend orchestration", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = createFetchMock();
  });

  it("loads papers, renders paper info, plan, critique, and enriched evidence table", async () => {
    render(<App />);

    // Paper list loads
    expect(await screen.findByText("s41591-023-02491-5")).toBeInTheDocument();

    // Select paper to fetch artifacts
    fireEvent.click(screen.getByText("s41591-023-02491-5"));

    // Paper info summary shows title and stats
    await waitFor(() => expect(screen.getByText("Mechanisms of antigen escape")).toBeInTheDocument());
    expect(screen.getByText(/Items: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Iterations: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Duration/)).toBeInTheDocument();

    // Evidence table columns for ABN data points
    expect(await screen.findByText("Variant")).toBeInTheDocument();
    expect(screen.getByText("Origin")).toBeInTheDocument();
    expect(screen.getByText("Build")).toBeInTheDocument();
    expect(screen.getByText("Start")).toBeInTheDocument();
    expect(screen.getByText("Stop")).toBeInTheDocument();
    expect(screen.getByText("HGVS")).toBeInTheDocument();
    expect(screen.getByText("CCF")).toBeInTheDocument();
    expect(screen.getByText("Source Title")).toBeInTheDocument();
    expect(screen.getByText("NCT IDs")).toBeInTheDocument();

    // Evidence row data rendered
    expect(screen.getByText("TNFRSF17")).toBeInTheDocument();
    expect(screen.getByText("BIALLELIC DELETION")).toBeInTheDocument();
    expect(screen.getByText("Teclistamab")).toBeInTheDocument();
    expect(screen.getByText("GRCh37")).toBeInTheDocument();
    expect(screen.getByText("0.12")).toBeInTheDocument();
    expect(screen.getByText("Nature Medicine study")).toBeInTheDocument();

    // Checkpoints JSON button
    fireEvent.click(screen.getByText("Checkpoints"));
    expect(await screen.findByText(/Raw 01_reader_output/)).toBeInTheDocument();
  });

  it("offers JSON modal for final output", async () => {
    render(<App />);
    fireEvent.click(await screen.findByText("s41591-023-02491-5"));
    await screen.findByText("Mechanisms of antigen escape");

    fireEvent.click(screen.getByText("View JSON"));
    await waitFor(() => expect(screen.getByText(/paper_id/)).toBeInTheDocument());
  });
});

