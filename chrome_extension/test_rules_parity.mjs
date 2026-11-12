// Check that rules.js gives the same result as rules.py on every saved observation in results/raw/.
// Run from the repo root: node chrome_extension/test_rules_parity.mjs
import { execFileSync } from "node:child_process";
import { evaluate } from "./rules.js";

const py = `
import json, os, rules
addr = json.load(open("tracking_address.json", encoding="utf-8"))
out = []
for run in sorted(r for r in os.listdir("results/raw") if os.path.isdir(os.path.join("results/raw", r))):
    d = os.path.join("results/raw", run)
    for name in sorted(n for n in os.listdir(d) if n.endswith(".json")):
        t = name[:-5]
        if t not in addr:
            continue
        obs = json.load(open(os.path.join(d, name), encoding="utf-8"))
        out.append({"run": run, "id": t, "address": addr[t], "obs": obs, "py": rules.evaluate(obs, t, addr[t])})
print(json.dumps(out))
`;
const cases = JSON.parse(execFileSync("python3", ["-c", py], { maxBuffer: 1 << 30 }).toString());
let bad = 0;
for (const c of cases) {
  const js = evaluate(c.obs, c.id, c.address);
  if (JSON.stringify(js) !== JSON.stringify(c.py)) {
    if (++bad <= 5) console.log("MISMATCH", c.run, c.id, "\n py:", JSON.stringify(c.py), "\n js:", JSON.stringify(js));
  }
}
console.log(`${cases.length - bad}/${cases.length} cases match`);
process.exit(bad ? 1 : 0);
