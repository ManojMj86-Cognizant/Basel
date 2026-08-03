"""Resolve the MCY hierarchy question for the extractor: what dimension/domain is MCY, what do members
x195/x311/x100/x310 mean (is x195 a 'total'?), and is a parent->child member relationship extractable from
the taxonomy? Prints member labels (from model.json) + searches domain definition linkbases for domain-member
arcs. Run from boe_xbrl_gen/ with PYTHONIOENCODING=utf-8."""
import sys, json, os, glob, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")

BASE = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
EXT = f"{BASE}/Banking_4.0.0"
m = json.load(open(f"{BASE}/model.json", encoding="utf-8"))

# 1) which domain does dimension MCY use? + member labels
dims = m.get("dimensions", {})
print("=== MCY dimension entry ===")
if isinstance(dims, dict):
    for k, v in dims.items():
        if k == "MCY" or (isinstance(k, str) and k.endswith(":MCY")) or "MCY" in str(k):
            print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:300]}")
dimmem = m.get("dim_members", {})
mcy_key = next((k for k in dimmem if k == "MCY" or str(k).endswith("MCY")), None)
print(f"\n=== dim_members['{mcy_key}'] first 8 ===")
if mcy_key:
    for mm in (dimmem[mcy_key][:8] if isinstance(dimmem[mcy_key], list) else []):
        print(f"  {mm}")

# 2) label lookup for the specific members across all domains
want = {"x195", "x311", "x100", "x310", "x156", "x246", "x309"}
print("\n=== labels for the members seen in b0736/b0872 (any domain) ===")
for dom, mems in m.get("members", {}).items():
    for mem in (mems if isinstance(mems, list) else []):
        if mem.get("code") in want:
            print(f"  {dom}:{mem.get('code'):>6}  {mem.get('label','')[:80]}")

# 3) search domain definition linkbases for domain-member / hierarchy arcs
print("\n=== domain-member arc hunt (dict/dom .xml linkbases) ===")
pats = ("domain-member", "domainMember", "dimension-domain", "all", "hypercube-dimension")
files = glob.glob(f"{EXT}/**/dict/dom/**/*.xml", recursive=True)[:2000]
hier_files = []
for f in files:
    try:
        head = open(f, encoding="utf-8", errors="replace").read(4000)
    except OSError:
        continue
    if "definitionArc" in head or "domain-member" in head:
        hier_files.append(f)
print(f"  candidate domain linkbase files with definitionArc/domain-member: {len(hier_files)}")
for f in hier_files[:6]:
    print(f"   {os.path.relpath(f, EXT)}")
# show arcroles present in one
if hier_files:
    txt = open(hier_files[0], encoding="utf-8", errors="replace").read()
    roles = sorted(set(re.findall(r'arcrole="([^"]+)"', txt)))
    print(f"\n  arcroles in {os.path.basename(hier_files[0])}:")
    for r in roles[:12]:
        print(f"     {r}")
    arcs = re.findall(r'<[\w:]*definitionArc[^>]*>', txt)
    print(f"  #definitionArc elements: {len(arcs)}; sample: {arcs[0][:200] if arcs else 'none'}")
