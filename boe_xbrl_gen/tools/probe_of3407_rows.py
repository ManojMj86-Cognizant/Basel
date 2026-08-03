"""Probe: what distinguishes OF34.07 rows r0010/r0040/r0180 in the table linkbase? (why res.resolve conflates
them). Prints each row position's concept + dims + rc-code so we can see the row-distinguishing aspect the
full-signature resolver must capture."""
import sys, os
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from src import dim_drs
import table_model

EXT = "studio/backend/.cache/packages/50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181/Banking_4.0.0"
rend = [t["path"] for t in table_model.list_tables(EXT) if t["code"].upper() == "OF34.07.01.01"][0]
print("rend:", os.path.relpath(rend, EXT))
p = table_model.parse_table(rend); rc = table_model.rc_codes(rend)
ax = p.get("axis_positions", {})
print("axes sizes:", {k: len(v) for k, v in ax.items()})
print("--- y-axis (row) positions ---")
for pos in ax.get("y", []):
    code = rc.get(pos.get("node"))
    if code in ("0010", "0015", "0025", "0040", "0050", "0070", "0180"):
        dd = {dim_drs.local(k): dim_drs.local(v) for k, v in pos.get("dims", {}).items()}
        print(f"  r{code}: concept={dim_drs.local(pos.get('concept') or '?')}  dims={dd}")
print("--- x-axis (col) positions ---")
for pos in ax.get("x", []):
    code = rc.get(pos.get("node"))
    if code in ("0010", "0030", "0060"):
        dd = {dim_drs.local(k): dim_drs.local(v) for k, v in pos.get("dims", {}).items()}
        print(f"  c{code}: concept={dim_drs.local(pos.get('concept') or '?')}  dims={dd}")
