import json
import sys

sp = sys.argv[1]
a = json.load(open(sp + r"\out_orig.json"))
b = json.load(open(sp + r"\out_new.json"))
print("routes identical:", a["routes"] == b["routes"], f"({len(a['routes'])} combos)")
diffs = [(x, y) for x, y in zip(a["results"], b["results"]) if x != y]
print(f"{len(a['results'])} requests compared, {len(diffs)} differ")
for x, y in diffs:
    print("-", x["label"])
    print("    orig:", x["status"], json.dumps(x["body"])[:300])
    print("    new :", y["status"], json.dumps(y["body"])[:300])


def same(prefix):
    xs = [(x, y) for x, y in zip(a["results"], b["results"]) if x["label"].startswith(prefix)]
    return sum(1 for x, y in xs if x == y), len(xs)


for p in ("patch_user", "self_", "worker_promote", "dashboard", "create_", "assign", "entry", "report"):
    print(p, "identical/total:", same(p))
