# Family alerts (Cloudflare Worker and Apps Script, 5.2.0; aboard list 5.3.0)

`worker.js` is the Cloudflare Worker `cruise-family-alerts`, separate from the Deck Finder Worker and from `cruise-refresh-trigger`. It runs the family price watch ("Watch this price" on the page) and sends the Make Selection booking requests. `apps-script/Code.gs` is the Apps Script that sends its emails from the owner's Gmail. NOTES.md, "Family price watch and booking emails".

- **What is stored:** price watches only, in the Cloudflare D1 database `cruise-family-alerts`: the email address, the option, ship and cabin code, party size, Florida answer, the person's choices (drop per guest, few left, sold out, how often), prices and dates. Links in the emails carry random tokens; only their SHA-256 is stored. Unconfirmed watches are deleted after 48 hours, a stopped watch at once, everything from Jun 11, 2027 (Eastern). Booking requests are never stored or logged: the Worker checks them, builds the two emails and drops them (5.3.0: except the cast ids their guests' first names match, kept with the hash of David's "Confirm aboard" link). The splash page's aboard list: cast ids only, kept through the trip and deleted from Jun 20, 2027 (Eastern).
- **Who can call it:** only the page's address, `https://dasatizabal.github.io` (plus `https://raw.githack.com` while `TEST_ORIGIN` is set for testing). Starting a watch and sending a booking request need Cloudflare Turnstile.
- **Secrets:** only in Cloudflare (Worker secrets `TURNSTILE_SECRET`, `APPS_SCRIPT_URL`, `APPS_SCRIPT_SECRET`) and in the Apps Script (Script Properties, `SHARED_SECRET`, the same value as `APPS_SCRIPT_SECRET`). Never in this repo, a note, an email or a file. The owner's email address is in no file and no setting: the Apps Script sends "owner" mail to the account it runs as.
- **Email limits:** a free Gmail account can send 100 emails a day from Apps Script. Price watch emails always leave 20 of them for booking requests; an alert that can't be sent waits for the next check. A booking request is sent whole (David's email and the sender's copy) or not at all.
- **Checks:** cron triggers `30 12 * * *` and `30 17 * * *` (UTC, after the price and count refreshes) read the published `data/prices.json`, `data/counts.json` and `data/florida.json`. No NCL calls. A price is checked once per new prices file, and never on a party size NCL didn't update that day. "At most once a day" watches are checked only on the morning check.
- **Logs:** counts and fixed words only. Never an email address, a name, a token or anything from a booking request.
- **Tests:** `node --test "tools/family-alerts/test/*.test.mjs"` (Node 22.13 or later; a stand-in for D1, the data files, Turnstile and the Apps Script; no network). The release check fails while `TEST_ORIGIN` is set.

## Setup

Do the parts in this order. Each part says what to keep for later. Never paste a secret anywhere except the place the step names.

### 1. Apps Script (sends the emails)

1. On a computer, open https://script.google.com/home and sign in with the Gmail account the emails should come from (David's).
2. Click "New project" at the top left.
3. Click "Untitled project" at the top, type `Cruise family mail` and click "Rename".
4. In a new tab, open https://github.com/DASatizabal/cruise-cabin-comparison/blob/family-tools-5.2.0/tools/family-alerts/apps-script/Code.gs and click the "Copy raw file" button (two overlapping squares) at the top right of the code.
5. Back in Apps Script, click inside the code of `Code.gs`, press Ctrl+A, press Delete, then press Ctrl+V. Press Ctrl+S to save.
6. Make the shared secret: press the Windows key, type `PowerShell`, press Enter, then paste this command and press Enter. It copies a 64 character secret to the clipboard and shows nothing:

   ```
   $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString('x2') }) | Set-Clipboard
   ```

7. Back in Apps Script, click "Project Settings" (the gear) in the left menu. At the bottom, under "Script Properties", click "Add script property". Property: `SHARED_SECRET`. Value: press Ctrl+V. Click "Save script properties". Close the PowerShell window.
8. Click "Editor" (the `< >` icon) in the left menu. In the toolbar, open the function list (it may say `doPost`), choose `checkSetup` and click "Run".
9. Google asks for permission: click "Review permissions", choose the same account, click "Advanced", then "Go to Cruise family mail (unsafe)" (it is your own script), then tick "Select all" if shown and click "Continue" or "Allow".
10. The execution log at the bottom says "Execution completed". Within a minute Gmail has an email "Cruise family mail: setup test" saying how many sends are left today. If the log shows "SHARED_SECRET is missing", redo step 7.
11. Click "Deploy" at the top right, then "New deployment". Click the gear next to "Select type" and choose "Web app". Description: `cruise family mail`. Execute as: "Me". Who has access: "Anyone". Click "Deploy". If Google asks for permission again, do step 9 again.
12. Click "Done". Keep this tab open. Part 4 copies the Web app address from "Deploy", "Manage deployments", and the secret from "Project Settings".

### 2. Turnstile (spam check on the page)

1. Open https://dash.cloudflare.com and sign in. If you have more than one account, choose the one that holds the Deck Finder Worker.
2. In the left menu, open "Turnstile". If you don't see it, type `Turnstile` in the search box at the top of the left menu.
3. Click "Add widget".
4. Widget name: `cruise family`.
5. Hostnames: add `dasatizabal.github.io`, then add `raw.githack.com` (temporary, for testing from the preview; removed in part 7).
6. Widget mode: "Managed". Pre-clearance: "No". Click "Create".
7. Copy the "Site Key" (it is public, it goes into the page) and send it to Claude. Leave the "Secret Key" where it is: part 4 copies it from the widget's settings.

### 3. D1 database (keeps the price watches)

1. In the Cloudflare dashboard, in the left menu, open "Storage & databases", then "D1 SQL database". If you don't see it, type `D1` in the search box at the top of the left menu.
2. Click "Create database" (or "Create").
3. Name: `cruise-family-alerts`. Location: leave "Automatic". Click "Create".
4. Nothing else: the Worker creates its two tables the first time it runs.

### 4. The Worker, its secrets, binding and cron triggers

1. In a new tab, open https://github.com/DASatizabal/cruise-cabin-comparison/blob/family-tools-5.2.0/tools/family-alerts/worker.js and click "Copy raw file".
2. In the Cloudflare dashboard, open "Compute (Workers)" and then "Workers & Pages" in the left menu.
3. Click "Create" (or "Create application"), then "Start with Hello World!" (on the Workers tab).
4. Worker name: `cruise-family-alerts`. Click "Deploy".
5. Click "Edit code". Click inside the code, press Ctrl+A, press Delete, press Ctrl+V, then click "Deploy" at the top right and confirm. Go back to the Worker's page (its name at the top left).
6. Open the "Bindings" tab (on some screens it is under "Settings", "Bindings"). Click "Add binding", choose "D1 database", click "Add binding". Variable name: `DB`. D1 database: `cruise-family-alerts`. Click "Add binding" (or "Deploy").
7. Open "Settings", find "Variables and Secrets", click "Add". Type: "Secret". Variable name: `TURNSTILE_SECRET`. For the value: in another tab open the Cloudflare dashboard, "Turnstile", click the `cruise family` widget, then "Settings" (or "Manage"), and click the copy button next to "Secret Key". Paste it as the value. Click "Deploy".
8. Click "Add" again. Type: "Secret". Variable name: `APPS_SCRIPT_URL`. For the value: in the Apps Script tab click "Deploy", "Manage deployments", and click "Copy" under "Web app" (the address ends with `/exec`). Paste it. Click "Deploy".
9. Click "Add" again. Type: "Secret". Variable name: `APPS_SCRIPT_SECRET`. For the value: in the Apps Script tab click "Project Settings", find `SHARED_SECRET` under "Script Properties", click "Edit script properties", select the whole value, press Ctrl+C, then click "Cancel". Paste it. Click "Deploy".
10. Still in "Settings", find "Trigger Events", click "Add", then "Cron Triggers". Type `30 12 * * *` and click "Add".
11. Click "Add", "Cron Triggers" again, type `30 17 * * *` and click "Add". These are UTC times: 8:30 AM and 1:30 PM Miami time until November 1, then 7:30 AM and 12:30 PM.
12. Open the "Logs" tab (it may be called "Observability"). If it shows a button to enable Workers Logs, click it.
13. In "Settings", "Domains & Routes", copy the `workers.dev` address (like `https://cruise-family-alerts.yourname.workers.dev`) and send it to Claude.

### 5. Claude puts the Worker's address and the site key into the page

Claude sets `FAMILY_API` and `TURNSTILE_SITE_KEY` in `index.html`, commits on the branch, and sends a raw.githack.com preview link pinned to that commit.

### 6. Test from the preview

1. Open the preview link on your phone. Pick an option, set the guests, and tap "Watch this price". Answer the Florida question, leave or change the drop amount, the two ticks and how often, type your email, wait for the check above the button to show a tick, and tap "Start watching".
2. Open the email "Confirm your cruise price watch" and tap the first link. The page opens with "Your price watch has started."
3. In the same email, tap the last link ("See or stop your price watches"). The page lists the watch with a "Stop this watch" button. Leave it running for the cron test.
4. Tap "Make Selection" on a card, fill everything in with test names (not real ones) and your own email as the sender, and tap "Send my selection to David". Gmail gets "Booking request: ..." (David's full copy) and "Your cruise selection was sent to David" (no dates of birth, no Latitudes numbers).
5. Cron test: open https://time.is/UTC and add 20 minutes to the UTC time (17:41 becomes 18:01). In the Worker's "Settings", "Trigger Events", add a cron trigger with the minute, a space, the hour and ` * * *` (for 18:01: `1 18 * * *`). At that time plus 3 minutes, open the Worker's "Logs": a line starts with `checks:` and gives only counts. Then delete that test trigger and keep `30 12 * * *` and `30 17 * * *`.
6. In the Worker's "Logs", check that no line shows an email address, a name or a link.
7. Back on the manage page from step 3, tap "Stop this watch".

### 7. Before merging

1. Claude sets `TEST_ORIGIN` to `""` in `worker.js` and commits (until then the release check fails on purpose).
2. Paste the new `worker.js` into the Worker again (part 4, steps 1 and 5, from the same branch address, after Claude's commit). The preview stops working for the price watch and booking requests; that is expected.
3. In Turnstile, open the `cruise family` widget's settings, remove the hostname `raw.githack.com` and save.

## Splash page update (5.3.0)

The Worker also keeps who is aboard for the splash page (NOTES.md, "Splash page"): new routes `GET /aboard`, `/aboard/open`, `/aboard/save` and `/aboard/link`, and two new tables it creates itself (`aboard`, `aboard_links`: cast ids and token hashes only). The Apps Script gets one new email kind (`aboard`, to the owner only). No new secrets, bindings or cron triggers. Claude gives the steps one at a time; they are:

1. Update the Apps Script (paste the new `Code.gs`, save, and deploy a new version of the same web app, so its address stays the same).
2. Add `raw.githack.com` to the Turnstile widget's hostnames again (for testing from the preview).
3. Claude sets `TEST_ORIGIN` to `"https://raw.githack.com"` and commits; paste that `worker.js` into the Worker.
4. Test from the preview: the deck, a Make Selection request with the "Confirm aboard" link, the checklist, and "Email me a private aboard link".
5. Before merging: Claude sets `TEST_ORIGIN` to `""` and commits; paste `worker.js` into the Worker again; remove `raw.githack.com` from the Turnstile widget; move the test people back to the dock with a fresh private link.
