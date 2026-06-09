/**
 * Cursor model resolution — aligned with infra-bootstrap .env (CURSOR_MODEL / CURSOR_AGENT_MODEL).
 */
import dotenv from "dotenv";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.join(__dirname, "..", "..");

/** When unset in .env; explicit ids e.g. composer-2.5 also valid. */
export const DEFAULT_CURSOR_MODEL = "composer-2.5";

let envLoaded = false;

function envCandidates(): string[] {
  const infraRoot = process.env.SENTINEL_INFRA_ROOT?.trim();
  return [
    infraRoot ? path.join(infraRoot, ".env") : "",
    path.join(PACKAGE_ROOT, "../../../.env"),
    "/workspace/infra-bootstrap/.env",
    path.join(PACKAGE_ROOT, ".env"),
  ].filter(Boolean);
}

function ensureCursorEnvLoaded(): void {
  if (envLoaded) {
    return;
  }
  envLoaded = true;
  if (
    process.env.CURSOR_API_KEY &&
    (process.env.CURSOR_AGENT_MODEL || process.env.CURSOR_MODEL)
  ) {
    return;
  }
  for (const envPath of envCandidates()) {
    if (fs.existsSync(envPath)) {
      dotenv.config({ path: envPath });
      break;
    }
  }
}

/** Map .env "default" / "auto" to Cursor SDK Auto mode id. */
export function normalizeCursorModelId(raw: string | undefined): string {
  const trimmed = raw?.trim();
  if (!trimmed) {
    return DEFAULT_CURSOR_MODEL;
  }
  if (trimmed.toLowerCase() === "default" || trimmed.toLowerCase() === "auto") {
    return "default";
  }
  return trimmed;
}

export function getCursorAgentModelId(): string {
  ensureCursorEnvLoaded();
  const agent = process.env.CURSOR_AGENT_MODEL?.trim();
  if (agent) {
    return normalizeCursorModelId(agent);
  }
  return normalizeCursorModelId(process.env.CURSOR_MODEL);
}

export function getCursorModelOption(): { id: string } {
  return { id: getCursorAgentModelId() };
}
