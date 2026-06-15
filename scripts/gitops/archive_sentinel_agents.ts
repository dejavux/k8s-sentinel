#!/usr/bin/env tsx
/**
 * Bulk archive Cursor cloud agents (clears sidebar clutter from k8s-sentinel).
 *
 * Usage:
 *   source ../../.env   # CURSOR_API_KEY
 *   npx tsx scripts/gitops/archive_sentinel_agents.ts --dry-run
 *   npx tsx scripts/gitops/archive_sentinel_agents.ts
 *   npx tsx scripts/gitops/archive_sentinel_agents.ts --all
 */
import { Agent } from "@cursor/sdk";

const DEFAULT_MATCH =
  process.env.SENTINEL_ARCHIVE_MATCH ??
  "(sentinel|kube-proxy|kube.proxy|kube-flannel|components|gitops)";

function parseArgs(argv: string[]) {
  let dryRun = false;
  let archiveAll = false;
  let matchPattern = DEFAULT_MATCH;
  let limit = 200;

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--dry-run") {
      dryRun = true;
    } else if (arg === "--all") {
      archiveAll = true;
    } else if (arg === "--match" && argv[i + 1]) {
      matchPattern = argv[i + 1];
      i += 1;
    } else if (arg === "--limit" && argv[i + 1]) {
      limit = Number.parseInt(argv[i + 1], 10);
      i += 1;
    }
  }

  return { dryRun, archiveAll, matchPattern, limit };
}

function matchesAgent(
  name: string,
  summary: string,
  archiveAll: boolean,
  regex: RegExp,
): boolean {
  if (archiveAll) {
    return true;
  }
  const haystack = `${name}\n${summary}`;
  return regex.test(haystack);
}

async function listCloudAgents(apiKey: string, maxItems: number) {
  const items = [];
  let cursor: string | undefined;
  while (items.length < maxItems) {
    const page = await Agent.list({
      runtime: "cloud",
      apiKey,
      limit: Math.min(50, maxItems - items.length),
      cursor,
      includeArchived: false,
    });
    items.push(...page.items);
    if (!page.nextCursor || page.items.length === 0) {
      break;
    }
    cursor = page.nextCursor;
  }
  return items;
}

async function main() {
  const apiKey = process.env.CURSOR_API_KEY;
  if (!apiKey) {
    console.error("CURSOR_API_KEY required");
    process.exit(1);
  }

  const { dryRun, archiveAll, matchPattern, limit } = parseArgs(
    process.argv.slice(2),
  );
  const regex = new RegExp(matchPattern, "i");

  const agents = await listCloudAgents(apiKey, limit);
  const targets = agents.filter((agent) =>
    matchesAgent(agent.name, agent.summary ?? "", archiveAll, regex),
  );

  console.error(
    `found ${agents.length} cloud agent(s); ${targets.length} match` +
      (archiveAll ? " (--all)" : ` (/${matchPattern}/)`),
  );

  if (targets.length === 0) {
    return;
  }

  for (const agent of targets) {
    const label = `${agent.agentId}  ${agent.name}`;
    if (dryRun) {
      console.log(`[dry-run] would archive ${label}`);
      continue;
    }
    await Agent.archive(agent.agentId, { apiKey });
    console.log(`archived ${label}`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
