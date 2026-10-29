// Cloudflare Worker "cruise-family-alerts" (5.2.0): the family price watch and the Make
// Selection emails for the June 2027 cruise page. Separate from the Deck Finder Worker and from
// cruise-refresh-trigger. Setup: tools/family-alerts/README.md. NOTES.md, "Family price watch
// and booking emails".
//
// Routes (POST with JSON, only from the page's own address; anything else is refused):
//   /watch        start a price watch: checks Turnstile, stores the watch unconfirmed and emails
//                 a confirmation link (the page with #confirm=TOKEN)
//   /confirm      starts a watch from that link
//   /unsubscribe  stops one watch (the link in every alert email)
//   /manage       lists the watches of one email address, or stops some of them
//   /booking      Make Selection: checks Turnstile, emails David the request and the sender a
//                 copy. Nothing from a booking request is stored or logged.
// Cron triggers (UTC): "30 12 * * *" and "30 17 * * *", after the price and count refreshes.
// A watch is one cabin on one ship at one party size (the 8 night card has one per ship), with
// the person's choices: the drop per guest that counts, whether to email when only a few cabins
// are left and when it sells out, and as soon as it happens or at most once a day (mornings).
//
// Binding: DB (the D1 database cruise-family-alerts; the tables are created here on first use).
// Secrets: TURNSTILE_SECRET, APPS_SCRIPT_URL, APPS_SCRIPT_SECRET. Never put them in this repo.
// The Worker reads only the published data files (no NCL calls). Email goes through the owner's
// Apps Script (apps-script/Code.gs), which sends from the owner's Gmail.
// Logs hold counts and fixed words only: never an email address, a name or a token.

const PAGE = "https://dasatizabal.github.io/cruise-cabin-comparison/";
const ORIGIN = "https://dasatizabal.github.io";
// Temporary, for testing from a raw.githack.com preview pinned to a commit. While it is set,
// tools/check_release.py fails, so it can't be merged: set it to "" and paste this file into the
// Worker again before merging.
const TEST_ORIGIN = "";
const TEST_PAGE = /^https:\/\/raw\.githack\.com\/DASatizabal\/cruise-cabin-comparison\/[0-9a-f]{7,40}\/index\.html$/;
const DATA_URL = PAGE + "data/";
const SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
// From the first sail date (Eastern) nothing is watched and everything stored is deleted.
const END_DAY = "2027-06-11";
const AGE_DAY = "2027-06-11";   // kids' ages on the page are on the first sail date
const OPTIONS = {
  G: { label: "Option 1: 3 nights", ships: ["G"] },
  A: { label: "Option 2: 5 nights", ships: ["A"] },
  8: { label: "Option 3: 8 nights", ships: ["G", "A"] },
};
const SHIP_NAMES = { G: "Norwegian Getaway", A: "Norwegian Aura" };
const MAX_WATCHES = 10;        // watches per email address (started or waiting for the link)
const MAX_NEW_PER_DAY = 3;     // unconfirmed watches per email address in 24 hours
const CONFIRM_HOURS = 48;      // an unconfirmed watch is deleted after this
const FEW_LEFT = 10;           // "only X left" below this (the page's rule)
const COUNTS_MAX_DAYS = 7, FL_MAX_DAYS = 15, FL_MIN_OFF = 1;   // the page's rules
const DROP_MIN = 1, DROP_MAX = 1000;   // dollars per guest the person may choose (the page offers $20)
const MAX_BODY = 32768;
const CHANGE_TEXT = "Prices can change until NCL confirms the booking.";
const PRICE_TEXT = "The price watched is the cruise fare with taxes, fees and port expenses for the guests in the cabin, before gratuities and Free at Sea extras.";
const GUARANTEE_TEXT = "Guarantee: NCL picks your cabin location";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS watches (
     id TEXT PRIMARY KEY, email TEXT NOT NULL, option TEXT NOT NULL, ship TEXT NOT NULL,
     code TEXT NOT NULL, guests INTEGER NOT NULL, florida INTEGER NOT NULL, drop_pp REAL NOT NULL,
     few INTEGER NOT NULL, sold_out INTEGER NOT NULL, frequency TEXT NOT NULL, label TEXT NOT NULL,
     page TEXT NOT NULL, baseline REAL NOT NULL, first_price REAL NOT NULL, last_price REAL,
     created_at TEXT NOT NULL, confirmed_at TEXT, checked_key TEXT, checked_day TEXT,
     few_sent INTEGER NOT NULL DEFAULT 0, sold_out_sent INTEGER NOT NULL DEFAULT 0)`,
  "CREATE INDEX IF NOT EXISTS watches_email ON watches (email)",
  // Only the SHA-256 of each token is kept; the token itself is only in the email.
  "CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, watch_id TEXT, email TEXT, created_at TEXT NOT NULL)",
  "CREATE INDEX IF NOT EXISTS tokens_watch ON tokens (watch_id)",
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return new Response("Cruise family alerts. Nothing to see here.\n", { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    const origin = request.headers.get("Origin") || "";
    if (!origins().includes(origin)) return new Response("Not allowed.\n", { status: 403, headers: { "content-type": "text/plain; charset=utf-8" } });
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: { ...cors(origin), "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400" } });
    }
    const route = ROUTES[url.pathname];
    if (request.method !== "POST" || !route) return reply(origin, { ok: false, error: "route", message: "Not found." }, 404);
    const raw = await request.text();
    let body;
    try {
      if (raw.length > MAX_BODY) throw new Error();
      body = JSON.parse(raw);
      if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error();
    } catch (e) {
      return reply(origin, { ok: false, error: "request", message: "The request didn't look right, so nothing was done. Please reload the page and try again." }, 400);
    }
    try {
      await ensureSchema(env);
      const [answer, status] = await route(env, body, { origin, ip: request.headers.get("CF-Connecting-IP") || "" });
      return reply(origin, answer, status || 200);
    } catch (e) {
      // Never log the error text: it could quote what was sent.
      console.log(`${url.pathname}: failed`);
      return reply(origin, { ok: false, error: "server", message: "Something went wrong on David's side. Please try again in a few minutes." }, 500);
    }
  },

  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runChecks(env, new Date()).catch(() => console.log("checks: failed")));
  },
};

const ROUTES = { "/watch": startWatch, "/confirm": confirmWatch, "/unsubscribe": unsubscribe, "/manage": manage, "/booking": booking };

const origins = () => [ORIGIN, TEST_ORIGIN].filter(Boolean);
const cors = origin => ({ "Access-Control-Allow-Origin": origin, Vary: "Origin" });
const reply = (origin, obj, status) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...cors(origin) } });
const refuse = (error, message, status = 400) => [{ ok: false, error, message }, status];

const schemaReady = new WeakSet();
async function ensureSchema(env) {
  if (schemaReady.has(env.DB)) return;
  // The first test version (2026-10-29) kept both 8 night cabins in one watch and had no choices.
  // Its watches (test watches only) can't be carried over, so its tables are replaced.
  const old = await env.DB.prepare("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'watches'").first("sql");
  if (old && old.includes("cabins TEXT")) await env.DB.batch([env.DB.prepare("DROP TABLE watches"), env.DB.prepare("DROP TABLE IF EXISTS tokens")]);
  await env.DB.batch(SCHEMA.map(s => env.DB.prepare(s)));
  schemaReady.add(env.DB);
}

// ---------- dates and money ----------
const easternDay = d => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
function fmtEastern(iso) {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "unknown";
  return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    .format(d).replace(/\s/g, " ") + " ET";
}
const ymd = iso => iso.split("-").map(Number);
const fmtIso = iso => { const [y, m, d] = ymd(iso); return `${MONTHS[m - 1]} ${d}, ${y}`; };
const fmtDay = iso => { const [, m, d] = ymd(iso); return `${MONTHS[m - 1]} ${d}`; };
const cents = n => Math.round(n * 100) / 100;
function money(n) {
  const r = cents(n);
  return "$" + r.toLocaleString("en-US", { minimumFractionDigits: Number.isInteger(r) ? 0 : 2, maximumFractionDigits: 2 });
}
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const daysSince = (t, now) => (now.getTime() - Date.parse(t)) / 86400000;

// ---------- tokens ----------
function newToken() {
  const b = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...b)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function sha256(text) {
  const h = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(h)].map(x => x.toString(16).padStart(2, "0")).join("");
}
const TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;
async function tokenRow(env, kind, token) {
  const t = newToken();
  return { token: t, stmt: env.DB.prepare("INSERT INTO tokens (hash, kind, watch_id, email, created_at) VALUES (?, ?, ?, ?, ?)")
    .bind(await sha256(t), kind, token.watchId || null, token.email || null, new Date().toISOString()) };
}
async function findToken(env, kind, token) {
  if (typeof token !== "string" || !TOKEN_RE.test(token)) return null;
  return env.DB.prepare("SELECT * FROM tokens WHERE hash = ? AND kind = ?").bind(await sha256(token), kind).first();
}

// ---------- the published data (no NCL calls) ----------
async function getJson(name) {
  try {
    const r = await fetch(`${DATA_URL}${name}?t=${Date.now()}`, { headers: { "Cache-Control": "no-cache" } });
    return r.ok ? await r.json() : null;
  } catch (e) {
    return null;
  }
}
async function loadData(now) {
  const [prices, counts, florida] = await Promise.all(["prices.json", "counts.json", "florida.json"].map(getJson));
  const ok = x => x && typeof x === "object" && x.sailings && Number.isFinite(Date.parse(x.saved_at));
  return {
    prices: ok(prices) && Array.isArray(prices.sailings) ? prices : null,
    counts: ok(counts) && counts.schema_version === 1 && daysSince(counts.saved_at, now) <= COUNTS_MAX_DAYS ? counts : null,
    florida: ok(florida) && florida.schema_version === 1 && daysSince(florida.saved_at, now) <= FL_MAX_DAYS ? florida : null,
  };
}
const shipOf = (prices, key) => prices.sailings.find(s => typeof s.id === "string" && s.id.startsWith(key === "G" ? "getaway" : "aura")) || null;
function findCategory(ship, code) {
  for (const t of ship.types || []) for (const c of t.categories || []) if (c.code === code) return { type: t, cat: c };
  return null;
}
// The Florida discount per guest for this cabin, by the page's rules: the latest check at most
// 15 days old, the cabin's own amount, $1 or more. Nothing else counts.
function flOff(florida, ship, code, now) {
  const sl = florida && florida.sailings[ship.id];
  const e = sl && sl.categories && sl.categories[code];
  if (!e || !Number.isFinite(e.off_pp) || !(daysSince(e.checked_at, now) <= FL_MAX_DAYS)) return 0;
  return e.off_pp >= FL_MIN_OFF ? e.off_pp : 0;
}

// The watched price: NCL's cabin price for the party (fare with taxes, fees and port expenses),
// minus the cabin's own Florida discount on guests 1 and 2 (never more than the fare) when the
// watch is for the Florida resident price. One cabin on one ship.
function priceNow(data, w, now) {
  const n = w.guests;
  const ship = shipOf(data.prices, w.ship);
  const found = ship && findCategory(ship, w.code);
  const e = found && found.cat.by_guests && found.cat.by_guests[String(n)];
  const ps = ship && ship.party_sizes && ship.party_sizes[String(n)];
  const p = { ship, cat: found ? found.cat : null, type: found ? found.type : null,
              updated: !!ship && !(ps && ps.updated === false),
              available: !!(e && e.available && Number.isFinite(e.cabin_total)),
              reason: !found ? "no longer on NCL's list" : e && e.reason ? e.reason : "not available", price: null };
  if (p.available) {
    const taxes = Number.isFinite(ship.taxes_per_guest) ? ship.taxes_per_guest * n : null;
    const fare = taxes === null ? e.cabin_total : e.cabin_total - taxes;
    p.price = cents(e.cabin_total - (w.florida ? Math.min(flOff(data.florida, ship, found.cat.code, now) * Math.min(n, 2), fare) : 0));
  }
  return p;
}

// What the watch is, for the emails and the page (no personal data).
function watchLabel(p, w) {
  return [`${OPTIONS[w.option].label}${w.option === "8" ? `, the ${p.ship.ship_short} cabin` : ""}`,
          `${p.ship.ship}, ${fmtDay(p.ship.depart)} to ${fmtIso(p.ship.return)} (${plural(p.ship.nights, "night", "nights")})`,
          `Cabin: ${p.cat.description || p.cat.title} (${p.cat.code})${p.cat.guarantee ? `. ${GUARANTEE_TEXT}` : ""}`,
          `${w.guests} guests, ${w.florida ? "Florida resident price (when NCL offers one on this cabin)" : "website price"}`].join("\n");
}
// The person's choices, in words (emails and the page's manage list say the same).
function choicesText(w) {
  return [`an email when the price drops by at least ${money(w.drop_pp)} per guest (${money(w.drop_pp * w.guests)} for the cabin)`,
          w.few ? `an email when fewer than ${FEW_LEFT} of these cabins are left` : null,
          w.sold_out ? `an email if it is no longer available for ${w.guests} guests` : null,
          w.frequency === "daily" ? "at most one email a day, in the morning" : "emails as soon as a check finds something (prices are checked twice a day)"].filter(Boolean);
}
const rowWatch = row => ({ option: row.option, ship: row.ship, code: row.code, guests: row.guests, florida: !!row.florida,
                           drop_pp: row.drop_pp, few: !!row.few, sold_out: !!row.sold_out, frequency: row.frequency });
const linkTo = (page, kind, token) => `${page}#${kind}=${token}`;

// ---------- email (the owner's Apps Script) ----------
// kind: "booking" may use the sends kept for booking requests; "watch" and "alert" may not.
// Returns one true or false per message.
async function mail(env, kind, messages) {
  if (!env.APPS_SCRIPT_URL || !env.APPS_SCRIPT_SECRET || !messages.length) return messages.map(() => false);
  try {
    const r = await fetch(env.APPS_SCRIPT_URL, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret: env.APPS_SCRIPT_SECRET, kind, messages }) });
    const a = await r.json();
    if (!a || a.ok !== true || !Array.isArray(a.sent)) return messages.map(() => false);
    return messages.map((_, i) => a.sent[i] === true);
  } catch (e) {
    return messages.map(() => false);
  }
}

async function turnstileOk(env, token, ip) {
  if (!env.TURNSTILE_SECRET || typeof token !== "string" || !token || token.length > 2048) return false;
  try {
    const form = new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token });
    if (ip) form.set("remoteip", ip);
    const r = await fetch(SITEVERIFY, { method: "POST", body: form });
    const a = await r.json();
    return a.success === true && origins().map(o => new URL(o).hostname).includes(a.hostname);
  } catch (e) {
    return false;
  }
}

// The page the links in the emails go back to: the published page, or while TEST_ORIGIN is set
// a raw.githack.com preview. It must be on the address the request came from.
function pageFor(page, origin) {
  if (typeof page !== "string" || !page.startsWith(origin + "/")) return null;
  if (page === PAGE || page === PAGE + "index.html") return page;
  if (TEST_ORIGIN && TEST_PAGE.test(page)) return page;
  return null;
}

const EMAIL_RE = /^[^\s@<>()",;:]+@[^\s@<>()",;:]+\.[^\s@<>()",;:]+$/;
const cleanEmail = v => typeof v === "string" && v.trim().length <= 254 && EMAIL_RE.test(v.trim()) ? v.trim().toLowerCase() : null;

// ---------- /watch ----------
async function startWatch(env, body, req) {
  const now = new Date();
  const email = cleanEmail(body.email);
  if (!email) return refuse("email", "Enter a valid email address.");
  const BAD = ["request", "The request didn't look right, so nothing was done. Please reload the page and try again."];
  const opt = OPTIONS[body.option];
  const n = body.guests;
  if (!opt || !opt.ships.includes(body.ship) || typeof body.cabin !== "string" || !/^[A-Z0-9]{1,4}$/.test(body.cabin) ||
      !Number.isInteger(n) || n < 2 || n > 5 || typeof body.florida !== "boolean" || typeof body.few !== "boolean" ||
      typeof body.sold_out !== "boolean" || !["now", "daily"].includes(body.frequency)) return refuse(...BAD);
  if (typeof body.drop_pp !== "number" || !Number.isFinite(body.drop_pp) || body.drop_pp < DROP_MIN || body.drop_pp > DROP_MAX) {
    return refuse("drop", `Choose a drop from ${money(DROP_MIN)} to ${money(DROP_MAX)} per guest.`);
  }
  const page = pageFor(body.page, req.origin);
  if (!page) return refuse(...BAD);
  if (!(await turnstileOk(env, body.turnstile, req.ip))) return refuse("check", "The check above the button didn't pass. Please try it again.");
  if (easternDay(now) >= END_DAY) return refuse("ended", "The cruise has started, so prices are no longer watched.");

  const data = await loadData(now);
  if (!data.prices) return refuse("data", "The prices couldn't be read right now. Please try again in a few minutes.", 503);
  const w = { option: body.option, ship: body.ship, code: body.cabin, guests: n, florida: body.florida, drop_pp: cents(body.drop_pp),
              few: body.few, sold_out: body.sold_out, frequency: body.frequency };
  const p = priceNow(data, w, now);
  if (!p.cat) return refuse("cabin", "That cabin isn't on NCL's list today, so there is no price to watch. Please reload the page.");
  if (p.price === null) return refuse("unavailable", `That cabin isn't available for ${n} guests today, so there is no price to watch.`);
  if (p.cat.guarantee) w.few = false;   // NCL doesn't show how many Guarantee cabins are left

  const day = new Date(now.getTime() - 86400000).toISOString(), live = new Date(now.getTime() - CONFIRM_HOURS * 3600000).toISOString();
  const active = await env.DB.prepare("SELECT COUNT(*) AS n FROM watches WHERE email = ? AND (confirmed_at IS NOT NULL OR created_at > ?)").bind(email, live).first("n");
  if (active >= MAX_WATCHES) return refuse("limit", `This email address already has ${MAX_WATCHES} price watches. Stop one first (the link is in every price watch email).`);
  const fresh = await env.DB.prepare("SELECT COUNT(*) AS n FROM watches WHERE email = ? AND confirmed_at IS NULL AND created_at > ?").bind(email, day).first("n");
  if (fresh >= MAX_NEW_PER_DAY) return refuse("daily", `This email address has ${MAX_NEW_PER_DAY} watches waiting for their confirmation link today. Open those emails first, or try again tomorrow.`);

  const id = newToken();
  const label = watchLabel(p, w);
  const confirm = await tokenRow(env, "confirm", { watchId: id });
  const mng = await tokenRow(env, "manage", { email });
  await env.DB.batch([
    env.DB.prepare("INSERT INTO watches (id, email, option, ship, code, guests, florida, drop_pp, few, sold_out, frequency, label, page, baseline, first_price, last_price, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
      .bind(id, email, w.option, w.ship, w.code, n, w.florida ? 1 : 0, w.drop_pp, w.few ? 1 : 0, w.sold_out ? 1 : 0, w.frequency, label, page, p.price, p.price, p.price, now.toISOString()),
    confirm.stmt, mng.stmt,
  ]);
  const text = [
    "Hi,", "",
    "Someone (hopefully you) asked to watch this price on David's cruise page:", "",
    label, `Price today: ${money(p.price)} for the cabin (${money(p.price / n)} per guest), prices as of ${fmtEastern(data.prices.saved_at)}`, "",
    `To start the watch, open this link within ${CONFIRM_HOURS} hours:`, linkTo(page, "confirm", confirm.token), "",
    "You asked for:", ...choicesText(w).map(x => `- ${x}`),
    `After a price drop email, the new price is the one watched. The few left and no longer available emails are sent once. Watches end on ${fmtIso(END_DAY)}.`,
    PRICE_TEXT, "",
    "If you didn't ask for this, ignore this email: nothing is watched unless the link is opened, and your address is deleted after 48 hours.", "",
    `See or stop your price watches: ${linkTo(page, "manage", mng.token)}`,
  ].join("\n");
  const [sent] = await mail(env, "watch", [{ to: email, subject: "Confirm your cruise price watch", body: text }]);
  if (!sent) {
    await env.DB.batch([env.DB.prepare("DELETE FROM tokens WHERE watch_id = ?").bind(id), env.DB.prepare("DELETE FROM watches WHERE id = ?").bind(id),
                        env.DB.prepare("DELETE FROM tokens WHERE kind = 'manage' AND email NOT IN (SELECT email FROM watches)")]);
    console.log("/watch: the confirmation email could not be sent, nothing kept");
    return refuse("mail", "The email couldn't be sent right now, so nothing was saved. Please try again later.", 503);
  }
  console.log("/watch: a watch is waiting for its confirmation link");
  return [{ ok: true, price: p.price, hours: CONFIRM_HOURS }];
}

const publicWatch = row => ({ id: row.id, label: row.label, price: row.last_price, watched: row.baseline, first_price: row.first_price,
                              guests: row.guests, choices: choicesText(rowWatch(row)), confirmed: !!row.confirmed_at, started: row.confirmed_at });

// ---------- /confirm ----------
async function confirmWatch(env, body) {
  const t = await findToken(env, "confirm", body.token);
  const row = t && await env.DB.prepare("SELECT * FROM watches WHERE id = ?").bind(t.watch_id).first();
  if (!row) return refuse("gone", "This link has expired or was already used. Start the watch again from the page if you still want it.", 404);
  const now = new Date();
  if (now.getTime() - Date.parse(row.created_at) > CONFIRM_HOURS * 3600000) {
    await env.DB.batch([env.DB.prepare("DELETE FROM tokens WHERE watch_id = ?").bind(row.id), env.DB.prepare("DELETE FROM watches WHERE id = ?").bind(row.id)]);
    return refuse("gone", "This link has expired or was already used. Start the watch again from the page if you still want it.", 404);
  }
  // The same cabin already watched for this address: keep that watch and its price, with the
  // new choices.
  const twin = await env.DB.prepare("SELECT * FROM watches WHERE email = ? AND ship = ? AND code = ? AND guests = ? AND florida = ? AND confirmed_at IS NOT NULL AND id <> ?")
    .bind(row.email, row.ship, row.code, row.guests, row.florida, row.id).first();
  if (twin) {
    await env.DB.batch([
      env.DB.prepare("UPDATE watches SET drop_pp = ?, few = ?, sold_out = ?, frequency = ?, option = ?, label = ?, page = ? WHERE id = ?")
        .bind(row.drop_pp, row.few, row.sold_out, row.frequency, row.option, row.label, row.page, twin.id),
      env.DB.prepare("DELETE FROM tokens WHERE watch_id = ?").bind(row.id), env.DB.prepare("DELETE FROM watches WHERE id = ?").bind(row.id)]);
    console.log("/confirm: already watched, choices updated");
    const { drop_pp, few, sold_out, frequency, option, label, page } = row;
    return [{ ok: true, already: true, watch: publicWatch({ ...twin, drop_pp, few, sold_out, frequency, option, label, page }) }];
  }
  await env.DB.batch([env.DB.prepare("UPDATE watches SET confirmed_at = ? WHERE id = ?").bind(now.toISOString(), row.id),
                      env.DB.prepare("DELETE FROM tokens WHERE watch_id = ? AND kind = 'confirm'").bind(row.id)]);
  console.log("/confirm: a watch started");
  return [{ ok: true, already: false, watch: publicWatch({ ...row, confirmed_at: now.toISOString() }) }];
}

// ---------- /unsubscribe ----------
async function unsubscribe(env, body) {
  const t = await findToken(env, "unsubscribe", body.token);
  const row = t && await env.DB.prepare("SELECT * FROM watches WHERE id = ?").bind(t.watch_id).first();
  if (!row) return refuse("gone", "This watch was already stopped.", 404);
  await stopWatches(env, [row.id]);
  console.log("/unsubscribe: a watch stopped");
  return [{ ok: true, watch: publicWatch(row) }];
}

async function stopWatches(env, ids) {
  await env.DB.batch(ids.flatMap(id => [env.DB.prepare("DELETE FROM tokens WHERE watch_id = ?").bind(id), env.DB.prepare("DELETE FROM watches WHERE id = ?").bind(id)]));
  // An address with no watches left: its "manage" links stop working, and the address is gone.
  await env.DB.prepare("DELETE FROM tokens WHERE kind = 'manage' AND email NOT IN (SELECT email FROM watches)").run();
}

// ---------- /manage ----------
async function manage(env, body) {
  const t = await findToken(env, "manage", body.token);
  if (!t) return refuse("gone", "There are no price watches for this link any more.", 404);
  const all = (await env.DB.prepare("SELECT * FROM watches WHERE email = ? ORDER BY created_at").bind(t.email).all()).results;
  if (body.stop !== undefined) {
    const ids = body.stop === "all" ? all.map(r => r.id) : all.filter(r => r.id === body.stop).map(r => r.id);
    if (!ids.length) return refuse("gone", "That watch was already stopped.", 404);
    await stopWatches(env, ids);
    console.log(`/manage: ${ids.length} stopped`);
  }
  const rows = (await env.DB.prepare("SELECT * FROM watches WHERE email = ? ORDER BY created_at").bind(t.email).all()).results;
  return [{ ok: true, watches: rows.filter(r => r.confirmed_at).map(publicWatch), waiting: rows.filter(r => !r.confirmed_at).length }];
}

// ---------- the twice daily check (cron) ----------
async function cleanUp(env, now) {
  const old = new Date(now.getTime() - CONFIRM_HOURS * 3600000).toISOString();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM tokens WHERE watch_id IN (SELECT id FROM watches WHERE confirmed_at IS NULL AND created_at < ?)").bind(old),
    env.DB.prepare("DELETE FROM watches WHERE confirmed_at IS NULL AND created_at < ?").bind(old),
    env.DB.prepare("DELETE FROM tokens WHERE watch_id IS NOT NULL AND watch_id NOT IN (SELECT id FROM watches)"),
    env.DB.prepare("DELETE FROM tokens WHERE kind = 'manage' AND email NOT IN (SELECT email FROM watches)"),
  ]);
}

// What changed for one watch. Nothing is decided on a party size NCL didn't update today.
function evaluate(data, row, now) {
  const w = rowWatch(row), n = w.guests;
  const p = priceNow(data, w, now);
  if (!p.updated) return { skip: true };
  const items = [], set = {};
  if (!p.available) {
    if (w.sold_out && !row.sold_out_sent) {
      items.push(`No longer available for ${n} guests (NCL: ${p.reason}). You won't get this email again; the watch stays on in case it comes back.`);
      set.sold_out_sent = 1;
    }
    return { items, set, drop: false };
  }
  set.last_price = p.price;
  if (row.baseline - p.price >= w.drop_pp * n - 0.005) {
    items.push(`Price drop: ${money(row.baseline)} to ${money(p.price)} for the cabin, ${money(row.baseline - p.price)} less (${money((row.baseline - p.price) / n)} per guest). From now on the watch compares with ${money(p.price)}.`);
    set.baseline = p.price;
  }
  if (data.counts && w.few && !row.few_sent && !p.cat.guarantee) {
    const c = data.counts.sailings[p.ship.id] && data.counts.sailings[p.ship.id][p.cat.code];
    const g = c && c.by_guests && c.by_guests[String(n)];
    if (g && g.reliable && Number.isInteger(g.cabins_left) && g.cabins_left >= 1 && g.cabins_left < FEW_LEFT) {
      items.push(`Only ${g.cabins_left} of these cabins left for ${n} guests (cabins left as of ${fmtIso(easternDay(new Date(data.counts.saved_at)))}). You won't get this email again.`);
      set.few_sent = 1;
    }
  }
  return { items, set, drop: set.baseline !== undefined };
}

async function runChecks(env, now) {
  await ensureSchema(env);
  if (easternDay(now) >= END_DAY) {
    await env.DB.batch([env.DB.prepare("DELETE FROM tokens"), env.DB.prepare("DELETE FROM watches")]);
    console.log("checks: the cruise has started, every watch and token deleted");
    return { ended: true };
  }
  await cleanUp(env, now);
  const data = await loadData(now);
  if (!data.prices) {
    console.log("checks: prices.json could not be read, nothing checked");
    return { checked: 0 };
  }
  // A watch is checked once per new prices file (or counts file). One whose email couldn't be
  // sent keeps its old key, so the next run tries again.
  const key = `${data.prices.saved_at}|${data.counts ? data.counts.saved_at : ""}`;
  // "Once a day" watches are checked once per Eastern day (the morning check), the others on
  // every check.
  const today = easternDay(now);
  const due = (await env.DB.prepare("SELECT * FROM watches WHERE confirmed_at IS NOT NULL AND (checked_key IS NULL OR checked_key <> ?)").bind(key).all()).results;
  const rows = due.filter(r => r.frequency !== "daily" || r.checked_day !== today);
  const quiet = [], byEmail = new Map();
  let skipped = 0;
  for (const row of rows) {
    const ev = evaluate(data, row, now);
    if (ev.skip) { skipped++; continue; }
    if (!ev.items.length) quiet.push([row, ev]);
    else byEmail.set(row.email, [...(byEmail.get(row.email) || []), [row, ev]]);
  }
  const update = (row, ev) => {
    const v = { ...row, ...ev.set };
    return env.DB.prepare("UPDATE watches SET last_price = ?, baseline = ?, few_sent = ?, sold_out_sent = ?, checked_key = ?, checked_day = ? WHERE id = ?")
      .bind(v.last_price, v.baseline, v.few_sent, v.sold_out_sent, key, today, row.id);
  };
  if (quiet.length) await env.DB.batch(quiet.map(([row, ev]) => update(row, ev)));

  const messages = [], groups = [];
  for (const [email, list] of byEmail) {
    const tokens = [], parts = [];
    for (const [row, ev] of list) {
      const t = await tokenRow(env, "unsubscribe", { watchId: row.id });
      tokens.push(t);
      parts.push([row.label, ...ev.items.map(x => `- ${x}`), `Stop this watch: ${linkTo(row.page, "unsubscribe", t.token)}`].join("\n"));
    }
    const m = await tokenRow(env, "manage", { email });
    tokens.push(m);
    const page = list[0][0].page;
    const body = ["Hi,", "", `News on the price you're watching on David's cruise page (prices as of ${fmtEastern(data.prices.saved_at)}):`, "",
                  parts.join("\n\n"), "", PRICE_TEXT, CHANGE_TEXT, "",
                  `See the page: ${page}`, `See or stop all your price watches: ${linkTo(page, "manage", m.token)}`].join("\n");
    await env.DB.batch(tokens.map(t => t.stmt));
    messages.push({ to: email, subject: list.some(([, ev]) => ev.drop) ? "Cruise price watch: the price dropped" : "Cruise price watch: news on your cabin", body });
    groups.push({ list, tokens });
  }
  const sent = await mail(env, "alert", messages);
  let waiting = 0;
  for (let i = 0; i < groups.length; i++) {
    if (sent[i]) {
      await env.DB.batch(groups[i].list.map(([row, ev]) => update(row, ev)));
    } else {
      waiting += groups[i].list.length;
      const hashes = await Promise.all(groups[i].tokens.map(t => sha256(t.token)));
      await env.DB.batch(hashes.map(h => env.DB.prepare("DELETE FROM tokens WHERE hash = ?").bind(h)));
    }
  }
  console.log(`checks: ${rows.length} watches to check, ${due.length - rows.length} once a day watches already checked today, ${skipped} skipped (prices not updated for that party size), ${sent.filter(Boolean).length} emails sent, ${waiting} alerts waiting for the next run`);
  return { checked: rows.length, later: due.length - rows.length, skipped, sent: sent.filter(Boolean).length, waiting };
}

// ---------- /booking (Make Selection) ----------
// Nothing from the request is stored or logged: it is checked, turned into the two emails and
// dropped. The amounts are the page's own; David confirms everything with NCL.
class Bad extends Error {}
const fail = () => { throw new Bad(); };
function str(v, max, optional = false) {
  if (v === null || v === undefined || v === "") return optional ? "" : fail();
  if (typeof v !== "string") fail();
  const s = v.replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
  if ((!s && !optional) || s.length > max) fail();
  return s;
}
const num = v => v === null ? null : typeof v === "number" && Number.isFinite(v) && Math.abs(v) < 1e6 ? v : fail();
// One line of the window's price breakdown, as the page shows it ("Cruise fare", "$3,138").
const line = x => { obj(x); return { item: str(x.item, 300), value: str(x.value, 60) }; };
const bool = v => typeof v === "boolean" ? v : fail();
const int = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi ? v : fail();
const oneOf = (v, list) => list.includes(v) ? v : fail();
const isoDate = v => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) ? v : fail();
const obj = v => v && typeof v === "object" && !Array.isArray(v) ? v : fail();
const list = (v, lo, hi) => Array.isArray(v) && v.length >= lo && v.length <= hi ? v : fail();

function readBooking(b) {
  const party = obj(b.party);
  const adults = int(party.adults, 1, 5);
  const kids = list(party.kid_ages, 0, 4).map(a => int(a, 0, 20));
  const total = adults + kids.length;
  if (total < 2 || total > 5) fail();
  const option = oneOf(b.option, Object.values(OPTIONS).map(o => o.label));
  const fl = obj(b.florida);
  const residents = bool(fl.residents);
  let address = null;
  if (fl.address !== null) {
    const a = obj(fl.address);
    address = { street: str(a.street, 120), city: str(a.city, 60), state: str(a.state, 20), zip: str(a.zip, 10) };
  }
  const sw = obj(b.page_switches);
  const bookings = list(b.bookings, 1, 2).map(k => {
    obj(k);
    const fas = obj(k.free_at_sea);
    const dep = k.ncl_deposit === null ? null : obj(k.ncl_deposit);
    return {
      ship: oneOf(k.ship, Object.values(SHIP_NAMES)), depart: isoDate(k.depart), return: isoDate(k.return), nights: int(k.nights, 1, 30),
      cabin_type: str(k.cabin_type, 60), category: str(k.category, 8), description: str(k.description, 300), guarantee: bool(k.guarantee),
      free_at_sea: { bar: bool(fas.bar), dining: bool(fas.dining), plus: bool(fas.plus) },
      lines: list(k.lines, 1, 12).map(line), price: num(k.total), onboard: list(k.onboard, 0, 1).map(line),
      choice: oneOf(k.deposit_choice, ["ncl", "credit1", "credit2"]),
      deposit: dep && { amount: num(dep.amount), rule: str(dep.rule, 200, true), hours: num(dep.due_hours), offer: dep.offer === null ? null : str(dep.offer, 120) },
      credits: int(k.credits, 0, 2), credit_value: num(k.credit_value), due: num(k.due_at_booking), balance: num(k.balance),
      balance_due: k.balance_due === null ? null : k.balance_due === "when booking" ? "when booking" : isoDate(k.balance_due), pay_david: num(k.pay_david),
    };
  });
  if (bookings.length !== OPTIONS[Object.keys(OPTIONS).find(x => OPTIONS[x].label === option)].ships.length) fail();
  const guests = list(b.guests, total, total).map((g, i) => {
    obj(g);
    if (g.position !== i + 1) fail();
    const adult = bool(g.adult);
    return { position: i + 1, adult, age: adult ? (g.age_on_sail_date === null ? null : fail()) : int(g.age_on_sail_date, 0, 20),
             first: str(g.first, 60), middle: str(g.middle, 60, true), last: str(g.last, 60), dob: isoDate(g.date_of_birth),
             gender: oneOf(g.gender, ["Female", "Male"]), citizenship: str(g.citizenship, 60),
             latitudes: g.latitudes === null ? null : /^\d{4,15}$/.test(g.latitudes) ? g.latitudes : fail() };
  });
  const g1 = obj(b.guest1), sender = obj(b.sender);
  const g1email = cleanEmail(g1.email), senderEmail = cleanEmail(sender.email);
  if (!g1email || !senderEmail) fail();
  return {
    option, party: { adults, kids }, residents, address, prepay: bool(sw.prepay_gratuities), flSwitch: bool(sw.florida_resident_rate),
    bookings, guests, g1: { email: g1email, phone: str(g1.phone, 30) },
    sender: { isGuest1: bool(sender.is_guest1), name: str(sender.name, 120), email: senderEmail },
    savedAt: str(b.prices_saved_at, 40), version: str(b.page_version, 20),
  };
}

const yes = v => v ? "yes" : "no";
const amount = v => v === null ? "David will confirm" : money(v);
function partyText(p) {
  const kids = p.kids.length ? ` and ${plural(p.kids.length, "kid", "kids")} (${p.kids.length === 1 ? "age" : "ages"} ${p.kids.join(" and ")} on ${fmtIso(AGE_DAY)})` : "";
  return plural(p.adults, "adult", "adults") + kids;
}
function depositText(k) {
  if (k.choice === "credit1") return "One of David's CruiseNext credits ($250 toward the cruise, pay David $125)";
  if (k.choice === "credit2") return "Two of David's CruiseNext credits, NCL's DoubleUp offer ($500 toward the cruise, pay David $250)";
  const d = k.deposit;
  if (!d || d.amount === null) return "NCL's deposit (not found on NCL today; David will confirm it)";
  return `NCL's deposit: ${money(d.amount)}${d.rule ? ` (${d.rule})` : ""}${d.hours ? `, due within ${d.hours} hours of booking` : ""}${d.offer ? `, with NCL's ${d.offer} offer` : ""}`;
}
const dueText = k => k.balance_due === "when booking" ? "due when booking" : k.balance_due ? `due by ${fmtIso(k.balance_due)}` : "due by NCL's final payment date (not found on NCL today)";

// full: David's email (everything). Otherwise the sender's copy: no dates of birth, no Latitudes
// numbers, and guest 1's address, email and phone only when the sender is guest 1.
function bookingText(b, full) {
  const out = [];
  const mine = full || b.sender.isGuest1;
  if (full) out.push("Booking request from the cruise page", "", `Sent by: ${b.sender.name} <${b.sender.email}>${b.sender.isGuest1 ? " (guest 1)" : ""}`);
  else out.push(`Hi ${b.sender.name},`, "", "David got your selection and will confirm by email. This is your copy. Dates of birth and Latitudes numbers went only to David.");
  out.push("", CHANGE_TEXT, "", `Option: ${b.option}`, `Party: ${partyText(b.party)}`,
           `Prepay gratuities on the page: ${b.prepay ? "yes" : "no, service charges are paid onboard"}`,
           `Florida resident rate switch on the page: ${b.flSwitch ? "on" : "off"}`,
           `Are guest 1 and guest 2 Florida residents? ${b.residents ? "Yes" : "No"}`);
  if (b.address && mine) out.push(`Guest 1's Florida home address: ${b.address.street}, ${b.address.city}, ${b.address.state} ${b.address.zip}`);
  b.bookings.forEach((k, i) => {
    out.push("", `${b.bookings.length > 1 ? `Booking ${i + 1}: ` : ""}${k.ship}, ${fmtDay(k.depart)} to ${fmtIso(k.return)} (${plural(k.nights, "night", "nights")})`,
             `Cabin: ${k.cabin_type}: ${k.description} (${k.category})${k.guarantee ? `. ${GUARANTEE_TEXT}` : ""}`,
             `Free at Sea: Unlimited Open Bar ${yes(k.free_at_sea.bar)}, Specialty Dining ${yes(k.free_at_sea.dining)}, Free at Sea Plus ${yes(k.free_at_sea.plus)}`);
    out.push(...k.lines.map(x => `${x.item}: ${x.value}`), `Total: ${amount(k.price)}`);
    if (k.onboard.length) out.push(...k.onboard.map(x => `${x.item}: ${x.value}`), "  Can be removed at Guest Services.");
    out.push(`Deposit: ${depositText(k)}`);
    if (k.credits) out.push(`CruiseNext ${k.credits === 2 ? "credits" : "credit"} toward the cruise: ${amount(k.credit_value)}`);
    out.push(`Paid to NCL at booking: ${amount(k.due)}`, `Balance, ${dueText(k)}: ${amount(k.balance)}`);
    if (k.credits) out.push(`Pay David for the credits: ${amount(k.pay_david)}`);
  });
  if (b.bookings.length > 1) {
    const sum = f => b.bookings.some(k => k[f] === null) ? null : b.bookings.reduce((t, k) => t + k[f], 0);
    out.push("", "Both bookings together", `Total: ${amount(sum("price"))}`, `Paid to NCL at booking: ${amount(sum("due"))}`, `Balances: ${amount(sum("balance"))}`);
    const david = sum("pay_david");
    if (david) out.push(`Pay David for the credits: ${money(david)}`);
  }
  out.push("", "Guests, in NCL's order (adults first, then kids oldest first):");
  for (const g of b.guests) {
    const name = [g.first, g.middle, g.last].filter(Boolean).join(" ");
    out.push(`Guest ${g.position}: ${name}, ${g.adult ? "adult" : `age ${g.age} on ${fmtIso(AGE_DAY)}`}${full ? `, born ${fmtIso(g.dob)}` : ""}, ${g.gender}, citizenship ${g.citizenship}${full && g.latitudes ? `, Latitudes number ${g.latitudes}` : ""}`);
  }
  if (mine) out.push(`Guest 1's email: ${b.g1.email}`, `Guest 1's mobile phone: ${b.g1.phone}`);
  out.push("", `Prices as of ${fmtEastern(b.savedAt)} (page version ${b.version}).`, CHANGE_TEXT);
  return out.join("\n");
}

async function booking(env, body, req) {
  let b;
  try {
    if (body.kind !== "booking") fail();
    b = readBooking(body);
  } catch (e) {
    if (!(e instanceof Bad)) throw e;
    return refuse("request", "The request didn't look right, so nothing was sent. Please reload the page and try again.");
  }
  if (!(await turnstileOk(env, body.turnstile, req.ip))) return refuse("check", "The check above the Send button didn't pass. Please try it again.");
  const sent = await mail(env, "booking", [
    { to: "owner", subject: `Booking request: ${b.option} (${b.sender.name})`, body: bookingText(b, true), replyTo: b.sender.email },
    { to: b.sender.email, subject: "Your cruise selection was sent to David", body: bookingText(b, false) },
  ]);
  if (!sent[0]) {
    console.log("/booking: not sent");
    return refuse("mail", "David's email service couldn't send it right now. Nothing was sent or saved. Please try again later.", 503);
  }
  console.log(`/booking: sent${sent[1] ? " with the copy" : ", the copy failed"}`);
  return [{ ok: true, copy: sent[1] }];
}
