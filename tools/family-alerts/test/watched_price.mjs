// The Worker's watched price for one cabin, for the cross-check in tools/page_test.py (the page's
// window must show the same number):
//   node tools/family-alerts/test/watched_price.mjs PRICES.json FLORIDA.json|- SHIP(G|A) CODE GUESTS 0|1
import { readFileSync } from "node:fs";
import { loadWorker } from "./helpers.mjs";

const [prices, florida, ship, code, guests, fl] = process.argv.slice(2);
const worker = await loadWorker();
const data = { prices: JSON.parse(readFileSync(prices, "utf-8")), counts: null,
               florida: florida === "-" ? null : JSON.parse(readFileSync(florida, "utf-8")) };
const p = worker.__t.priceNow(data, { option: ship, ship, code, guests: Number(guests), florida: fl === "1" }, new Date());
process.stdout.write(JSON.stringify(p.price) + "\n");
