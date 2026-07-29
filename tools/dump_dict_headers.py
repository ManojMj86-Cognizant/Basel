import sys
import openpyxl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path = sys.argv[1]
sheets = sys.argv[2].split(",")
nrows = int(sys.argv[3]) if len(sys.argv) > 3 else 4
wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
for sh in sheets:
    ws = wb[sh]
    print("=" * 90)
    print(f"SHEET: {sh}")
    print("=" * 90)
    for i, row in enumerate(ws.iter_rows(min_row=1, max_row=nrows, values_only=True)):
        cells = [("" if c is None else str(c))[:32] for c in row]
        # trim trailing empties
        while cells and cells[-1] == "":
            cells.pop()
        print(f"r{i+1} ({len(cells)} cols): " + " | ".join(f"[{chr(65+j) if j<26 else 'A'+chr(65+j-26)}]{v}" for j, v in enumerate(cells)))
