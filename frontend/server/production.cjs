/* Production server that serves both static files and API endpoints */
const express = require("express");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const { spawn } = require("child_process");

const app = express();
// CORS with proper headers for PDF.js Range requests
app.use(cors({
  origin: '*',
  exposedHeaders: ['Content-Range', 'Accept-Ranges', 'Content-Length'],
  allowedHeaders: ['Range', 'Accept', 'Content-Type']
}));
app.use(express.json());

// Paths (configurable via env)
const ROOT = path.resolve(__dirname, "..", "..");
const DATA_ROOT = process.env.DATA_ROOT || path.join(ROOT, "data", "papers");
const OUTPUTS_ROOT = process.env.OUTPUTS_ROOT || path.join(ROOT, "outputs");
const LOGS_ROOT = process.env.LOGS_ROOT || path.join(ROOT, "logs");
const PYTHON = process.env.PYTHON_BIN || "python3.11";
const EXTRACTION_SCRIPT =
  process.env.EXTRACTION_SCRIPT || path.join(ROOT, "scripts", "run_extraction.py");

// Serve static files from dist directory
const distPath = path.join(__dirname, "..", "dist");
console.log(`Serving static files from: ${distPath}`);
app.use(express.static(distPath));

// Multer storage for uploads into a temp location before we move them
const upload = multer({ dest: path.join(ROOT, "tmp_uploads") });

function safeJsonRead(filePath) {
  try {
    const data = fs.readFileSync(filePath, "utf8");
    return JSON.parse(data);
  } catch (err) {
    return null;
  }
}

async function listPapers() {
  const entries = await fsp.readdir(DATA_ROOT, { withFileTypes: true });
  const papers = [];
  for (const entry of entries) {
    if (entry.isDirectory()) {
      const pdfs = (await fsp.readdir(path.join(DATA_ROOT, entry.name))).filter((f) =>
        f.toLowerCase().endsWith(".pdf")
      );
      if (pdfs.length > 0) {
        papers.push({ id: entry.name, pdf: path.join(DATA_ROOT, entry.name, pdfs[0]) });
      }
    } else if (entry.isFile() && entry.name.toLowerCase().endsWith(".pdf")) {
      const stem = entry.name.replace(/\\.pdf$/i, "");
      papers.push({ id: stem, pdf: path.join(DATA_ROOT, entry.name) });
    }
  }
  // Annotate with output/checkpoint presence
  return papers.map((p) => {
    const finalPath = path.join(OUTPUTS_ROOT, `${p.id}_extraction.json`);
    const checkpointDir = path.join(OUTPUTS_ROOT, "checkpoints", p.id);
    return {
      id: p.id,
      pdfPath: p.pdf,
      hasOutput: fs.existsSync(finalPath),
      hasCheckpoints: fs.existsSync(checkpointDir),
    };
  });
}

function resolvePdfPath(paperId) {
  const folder = path.join(DATA_ROOT, paperId);
  const folderPdf = path.join(folder, `${paperId}.pdf`);
  if (fs.existsSync(folderPdf)) return folderPdf;
  if (fs.existsSync(folder) && fs.statSync(folder).isDirectory()) {
    const pdfs = fs.readdirSync(folder).filter((f) => f.toLowerCase().endsWith(".pdf"));
    if (pdfs.length) return path.join(folder, pdfs[0]);
  }
  const flatPdf = path.join(DATA_ROOT, `${paperId}.pdf`);
  if (fs.existsSync(flatPdf)) return flatPdf;
  return null;
}

// API Routes
app.get("/api/papers", async (_req, res) => {
  try {
    const papers = await listPapers();
    res.json({ papers });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: String(err) });
  }
});

app.get("/api/papers/:id/pdf", (req, res) => {
  const pdfPath = resolvePdfPath(req.params.id);
  if (!pdfPath) return res.status(404).json({ error: "PDF not found" });

  // Get file stats for Range request support
  const stat = fs.statSync(pdfPath);
  const fileSize = stat.size;
  const range = req.headers.range;

  // Set Content-Type
  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Accept-Ranges', 'bytes');

  if (range) {
    // Parse Range header (e.g., "bytes=0-1023")
    const parts = range.replace(/bytes=/, '').split('-');
    const start = parseInt(parts[0], 10);
    const end = parts[1] ? parseInt(parts[1], 10) : fileSize - 1;
    const chunksize = (end - start) + 1;

    // Create read stream for the requested range
    const file = fs.createReadStream(pdfPath, { start, end });

    // Send 206 Partial Content with proper headers
    res.writeHead(206, {
      'Content-Range': `bytes ${start}-${end}/${fileSize}`,
      'Content-Length': chunksize,
    });

    file.pipe(res);
  } else {
    // No range requested, send entire file
    res.writeHead(200, {
      'Content-Length': fileSize,
    });
    fs.createReadStream(pdfPath).pipe(res);
  }
});

app.get("/api/papers/:id/checkpoints", async (req, res) => {
  const dir = path.join(OUTPUTS_ROOT, "checkpoints", req.params.id);
  if (!fs.existsSync(dir)) return res.json({ checkpoints: [] });
  const files = await fsp.readdir(dir);
  const checkpoints = files
    .filter((f) => f.endsWith(".json"))
    .map((f) => ({
      name: f,
      data: safeJsonRead(path.join(dir, f)),
    }));
  res.json({ checkpoints });
});

app.get("/api/papers/:id/output", (_req, res) => {
  const p = path.join(OUTPUTS_ROOT, `${_req.params.id}_extraction.json`);
  if (!fs.existsSync(p)) return res.status(404).json({ error: "Output not found" });
  const data = safeJsonRead(p);
  res.json({ output: data });
});

app.get("/api/papers/:id/logs", async (req, res) => {
  const pattern = `${req.params.id}_*.log`;
  if (!fs.existsSync(LOGS_ROOT)) return res.json({ logs: [] });
  const files = (await fsp.readdir(LOGS_ROOT)).filter((f) => f.includes(req.params.id));
  res.json({ logs: files.map((f) => path.join(LOGS_ROOT, f)) });
});

app.get("/api/papers/:id/session", async (req, res) => {
  try {
    const sessionPath = path.join(OUTPUTS_ROOT, "logs", `${req.params.id}_session.jsonl`);
    if (!fs.existsSync(sessionPath)) return res.json({ events: [] });
    const lines = (await fsp.readFile(sessionPath, "utf8"))
      .split("\n")
      .filter((l) => l.trim())
      .map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
    res.json({ events: lines });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

app.post("/api/extract", upload.single("file"), async (req, res) => {
  try {
    let pdfPath = req.body.pdfPath;
    // If a file was uploaded, move it into data/papers/<id>/
    if (req.file) {
      const originalName = req.file.originalname || "uploaded.pdf";
      const stem = originalName.replace(/\\.pdf$/i, "") || "uploaded";
      const targetDir = path.join(DATA_ROOT, stem);
      await fsp.mkdir(targetDir, { recursive: true });
      const targetPath = path.join(targetDir, originalName);
      await fsp.rename(req.file.path, targetPath);
      pdfPath = targetPath;
    }
    if (!pdfPath) return res.status(400).json({ error: "pdfPath or file required" });

    // Spawn extraction
    const args = [EXTRACTION_SCRIPT, pdfPath];
    const child = spawn(PYTHON, args, { cwd: ROOT });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (d) => (stdout += d.toString()));
    child.stderr.on("data", (d) => (stderr += d.toString()));
    child.on("close", (code) => {
      res.json({
        status: code === 0 ? "ok" : "error",
        exitCode: code,
        stdout,
        stderr,
      });
    });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: String(err) });
  }
});

// Serve React app for all other routes (SPA fallback)
app.use((req, res) => {
  res.sendFile(path.join(distPath, "index.html"));
});

const PORT = process.env.PORT || 4177;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Production server running on http://0.0.0.0:${PORT}`);
  console.log(`Data root: ${DATA_ROOT}`);
  console.log(`Outputs root: ${OUTPUTS_ROOT}`);
  console.log(`Logs root: ${LOGS_ROOT}`);
});
