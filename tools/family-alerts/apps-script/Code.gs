// Apps Script "Cruise family mail" (5.2.0): sends the emails of the Cloudflare Worker
// cruise-family-alerts (tools/family-alerts/worker.js) from the owner's Gmail.
// Setup: tools/family-alerts/README.md, part 1. Deployed as a web app that runs as the owner.
//
// - Refuses every request without the shared secret (Script Properties, SHARED_SECRET; the same
//   value is the Worker's APPS_SCRIPT_SECRET secret). Never put the secret in this file.
// - "owner" as a recipient means the owner's own address (the account this script runs as), so
//   the address is in no file and no Worker setting.
// - Respects Gmail's daily limit (MailApp.getRemainingDailyQuota(), 100 a day on a free Gmail
//   account): price watch emails ("watch", "alert") always leave RESERVED_FOR_BOOKINGS sends for
//   booking requests. A message not sent is answered false; the Worker tries an alert again on
//   its next run.
// - Logs nothing: no Logger or console calls, so no address, name or text is ever written down.

var RESERVED_FOR_BOOKINGS = 20;
var MAX_MESSAGES = 50;
var SENDER_NAME = "David's cruise page";
var KINDS = { watch: true, alert: true, booking: true };

function doPost(e) {
  var answer;
  try {
    answer = handle(JSON.parse(e.postData.contents));
  } catch (err) {
    answer = { ok: false, error: "bad request" };
  }
  return ContentService.createTextOutput(JSON.stringify(answer)).setMimeType(ContentService.MimeType.JSON);
}

function doGet() {
  return ContentService.createTextOutput("Nothing here.");
}

function sameText(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  var diff = 0;
  for (var i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function validMessage(m) {
  return m && typeof m.to === "string" && m.to.length <= 254 && (m.to === "owner" || /^[^\s@<>(),;:"]+@[^\s@<>(),;:"]+\.[^\s@<>(),;:"]+$/.test(m.to)) &&
    typeof m.subject === "string" && m.subject.length > 0 && m.subject.length <= 200 &&
    typeof m.body === "string" && m.body.length > 0 && m.body.length <= 20000 &&
    (m.replyTo === undefined || (typeof m.replyTo === "string" && /^[^\s@<>(),;:"]+@[^\s@<>(),;:"]+\.[^\s@<>(),;:"]+$/.test(m.replyTo)));
}

function handle(req) {
  var secret = PropertiesService.getScriptProperties().getProperty("SHARED_SECRET");
  if (!secret || secret.length < 32 || !req || !sameText(req.secret, secret)) return { ok: false, error: "forbidden" };
  if (!KINDS[req.kind] || !Array.isArray(req.messages) || !req.messages.length || req.messages.length > MAX_MESSAGES) return { ok: false, error: "bad request" };
  for (var i = 0; i < req.messages.length; i++) if (!validMessage(req.messages[i])) return { ok: false, error: "bad request" };

  var remaining = MailApp.getRemainingDailyQuota();
  var keep = req.kind === "booking" ? 0 : RESERVED_FOR_BOOKINGS;
  // A booking request is sent whole or not at all (David's email and the sender's copy).
  if (req.kind === "booking" && remaining < req.messages.length) return { ok: false, error: "quota", sent: req.messages.map(function () { return false; }) };
  var owner = Session.getEffectiveUser().getEmail();
  var sent = [];
  for (var j = 0; j < req.messages.length; j++) {
    var m = req.messages[j];
    if (remaining - keep < 1) { sent.push(false); continue; }
    var mail = { to: m.to === "owner" ? owner : m.to, subject: m.subject, body: m.body, name: SENDER_NAME };
    if (m.replyTo) mail.replyTo = m.replyTo;
    try {
      MailApp.sendEmail(mail);
      remaining--;
      sent.push(true);
    } catch (err) {
      sent.push(false);
    }
  }
  return { ok: true, sent: sent, remaining: remaining };
}

// Run once from the editor (part 1 of the setup): asks for the permissions, checks the secret is
// set, and sends one test email to the owner with the number of sends left today. Stops with an
// error if the secret is missing. Writes nothing to the log.
function checkSetup() {
  var secret = PropertiesService.getScriptProperties().getProperty("SHARED_SECRET");
  if (!secret || secret.length < 32) throw new Error("SHARED_SECRET is missing or shorter than 32 characters. Add it in Project Settings, Script Properties.");
  MailApp.sendEmail({ to: Session.getEffectiveUser().getEmail(), subject: "Cruise family mail: setup test", name: SENDER_NAME,
                      body: "The Apps Script for the cruise page can send email from this account. Sends left today: " + MailApp.getRemainingDailyQuota() + "." });
}
