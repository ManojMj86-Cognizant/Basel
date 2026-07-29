import time, sys, os
BACKEND = r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\studio\backend"
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)
from app import genvalid_store as gv

PKG = "50c2f2d9c248d453b11fea67dbc6070113bd182d099a4b271b5299b38ea3e181"
gv._JOBS[PKG] = {"status": "solving", "t0": time.time(), "entryPoint": "pra001"}
t0 = time.time()
gv._run(PKG, {}, {"lei": "ABCDEFGHIJ0123456789", "date": "2026-02-28"}, entry_point="pra001")
j = gv._JOBS[PKG]
print("=== regen done in", round(time.time() - t0, 1), "s ===")
print("status     :", j.get("status"))
print("ruleDriven :", j.get("ruleDriven"))
print("crosstable :", j.get("crosstable"), "overrode:", j.get("crosstableOverrode"), "err:", j.get("crosstableError"))
print("constSum   :", j.get("constSum"), "err:", j.get("constSumError"))
print("openLink   :", j.get("openLink"), "err:", j.get("openLinkError"))
print("nonnegSolve:", j.get("nonnegSolve"), "err:", j.get("nonnegError"))
print("openRows   :", j.get("openRowsPopulated"), "err:", j.get("openRowsError"))
print("isNullRem  :", j.get("isNullRemoved"))
print("error      :", j.get("error"))
res = j.get("result") or {}
for inst in (res.get("instances") or []):
    print("instance   :", inst.get("name"), "facts=", inst.get("facts"))
