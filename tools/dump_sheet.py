import sys
import openpyxl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path, sheet = sys.argv[1], sys.argv[2]
maxr = int(sys.argv[3]) if len(sys.argv) > 3 else 40
maxc = int(sys.argv[4]) if len(sys.argv) > 4 else 14
wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
ws = wb[sheet]
print(f"SHEET {sheet}  merged={len(ws.merged_cells.ranges)} ranges")
ncomments = 0
for i, row in enumerate(ws.iter_rows(min_row=1, max_row=maxr, max_col=maxc)):
    out = []
    for c in row:
        v = "" if c.value is None else str(c.value).replace("\n", " ")
        if c.comment:
            ncomments += 1
            v += f"  <<CMT:{c.comment.text[:120].strip()}>>"
        out.append(f"{c.coordinate}={v}" if v else "")
    line = " | ".join(x for x in out if x)
    if line:
        print(f"r{i+1}: {line}")
print(f"\nTOTAL comments in scanned area: {ncomments}")
