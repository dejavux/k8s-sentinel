/**
 * Cursor Agent runtime — local (dev workstation) vs cloud (K8s / CI).
 * Cloud avoids local executor in containers where Agent.prompt local mode fails fast.
 */
import fs from "fs";

import { getCursorModelOption } from "./cursor-model.js";

export type CursorAgentRuntime = "local" | "cloud";

export function resolveCursorAgentRuntime(): CursorAgentRuntime {
  const explicit = process.env.CURSOR_AGENT_RUNTIME?.trim().toLowerCase();
  if (explicit === "cloud" || explicit === "local") {
    return explicit;
  }
  if (process.env.KUBERNETES_SERVICE_HOST) {
    return "cloud";
  }
  return "local";
}

export function getGithubRepoUrl(): string {
  const repo = process.env.SENTINEL_GITHUB_REPO?.trim();
  if (!repo) {
    throw new Error("SENTINEL_GITHUB_REPO is required for GitOps");
  }
  if (repo.startsWith("http://") || repo.startsWith("https://")) {
    return repo.replace(/\.git$/, "");
  }
  return `https://github.com/${repo}`;
}

export function getAgentPromptOptions(apiKey: string) {
  const model = getCursorModelOption();
  const runtime = resolveCursorAgentRuntime();

  if (runtime === "cloud") {
    const branch = process.env.SENTINEL_GITHUB_BASE?.trim() || "main";
    return {
      apiKey,
      model,
      cloud: {
        repos: [{ url: getGithubRepoUrl(), startingRef: branch }],
        skipReviewerRequest: true,
      },
    };
  }

  const infraRoot = process.env.SENTINEL_INFRA_ROOT?.trim();
  const cwd =
    infraRoot && fs.existsSync(infraRoot)
      ? infraRoot
      : process.cwd();
  return {
    apiKey,
    model,
    local: { cwd, settingSources: [] as const },
  };
}

export function formatAgentRuntimeLabel(): string {
  const runtime = resolveCursorAgentRuntime();
  if (runtime === "cloud") {
    const branch = process.env.SENTINEL_GITHUB_BASE?.trim() || "main";
    return `cloud repo=${getGithubRepoUrl()}@${branch}`;
  }
  const infraRoot = process.env.SENTINEL_INFRA_ROOT?.trim();
  return `local cwd=${infraRoot && fs.existsSync(infraRoot) ? infraRoot : process.cwd()}`;
}
