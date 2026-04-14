# EC2 Deployment Guide

## Prerequisites

1. AWS CLI installed and configured with your credentials
2. An existing EC2 instance with:
   - Ubuntu/Amazon Linux
   - Security group allowing:
     - Port 22 (SSH)
     - Port 80 (HTTP) or 443 (HTTPS)
     - Port 4177 (or your custom port)

## Step 1: Build Locally

```bash
npm run build
```

## Step 2: Configure Your EC2 Details

Set these environment variables or replace in commands below:

```bash
export EC2_HOST="ec2-xx-xxx-xxx-xxx.compute-1.amazonaws.com"  # Your EC2 public DNS
export EC2_USER="ec2-user"  # Or "ubuntu" depending on your AMI
export KEY_PATH="~/.ssh/your-key.pem"  # Path to your SSH key
```

## Step 3: Transfer Files to EC2

Transfer the entire project to your EC2 instance:

```bash
# From the project root
cd /path/to/civic-extraction-agent
tar -czf deployment.tar.gz --exclude='node_modules' --exclude='__pycache__' --exclude='.git' .
scp -i $KEY_PATH deployment.tar.gz $EC2_USER@$EC2_HOST:~/
```

## Step 4: SSH into EC2 and Setup

```bash
ssh -i $KEY_PATH $EC2_USER@$EC2_HOST
```

Once connected to EC2:

```bash
# Extract the files
mkdir -p ~/civic_extraction
cd ~/civic_extraction
tar -xzf ~/deployment.tar.gz
rm ~/deployment.tar.gz

# Install Node.js (if not already installed)
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -  # For Amazon Linux
# OR for Ubuntu:
# curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo yum install -y nodejs  # For Amazon Linux
# OR for Ubuntu:
# sudo apt-get install -y nodejs

# Install Python 3.11 (if not already installed)
sudo yum install -y python3.11 python3.11-pip  # Amazon Linux
# OR for Ubuntu:
# sudo apt-get install -y python3.11 python3.11-pip

# Install Python dependencies (if you have any)
cd ~/civic_extraction
# If you have a requirements.txt:
# python3.11 -m pip install -r requirements.txt

# Install Node.js dependencies for the server
cd frontend
npm install --production

# Install PM2 globally to manage the server process
sudo npm install -g pm2
```

## Step 5: Update Server Configuration

The server needs to serve both the static files and the API. Create a production server file:

```bash
cd ~/civic_extraction/frontend
```

Copy this into `server/production.cjs`:

```javascript
const express = require("express");
const cors = require("cors");
const multer = require("multer");
const fs = require("fs");
const fsp = require("fs/promises");
const path = require("path");
const { spawn } = require("child_process");

const app = express();
app.use(cors());
app.use(express.json());

// Paths
const ROOT = path.resolve(__dirname, "..", "..");
const DATA_ROOT = process.env.DATA_ROOT || path.join(ROOT, "data", "papers");
const OUTPUTS_ROOT = process.env.OUTPUTS_ROOT || path.join(ROOT, "outputs");
const LOGS_ROOT = process.env.LOGS_ROOT || path.join(ROOT, "logs");
const PYTHON = process.env.PYTHON_BIN || "python3.11";
const EXTRACTION_SCRIPT = process.env.EXTRACTION_SCRIPT || path.join(ROOT, "scripts", "run_extraction.py");

// Serve static files from dist
app.use(express.static(path.join(__dirname, "..", "dist")));

// Multer storage
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
  res.sendFile(pdfPath);
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

// Serve React app for all other routes
app.get("*", (req, res) => {
  res.sendFile(path.join(__dirname, "..", "dist", "index.html"));
});

const PORT = process.env.PORT || 4177;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Server running on http://0.0.0.0:${PORT}`);
});
```

## Step 6: Start the Server with PM2

```bash
cd ~/civic_extraction/frontend

# Start the server
pm2 start server/production.cjs --name civic-app

# Save PM2 configuration
pm2 save

# Setup PM2 to start on system boot
pm2 startup
# Follow the command output instructions
```

## Step 7: Configure Security Group

Update your EC2 security group to allow traffic on port 4177:

```bash
# On your LOCAL machine (not EC2):
# Get your security group ID
aws ec2 describe-instances --filters "Name=dns-name,Values=$EC2_HOST" --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text

# Add inbound rule for port 4177
aws ec2 authorize-security-group-ingress \
  --group-id <YOUR_SECURITY_GROUP_ID> \
  --protocol tcp \
  --port 4177 \
  --cidr 0.0.0.0/0
```

## Step 8: Access Your Application

Your app should now be accessible at:
```
http://<EC2_PUBLIC_IP>:4177
```

## Optional: Setup Nginx Reverse Proxy (Port 80/443)

If you want to use port 80 instead of 4177:

```bash
# Install Nginx
sudo yum install -y nginx  # Amazon Linux
# OR
# sudo apt-get install -y nginx  # Ubuntu

# Create Nginx config
sudo tee /etc/nginx/conf.d/civic.conf > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://localhost:4177;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
EOF

# Start Nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

Then allow port 80 in your security group:
```bash
aws ec2 authorize-security-group-ingress \
  --group-id <YOUR_SECURITY_GROUP_ID> \
  --protocol tcp \
  --port 80 \
  --cidr 0.0.0.0/0
```

## Useful PM2 Commands

```bash
# View logs
pm2 logs civic-app

# Restart the app
pm2 restart civic-app

# Stop the app
pm2 stop civic-app

# View status
pm2 status

# Monitor
pm2 monit
```

## Updating Your Application

When you make changes:

```bash
# Local machine
npm run build
cd ..
tar -czf deployment.tar.gz --exclude='node_modules' --exclude='__pycache__' --exclude='.git' frontend/dist frontend/server
scp -i $KEY_PATH deployment.tar.gz $EC2_USER@$EC2_HOST:~/

# On EC2
cd ~/civic_extraction
tar -xzf ~/deployment.tar.gz
pm2 restart civic-app
```
