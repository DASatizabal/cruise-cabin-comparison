// Tests of tools/family-alerts/worker.js: node --test "tools/family-alerts/test/*.test.mjs"
// No network and no NCL calls: the data files, Turnstile and the Apps Script are stand-ins.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadWorker, FakeD1, fakeNet, env as makeEnv, post, readJson, sha256, logs, REPO,
         PAGE, ORIGIN, GITHACK, GITHACK_PAGE } from "./helpers.mjs";

const worker = await loadWorker();
const net = fakeNet();
const NOW = new Date();
const EM_DASH = String.fromCharCode(0x2014);
const iso = d => d.toISOString().replace(/\.\d{3}Z$/, "Z");
const hoursAgo = h => iso(new Date(NOW.getTime() - h * 3600000));
const money = n => "$" + n.toLocaleString("en-US", { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 });

const PRICES = readJson("data/prices.json");
const getaway = PRICES.sailings.find(s => s.id.startsWith("getaway"));
const aura = PRICES.sailings.find(s => s.id.startsWith("aura"));
const cats = s => s.types.flatMap(t => t.categories.map(c => ({ t, c })));
// A Balcony cabin that isn't a Guarantee and is available for 2 to 4 guests on each ship.
const pick = s => cats(s).find(({ t, c }) => t.code === "BALCONY" && !c.guarantee && ["2", "3", "4"].every(g => c.by_guests[g].available)).c;
const GB = pick(getaway), AB = pick(aura);
const GTY = cats(getaway).find(({ c }) => c.guarantee && c.by_guests["2"].available).c;
// A category that isn't available for some party size, for the refused watch.
const closed = cats(getaway).map(({ c }) => c).map(c => [c, ["2", "3", "4", "5"].find(g => !c.by_guests[g].available)]).find(([, g]) => g);

function files({ prices = PRICES, counts = null, florida = null } = {}) {
  net.files = { "prices.json": prices, "counts.json": counts, "florida.json": florida };
}
function countsFile(left = {}, savedHoursAgo = 1) {
  const sailings = {};
  for (const s of [getaway, aura]) {
    sailings[s.id] = {};
    for (const { c } of cats(s)) {
      if (c.guarantee) continue;
      sailings[s.id][c.code] = { open_decks: [], open_locations: [], by_guests: Object.fromEntries(["2", "3", "4", "5"].map(g =>
        [g, { cabins_left: left[`${s.id}/${c.code}/${g}`] ?? 80, reliable: true, why: null, checked_at: hoursAgo(1) }])) };
    }
  }
  return { schema_version: 1, saved_at: hoursAgo(savedHoursAgo), mode: "full", sailings };
}
function floridaFile(off, days = 1) {
  const at = hoursAgo(days * 24);
  const sailings = {};
  for (const s of [getaway, aura]) {
    sailings[s.id] = { package_id: s.package_id, missing: [], categories: {} };
    for (const { t, c } of cats(s)) sailings[s.id].categories[c.code] = { type: t.code, website_fare_pp: 1000, florida_fare_pp: 1000 - (off[c.code] || 0), off_pp: off[c.code] || 0, checked_at: at, source: "test" };
  }
  return { schema_version: 1, saved_at: at, guests: 2, source: "test", check: "full", checked_on: at.slice(0, 10), sailings };
}
// A copy of the prices with changes: fn(copy, getaway, aura) edits it; saved_at moves on by minutes.
let bump = 0;
function pricesWith(fn) {
  const p = structuredClone(PRICES);
  p.saved_at = iso(new Date(Date.parse(PRICES.saved_at) + ++bump * 60000));
  fn(p, p.sailings.find(s => s.id.startsWith("getaway")), p.sailings.find(s => s.id.startsWith("aura")));
  return p;
}
const catIn = (s, code) => cats(s).find(({ c }) => c.code === code).c;
const setPrice = (ship, code, n, total) => pricesWith((p, g, a) => { catIn(ship === "G" ? g : a, code).by_guests[String(n)].cabin_total = total; });

const fresh = () => { const db = new FakeD1(); return { db, env: makeEnv(db) }; };
const watchBody = (over = {}) => ({ option: "G", ship: "G", cabin: GB.code, guests: 2, florida: false, drop_pp: 20, few: true, sold_out: true,
                                    frequency: "now", email: "Family.One@Example.com", page: PAGE, turnstile: "good-token", ...over });
const lastMail = () => net.mails[net.mails.length - 1];
const linkToken = (text, kind) => (text.match(new RegExp(`#${kind}=([A-Za-z0-9_-]{43})`)) || [])[1];

async function started(e, over = {}) {
  const before = net.mails.length;
  const r = await post(worker, e, "/watch", watchBody(over));
  assert.equal(r.status, 200, JSON.stringify(r.body));
  assert.equal(net.mails.length, before + 1);
  const m = lastMail();
  const c = await post(worker, e, "/confirm", { token: linkToken(m.body, "confirm") });
  assert.equal(c.status, 200, JSON.stringify(c.body));
  return { mail: m, watch: c.body.watch };
}

test("GET / answers with a short message; other origins are refused; the preflight", async () => {
  const { env } = fresh();
  files();
  const r = await worker.default.fetch(new Request("https://family.test/"), env);
  assert.equal(r.status, 200);
  assert.match(await r.text(), /Nothing to see here/);
  const bad = await post(worker, env, "/watch", watchBody(), "https://evil.example");
  assert.equal(bad.status, 403);
  const pre = await worker.default.fetch(new Request("https://family.test/watch", { method: "OPTIONS", headers: { Origin: ORIGIN } }), env);
  assert.equal(pre.status, 204);
  assert.equal(pre.headers.get("Access-Control-Allow-Origin"), ORIGIN);
  assert.equal((await post(worker, env, "/nothing", {})).status, 404);
  assert.equal((await post(worker, env, "/watch", "{not json")).status, 400);
  assert.equal((await post(worker, env, "/watch", "x".repeat(40000))).status, 400);
});

test("watch: stored unconfirmed with the person's choices, a confirmation email, tokens kept only as SHA-256", async () => {
  const { db, env } = fresh();
  files();
  const r = await post(worker, env, "/watch", watchBody());
  assert.equal(r.status, 200);
  const price = GB.by_guests["2"].cabin_total;
  assert.deepEqual(r.body, { ok: true, price, hours: 48 });
  const m = lastMail();
  assert.deepEqual([m.kind, m.to, m.subject], ["watch", "family.one@example.com", "Confirm your cruise price watch"]);
  const confirm = linkToken(m.body, "confirm"), manage = linkToken(m.body, "manage");
  assert.ok(m.body.includes(`${PAGE}#confirm=${confirm}`));
  assert.ok(m.body.includes(`Option 1: 3 nights\nNorwegian Getaway, Jun 11 to Jun 14, 2027 (3 nights)\nCabin: ${GB.description} (${GB.code})\n2 guests, website price\nPrice today: ${money(price)} for the cabin (${money(price / 2)} per guest)`), m.body);
  assert.ok(m.body.includes(["You asked for:", "- an email when the price drops by at least $20 per guest ($40 for the cabin)",
                             "- an email when fewer than 10 of these cabins are left", "- an email if it is no longer available for 2 guests",
                             "- emails as soon as a check finds something (prices are checked twice a day)"].join("\n")), m.body);
  const [w] = db.rows("watches");
  assert.deepEqual([w.confirmed_at, w.baseline, w.ship, w.code, w.drop_pp, w.few, w.sold_out, w.frequency], [null, price, "G", GB.code, 20, 1, 1, "now"]);
  const dump = db.dump();
  assert.ok(!dump.includes(confirm) && !dump.includes(manage), "a token is stored as it is");
  assert.deepEqual(db.rows("tokens").map(t => t.hash).sort(), [sha256(confirm), sha256(manage)].sort());
  assert.deepEqual(db.tables(), ["aboard", "aboard_links", "tokens", "watches"]);
});

test("watch: the 8 night card watches one ship's cabin; other choices; a Guarantee cabin has no few left email", async () => {
  const { db, env } = fresh();
  files();
  await post(worker, env, "/watch", watchBody({ option: "8", ship: "A", cabin: AB.code, guests: 3, drop_pp: 35, few: false, sold_out: false, frequency: "daily" }));
  const m = lastMail();
  assert.ok(m.body.includes(`Option 3: 8 nights, the Aura cabin\nNorwegian Aura, Jun 14 to Jun 19, 2027 (5 nights)\nCabin: ${AB.description} (${AB.code})\n3 guests, website price`), m.body);
  assert.ok(m.body.includes("You asked for:\n- an email when the price drops by at least $35 per guest ($105 for the cabin)\n- at most one email a day, in the morning"), m.body);
  assert.deepEqual(db.rows("watches").map(w => [w.option, w.ship, w.baseline]), [["8", "A", AB.by_guests["3"].cabin_total]]);
  await post(worker, env, "/watch", watchBody({ cabin: GTY.code, email: "g@example.com" }));
  assert.equal(db.rows("watches").find(w => w.code === GTY.code).few, 0);
  assert.ok(!lastMail().body.includes("fewer than 10") && lastMail().body.includes(GTY.description));
});

test("watch: refused requests store and send nothing", async () => {
  const { db, env } = fresh();
  files();
  const sends = net.mails.length;
  const cases = [
    [{ email: "not-an-email" }, "email"], [{ turnstile: "bad-token" }, "check"], [{ option: "X" }, "request"],
    [{ ship: "A" }, "request"], [{ option: "8", ship: "X" }, "request"], [{ guests: 6 }, "request"], [{ florida: "yes" }, "request"],
    [{ cabin: "b4; DROP" }, "request"], [{ few: "yes" }, "request"], [{ sold_out: 1 }, "request"], [{ frequency: "weekly" }, "request"],
    [{ drop_pp: 0 }, "drop"], [{ drop_pp: 1001 }, "drop"], [{ drop_pp: "20" }, "drop"], [{ drop_pp: null }, "drop"],
    [{ page: "https://example.com/" }, "request"], [{ page: "https://dasatizabal.github.io/other/" }, "request"],
    [{ cabin: "ZZ" }, "cabin"], [{ cabin: closed[0].code, guests: Number(closed[1]) }, "unavailable"],
  ];
  for (const [over, error] of cases) {
    const r = await post(worker, env, "/watch", watchBody(over));
    assert.equal(r.status, 400, JSON.stringify(over));
    assert.equal(r.body.error, error, JSON.stringify(over));
    assert.ok(r.body.message && !r.body.message.includes(EM_DASH));
  }
  assert.equal(net.mails.length, sends);
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0);
  net.tsHost = "example.com";
  assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "check");
  net.tsHost = "dasatizabal.github.io";
  net.files = {};
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 503);
  files();
  net.mailMode = "quota";
  const q = await post(worker, env, "/watch", watchBody());
  net.mailMode = "ok";
  assert.deepEqual([q.status, q.body.error], [503, "mail"]);
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0);
});

test("watch: a raw.githack.com preview works only while TEST_ORIGIN is set (testing before a merge)", async () => {
  const { env } = fresh();
  files();
  const testing = await loadWorker({ testOrigin: GITHACK });
  try {
    net.tsHost = "raw.githack.com";
    const r = await post(testing, env, "/watch", watchBody({ page: GITHACK_PAGE }), GITHACK);
    assert.equal(r.status, 200, JSON.stringify(r.body));
    assert.ok(lastMail().body.includes(GITHACK_PAGE + "#confirm="));
    assert.equal((await post(testing, env, "/watch", watchBody({ page: GITHACK_PAGE }))).body.error, "request");
    // The Worker as committed: no preview address.
    assert.equal(worker.__t.TEST_ORIGIN, "");
    assert.equal((await post(worker, env, "/watch", watchBody({ page: GITHACK_PAGE }), GITHACK)).status, 403);
    assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "check", "Turnstile solved on raw.githack.com");
  } finally {
    net.tsHost = "dasatizabal.github.io";
  }
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);
});

test("watch: 3 unconfirmed a day and 10 watches per email address", async () => {
  const { db, env } = fresh();
  files();
  for (let i = 0; i < 3; i++) assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);
  assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "daily");
  assert.equal((await post(worker, env, "/watch", watchBody({ email: "other@example.com" }))).status, 200);
  db.db.exec("UPDATE watches SET confirmed_at = created_at");
  for (let i = 0; i < 6; i++) {
    db.db.prepare(`INSERT INTO watches (id, email, option, ship, code, guests, florida, drop_pp, few, sold_out, frequency, label, page, baseline, first_price, created_at, confirmed_at)
                   VALUES (?, 'family.one@example.com', 'G', 'G', 'BF', 2, 0, 20, 1, 1, 'now', 'x', ?, 1, 1, ?, ?)`).run(`id${i}`, PAGE, hoursAgo(100), hoursAgo(99));
  }
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);   // the 10th
  assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "limit");
});

test("the first test version's tables are replaced", async () => {
  const { db, env } = fresh();
  db.db.exec(`CREATE TABLE watches (id TEXT PRIMARY KEY, email TEXT NOT NULL, option TEXT NOT NULL, guests INTEGER NOT NULL, florida INTEGER NOT NULL,
              cabins TEXT NOT NULL, label TEXT NOT NULL, page TEXT NOT NULL, baseline REAL NOT NULL, first_price REAL NOT NULL, last_price REAL,
              created_at TEXT NOT NULL, confirmed_at TEXT, checked_key TEXT, few_sent INTEGER NOT NULL DEFAULT 0, sold_out_sent INTEGER NOT NULL DEFAULT 0)`);
  db.db.exec("CREATE TABLE tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, watch_id TEXT, email TEXT, created_at TEXT NOT NULL)");
  db.db.exec(`INSERT INTO watches (id, email, option, guests, florida, cabins, label, page, baseline, first_price, created_at) VALUES ('old', 'a@example.com', '8', 2, 0, '{}', 'x', 'p', 1, 1, 'now')`);
  db.db.exec("INSERT INTO tokens VALUES ('h', 'manage', NULL, 'a@example.com', 'now')");
  files();
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);
  assert.deepEqual(db.rows("watches").map(w => w.email), ["family.one@example.com"]);
  assert.ok(db.rows("tokens").every(t => t.email !== "a@example.com"));
  // The new tables are kept on the next start (a new binding object for the same database).
  const again = Object.assign(Object.create(FakeD1.prototype), { db: db.db });
  assert.equal((await post(worker, makeEnv(again), "/watch", watchBody({ email: "b@example.com" }))).status, 200);
  assert.equal(db.rows("watches").length, 2);
});

test("confirm: starts once; the same cabin again keeps one watch with the new choices; expired after 48 hours", async () => {
  const { db, env } = fresh();
  files();
  await post(worker, env, "/watch", watchBody());
  const token = linkToken(lastMail().body, "confirm");
  const c = await post(worker, env, "/confirm", { token });
  assert.equal(c.status, 200);
  assert.equal(c.body.already, false);
  assert.equal(c.body.watch.watched, GB.by_guests["2"].cabin_total);
  assert.deepEqual(c.body.watch.choices, ["an email when the price drops by at least $20 per guest ($40 for the cabin)", "an email when fewer than 10 of these cabins are left",
                                          "an email if it is no longer available for 2 guests", "emails as soon as a check finds something (prices are checked twice a day)"]);
  assert.ok(c.body.watch.label.startsWith("Option 1: 3 nights\nNorwegian Getaway"));
  assert.ok(!JSON.stringify(c.body).includes("@"), "the answer has no email address");
  assert.equal((await post(worker, env, "/confirm", { token })).status, 404);
  await post(worker, env, "/watch", watchBody({ email: "FAMILY.ONE@example.com", drop_pp: 50, few: false, frequency: "daily" }));
  const twin = await post(worker, env, "/confirm", { token: linkToken(lastMail().body, "confirm") });
  assert.equal(twin.body.already, true);
  assert.deepEqual(twin.body.watch.choices, ["an email when the price drops by at least $50 per guest ($100 for the cabin)", "an email if it is no longer available for 2 guests", "at most one email a day, in the morning"]);
  assert.deepEqual(db.rows("watches").map(w => [w.drop_pp, w.few, w.frequency]), [[50, 0, "daily"]]);
  await post(worker, env, "/watch", watchBody({ guests: 3 }));
  db.db.prepare("UPDATE watches SET created_at = ? WHERE confirmed_at IS NULL").run(hoursAgo(49));
  assert.equal((await post(worker, env, "/confirm", { token: linkToken(lastMail().body, "confirm") })).status, 404);
  assert.equal(db.rows("watches").length, 1);
  assert.equal((await post(worker, env, "/confirm", { token: "short" })).status, 404);
});

test("manage and unsubscribe", async () => {
  const { db, env } = fresh();
  files();
  const a = await started(env);
  await started(env, { option: "A", ship: "A", cabin: AB.code, guests: 3 });
  await post(worker, env, "/watch", watchBody({ option: "8", ship: "A", cabin: AB.code }));   // waiting for its link
  const token = linkToken(a.mail.body, "manage");
  const list = await post(worker, env, "/manage", { token });
  assert.equal(list.status, 200);
  assert.deepEqual([list.body.watches.length, list.body.waiting], [2, 1]);
  assert.ok(list.body.watches.every(w => w.choices.length === 4));
  const stop = await post(worker, env, "/manage", { token, stop: list.body.watches[0].id });
  assert.equal(stop.body.watches.length, 1);
  assert.equal((await post(worker, env, "/manage", { token, stop: "nope" })).status, 404);
  const all = await post(worker, env, "/manage", { token, stop: "all" });
  assert.deepEqual([all.body.watches, all.body.waiting], [[], 0]);
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0, "the address and its links are gone");
  assert.equal((await post(worker, env, "/manage", { token })).status, 404);
});

test("checks: a drop of at least the chosen amount per guest, once; then the new price is watched", async () => {
  const { db, env } = fresh();
  files();
  await started(env);   // $20 per guest at 2 guests: $40 for the cabin
  let r = await worker.__t.runChecks(env, NOW);
  assert.deepEqual([r.checked, r.sent], [1, 0]);
  assert.equal((await worker.__t.runChecks(env, NOW)).checked, 0, "the same files are not checked twice");
  const was = GB.by_guests["2"].cabin_total;
  files({ prices: setPrice("G", GB.code, 2, was - 39.5) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0, "$39.50 is less than $40");
  assert.equal(db.rows("watches")[0].last_price, was - 39.5);
  files({ prices: setPrice("G", GB.code, 2, was - 40) });
  r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.sent, 1);
  const m = lastMail();
  assert.deepEqual([m.kind, m.subject], ["alert", "Cruise price watch: the price dropped"]);
  assert.ok(m.body.includes(`- Price drop: ${money(was)} to ${money(was - 40)} for the cabin, $40 less ($20 per guest). From now on the watch compares with ${money(was - 40)}.`), m.body);
  assert.equal(db.rows("watches")[0].baseline, was - 40);
  files({ prices: setPrice("G", GB.code, 2, was) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  files({ prices: setPrice("G", GB.code, 2, was - 41) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0, "only $1 below the price watched");
  const u = await post(worker, env, "/unsubscribe", { token: linkToken(m.body, "unsubscribe") });
  assert.equal(u.status, 200);
  assert.equal(db.rows("watches").length, 0);
  assert.equal((await post(worker, env, "/unsubscribe", { token: linkToken(m.body, "unsubscribe") })).status, 404);
});

test("checks: few left and sold out once each, only when ticked; a party size NCL didn't update is skipped", async () => {
  const { db, env } = fresh();
  files({ counts: countsFile() });
  await started(env, { guests: 3 });
  await started(env, { guests: 3, email: "quiet@example.com", few: false, sold_out: false });
  await worker.__t.runChecks(env, NOW);
  files({ counts: countsFile({ [`${getaway.id}/${GB.code}/3`]: 7 }, 0.5) });
  let r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.sent, 1);
  assert.deepEqual([lastMail().to, lastMail().subject], ["family.one@example.com", "Cruise price watch: news on your cabin"]);
  assert.match(lastMail().body, /- Only 7 of these cabins left for 3 guests \(cabins left as of [A-Z][a-z]{2} \d+, 20\d\d\)\. You won't get this email again\./);
  files({ counts: countsFile({ [`${getaway.id}/${GB.code}/3`]: 4 }, 0.2) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  // Counts more than 7 days old are not used.
  const { env: env2 } = fresh();
  files({ counts: countsFile({ [`${getaway.id}/${GB.code}/2`]: 3 }, 24 * 8) });
  await started(env2);
  assert.equal((await worker.__t.runChecks(env2, NOW)).sent, 0);
  const soldOut = (g, ps = true) => { catIn(g, GB.code).by_guests["3"] = { available: false, sold_out: true, reason: "Sold out" }; g.party_sizes["3"].updated = ps; };
  files({ prices: pricesWith((p, g) => soldOut(g, false)) });
  r = await worker.__t.runChecks(env, NOW);
  assert.deepEqual([r.skipped, r.sent], [2, 0]);
  files({ prices: pricesWith((p, g) => soldOut(g)) });
  r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.sent, 1, "only the watch that asked for it");
  assert.ok(lastMail().body.includes("- No longer available for 3 guests (NCL: Sold out)."));
  files({ prices: pricesWith((p, g) => soldOut(g)) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  assert.deepEqual(db.rows("watches").map(w => w.sold_out_sent), [1, 0]);
});

test("checks: once a day watches only on the first check of an Eastern day", async () => {
  const { env } = fresh();
  files();
  await started(env, { frequency: "daily" });
  await started(env, { email: "now@example.com" });
  const morning = new Date(NOW.getTime());
  await worker.__t.runChecks(env, morning);
  const was = GB.by_guests["2"].cabin_total;
  files({ prices: setPrice("G", GB.code, 2, was - 100) });
  const afternoon = new Date(morning.getTime() + 60000);
  let r = await worker.__t.runChecks(env, afternoon);
  assert.deepEqual([r.later, r.sent, lastMail().to], [1, 1, "now@example.com"]);
  r = await worker.__t.runChecks(env, new Date(morning.getTime() + 86400000));
  assert.deepEqual([r.checked, r.sent, lastMail().to], [1, 1, "family.one@example.com"]);
});

test("checks: an alert that can't be sent waits for the next run; one email per address", async () => {
  const { db, env } = fresh();
  files();
  await started(env);
  await started(env, { option: "A", ship: "A", cabin: AB.code });
  await started(env, { email: "other@example.com" });
  await worker.__t.runChecks(env, NOW);
  files({ prices: pricesWith((p, g, a) => { catIn(g, GB.code).by_guests["2"].cabin_total -= 50; catIn(a, AB.code).by_guests["2"].cabin_total -= 50; }) });
  const tokens = db.rows("tokens").length;
  net.mailMode = "quota";
  let r = await worker.__t.runChecks(env, NOW);
  net.mailMode = "ok";
  assert.deepEqual([r.sent, r.waiting], [0, 3]);
  assert.equal(db.rows("tokens").length, tokens, "the links of an email not sent are removed");
  assert.equal(db.rows("watches").filter(w => w.baseline === w.first_price).length, 3);
  const sends = net.mails.length;
  r = await worker.__t.runChecks(env, NOW);
  assert.deepEqual([r.sent, r.waiting], [2, 0]);
  const mine = net.mails.slice(sends).find(m => m.to === "family.one@example.com");
  assert.equal((mine.body.match(/- Price drop/g) || []).length, 2);
  assert.equal((mine.body.match(/#unsubscribe=/g) || []).length, 2);
  assert.equal((mine.body.match(/#manage=/g) || []).length, 1);
  assert.equal((await worker.__t.runChecks(env, NOW)).checked, 0);
});

test("the price watched: NCL's cabin price, minus the cabin's own Florida discount when asked", async () => {
  const t = worker.__t;
  const data = (florida = null) => ({ prices: PRICES, counts: null, florida });
  const w = (ship, code, n, florida) => ({ option: ship, ship, code, guests: n, florida });
  for (const n of [2, 3, 4]) {
    assert.equal(t.priceNow(data(), w("G", GB.code, n, false), NOW).price, GB.by_guests[String(n)].cabin_total);
    assert.equal(t.priceNow(data(), w("A", AB.code, n, true), NOW).price, AB.by_guests[String(n)].cabin_total);
  }
  const fl = floridaFile({ [GB.code]: 60, [AB.code]: 0.5 });
  assert.equal(t.priceNow(data(fl), w("G", GB.code, 3, true), NOW).price, GB.by_guests["3"].cabin_total - 120, "guests 1 and 2");
  assert.equal(t.priceNow(data(fl), w("A", AB.code, 3, true), NOW).price, AB.by_guests["3"].cabin_total, "under $1 is no discount");
  assert.equal(t.priceNow(data(fl), w("G", GB.code, 3, false), NOW).price, GB.by_guests["3"].cabin_total);
  assert.equal(t.priceNow(data(floridaFile({ [GB.code]: 100000 })), w("G", GB.code, 2, true), NOW).price, 2 * getaway.taxes_per_guest, "never more than the fare");
  assert.equal(t.priceNow(data(floridaFile({ [GB.code]: 60 }, 16)), w("G", GB.code, 2, true), NOW).price, GB.by_guests["2"].cabin_total, "older than 15 days");
  const { db, env } = fresh();
  files({ florida: fl });
  await started(env, { florida: true });
  assert.equal(db.rows("watches")[0].baseline, GB.by_guests["2"].cabin_total - 120);
  assert.ok(lastMail().body.includes("2 guests, Florida resident price (when NCL offers one on this cabin)"));
  files({ florida: floridaFile({ [GB.code]: 60 }, 16) });
  assert.equal((await post(worker, env, "/watch", watchBody({ florida: true, email: "x@example.com" }))).body.price, GB.by_guests["2"].cabin_total);
});

test("checks: unconfirmed watches go after 48 hours; everything is deleted from Jun 11, 2027", async () => {
  const { db, env } = fresh();
  files();
  await started(env);
  await post(worker, env, "/watch", watchBody({ guests: 3 }));
  db.db.prepare("UPDATE watches SET created_at = ? WHERE confirmed_at IS NULL").run(hoursAgo(49));
  await worker.__t.runChecks(env, NOW);
  assert.equal(db.rows("watches").length, 1);
  assert.ok(db.rows("tokens").every(t => t.kind === "manage"));
  assert.equal(worker.__t.easternDay(new Date("2027-06-11T03:59:00Z")), "2027-06-10");
  assert.equal((await worker.__t.runChecks(env, new Date("2027-06-11T03:59:00Z"))).ended, undefined);
  assert.equal((await worker.__t.runChecks(env, new Date("2027-06-11T04:00:00Z"))).ended, true);
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0);
});

// ---------- /booking ----------
const LINES = [{ item: "Cruise fare", value: "$1,500" }, { item: "Taxes, fees and port expenses: 3 x $150", value: "$450" },
               { item: "Florida resident rate (checked Oct 27): 2 guests x $60 off the fare", value: "−$120" },
               { item: "Unlimited Open Bar: 2 guests x $81, 1 guest x $37.50 (soda package, under 21)", value: "$199.50" },
               { item: "Specialty Dining - 1 Meal: 3 guests x $20", value: "$60" },
               { item: "Gratuities paid now (service charges are paid onboard)", value: "$259.50" }];
const ONBOARD = [{ item: "Service charges (crew gratuities) (paid onboard, not in the total): 3 guests x $20 x 3 nights", value: "$180 onboard" }];
function bookingBody(over = {}) {
  const b = {
    kind: "booking", page_version: "5.2.0", prices_saved_at: "2026-10-28T10:21:44Z", note: "Prices can change until NCL confirms the booking.",
    option: "Option 1: 3 nights", party: { adults: 2, kid_ages: [15] }, page_switches: { prepay_gratuities: false, florida_resident_rate: true },
    florida: { residents: true, address: { street: "1 Test Street", city: "Miami", state: "FL", zip: "33101" } },
    bookings: [{ ship: "Norwegian Getaway", depart: "2027-06-11", return: "2027-06-14", nights: 3, cabin_type: "Balcony",
                 category: "B4", description: "Balcony, Decks 9 to 12", guarantee: false, free_at_sea: { bar: true, dining: true, plus: false },
                 lines: LINES, total: 2089.5, onboard: ONBOARD,
                 deposit_choice: "credit1", ncl_deposit: { amount: 150, rule: "$50 per guest", due_hours: 74, offer: "2-For-1 Deposits" },
                 credits: 1, credit_value: 250, due_at_booking: 0, balance: 1839.5, balance_due: "2027-02-11", pay_david: 125 }],
    guests: [{ position: 1, adult: true, age_on_sail_date: null, first: "Ann", middle: "", last: "Tester", date_of_birth: "1980-02-03", gender: "Female", citizenship: "USA", latitudes: "123456789" },
             { position: 2, adult: true, age_on_sail_date: null, first: "Bob", middle: "Q", last: "Tester", date_of_birth: "1979-04-05", gender: "Male", citizenship: "USA", latitudes: "987654321" },
             { position: 3, adult: false, age_on_sail_date: 15, first: "Cy", middle: "", last: "Tester", date_of_birth: "2011-08-09", gender: "Male", citizenship: "USA", latitudes: null }],
    guest1: { email: "ann@example.com", phone: "305 555 0100" },
    sender: { is_guest1: false, name: "Sam Sender", email: "sam@example.com" },
    turnstile: "good-token",
  };
  return { ...b, ...over };
}

test("booking: David gets everything, the sender a copy without dates of birth or Latitudes numbers; the window's lines; nothing stored", async () => {
  const { db, env } = fresh();
  files();
  const before = db.dump();
  const sends = net.mails.length;
  const r = await post(worker, env, "/booking", bookingBody());
  assert.equal(r.status, 200, JSON.stringify(r.body));
  assert.deepEqual(r.body, { ok: true, copy: true });
  const [toDavid, copy] = net.mails.slice(sends);
  assert.deepEqual([toDavid.to, toDavid.kind, toDavid.replyTo, toDavid.subject], ["owner", "booking", "sam@example.com", "Booking request: Option 1: 3 nights (Sam Sender)"]);
  assert.deepEqual([copy.to, copy.subject, copy.replyTo], ["sam@example.com", "Your cruise selection was sent to David", undefined]);
  const breakdown = [...LINES.map(x => `${x.item}: ${x.value}`), "Total: $2,089.50", `${ONBOARD[0].item}: ${ONBOARD[0].value}`, "  Can be removed at Guest Services."].join("\n");
  for (const body of [toDavid.body, copy.body]) assert.ok(body.includes(breakdown), body);
  for (const x of ["born Feb 3, 1980", "born Apr 5, 1979", "born Aug 9, 2011", "Latitudes number 123456789", "Latitudes number 987654321",
                   "1 Test Street, Miami, FL 33101", "Guest 1's email: ann@example.com", "Guest 1's mobile phone: 305 555 0100",
                   "Sent by: Sam Sender <sam@example.com>", "Prices can change until NCL confirms the booking.", "Cabin: Balcony: Balcony, Decks 9 to 12 (B4)",
                   "Party: 2 adults and 1 kid (age 15 on Jun 11, 2027)", "Deposit: One of David's CruiseNext credits ($250 toward the cruise, pay David $125)",
                   "Balance, due by Feb 11, 2027: $1,839.50", "Guest 3: Cy Tester, age 15 on Jun 11, 2027"]) {
    assert.ok(toDavid.body.includes(x), x);
  }
  for (const x of ["1980", "1979", "2011-08-09", "Aug 9, 2011", "123456789", "987654321", "Test Street", "ann@example.com", "555 0100"]) {
    assert.ok(!copy.body.includes(x), "the copy has " + x);
  }
  for (const x of ["Hi Sam Sender,", "Guest 1: Ann Tester, adult, Female, citizenship USA"]) assert.ok(copy.body.includes(x), x);
  const me = await post(worker, env, "/booking", bookingBody({ sender: { is_guest1: true, name: "Ann Tester", email: "ann@example.com" } }));
  assert.equal(me.status, 200);
  const mine = lastMail();
  assert.ok(mine.body.includes("1 Test Street") && mine.body.includes("ann@example.com") && !mine.body.includes("1980") && !mine.body.includes("123456789"));
  // Nothing stored but the "Confirm aboard" link's hash and the cast ids it pre-ticks (none here).
  assert.deepEqual([before, db.tables(), db.rows("watches"), db.rows("tokens"), db.rows("aboard")], ["[]", ["aboard", "aboard_links", "tokens", "watches"], [], [], []], "nothing stored");
  assert.ok(db.rows("aboard_links").every(r => r.preticks === "" && r.source === "booking"));
  assert.ok(!db.dump().includes("Tester") && !db.dump().includes("ann@example.com"));
  for (const m of net.mails.slice(sends)) assert.ok(!(m.body + m.subject).includes(EM_DASH));
  // Prepaid: no onboard line.
  const pre = bookingBody();
  pre.bookings[0].onboard = [];
  await post(worker, env, "/booking", pre);
  assert.ok(!net.mails[net.mails.length - 2].body.includes("Can be removed at Guest Services."));
});

test("booking: 8 nights, two bookings and the totals; NCL's deposit wording", async () => {
  const { env } = fresh();
  files();
  const two = bookingBody();
  const g = two.bookings[0];
  two.option = "Option 3: 8 nights";
  two.bookings = [{ ...g, total: 2000, deposit_choice: "ncl", credits: 0, credit_value: 0, due_at_booking: 150, balance: 1850, pay_david: 0 },
                  { ...g, ship: "Norwegian Aura", depart: "2027-06-14", return: "2027-06-19", nights: 5, total: 3000, deposit_choice: "credit2", credits: 2, credit_value: 500, due_at_booking: 0, balance: 2500, pay_david: 250, balance_due: "2027-02-14" }];
  const r = await post(worker, env, "/booking", two);
  assert.equal(r.status, 200, JSON.stringify(r.body));
  const body = net.mails[net.mails.length - 2].body;
  for (const x of ["Booking 1: Norwegian Getaway, Jun 11 to Jun 14, 2027 (3 nights)", "Booking 2: Norwegian Aura, Jun 14 to Jun 19, 2027 (5 nights)",
                   "Deposit: NCL's deposit: $150 ($50 per guest), due within 74 hours of booking, with NCL's 2-For-1 Deposits offer",
                   "Deposit: Two of David's CruiseNext credits, NCL's DoubleUp offer ($500 toward the cruise, pay David $250)",
                   "Both bookings together\nTotal: $5,000\nPaid to NCL at booking: $150\nBalances: $4,350\nPay David for the credits: $250"]) {
    assert.ok(body.includes(x), x);
  }
  assert.equal((await post(worker, env, "/booking", { ...two, bookings: [two.bookings[0]] })).status, 400);
});

test("booking: malformed requests, a failed check and a busy email service send nothing", async () => {
  const { env } = fresh();
  files();
  const sends = net.mails.length;
  const bad = [
    { kind: "watch" }, { option: "Option 9" }, { party: { adults: 0, kid_ages: [5, 6] } }, { party: { adults: 4, kid_ages: [1, 2] } },
    { guests: [] }, { guest1: { email: "nope", phone: "1" } }, { sender: { is_guest1: false, name: "", email: "sam@example.com" } },
    { florida: { residents: "yes", address: null } },
  ];
  for (const over of bad) assert.equal((await post(worker, env, "/booking", bookingBody(over))).status, 400, JSON.stringify(over));
  const edits = [b => { b.guests[0].latitudes = "12ab"; }, b => { b.guests[0].first = "x".repeat(61); }, b => { b.bookings[0].lines = []; },
                 b => { b.bookings[0].lines[0].value = 5; }, b => { b.bookings[0].onboard = [ONBOARD[0], ONBOARD[0]]; }, b => { b.bookings[0].total = "1"; }];
  for (const edit of edits) {
    const b = bookingBody();
    b.bookings[0] = structuredClone(b.bookings[0]);
    b.guests = structuredClone(b.guests);
    edit(b);
    assert.equal((await post(worker, env, "/booking", b)).status, 400, edit.toString());
  }
  assert.equal((await post(worker, env, "/booking", bookingBody({ turnstile: "bad-token" }))).body.error, "check");
  assert.equal(net.mails.length, sends);
  net.mailMode = "quota";
  const busy = await post(worker, env, "/booking", bookingBody());
  net.mailMode = "ok";
  assert.deepEqual([busy.status, busy.body.error], [503, "mail"]);
});

test("the Worker's logs hold nothing personal; it calls no other address", async () => {
  const text = logs.join("\n");
  assert.ok(logs.length > 10);
  for (const x of ["@", "Tester", "Sam Sender", "Test Street", "123456789", "1980", "305 555"]) assert.ok(!text.includes(x), x);
  assert.ok(!/[A-Za-z0-9_-]{43}/.test(text), "a token in the logs");
  const hosts = new Set(net.calls.map(u => new URL(u).host));
  assert.deepEqual([...hosts].sort(), ["challenges.cloudflare.com", "dasatizabal.github.io", "script.google.test"]);
  assert.ok(net.calls.every(u => !/ncl\.com/i.test(u)));
});

test("the Worker file: TEST_ORIGIN off and no em dash", () => {
  const src = readFileSync(new URL("tools/family-alerts/worker.js", REPO), "utf-8");
  assert.match(src, /^const TEST_ORIGIN = "";$/m, "the preview address is switched off in the committed Worker");
  assert.ok(!src.includes(EM_DASH));
});
