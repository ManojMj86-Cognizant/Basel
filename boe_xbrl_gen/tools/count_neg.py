"""Count negative numeric facts in the regenerated PRA001 (the ≥0 shippability metric)."""
from lxml import etree

BASE = r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend\.cache\packages\50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
OUT = BASE + r"\solved\_genvalid_pra001.xbrl"
X = "http://www.xbrl.org/2003/instance"

data = open(OUT, "rb").read()
data = data[3:] if data[:3] == b"\xef\xbb\xbf" else data
root = etree.fromstring(data)

numeric = neg = exactly_neg1000 = 0
for el in root:
    if el.get("contextRef") is None:
        continue
    t = (el.text or "").strip()
    try:
        v = float(t)
    except ValueError:
        continue
    numeric += 1
    if v < 0:
        neg += 1
        if v == -1000:
            exactly_neg1000 += 1

print("numeric facts :", numeric)
print("negative      :", neg)
print("  of which -1000:", exactly_neg1000)
