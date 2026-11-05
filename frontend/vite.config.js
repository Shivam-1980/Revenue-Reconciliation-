import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";

// HTTPS for the dev server when EKO_HTTPS=true (environment or backend/.env); same certificate as the backend.
function flag(name) {
  if (process.env[name] !== undefined) return /^(1|true|yes|on)$/i.test(process.env[name]);
  try {
    const text = fs.readFileSync(path.resolve(__dirname, "../backend/.env"), "utf8");
    const m = text.match(new RegExp(`^\s*${name}\s*=\s*(\S+)`, "mi"));
    return !!m && /^(1|true|yes|on)$/i.test(m[1]);
  } catch (_) { return false; }
}

const certDir = path.resolve(__dirname, "../backend/data/certs");
const https = flag("EKO_HTTPS") && fs.existsSync(path.join(certDir, "eko-local.crt"))
  ? { cert: fs.readFileSync(path.join(certDir, "eko-local.crt")), key: fs.readFileSync(path.join(certDir, "eko-local.key")) }
  : undefined;

export default defineConfig({ server: { https } });
