// Test helpers for the cruise-family-alerts Worker (node --test, no network, no NCL calls):
// the Worker loaded from its file, a stand-in for D1 (node:sqlite in memory), and a stand-in
// for every address the Worker may call (the published data files, Turnstile, the Apps Script).
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";

export const REPO = new URL("../../../", import.meta.url);
export const PAGE = "https://dasatizabal.github.io/cruise-cabin-comparison/";
export const ORIGIN = "https://dasatizabal.github.io";
export const GITHACK = "https://raw.githack.com";
export const GITHACK_PAGE = "https://raw.githack.com/DASatizabal/cruise-cabin-comparison/0123456789abcdef0123456789abcdef01234567/index.html";
export const APPS_URL = "https://script.google.test/exec";
export const SECRET = "s".repeat(40);
export const readJson = path => JSON.parse(readFileSync(new URL(path, REPO), "utf-8"));
export const sha256 = t => createHash("sha256").update(t).digest("hex");

let loads = 0;
// The Worker file as it is, plus a line that hands its inner functions to the tests.
// testOrigin: replace TEST_ORIGIN (for example "" to test the merged setting).
export async function loadWorker({ testOrigin } = {}) {
  let src = readFileSync(new URL("tools/family-alerts/worker.js", REPO), "utf-8");
  if (testOrigin !== undefined) {
    const line = /^const TEST_ORIGIN = ".*";$/m;
    if (!line.test(src)) throw new Error("TEST_ORIGIN line not found");
    src = src.replace(line, `const TEST_ORIGIN = ${JSON.stringify(testOrigin)};`);
  }
  src += `\n// load ${++loads}\nexport const __t = { priceNow, evaluate, runChecks, readBooking, bookingText, easternDay, TEST_ORIGIN, END_DAY };\n`;
  return import("data:text/javascript;base64," + Buffer.from(src).toString("base64"));
}

class Stmt {
  constructor(db, sql, args = []) { this.db = db; this.sql = sql; this.args = args; }
  bind(...args) {
    for (const a of args) if (a === undefined || typeof a === "boolean" || (typeof a === "object" && a !== null)) throw new Error(`D1 can't bind ${a}`);
    return new Stmt(this.db, this.sql, args);
  }
  async first(col) { const r = this.db.prepare(this.sql).get(...this.args); return r ? (col ? r[col] : { ...r }) : null; }
  async all() { return { results: this.db.prepare(this.sql).all(...this.args).map(r => ({ ...r })) }; }
  async run() { return this._run(); }
  _run() { const r = this.db.prepare(this.sql).run(...this.args); return { meta: { changes: Number(r.changes) } }; }
}

export class FakeD1 {
  constructor() { this.db = new DatabaseSync(":memory:"); }
  prepare(sql) { return new Stmt(this.db, sql); }
  async batch(stmts) {
    this.db.exec("BEGIN");
    try { const out = stmts.map(s => s._run()); this.db.exec("COMMIT"); return out; } catch (e) { this.db.exec("ROLLBACK"); throw e; }
  }
  rows(table) { return this.db.prepare(`SELECT * FROM ${table}`).all().map(r => ({ ...r })); }
  tables() { return this.db.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all().map(r => r.name); }
  dump() { return JSON.stringify(this.tables().map(t => this.rows(t))); }
}

// The network as the Worker sees it. Anything else fails the test (so no NCL address, ever).
export function fakeNet() {
  const net = {
    files: {}, mailMode: "ok", tsHost: "dasatizabal.github.io", mails: [], verifies: 0, calls: [],
    async fetch(url, init = {}) {
      url = String(url);
      net.calls.push(url);
      if (url.startsWith(PAGE + "data/")) {
        const name = url.slice((PAGE + "data/").length).split("?")[0];
        const body = net.files[name];
        return body === undefined || body === null ? new Response("Not found", { status: 404 }) : Response.json(structuredClone(body));
      }
      if (url === "https://challenges.cloudflare.com/turnstile/v0/siteverify") {
        net.verifies++;
        const form = new URLSearchParams(init.body.toString());
        const good = form.get("secret") === "ts-secret" && form.get("response") === "good-token";
        return Response.json(good ? { success: true, hostname: net.tsHost } : { success: false, "error-codes": ["invalid-input-response"] });
      }
      if (url === APPS_URL) {
        const req = JSON.parse(init.body);
        if (req.secret !== SECRET) return Response.json({ ok: false, error: "forbidden" });
        const sent = req.messages.map(() => net.mailMode === "ok");
        net.mails.push(...req.messages.map((m, i) => ({ ...m, kind: req.kind, sent: sent[i] })));
        return Response.json(net.mailMode === "down" ? { ok: false } : { ok: true, sent, remaining: 50 });
      }
      throw new Error("unexpected address in the test: " + url);
    },
  };
  globalThis.fetch = net.fetch;
  return net;
}

export const env = db => ({ DB: db, TURNSTILE_SECRET: "ts-secret", APPS_SCRIPT_URL: APPS_URL, APPS_SCRIPT_SECRET: SECRET });

export async function post(worker, e, path, body, origin = ORIGIN) {
  const r = await worker.default.fetch(new Request("https://family.test" + path, {
    method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body: typeof body === "string" ? body : JSON.stringify(body) }), e);
  return { status: r.status, body: await r.json().catch(() => null), headers: r.headers };
}

// Logs written by the Worker during the tests (to make sure nothing personal is in them).
export const logs = [];
const log = console.log;
console.log = (...a) => { logs.push(a.join(" ")); };
export const realLog = log;
