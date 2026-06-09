#!/usr/bin/env tsx
/**
 * Generate fix PR metadata from Sentinel check/fix JSON via Cursor SDK.
 * Usage: echo '{"checks":{...}}' | npx tsx cursor_fix_pr.ts
 */
import { Agent } from "@cursor/sdk";
import { getCursorModelOption } from "../lib/cursor-model.js";

async function main() {
  const input = await new Promise<string>((resolve) => {
    let buf = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (buf += c));
    process.stdin.on("end", () => resolve(buf));
  });

  const apiKey = process.env.CURSOR_API_KEY;
  if (!apiKey) {
    console.error("CURSOR_API_KEY required");
    process.exit(1);
  }

  const prompt = `你是 infra-bootstrap 基礎設施工程師。根據 Sentinel 檢查/修復結果，產生 GitHub PR 資訊。

輸入 JSON:
${input.slice(0, 80000)}

重點處理 checks.pods / fixes.pods：
- CrashLoopBackOff：比對 pod logs、events、ConfigMap 掛載 key 與 deployment args（例如 loki local-config.yaml）
- Pending：資源不足 / disk-pressure / affinity — 建議 manifest 或 node 維護腳本變更
- NotReady：sidecar 或 probe 問題 — 修正 deployment/statefulset manifest
- 參考 repo 路徑：70_monitoring/manifests/platform/loki/、60_apps/k8s-sentinel/、40_k8s/

輸出純 JSON（不要 markdown fence）:
{
  "title": "fix(sentinel): ...",
  "body": "## Summary\\n...\\n## Test plan\\n- [ ] ...",
  "branch": "sentinel/fix-...",
  "files": [{"path":"relative/path","content":"..."}]
}

只包含需要提交到 repo 的修復檔案（manifest、playbook、腳本）。低風險 ConfigMap/deployment 修正可自動 merge。`;

  const result = await Agent.prompt(prompt, {
    apiKey,
    model: getCursorModelOption(),
  });

  if (result.status !== "finished" || !result.result?.trim()) {
    console.error(`Agent failed: ${result.status} model=${getCursorModelOption().id}`);
    process.exit(1);
  }
  const text = result.result.trim();
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) {
    console.error("no JSON in agent output");
    process.exit(1);
  }
  process.stdout.write(match[0]);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
