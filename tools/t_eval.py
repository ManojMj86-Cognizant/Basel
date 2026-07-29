import sys
sys.path.insert(0, r"C:\Users\177069\ClaudeLearning\boe_xbrl_gen\src")
import expr as E

t = "iaf:max((0,iaf:numeric-subtract($v1,$v2),iaf:numeric-subtract($v2,$v1)))"
ast = E.parse(t)
print("AST:", ast)
print("seq eval:", E.evaluate(("seq", [("num", 0.0)]), {}))
print("sub eval:", E.evaluate(E.parse("iaf:numeric-subtract($v1,$v2)"), {"v1": 9913000.0, "v2": 1949000.0}))
print("max eval:", E.evaluate(ast, {"v1": 9913000.0, "v2": 1949000.0}))
