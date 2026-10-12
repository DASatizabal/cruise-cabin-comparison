// Cloudflare Worker "cruise-refresh-trigger": starts the "Refresh prices" GitHub workflow
// on a timer, because GitHub's own schedule is unreliable for this repo (NOTES.md).
//
// Cron triggers (set in the Cloudflare dashboard): "20 10 * * *" and "5 15 * * *" (UTC).
// Secret: GITHUB_TOKEN, a fine-grained token for this one repository with only
// "Actions: Read and write". Never put the token in this file or anywhere in the repo.
//
// Each run asks GitHub to start the workflow on main with source "timer". The workflow's
// first job skips work already done today, so extra or late runs cost nothing.
// Visiting the Worker's address only returns a short message; it never starts a run.

const DISPATCH_URL =
  "https://api.github.com/repos/DASatizabal/cruise-cabin-comparison/actions/workflows/refresh-prices.yml/dispatches";

export default {
  async fetch() {
    return new Response("Cruise price refresh timer. Nothing to see here.\n", {
      headers: { "content-type": "text/plain; charset=utf-8" },
    });
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(startRefresh(env, controller.cron));
  },
};

async function startRefresh(env, cron) {
  if (!env.GITHUB_TOKEN) {
    console.log(`cron "${cron}": the GITHUB_TOKEN secret is missing, nothing sent`);
    return;
  }
  try {
    const res = await fetch(DISPATCH_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cruise-refresh-trigger",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { source: "timer" } }),
    });
    if (res.ok) {
      console.log(`cron "${cron}": GitHub answered ${res.status}, "Refresh prices" started`);
    } else {
      // 401: token wrong or expired. 403 or 404: token lacks "Actions: Read and write" for this repo.
      const text = (await res.text()).slice(0, 300);
      console.log(`cron "${cron}": GitHub answered ${res.status}, no run started: ${text}`);
    }
  } catch (e) {
    console.log(`cron "${cron}": could not reach GitHub: ${e}`);
  }
}
