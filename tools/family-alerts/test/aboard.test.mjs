// Tests of the splash page's aboard list in tools/family-alerts/worker.js (5.3.0):
// node --test "tools/family-alerts/test/*.test.mjs". No network and no NCL calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import { loadWorker, FakeD1, fakeNet, env as makeEnv, post, readJson, sha256, logs, PAGE, ORIGIN, GITHACK, GITHACK_PAGE } from "./helpers.mjs";

const worker = await loadWorker();
const preview = await loadWorker({ testOrigin: GITHACK });
const net = fakeNet();
const CAST = readJson("splash/cast.json");
const SPLASH = PAGE + "splash/";
const GITHACK_SPLASH = GITHACK_PAGE.replace(/index\.html$/, "splash/index.html");
const EM_DASH = String.fromCharCode(0x2014);
const fresh = () => { const db = new FakeD1(); return { db, env: makeEnv(db) }; };
const linkToken = text => (text.match(/#aboard=([A-Za-z0-9_-]{43})/) || [])[1];
const lastMail = () => net.mails[net.mails.length - 1];

function site({ cast = CAST, preview: pv = null } = {}) {
  net.files = { "prices.json": readJson("data/prices.json") };
  net.site = { [SPLASH + "cast.json"]: cast };
  if (pv) net.site[GITHACK_SPLASH.replace(/index\.html$/, "cast.json")] = pv;
}
async function getAboard(w, e, origin) {
  const r = await w.default.fetch(new Request("https://family.test/aboard", { headers: origin ? { Origin: origin } : {} }), e);
  return { status: r.status, body: await r.json(), headers: r.headers };
}
const guest = (i, first, adult = true) => ({ position: i + 1, adult, age_on_sail_date: adult ? null : 12, first, middle: "", last: "Private", date_of_birth: adult ? "1980-01-01" : "2015-01-01", gender: "Female", citizenship: "USA", latitudes: null });
function bookingBody(firsts, over = {}) {
  return {
    kind: "booking", page: PAGE, page_version: "5.3.0", prices_saved_at: "2026-10-29T10:22:38Z", option: "Option 1: 3 nights",
    party: { adults: firsts.length, kid_ages: [] }, page_switches: { prepay_gratuities: false, florida_resident_rate: true },
    florida: { residents: false, address: null },
    bookings: [{ ship: "Norwegian Getaway", depart: "2027-06-11", return: "2027-06-14", nights: 3, cabin_type: "Balcony", category: "BF",
                 description: "Balcony", guarantee: false, free_at_sea: { bar: true, dining: true, plus: false },
                 lines: [{ item: "Cruise fare", value: "$578" }], total: 1110, onboard: [], deposit_choice: "ncl",
                 ncl_deposit: { amount: 100, rule: "$50 per guest", due_hours: 74, offer: null }, credits: 0, credit_value: 0,
                 due_at_booking: 100, balance: 1010, balance_due: "2027-02-11", pay_david: 0 }],
    guests: firsts.map((f, i) => guest(i, f)), guest1: { email: "g1@example.com", phone: "305 555 0101" },
    sender: { is_guest1: false, name: "Sam Sender", email: "sam@example.com" }, turnstile: "good-token", ...over,
  };
}
async function book(w, e, firsts, over, origin = ORIGIN) {
  const before = net.mails.length;
  const r = await post(w, e, "/booking", bookingBody(firsts, over), origin);
  assert.equal(r.status, 200, JSON.stringify(r.body));
  const [toDavid, copy] = net.mails.slice(before);
  return { toDavid, copy, token: linkToken(toDavid.body) };
}
async function buttonLink(w, e, page = SPLASH, origin = ORIGIN) {
  const before = net.mails.length;
  const r = await post(w, e, "/aboard/link", { turnstile: "good-token", page }, origin);
  return { r, mail: net.mails.length > before ? lastMail() : null };
}

test("GET /aboard: public, read only, cast ids only, any origin, cached for a minute", async () => {
  const { env } = fresh();
  for (const origin of [null, ORIGIN, "https://evil.example"]) {
    const a = await getAboard(worker, env, origin);
    assert.equal(a.status, 200);
    assert.deepEqual(a.body, { ok: true, aboard: [], updated_at: null });
    assert.equal(a.headers.get("Access-Control-Allow-Origin"), "*");
    assert.equal(a.headers.get("Cache-Control"), "public, max-age=60");
  }
  // Writing needs the page's own origin, like every POST route.
  assert.equal((await post(worker, env, "/aboard/save", { token: "x", aboard: [] }, "https://evil.example")).status, 403);
});

test("booking: David's email has a Confirm aboard link pre-ticked by first name; the sender's copy has none; only cast ids stored", async () => {
  const { db, env } = fresh();
  site();
  const { toDavid, copy, token } = await book(worker, env, ["Zin", "tony", "Luis", "Zin"]);
  assert.ok(token, toDavid.body);
  assert.ok(toDavid.body.includes(`Splash page\nConfirm aboard (for you only: it opens the splash page's checklist and works once, within 30 days):\n${SPLASH}#aboard=${token}`));
  assert.ok(toDavid.body.includes("Pre-ticked from this request: Zin, Tony."));
  assert.ok(toDavid.body.includes("Not matched to the cast: Luis. Tick the right person by hand."));
  assert.ok(!copy.body.includes("aboard") && !copy.body.includes(token), "the sender's copy has no link");
  const rows = db.rows("aboard_links");
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].hash, rows[0].preticks, rows[0].source], [sha256(token), "zin,tony", "booking"]);
  assert.ok(!db.dump().includes(token) && !db.dump().includes("Luis") && !db.dump().includes("Private"), "no token, name or anything else from the request");
  assert.deepEqual(db.rows("aboard"), []);
  // Accents and capitals don't matter; "David" is not "David Jr.".
  const m = worker.__t.matchCast([{ id: "zoe", name: "Zoe" }, { id: "david", name: "David" }, { id: "david-jr", name: "David Jr." }], ["ZOË", "David", "David"]);
  assert.deepEqual([m.matched.map(p => p.id), m.unmatched], [["zoe", "david"], []]);
  for (const x of [toDavid, copy]) assert.ok(!(x.body + x.subject).includes(EM_DASH));
});

test("booking: a cast list that can't be read still sends the link, nobody pre-ticked; an email that isn't sent keeps nothing", async () => {
  const { db, env } = fresh();
  site({ cast: null });
  const { toDavid } = await book(worker, env, ["Zin", "Luis"]);
  assert.ok(toDavid.body.includes("The cast list couldn't be read, so nobody is pre-ticked."));
  assert.equal(db.rows("aboard_links")[0].preticks, "");
  site();
  net.mailMode = "quota";
  const r = await post(worker, env, "/booking", bookingBody(["Zin", "Luis"]));
  net.mailMode = "ok";
  assert.equal(r.status, 503);
  assert.equal(db.rows("aboard_links").length, 1, "the failed request's link is gone");
  // Without Turnstile nothing is stored.
  assert.equal((await post(worker, env, "/booking", bookingBody(["Zin", "Luis"], { turnstile: "bad" }))).body.error, "check");
  assert.equal(db.rows("aboard_links").length, 1);
});

test("open and save: the checklist, saved once; moving people back to the dock; the public list follows", async () => {
  const { db, env } = fresh();
  site();
  const { token } = await book(worker, env, ["Zin", "Tony"]);
  const open = await post(worker, env, "/aboard/open", { token, page: SPLASH });
  assert.deepEqual([open.status, open.body], [200, { ok: true, aboard: [], preticks: ["zin", "tony"] }]);
  assert.equal((await post(worker, env, "/aboard/open", { token, page: SPLASH })).status, 200, "opening doesn't use it up");
  const save = await post(worker, env, "/aboard/save", { token, page: SPLASH, aboard: ["tony", "zin", "alex"] });
  assert.deepEqual([save.status, save.body], [200, { ok: true, aboard: ["zin", "tony", "alex"] }], "in cast order");
  assert.deepEqual((await getAboard(worker, env)).body.aboard, ["alex", "tony", "zin"]);
  for (const path of ["/aboard/open", "/aboard/save"]) {
    const again = await post(worker, env, path, { token, page: SPLASH, aboard: [] });
    assert.deepEqual([again.status, again.body.error], [404, "gone"], path);
  }
  // A link from the button: nothing pre-ticked; unticking moves someone back to the dock.
  const { mail } = await buttonLink(worker, env);
  const t2 = linkToken(mail.body);
  assert.deepEqual((await post(worker, env, "/aboard/open", { token: t2, page: SPLASH })).body, { ok: true, aboard: ["alex", "tony", "zin"], preticks: [] });
  assert.equal((await post(worker, env, "/aboard/save", { token: t2, page: SPLASH + "index.html", aboard: ["zin"] })).status, 200);
  assert.deepEqual((await getAboard(worker, env)).body.aboard, ["zin"]);
  assert.ok((await getAboard(worker, env)).body.updated_at);
  assert.deepEqual(db.tables().filter(x => x.startsWith("aboard")), ["aboard", "aboard_links"]);
  assert.deepEqual(Object.keys(db.rows("aboard")[0]).sort(), ["id", "updated_at"]);
});

test("save: refused requests change nothing and keep the link", async () => {
  const { db, env } = fresh();
  site();
  const { token } = await book(worker, env, ["Zin", "Luis"]);
  const bad = [{ aboard: ["nobody-here"] }, { aboard: ["zin", "zin"] }, { aboard: ["Zin"] }, { aboard: "zin" }, { aboard: Array(41).fill("x") },
               { aboard: ["zin"], page: PAGE }, { aboard: ["zin"], page: GITHACK_SPLASH }, { aboard: ["zin"], token: "short" }];
  for (const over of bad) {
    const r = await post(worker, env, "/aboard/save", { token, page: SPLASH, ...over });
    assert.ok(r.status >= 400, JSON.stringify(over));
  }
  site({ cast: null });
  assert.equal((await post(worker, env, "/aboard/save", { token, page: SPLASH, aboard: ["zin"] })).status, 503);
  assert.deepEqual([db.rows("aboard"), db.rows("aboard_links").length], [[], 1]);
  // A link older than 30 days doesn't open, and the daily check deletes it.
  db.db.prepare("UPDATE aboard_links SET created_at = ?").run(new Date(Date.now() - 31 * 86400000).toISOString());
  assert.equal((await post(worker, env, "/aboard/open", { token, page: SPLASH })).status, 404);
  await worker.__t.aboardCleanUp(env, new Date());
  assert.equal(db.rows("aboard_links").length, 0);
});

test("Email me a private aboard link: Turnstile, to David only, 3 in 24 hours, nothing kept when it can't be sent", async () => {
  const { db, env } = fresh();
  site();
  assert.equal((await post(worker, env, "/aboard/link", { turnstile: "bad", page: SPLASH })).body.error, "check");
  assert.equal((await post(worker, env, "/aboard/link", { turnstile: "good-token", page: PAGE })).body.error, "request");
  net.mailMode = "quota";
  assert.equal((await buttonLink(worker, env)).r.status, 503);
  net.mailMode = "ok";
  assert.equal(db.rows("aboard_links").length, 0);
  for (let i = 0; i < 3; i++) {
    const { r, mail } = await buttonLink(worker, env);
    assert.equal(r.status, 200);
    assert.deepEqual([mail.to, mail.kind, mail.subject], ["owner", "aboard", "Your private aboard link"]);
    assert.ok(mail.body.includes(`${SPLASH}#aboard=`));
  }
  const fourth = await buttonLink(worker, env);
  assert.deepEqual([fourth.r.status, fourth.r.body.error, fourth.mail], [400, "daily", null]);
  assert.ok(db.rows("aboard_links").every(r => r.source === "button" && r.preticks === ""));
});

test("preview: links go to the raw.githack.com splash page only while TEST_ORIGIN is set", async () => {
  const { env } = fresh();
  const pv = { schema_version: 1, deck: "deck.svg", cast: [{ id: "tester", name: "Ann" }] };
  site({ preview: pv });
  const a = await book(preview, env, ["Ann", "Bob"], { page: GITHACK_PAGE }, GITHACK);
  assert.ok(a.toDavid.body.includes(`${GITHACK_SPLASH}#aboard=${a.token}`));
  assert.ok(a.toDavid.body.includes("Pre-ticked from this request: Ann."), "the preview's own cast list");
  const r = await post(preview, env, "/aboard/save", { token: a.token, page: GITHACK_SPLASH, aboard: ["tester"] }, GITHACK);
  assert.deepEqual(r.body, { ok: true, aboard: ["tester"] });
  const b = await post(preview, env, "/aboard/link", { turnstile: "good-token", page: GITHACK_SPLASH }, GITHACK);
  assert.equal(b.status, 200);
  assert.ok(lastMail().body.includes(`${GITHACK_SPLASH}#aboard=`));
  // Merged (TEST_ORIGIN ""): the published splash page only.
  assert.equal(worker.__t.splashNextTo(GITHACK_PAGE, GITHACK), SPLASH);
  assert.equal(worker.__t.splashFor(GITHACK_SPLASH, GITHACK), null);
  assert.equal(preview.__t.splashFor("https://raw.githack.com/someone/else/0123456/splash/index.html", GITHACK), null);
});

test("the trip: kept through Jun 19, 2027 (Eastern), deleted from Jun 20; Jun 11 deletes only the price watches", async () => {
  const { db, env } = fresh();
  site();
  const { token } = await book(worker, env, ["Zin", "Luis"]);
  await post(worker, env, "/aboard/save", { token, page: SPLASH, aboard: ["zin"] });
  await book(worker, env, ["Tony", "Luis"]);
  db.db.prepare("UPDATE aboard_links SET created_at = ?").run("2027-06-10T12:00:00.000Z");
  const sailDay = new Date("2027-06-11T12:30:00Z");
  assert.equal((await worker.__t.runChecks(env, sailDay)).ended, true);
  assert.deepEqual([db.rows("aboard").length, db.rows("aboard_links").length], [1, 1], "the aboard list stays during the trip");
  assert.deepEqual((await worker.__t.aboardNow(env, new Date("2027-06-20T03:59:00Z"))).aboard, ["zin"], "Jun 19, 11:59 PM Eastern");
  assert.deepEqual((await worker.__t.aboardNow(env, new Date("2027-06-20T04:00:00Z"))).aboard, [], "Jun 20 Eastern");
  await worker.__t.runChecks(env, new Date("2027-06-20T03:59:00Z"));
  assert.equal(db.rows("aboard").length, 1);
  await worker.__t.runChecks(env, new Date("2027-06-20T12:30:00Z"));
  assert.deepEqual([db.rows("aboard"), db.rows("aboard_links")], [[], []]);
  assert.equal(worker.__t.TRIP_OVER_DAY, "2027-06-20");
});

test("aboard routes: the logs hold nothing personal, and no address but the site, Turnstile and the Apps Script", () => {
  const text = logs.join("\n");
  for (const x of ["@", "Luis", "Private", "Sam Sender", "Zin", "tony"]) assert.ok(!text.includes(x), x);
  assert.ok(!/[A-Za-z0-9_-]{43}/.test(text), "a token in the logs");
  const hosts = new Set(net.calls.map(u => new URL(u).host));
  assert.deepEqual([...hosts].sort(), ["challenges.cloudflare.com", "dasatizabal.github.io", "raw.githack.com", "script.google.test"]);
  assert.ok(net.calls.every(u => !/ncl\.com/i.test(u)));
});
