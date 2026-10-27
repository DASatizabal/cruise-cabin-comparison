# June Florida resident rates on the AI PC

This sets up the AI PC to check, once a week, whether NCL offers a Florida resident discount on the June sailings (Norwegian Getaway Jun 11, 2027 and Norwegian Aura Jun 14, 2027), and to publish the result on the June page. NCL only shows these prices to an account with a Florida address, so it uses the same signed-in Chrome profile as the Joy page's Florida task: `D:\AI-VAULT\ncl-profile`.

What it does:
- Once a week, a light check: for the cheapest Inside, Oceanview, Balcony, Club Balcony Suite and Haven cabin on each ship, at 2 guests, it asks NCL for the website price (signed out) and the Florida price (signed in). That is 22 NCL calls, 10 of them signed in, about 1 minute.
- Only if that check finds a real discount ($1 or more off per guest on any cabin), it checks every cabin on both ships the same day (about 122 calls, 60 signed in, about 5 minutes), so the page has each cabin's exact amount. While the discount lasts it does that every week instead of the light check. When the discount is gone, it goes back to light checks.
- It saves only numbers, cabin codes and dates in `data/florida.json` and sends that file to GitHub, which republishes the page in about a minute. No names, email, Latitudes number or anything else from your account.
- It only uses NCL's price calls, never anything that books or holds a cabin, and stops at once if NCL's answer ever mentions a hold.
- The scheduled task runs at 9:00 AM, 1:00 PM and 5:00 PM every day, 2 hours away from the Joy task's runs (7:00 AM, 11:00 AM, 3:00 PM and 7:00 PM). Runs on days when no check is due finish in seconds and make no NCL calls. The later runs of a day only matter when an earlier one failed or the PC was off.
- It never opens the Chrome profile while the Joy task is using it: it waits 2 minutes, up to 3 times, and never starts when the Joy task is due within 20 minutes.

**Keep the folder `D:\AI-VAULT\ncl-profile` until after the June cruise (Jun 11, 2027).** It holds your signed-in NCL session, and both the Joy task and this June task use it. The Joy README says to delete it after the Joy cruise (Nov 20, 2026). Do not delete it then: the June check would stop working. Anyone with that folder could act as you on ncl.com, so keep it on the AI PC and never copy it into a repository or send it to anyone.

## First-time setup

Do these steps after the 5.1.0 pull request is merged into main.

1. On the AI PC, press the Windows key, type `PowerShell`, and press Enter.
2. Make the separate copy of the June repository (this copy is only for the Florida task). Type this and press Enter:
   ```
   cd D:\Repos
   ```
3. Type this and press Enter. It prints `Cloning into 'cruise-cabin-comparison'...`:
   ```
   git clone https://github.com/DASatizabal/cruise-cabin-comparison.git
   ```
4. Type this and press Enter:
   ```
   cd D:\Repos\cruise-cabin-comparison
   ```
5. Type this and press Enter:
   ```
   git config user.name "DASatizabal"
   ```
6. Type this and press Enter. It makes this copy sign its updates with GitHub's private address instead of your personal email, because the repository is public. The script refuses to publish without exactly this address:
   ```
   git config user.email "174554998+DASatizabal@users.noreply.github.com"
   ```
7. Make sure the browser tool is installed (it already is if the Joy task works; this does no harm). Type this and press Enter:
   ```
   py -3 -m pip install playwright tzdata
   ```
8. Run the first check by hand. Do it at a time that is not within 20 minutes of the Joy task's runs (7:00 AM, 11:00 AM, 3:00 PM, 7:00 PM); for example between 4:00 PM and 6:30 PM. Type this and press Enter:
   ```
   py -3 tools\fetch_florida.py --push
   ```
   It prints each cabin with its website and Florida price, then `Wrote ...florida.json` and `Pushed to main; the page republishes in about a minute.` The first time, Git may open a browser window asking you to sign in to GitHub. Sign in as DASatizabal and allow access (the scheduled task runs in the background and can't show that window, so this has to happen once by hand).
9. Check the page: open https://dasatizabal.github.io/cruise-cabin-comparison/ and look at the top. It should say "Florida rates as of" with today's date, and under the "Florida resident rate" switch either "Selected. NCL isn't offering a Florida resident discount on these sailings right now (checked ...)" or NCL's Florida prices.

If step 8 prints `NOT SIGNED IN`, follow "When the login expires" below, then do step 8 again.

## Run it on a schedule

10. In PowerShell, type this as one line and press Enter. It runs the check every day at 9:00 AM, 1:00 PM and 5:00 PM (the AI PC's clock) and writes a log. If you already created the task, running this replaces it:
    ```
    schtasks /Create /TN "June Florida rates" /SC DAILY /ST 09:00 /RI 240 /DU 0008:00 /F /TR "cmd /c cd /d D:\Repos\cruise-cabin-comparison && py -3 tools\fetch_florida.py --push >> D:\AI-VAULT\ncl-profile\june-florida-log.txt 2>&1"
    ```
    It should print `SUCCESS: The scheduled task "June Florida rates" has successfully been created.` The task runs while you're signed in to Windows, which is how the AI PC normally runs.
11. Check the task's next run time. Type this and press Enter:
    ```
    Get-ScheduledTaskInfo -TaskName "June Florida rates"
    ```
    `NextRunTime` should be the next 9:00 AM, 1:00 PM or 5:00 PM.
12. The next day, open `D:\AI-VAULT\ncl-profile\june-florida-log.txt` in Notepad. Runs with nothing due end with `Not due: ... No NCL calls made.` and `Nothing new to publish.` A week after step 8, the 9:00 AM run's lines should end with `Pushed to main`.

## When the login expires

Your NCL login currently expires on Dec 13, 2026, and the log warns 14 days before. You'll notice one of these: the log's last lines say `NOT SIGNED IN`, or the "Florida rates as of" date at the top of the page turns amber (more than 9 days old). After 15 days without a check the page stops using the Florida prices and shows website prices.

To fix it, sign in again. Signing in from either the Joy or the June copy works, because they share the profile. Do it at a time that is not within 20 minutes of a Joy or June run.

1. Open PowerShell and type this, then press Enter:
   ```
   cd D:\Repos\cruise-cabin-comparison
   ```
2. Type this and press Enter:
   ```
   py -3 tools\fetch_florida.py --setup
   ```
3. A Chrome window opens on ncl.com. Sign in to your NCL account (the one with your Florida address). If NCL shows "Remember me" or "Keep me signed in", tick it.
4. When the page shows you're signed in, click back on the PowerShell window and press Enter. It prints `Signed in: yes (login expires ...)`. Nothing else changes; the next scheduled run picks it up.

## If NCL blocks the hidden browser

If the log shows `failed` for every cabin, or `HTTP 403`, NCL may be blocking the hidden browser window. Type this as one line and press Enter, to make the task use a visible window instead:
```
schtasks /Create /TN "June Florida rates" /SC DAILY /ST 09:00 /RI 240 /DU 0008:00 /F /TR "cmd /c cd /d D:\Repos\cruise-cabin-comparison && py -3 tools\fetch_florida.py --push --show >> D:\AI-VAULT\ncl-profile\june-florida-log.txt 2>&1"
```

## What the log lines mean

- `Not due: ...`: no check this week yet, no NCL calls. Normal on 6 days out of 7.
- `Profile busy (...)`: the Joy task had the Chrome profile; no NCL calls. The next run tries again.
- `Not publishing: this clone's Git email isn't GitHub's private noreply address`: do step 6 again, in `D:\Repos\cruise-cabin-comparison`.
- `Not publishing: this clone is on branch ...`: type `git switch main` in `D:\Repos\cruise-cabin-comparison` and press Enter.
- `Push failed`: the file is saved on the AI PC; the next run sends it. To send it now, type `git push origin HEAD:main` in `D:\Repos\cruise-cabin-comparison` and press Enter.

## After the cruise

The script stops checking by itself from Jun 11, 2027. To remove the task, type this and press Enter:
```
schtasks /Delete /TN "June Florida rates" /F
```
You can also delete the folder `D:\AI-VAULT\ncl-profile` then, once the Joy task is gone too, which signs that browser out of NCL for good.
