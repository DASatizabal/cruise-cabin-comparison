// Tests of tools/family-alerts/worker.js: node --test tools/family-alerts/test/
// No network and no NCL calls: the data files, Turnstile and the Apps Script are stand-ins.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadWorker, FakeD1, fakeNet, env as makeEnv, post, readJson, sha256, logs, REPO,
         PAGE, ORIGIN, GITHACK, GITHACK_PAGE } from "./helpers.mjs";

const worker = await loadWorker();
const net = fakeNet();
const NOW = new Date();
const iso = d => d.toISOString().replace(/\.\d{3}Z$/, "Z");
const hoursAgo = h => iso(new Date(NOW.getTime() - h * 3600000));

const PRICES = readJson("data/prices.json");
const getaway = PRICES.sailings.find(s => s.id.startsWith("getaway"));
const aura = PRICES.sailings.find(s => s.id.startsWith("aura"));
const cats = s => s.types.flatMap(t => t.categories.map(c => ({ t, c })));
// A Balcony cabin that isn't a Guarantee and is available for 2 to 4 guests on each ship.
const pick = s => cats(s).find(({ t, c }) => t.code === "BALCONY" && !c.guarantee && ["2", "3", "4"].every(g => c.by_guests[g].available)).c;
const GB = pick(getaway), AB = pick(aura);
// A category that isn't available for some party size, for the refused watch.
const closed = cats(getaway).map(({ c }) => c).map(c => [c, ["2", "3", "4", "5"].find(g => !c.by_guests[g].available)]).find(([, g]) => g);

function files({ prices = PRICES, counts = null, florida = null } = {}) {
  net.files = { "prices.json": prices, "counts.json": counts, "florida.json": florida };
}
function countsFile(left = {}) {
  const sailings = {};
  for (const s of [getaway, aura]) {
    sailings[s.id] = {};
    for (const { c } of cats(s)) {
      if (c.guarantee) continue;
      sailings[s.id][c.code] = { open_decks: [], open_locations: [], by_guests: Object.fromEntries(["2", "3", "4", "5"].map(g =>
        [g, { cabins_left: left[`${s.id}/${c.code}/${g}`] ?? 80, reliable: true, why: null, checked_at: hoursAgo(1) }])) };
    }
  }
  return { schema_version: 1, saved_at: hoursAgo(1), mode: "full", sailings };
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
// A copy of the prices with changes: fn(copy) edits it; saved_at moves on by minutes.
let bump = 0;
function pricesWith(fn) {
  const p = structuredClone(PRICES);
  p.saved_at = iso(new Date(Date.parse(PRICES.saved_at) + ++bump * 60000));
  fn(p, p.sailings.find(s => s.id.startsWith("getaway")), p.sailings.find(s => s.id.startsWith("aura")));
  return p;
}
const catIn = (s, code) => cats(s).find(({ c }) => c.code === code).c;

const fresh = () => { const db = new FakeD1(); return { db, env: makeEnv(db) }; };
const watchBody = (over = {}) => ({ option: "G", guests: 2, cabins: { G: GB.code }, florida: false, email: "Family.One@Example.com", page: PAGE, turnstile: "good-token", ...over });
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
  const none = await post(worker, env, "/nothing", {});
  assert.equal(none.status, 404);
  assert.equal((await post(worker, env, "/watch", "{not json")).status, 400);
  assert.equal((await post(worker, env, "/watch", "x".repeat(40000))).status, 400);
});

test("watch: stored unconfirmed, a confirmation email, tokens kept only as SHA-256", async () => {
  const { db, env } = fresh();
  files();
  const r = await post(worker, env, "/watch", watchBody());
  assert.equal(r.status, 200);
  assert.deepEqual(r.body, { ok: true, price: GB.by_guests["2"].cabin_total, hours: 48 });
  const m = lastMail();
  assert.equal(m.kind, "watch");
  assert.equal(m.to, "family.one@example.com");
  assert.equal(m.subject, "Confirm your cruise price watch");
  const confirm = linkToken(m.body, "confirm"), manage = linkToken(m.body, "manage");
  assert.ok(m.body.includes(`${PAGE}#confirm=${confirm}`));
  assert.ok(m.body.includes(`Option 1: 3 nights\nNorwegian Getaway, Jun 11 to Jun 14, 2027 (3 nights)\nCabin: ${GB.description} (${GB.code})\n2 guests, website price`));
  assert.ok(m.body.includes("Prices are checked twice a day. Watches end on Jun 11, 2027."));
  const [w] = db.rows("watches");
  assert.equal(w.confirmed_at, null);
  assert.equal(w.baseline, GB.by_guests["2"].cabin_total);
  const dump = db.dump();
  assert.ok(!dump.includes(confirm) && !dump.includes(manage), "a token is stored as it is");
  assert.deepEqual(db.rows("tokens").map(t => t.hash).sort(), [sha256(confirm), sha256(manage)].sort());
  assert.deepEqual(db.tables(), ["tokens", "watches"]);
});

test("watch: refused requests store and send nothing", async () => {
  const { db, env } = fresh();
  files();
  const sends = net.mails.length;
  const cases = [
    [{ email: "not-an-email" }, 400, "email"],
    [{ turnstile: "bad-token" }, 400, "check"],
    [{ option: "X" }, 400, "request"],
    [{ guests: 6 }, 400, "request"],
    [{ florida: "yes" }, 400, "request"],
    [{ cabins: { G: "b4; DROP" } }, 400, "request"],
    [{ page: "https://example.com/" }, 400, "request"],
    [{ page: "https://dasatizabal.github.io/other/" }, 400, "request"],
    [{ cabins: { G: "ZZ" } }, 400, "cabin"],
    [{ cabins: { G: closed[0].code }, guests: Number(closed[1]) }, 400, "unavailable"],
    [{ option: "8", cabins: { G: GB.code } }, 400, "request"],
  ];
  for (const [over, status, error] of cases) {
    const r = await post(worker, env, "/watch", watchBody(over));
    assert.equal(r.status, status, JSON.stringify(over));
    assert.equal(r.body.error, error, JSON.stringify(over));
    assert.ok(r.body.message && !/\u2014/.test(r.body.message));
  }
  assert.equal(net.mails.length, sends);
  assert.equal(db.rows("watches").length, 0);
  assert.equal(db.rows("tokens").length, 0);
  // Turnstile from another site.
  net.tsHost = "example.com";
  assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "check");
  net.tsHost = "dasatizabal.github.io";
  // The prices can't be read.
  net.files = {};
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 503);
  // The email can't be sent: nothing kept.
  files();
  net.mailMode = "quota";
  const q = await post(worker, env, "/watch", watchBody());
  net.mailMode = "ok";
  assert.equal(q.status, 503);
  assert.equal(q.body.error, "mail");
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0);
});

test("watch: the githack preview works while TEST_ORIGIN is set, and not once it is empty", async () => {
  const { env } = fresh();
  files();
  net.tsHost = "raw.githack.com";
  const r = await post(worker, env, "/watch", watchBody({ page: GITHACK_PAGE }), GITHACK);
  assert.equal(r.status, 200, JSON.stringify(r.body));
  assert.ok(lastMail().body.includes(GITHACK_PAGE + "#confirm="));
  // The preview page must be on the address the request came from.
  assert.equal((await post(worker, env, "/watch", watchBody({ page: GITHACK_PAGE }))).body.error, "request");
  const merged = await loadWorker({ testOrigin: "" });
  assert.equal(merged.__t.TEST_ORIGIN, "");
  assert.equal((await post(merged, env, "/watch", watchBody({ page: GITHACK_PAGE }), GITHACK)).status, 403);
  // Turnstile solved on raw.githack.com doesn't count once the test address is gone.
  assert.equal((await post(merged, env, "/watch", watchBody())).body.error, "check");
  net.tsHost = "dasatizabal.github.io";
  assert.equal((await post(merged, env, "/watch", watchBody())).status, 200);
});

test("watch: 3 unconfirmed a day and 10 watches per email address", async () => {
  const { db, env } = fresh();
  files();
  for (let i = 0; i < 3; i++) assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);
  const r = await post(worker, env, "/watch", watchBody());
  assert.equal(r.body.error, "daily");
  // Another address isn't affected.
  assert.equal((await post(worker, env, "/watch", watchBody({ email: "other@example.com" }))).status, 200);
  // Started watches count toward 10.
  db.db.exec("UPDATE watches SET confirmed_at = created_at");
  for (let i = 0; i < 6; i++) db.db.prepare("INSERT INTO watches (id, email, option, guests, florida, cabins, label, page, baseline, first_price, created_at, confirmed_at) VALUES (?, 'family.one@example.com', 'G', 2, 0, '{}', 'x', ?, 1, 1, ?, ?)").run(`id${i}`, PAGE, hoursAgo(100), hoursAgo(99));
  assert.equal((await post(worker, env, "/watch", watchBody())).status, 200);   // the 10th
  assert.equal((await post(worker, env, "/watch", watchBody())).body.error, "limit");
});

test("confirm: starts once; the same watch twice keeps one; expired after 48 hours", async () => {
  const { db, env } = fresh();
  files();
  await post(worker, env, "/watch", watchBody());
  const token = linkToken(lastMail().body, "confirm");
  const c = await post(worker, env, "/confirm", { token });
  assert.equal(c.status, 200);
  assert.equal(c.body.already, false);
  assert.equal(c.body.watch.watched, GB.by_guests["2"].cabin_total);
  assert.ok(c.body.watch.label.startsWith("Option 1: 3 nights\nNorwegian Getaway"));
  assert.ok(!JSON.stringify(c.body).includes("@"), "the answer has no email address");
  assert.equal((await post(worker, env, "/confirm", { token })).status, 404);
  await post(worker, env, "/watch", watchBody({ email: "FAMILY.ONE@example.com" }));
  const twin = await post(worker, env, "/confirm", { token: linkToken(lastMail().body, "confirm") });
  assert.equal(twin.body.already, true);
  assert.equal(db.rows("watches").length, 1);
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
  await started(env, { option: "A", cabins: { A: AB.code }, guests: 3 });
  await post(worker, env, "/watch", watchBody({ option: "8", cabins: { G: GB.code, A: AB.code } }));   // waiting for its link
  const token = linkToken(a.mail.body, "manage");
  const list = await post(worker, env, "/manage", { token });
  assert.equal(list.status, 200);
  assert.equal(list.body.watches.length, 2);
  assert.equal(list.body.waiting, 1);
  const stop = await post(worker, env, "/manage", { token, stop: list.body.watches[0].id });
  assert.equal(stop.body.watches.length, 1);
  assert.equal((await post(worker, env, "/manage", { token, stop: "nope" })).status, 404);
  const all = await post(worker, env, "/manage", { token, stop: "all" });
  assert.deepEqual([all.body.watches, all.body.waiting], [[], 0]);
  assert.equal(db.rows("watches").length, 0);
  assert.equal(db.rows("tokens").length, 0, "the address and its links are gone");
  assert.equal((await post(worker, env, "/manage", { token })).status, 404);
});

test("checks: a price drop is sent once and becomes the new price watched", async () => {
  const { db, env } = fresh();
  files();
  await started(env);
  let r = await worker.__t.runChecks(env, NOW);
  assert.deepEqual([r.checked, r.sent], [1, 0]);
  r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.checked, 0, "the same files are not checked twice");
  const was = GB.by_guests["2"].cabin_total;
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["2"].cabin_total = was - 100.5; }) });
  const sends = net.mails.length;
  r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.sent, 1);
  assert.equal(net.mails.length, sends + 1);
  const m = lastMail();
  assert.equal(m.kind, "alert");
  assert.equal(m.subject, "Cruise price watch: the price dropped");
  const money = n => "$" + n.toLocaleString("en-US", { minimumFractionDigits: Number.isInteger(n) ? 0 : 2, maximumFractionDigits: 2 });
  assert.ok(m.body.includes(`- Price drop: ${money(was)} to ${money(was - 100.5)} ($100.50 less).`), m.body);
  assert.equal(db.rows("watches")[0].baseline, was - 100.5);
  // Up again, then back to the new price: nothing.
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["2"].cabin_total = was; }) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["2"].cabin_total = was - 100.5; }) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  // Less than $1 lower: nothing.
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["2"].cabin_total = was - 101; }) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  // The stop link in the alert works.
  const u = await post(worker, env, "/unsubscribe", { token: linkToken(m.body, "unsubscribe") });
  assert.equal(u.status, 200);
  assert.equal(db.rows("watches").length, 0);
  assert.equal((await post(worker, env, "/unsubscribe", { token: linkToken(m.body, "unsubscribe") })).status, 404);
});

test("checks: few left once, sold out once, a party size NCL didn't update is skipped", async () => {
  const { db, env } = fresh();
  files({ counts: countsFile() });
  await started(env, { guests: 3 });
  await worker.__t.runChecks(env, NOW);
  files({ counts: { ...countsFile({ [`${getaway.id}/${GB.code}/3`]: 7 }), saved_at: hoursAgo(0.5) } });
  let r = await worker.__t.runChecks(env, NOW);
  assert.equal(r.sent, 1);
  assert.equal(lastMail().subject, "Cruise price watch: news on your cabin");
  assert.match(lastMail().body, /- Only 7 of these cabins left on the Norwegian Getaway for 3 guests \(cabins left as of [A-Z][a-z]{2} \d+, 20\d\d\)\. You won't get this email again\./);
  files({ counts: { ...countsFile({ [`${getaway.id}/${GB.code}/3`]: 4 }), saved_at: hoursAgo(0.2) } });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  // Counts more than 7 days old are not used.
  const { env: env2 } = fresh();
  files({ counts: { ...countsFile({ [`${getaway.id}/${GB.code}/2`]: 3 }), saved_at: hoursAgo(24 * 8) } });
  await started(env2);
  assert.equal((await worker.__t.runChecks(env2, NOW)).sent, 0);
  // Not updated today at 3 guests: skipped, nothing decided.
  files({ prices: pricesWith((p, g) => { g.party_sizes["3"].updated = false; catIn(g, GB.code).by_guests["3"] = { available: false, sold_out: true, reason: "Sold out" }; }) });
  r = await worker.__t.runChecks(env, NOW);
  assert.deepEqual([r.skipped, r.sent], [1, 0]);
  // Sold out at 3 guests: once.
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["3"] = { available: false, sold_out: true, reason: "Sold out" }; }) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 1);
  assert.ok(lastMail().body.includes("- No longer available for 3 guests on the Norwegian Getaway (NCL: Sold out)."));
  files({ prices: pricesWith((p, g) => { catIn(g, GB.code).by_guests["3"] = { available: false, sold_out: true, reason: "Sold out" }; }) });
  assert.equal((await worker.__t.runChecks(env, NOW)).sent, 0);
  assert.equal(db.rows("watches")[0].sold_out_sent, 1);
});

test("checks: an alert that can't be sent waits for the next run; one email per address", async () => {
  const { db, env } = fresh();
  files();
  await started(env);
  await started(env, { option: "A", cabins: { A: AB.code } });
  await started(env, { email: "other@example.com" });
  await worker.__t.runChecks(env, NOW);
  const cheaper = pricesWith((p, g, a) => { catIn(g, GB.code).by_guests["2"].cabin_total -= 50; catIn(a, AB.code).by_guests["2"].cabin_total -= 50; });
  files({ prices: cheaper });
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
  const total = (s, c, n) => c.by_guests[String(n)].cabin_total;
  for (const n of [2, 3, 4]) {
    assert.equal(t.priceNow(data(), { option: "G", guests: n, florida: false, cabins: { G: GB.code } }, NOW).price, total(getaway, GB, n));
    assert.equal(t.priceNow(data(), { option: "8", guests: n, florida: true, cabins: { G: GB.code, A: AB.code } }, NOW).price,
                 Math.round((total(getaway, GB, n) + total(aura, AB, n)) * 100) / 100);
  }
  const fl = floridaFile({ [GB.code]: 60, [AB.code]: 0.5 });
  const w = (florida, n = 3) => ({ option: "8", guests: n, florida, cabins: { G: GB.code, A: AB.code } });
  assert.equal(t.priceNow(data(fl), w(true), NOW).price, total(getaway, GB, 3) - 120 + total(aura, AB, 3), "guests 1 and 2, under $1 is no discount");
  assert.equal(t.priceNow(data(fl), w(false), NOW).price, total(getaway, GB, 3) + total(aura, AB, 3));
  // Never more than the fare.
  const huge = floridaFile({ [GB.code]: 100000 });
  assert.equal(t.priceNow(data(huge), { option: "G", guests: 2, florida: true, cabins: { G: GB.code } }, NOW).price, 2 * getaway.taxes_per_guest);
  // A check more than 15 days old is not used (the Worker also drops the whole file then).
  const old = floridaFile({ [GB.code]: 60 }, 16);
  assert.equal(t.priceNow(data(old), { option: "G", guests: 2, florida: true, cabins: { G: GB.code } }, NOW).price, total(getaway, GB, 2));
  // Through a watch: the Florida file from the site.
  const { db, env } = fresh();
  files({ florida: fl });
  await started(env, { florida: true, option: "8", cabins: { G: GB.code, A: AB.code } });
  assert.equal(db.rows("watches")[0].baseline, total(getaway, GB, 2) - 120 + total(aura, AB, 2));
  assert.ok(lastMail().body.includes("2 guests, Florida resident price (when NCL offers one on this cabin)"));
  files({ florida: floridaFile({ [GB.code]: 60 }, 16) });
  assert.equal((await post(worker, env, "/watch", watchBody({ florida: true, email: "x@example.com" }))).body.price, total(getaway, GB, 2));
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
  const r = await worker.__t.runChecks(env, new Date("2027-06-11T04:00:00Z"));
  assert.equal(r.ended, true);
  assert.equal(db.rows("watches").length + db.rows("tokens").length, 0);
});

// ---------- /booking ----------
function bookingBody(over = {}) {
  const b = {
    kind: "booking", page_version: "5.2.0", prices_saved_at: "2026-10-28T10:21:44Z", note: "Prices can change until NCL confirms the booking.",
    option: "Option 1: 3 nights", party: { adults: 2, kid_ages: [15] }, page_switches: { prepay_gratuities: false, florida_resident_rate: true },
    florida: { residents: true, address: { street: "1 Test Street", city: "Miami", state: "FL", zip: "33101" } },
    bookings: [{ ship: "Norwegian Getaway", depart: "2027-06-11", return: "2027-06-14", nights: 3, cabin_type: "Balcony", category: "B4",
                 description: "Balcony, Decks 9 to 12", guarantee: false, free_at_sea: { bar: true, dining: true, plus: false },
                 fare: 1500, taxes: 450, florida_discount: 120, price_without_gratuities: 1830,
                 not_in_price: [{ item: "Open Bar gratuity: 2 x $81", amount: 162, paid: "with the balance" }, { item: "Service charges", amount: 180, paid: "onboard" }],
                 deposit_choice: "credit1", ncl_deposit: { amount: 150, rule: "$50 per guest", due_hours: 74, offer: "2-For-1 Deposits" },
                 credits: 1, credit_value: 250, due_at_booking: 0, balance: 1580, balance_due: "2027-02-11", pay_david: 125 }],
    guests: [{ position: 1, adult: true, age_on_sail_date: null, first: "Ann", middle: "", last: "Tester", date_of_birth: "1980-02-03", gender: "Female", citizenship: "USA", latitudes: "123456789" },
             { position: 2, adult: true, age_on_sail_date: null, first: "Bob", middle: "Q", last: "Tester", date_of_birth: "1979-04-05", gender: "Male", citizenship: "USA", latitudes: "987654321" },
             { position: 3, adult: false, age_on_sail_date: 15, first: "Cy", middle: "", last: "Tester", date_of_birth: "2011-08-09", gender: "Male", citizenship: "USA", latitudes: null }],
    guest1: { email: "ann@example.com", phone: "305 555 0100" },
    sender: { is_guest1: false, name: "Sam Sender", email: "sam@example.com" },
    turnstile: "good-token",
  };
  return { ...b, ...over };
}

test("booking: David gets everything, the sender a copy without dates of birth or Latitudes numbers; nothing stored", async () => {
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
  for (const x of ["born Feb 3, 1980", "born Apr 5, 1979", "born Aug 9, 2011", "Latitudes number 123456789", "Latitudes number 987654321",
                   "1 Test Street, Miami, FL 33101", "Guest 1's email: ann@example.com", "Guest 1's mobile phone: 305 555 0100",
                   "Sent by: Sam Sender <sam@example.com>", "Prices can change until NCL confirms the booking.",
                   "Party: 2 adults and 1 kid (age 15 on Jun 11, 2027)", "Deposit: One of David's CruiseNext credits ($250 toward the cruise, pay David $125)",
                   "Balance, due by Feb 11, 2027: $1,580", "Florida resident rate: $120 off the fare", "Guest 3: Cy Tester, age 15 on Jun 11, 2027"]) {
    assert.ok(toDavid.body.includes(x), x);
  }
  for (const x of ["1980", "1979", "2011-08-09", "Aug 9, 2011", "123456789", "987654321", "Test Street", "ann@example.com", "555 0100"]) {
    assert.ok(!copy.body.includes(x), "the copy has " + x);
  }
  for (const x of ["Hi Sam Sender,", "Guest 1: Ann Tester, adult, Female, citizenship USA", "Prices can change until NCL confirms the booking.", "Price without gratuities: $1,830"]) {
    assert.ok(copy.body.includes(x), x);
  }
  // The sender is guest 1: their own address, email and phone, still no dates of birth or Latitudes numbers.
  const me = await post(worker, env, "/booking", bookingBody({ sender: { is_guest1: true, name: "Ann Tester", email: "ann@example.com" } }));
  assert.equal(me.status, 200);
  const mine = lastMail();
  assert.ok(mine.body.includes("1 Test Street") && mine.body.includes("ann@example.com") && !mine.body.includes("1980") && !mine.body.includes("123456789"));
  assert.deepEqual([before, db.tables(), db.rows("watches"), db.rows("tokens")], ["[]", ["tokens", "watches"], [], []], "nothing stored");
  for (const m of net.mails.slice(sends)) assert.ok(!/\u2014/.test(m.body + m.subject));
});

test("booking: 8 nights, two bookings and the totals; NCL's deposit wording", async () => {
  const { env } = fresh();
  files();
  const two = bookingBody();
  const g = two.bookings[0];
  two.option = "Option 3: 8 nights";
  two.bookings = [{ ...g, deposit_choice: "ncl", credits: 0, credit_value: 0, due_at_booking: 150, balance: 1680, pay_david: 0 },
                  { ...g, ship: "Norwegian Aura", depart: "2027-06-14", return: "2027-06-19", nights: 5, deposit_choice: "credit2", credits: 2, credit_value: 500, due_at_booking: 0, balance: 1330, pay_david: 250, balance_due: "2027-02-14" }];
  const r = await post(worker, env, "/booking", two);
  assert.equal(r.status, 200, JSON.stringify(r.body));
  const body = net.mails[net.mails.length - 2].body;
  for (const x of ["Booking 1: Norwegian Getaway, Jun 11 to Jun 14, 2027 (3 nights)", "Booking 2: Norwegian Aura, Jun 14 to Jun 19, 2027 (5 nights)",
                   "Deposit: NCL's deposit: $150 ($50 per guest), due within 74 hours of booking, with NCL's 2-For-1 Deposits offer",
                   "Deposit: Two of David's CruiseNext credits, NCL's DoubleUp offer ($500 toward the cruise, pay David $250)",
                   "Both bookings together", "Price without gratuities: $3,660", "Paid to NCL at booking: $150", "Balances: $3,010", "Pay David for the credits: $250"]) {
    assert.ok(body.includes(x), x);
  }
  // 8 nights with one booking, or one ship with two: refused.
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
  const g = bookingBody();
  g.guests[0].latitudes = "12ab";
  assert.equal((await post(worker, env, "/booking", g)).status, 400);
  const long = bookingBody();
  long.guests[0].first = "x".repeat(61);
  assert.equal((await post(worker, env, "/booking", long)).status, 400);
  assert.equal((await post(worker, env, "/booking", bookingBody({ turnstile: "bad-token" }))).body.error, "check");
  assert.equal(net.mails.length, sends);
  net.mailMode = "quota";
  const busy = await post(worker, env, "/booking", bookingBody());
  net.mailMode = "ok";
  assert.equal(busy.status, 503);
  assert.equal(busy.body.error, "mail");
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

test("the Worker file: TEST_ORIGIN line and no em dash", () => {
  const src = readFileSync(new URL("tools/family-alerts/worker.js", REPO), "utf-8");
  assert.match(src, /^const TEST_ORIGIN = "(https:\/\/raw\.githack\.com)?";$/m);
  assert.ok(!src.includes("\u2014"));
});
