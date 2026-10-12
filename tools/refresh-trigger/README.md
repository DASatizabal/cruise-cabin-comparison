# Refresh trigger (Cloudflare Worker)

`worker.js` is a small Cloudflare Worker, separate from the Deck Finder Worker. At 10:20 and 15:05 UTC it asks GitHub to start the "Refresh prices" workflow on `main` with source `timer`. The workflow's first job skips work already done today, so a late or extra run costs nothing. Visiting the Worker's address only shows a short message.

The token lives only in Cloudflare as the secret `GITHUB_TOKEN`. Never put it in this repo.

Merge the version that adds the `source` input (4.10.0) into `main` before setting this up. Until then GitHub refuses the Worker's request with 422 ("Unexpected inputs").

## 1. Create the GitHub token

1. On a computer, open https://github.com/settings/personal-access-tokens/new and sign in if asked. (The long way there: tap your profile photo at the top right, then Settings, then Developer settings at the bottom of the left menu, then Personal access tokens, then Fine-grained tokens, then Generate new token.)
2. Token name: `cruise refresh trigger`.
3. Description: `Starts Refresh prices from the Cloudflare Worker`.
4. Resource owner: `DASatizabal`.
5. Expiration: choose Custom, then pick June 30, 2027 (after the cruise).
6. Repository access: choose "Only select repositories", then pick `DASatizabal/cruise-cabin-comparison`.
7. Permissions: open "Repository permissions". If you see a list, find "Actions" and set it to "Read and write". If you see an "Add permissions" button instead, tap it, tick "Actions", and set it to "Read and write". Leave everything else as it is. GitHub adds "Metadata: Read-only" by itself; that is expected.
8. Tap "Generate token", then "Generate token" again in the confirmation box.
9. Tap the copy button next to the token, which starts with `github_pat_`. Paste it into Cloudflare in part 2, step 9, right away. Do not save it in a note, email or file. If you lose it before pasting, open the token's page and tap "Regenerate token".

When it expires: GitHub emails you about a week before June 30, 2027. If the trip is over, do nothing; the Worker then logs "GitHub answered 401" and starts nothing. To keep it working, open https://github.com/settings/personal-access-tokens, tap "cruise refresh trigger", tap "Regenerate token", pick a new date up to one year away, tap "Regenerate token", copy the new token, and replace the secret: part 2, steps 7 to 10, choosing the existing `GITHUB_TOKEN` and tapping its edit (pencil) button instead of "Add".

## 2. Create the Worker in the Cloudflare dashboard

1. In a new tab, open https://github.com/DASatizabal/cruise-cabin-comparison/blob/main/tools/refresh-trigger/worker.js and tap the "Copy raw file" button (two overlapping squares) at the top right of the code.
2. Open https://dash.cloudflare.com and sign in. If you have more than one account, choose the one that holds the Deck Finder Worker.
3. In the left menu, open "Compute (Workers)" and then "Workers & Pages".
4. Tap "Create" (or "Create application"), then "Start with Hello World!" (on the Workers tab).
5. Worker name: `cruise-refresh-trigger`. Tap "Deploy".
6. Tap "Edit code". Click inside the code, select everything (Ctrl+A), press Delete, paste the code from step 1 (Ctrl+V), then tap "Deploy" at the top right and confirm. Go back to the Worker's page (its name at the top left).
7. Open the "Settings" tab, find "Variables and Secrets", and tap "Add".
8. Type: "Secret". Variable name: `GITHUB_TOKEN`.
9. Value: paste the token from part 1.
10. Tap "Deploy".
11. Still in "Settings", find "Trigger Events" and tap "Add", then "Cron Triggers".
12. Choose the cron expression option and type `20 10 * * *`. Tap "Add".
13. Tap "Add", then "Cron Triggers" again, type `5 15 * * *` and tap "Add".
14. "Trigger Events" now lists both cron triggers. These are UTC times: 6:20 AM and 11:05 AM Miami time until November 1, then 5:20 AM and 10:05 AM.
15. Open the "Logs" tab (it may be called "Observability"). If it shows a button to enable Workers Logs, tap it.

## 3. Test it once right away

1. Open https://time.is/UTC and note the UTC time. Add 20 minutes. Example: 17:41 becomes 18:01.
2. In the Worker's "Settings", "Trigger Events", tap "Add", then "Cron Triggers", and type the minute, a space, the hour, then ` * * *`. For 18:01 that is `1 18 * * *`. Tap "Add". (Cloudflare can take several minutes to pick up a new trigger, which is why it is 20 minutes ahead.)
3. At that time plus 3 minutes, open the Worker's "Logs" tab. You should see a line like `cron "1 18 * * *": GitHub answered 204, "Refresh prices" started`. You can also check "Settings", "Trigger Events", "View events".
   - "GitHub answered 401": the token was pasted wrong or has expired. Redo part 2, steps 7 to 10 with a fresh token (part 1, "When it expires").
   - "GitHub answered 403" or "404": the token lacks "Actions: Read and write" for this repository. Create a new token (part 1) and replace the secret.
   - "GitHub answered 422": the version with the `source` input is not on `main` yet. Merge it, then repeat this test.
4. Open https://github.com/DASatizabal/cruise-cabin-comparison/actions and tap "Refresh prices" in the left list. The newest run is titled "Refresh prices (timer)" and says it was manually run by you (the token is yours). Tap it. The "Refresh decision" notice mentions "started by the Cloudflare timer". If nothing was saved today it says "Full run"; wait about 10 to 15 minutes for every box to turn green.
5. Back in Cloudflare, "Settings", "Trigger Events": delete the test trigger (the one you added in step 2) with its delete (trash can) button. Keep `20 10 * * *` and `5 15 * * *`.

## 4. Check the next morning

1. After 6:20 AM Miami time (10:20 UTC), with 7:00 AM a good time, open https://github.com/DASatizabal/cruise-cabin-comparison/actions and tap "Refresh prices".
2. Look for a "Refresh prices (timer)" run that started within a few minutes after 6:20 AM. Tap it. The "Refresh decision" notice should say "Full run: prices were not refreshed today yet (started by the Cloudflare timer, ...)". Wait until every box is green.
3. If there is no timer run, open the Worker's "Logs" tab in Cloudflare and read the line for `20 10 * * *` (see part 3, step 3 for what each answer means).
4. Open https://dasatizabal.github.io/cruise-cabin-comparison/ and pull down to refresh. "Prices as of" and "Cabins left as of" should both show that day's date.
5. After 11:05 AM Miami time (15:05 UTC) there is a second "Refresh prices (timer)" run. Its notice should say "Skipped: prices and counts were both already refreshed today", with only "decide" and "keepalive" green. That is correct.
