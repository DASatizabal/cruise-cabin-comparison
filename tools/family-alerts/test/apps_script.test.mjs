// Tests of tools/family-alerts/apps-script/Code.gs with stand-ins for Google's services.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { REPO } from "./helpers.mjs";

const SRC = readFileSync(new URL("tools/family-alerts/apps-script/Code.gs", REPO), "utf-8");
const SECRET = "k".repeat(40);

function script({ quota = 100, secret = SECRET, failOn = null } = {}) {
  const sent = [];
  const ctx = {
    PropertiesService: { getScriptProperties: () => ({ getProperty: k => (k === "SHARED_SECRET" ? secret : null) }) },
    MailApp: {
      getRemainingDailyQuota: () => quota,
      sendEmail(m) { if (failOn && m.to === failOn) throw new Error("bad address"); quota--; sent.push(m); },
    },
    Session: { getEffectiveUser: () => ({ getEmail: () => "owner@example.com" }) },
    ContentService: { MimeType: { JSON: "json" }, createTextOutput: t => ({ text: t, setMimeType() { return this; } }) },
    Array, JSON, Error,
  };
  vm.runInNewContext(SRC, ctx);
  const call = body => JSON.parse(ctx.doPost({ postData: { contents: typeof body === "string" ? body : JSON.stringify(body) } }).text);
  return { ctx, sent, call, quota: () => quota };
}
const msg = (to = "a@example.com") => ({ to, subject: "Subject", body: "Body" });

test("refuses requests without the shared secret, and sends nothing", () => {
  const s = script();
  assert.equal(s.call({ secret: "wrong", kind: "alert", messages: [msg()] }).error, "forbidden");
  assert.equal(s.call({ kind: "alert", messages: [msg()] }).error, "forbidden");
  assert.equal(s.call("not json").error, "bad request");
  assert.equal(script({ secret: null }).call({ secret: SECRET, kind: "alert", messages: [msg()] }).error, "forbidden");
  assert.equal(script({ secret: "short" }).call({ secret: "short", kind: "alert", messages: [msg()] }).error, "forbidden");
  assert.equal(s.sent.length, 0);
});

test("checks every message before sending any", () => {
  const s = script();
  for (const messages of [[], [msg("not an address")], [{ ...msg(), subject: "" }], [msg(), { ...msg(), replyTo: "x" }], Array(51).fill(msg())]) {
    assert.equal(s.call({ secret: SECRET, kind: "alert", messages }).error, "bad request");
  }
  assert.equal(s.call({ secret: SECRET, kind: "other", messages: [msg()] }).error, "bad request");
  assert.equal(s.sent.length, 0);
});

test("\"owner\" is the account the script runs as; reply-to and the sender name", () => {
  const s = script();
  const a = s.call({ secret: SECRET, kind: "booking", messages: [{ ...msg("owner"), replyTo: "sam@example.com" }, msg("sam@example.com")] });
  assert.deepEqual(a, { ok: true, sent: [true, true], remaining: 98 });
  assert.deepEqual(s.sent.map(m => [m.to, m.replyTo, m.name]), [["owner@example.com", "sam@example.com", "David's cruise page"], ["sam@example.com", undefined, "David's cruise page"]]);
});

test("price watch emails leave 20 sends a day for booking requests", () => {
  const s = script({ quota: 22 });
  const a = s.call({ secret: SECRET, kind: "alert", messages: [msg(), msg(), msg()] });
  assert.deepEqual(a.sent, [true, true, false]);
  assert.equal(s.call({ secret: SECRET, kind: "watch", messages: [msg()] }).sent[0], false);
  assert.deepEqual(s.call({ secret: SECRET, kind: "booking", messages: [msg("owner"), msg()] }).sent, [true, true]);
  assert.equal(s.quota(), 18);
});

test("the splash page's private aboard link (\"aboard\") also leaves 20 sends for booking requests", () => {
  const s = script({ quota: 21 });
  assert.deepEqual(s.call({ secret: SECRET, kind: "aboard", messages: [msg("owner"), msg("owner")] }).sent, [true, false]);
  assert.equal(s.sent[0].to, "owner@example.com");
});

test("a booking request is sent whole or not at all", () => {
  const s = script({ quota: 1 });
  const a = s.call({ secret: SECRET, kind: "booking", messages: [msg("owner"), msg()] });
  assert.deepEqual([a.ok, a.error, a.sent], [false, "quota", [false, false]]);
  assert.equal(s.sent.length, 0);
});

test("a message Gmail refuses is answered false, the others still go", () => {
  const s = script({ failOn: "bad@example.com" });
  assert.deepEqual(s.call({ secret: SECRET, kind: "alert", messages: [msg("bad@example.com"), msg()] }).sent, [false, true]);
});

test("checkSetup: stops without the secret, else one test email to the owner", () => {
  assert.throws(() => script({ secret: null }).ctx.checkSetup(), /SHARED_SECRET is missing/);
  const s = script();
  s.ctx.checkSetup();
  assert.equal(s.sent.length, 1);
  assert.equal(s.sent[0].to, "owner@example.com");
  assert.match(s.sent[0].body, /Sends left today: 100\./);
});

test("the script logs nothing and holds no address or secret", () => {
  assert.ok(!/\b(Logger|console)\./.test(SRC));
  assert.ok(!/@[a-z0-9-]+\.[a-z]{2,}/i.test(SRC.replace(/\/\^.*?\$\//g, "")));
  assert.ok(!SRC.includes(String.fromCharCode(0x2014)));
});
