// The Worker's watched price for one watch, for the cross-check in tools/page_test.py (the page's
// window must show the same number):
//   node tools/family-alerts/test/watched_price.mjs PRICES.json FLORIDA.json|- OPTION GUESTS 0|1 GCODE|- ACODE|-
import { readFileSync } from "node:fs";
import { loadWorker } from "./helpers.mjs";

const [prices, florida, option, guests, fl, g, a] = process.argv.slice(2);
const worker = await loadWorker();
const data = { prices: JSON.parse(readFileSync(prices, "utf-8")), counts: null,
               florida: florida === "-" ? null : JSON.parse(readFileSync(florida, "utf-8")) };
const cabins = {};
if (g !== "-") cabins.G = g;
if (a !== "-") cabins.A = a;
const pr = worker.__t.priceNow(data, { option, guests: Number(guests), florida: fl === "1", cabins }, new Date());
process.stdout.write(JSON.stringify(pr.price) + "\n");
