"""Load the taxonomy package via Arelle and dump dimension-default members
(dimension clark -> default member clark) to JSON. One-time taxonomy artifact."""
import json
import sys

from arelle import Cntlr, PackageManager, ModelManager
from arelle.RuntimeOptions import RuntimeOptions

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

pkg = r"C:\Users\177069\ClaudeLearning\boebanking400.zip"
# Use any module entry point's DTS by loading a sample instance is heavy; instead load
# a module schema directly. We load via a sample instance to get the full DTS.
sample = sys.argv[1]
out = sys.argv[2]

cntlr = Cntlr.Cntlr(logFileName="logToBuffer")
cntlr.startLogging()
PackageManager.init(cntlr)
PackageManager.addPackage(cntlr, pkg)
PackageManager.rebuildRemappings(cntlr)
PackageManager.save(cntlr)

mm = ModelManager.initialize(cntlr)
modelXbrl = mm.load(sample)

# populate dimension defaults from the DTS dimension-default relationships
from arelle import ValidateXbrlDimensions
ValidateXbrlDimensions.loadDimensionDefaults(modelXbrl)

defaults = {}
dd = getattr(modelXbrl, "qnameDimensionDefaults", {}) or {}
for dimQn, memQn in dd.items():
    defaults[f"{{{dimQn.namespaceURI}}}{dimQn.localName}"] = \
        f"{{{memQn.namespaceURI}}}{memQn.localName}"

# fallback: walk the dimension-default relationship set directly
if not defaults:
    from arelle import XbrlConst
    rels = modelXbrl.relationshipSet(XbrlConst.dimensionDefault)
    for rel in rels.modelRelationships:
        dim, mem = rel.fromModelObject, rel.toModelObject
        if dim is not None and mem is not None:
            defaults[f"{{{dim.qname.namespaceURI}}}{dim.qname.localName}"] = \
                f"{{{mem.qname.namespaceURI}}}{mem.qname.localName}"

with open(out, "w", encoding="utf-8") as fh:
    json.dump(defaults, fh, ensure_ascii=False, indent=1)
print(f"dimension defaults: {len(defaults)} -> {out}")
for k, v in list(defaults.items())[:8]:
    print(f"  {k} -> {v}")
