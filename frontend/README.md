## Evidence Viewer Frontend

A Vite + React single-page app to browse CIViC extraction artifacts. It uses a lightweight Express API to read existing PDFs, checkpoints, and final outputs, and can trigger new extractions via the existing Python pipeline.

### Prerequisites
- Node 18+
- Python available at `python3.11` (override with `PYTHON_BIN`)

### Install
```bash
cd frontend
npm install
```

### Run API server
```bash
# from frontend/
DATA_ROOT=../data/papers \
OUTPUTS_ROOT=../outputs \
LOGS_ROOT=../logs \
PYTHON_BIN=python3.11 \
EXTRACTION_SCRIPT=../scripts/run_extraction.py \
npm run server
```
Default API port: `4177`.

### Run frontend
```bash
# from frontend/
npm run dev
```
Open the Vite dev URL (default http://localhost:5173). The API has CORS enabled; no proxy needed.

### UI map
- Sidebar: lists papers discovered in `data/papers/`, annotated with output/checkpoint availability.
- PDF tab: streams `/api/papers/:id/pdf` (original paper).
- Final Output: renders `outputs/<paper_id>_extraction.json` if present.
- Agent Checkpoints: renders JSON from `outputs/checkpoints/<paper_id>/01-04_*.json`.
- Upload/Run: upload a PDF or provide a PDF path and trigger the Python pipeline via `/api/extract`. On completion, the paper list refreshes.

### API endpoints (Express)
- `GET /api/papers` — list papers with status flags.
- `GET /api/papers/:id/pdf` — stream the PDF.
- `GET /api/papers/:id/checkpoints` — return checkpoint JSONs.
- `GET /api/papers/:id/output` — return final extraction JSON.
- `GET /api/papers/:id/logs` — list matching log file paths.
- `POST /api/extract` — multipart upload (`file`) or `{ pdfPath }` to invoke `run_extraction.py`.

### Notes
- Paths are env-configurable; defaults assume running from `frontend/` inside the repo root.
- The API spawns the existing Python script; ensure your `.env` is configured at the repo root for the extraction to work.
# React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Babel](https://babeljs.io/) (or [oxc](https://oxc.rs) when used in [rolldown-vite](https://vite.dev/guide/rolldown)) for Fast Refresh
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/) for Fast Refresh

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
