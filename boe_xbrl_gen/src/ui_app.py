r"""
Local Streamlit UI for the BoE Banking XBRL generator.

Run:  streamlit run src\ui_app.py
(or:  python -m streamlit run src\ui_app.py)

Tabs:
  1. Analyze  — point at the release folders, list every template and the validation
                rules relevant to each; drill into a template's datapoints + rules.
  2. Generate — pick a module, generate a random-valued instance, solve the business
                rules, validate with Arelle, show the violation count, download the file.

Inputs default to the local extracted release folders; override the paths if needed.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(SRC))
import analyzer
import generate as gen_mod
import solve as solve_mod
import solve_all
import solve_loop
import sweep
from instance import Instance

ROOT = r"C:\Users\177069\ClaudeLearning"
DEF_ANNOTATED = fr"{ROOT}\boebankingtaxonomydpmv400"
DEF_VALIDATIONS = fr"{ROOT}\boebankingtaxonomyvalidationsv400"
DEF_PKG = fr"{ROOT}\boebanking400.zip"
DEF_SAMPLES = fr"{ROOT}\boebankingtaxonomysampleinstancesv400"
DEF_MODEL = fr"{ROOT}\boe_xbrl_gen\model\dpm_model.json"
DEF_DEFAULTS = fr"{ROOT}\boe_xbrl_gen\model\dim_defaults.json"
OUT = fr"{ROOT}\boe_xbrl_gen\out\ui"

st.set_page_config(page_title="BoE Banking XBRL Generator", layout="wide")


@st.cache_data(show_spinner="Analyzing package (templates + rules)…")
def run_analyze(annotated_dir, validations_dir):
    return analyzer.analyze(annotated_dir, validations_dir)


@st.cache_data(show_spinner="Reading template datapoints…")
def get_datapoints(annotated_dir, workbook, sheet):
    return analyzer.template_datapoints(annotated_dir, workbook, sheet)


# ------------------------------------------------------------------ sidebar inputs
st.sidebar.header("Inputs")
annotated_dir = st.sidebar.text_input("DPM annotated templates folder", DEF_ANNOTATED)
validations_dir = st.sidebar.text_input("Validations folder", DEF_VALIDATIONS)
pkg = st.sidebar.text_input("Taxonomy package (.zip)", DEF_PKG)
samples_dir = st.sidebar.text_input("Sample instances folder", DEF_SAMPLES)

st.title("Bank of England Banking XBRL — Generator & Analyzer (v4.0.0)")

tab_analyze, tab_generate = st.tabs(["🔍 Analyze package", "⚙️ Generate & validate"])

# =================================================================== ANALYZE tab
with tab_analyze:
    if st.button("Analyze package", type="primary"):
        st.session_state["analysis"] = run_analyze(annotated_dir, validations_dir)

    analysis = st.session_state.get("analysis")
    if analysis:
        templates = analysis["templates"]
        rules = analysis["rules"]
        df = pd.DataFrame([
            {"template": c, "title": t["title"][:70], "rules": t["n_rules"],
             "classes": ", ".join(f"{k}:{v}" for k, v in t["rule_classes"].items())}
            for c, t in templates.items()
        ]).sort_values("template")

        st.subheader(f"{len(templates)} templates · {len(rules)} rules")
        query = st.text_input("Filter templates (code or title contains)…", "")
        view = df[df.apply(lambda r: query.lower() in (r["template"] + " " + r["title"]).lower(), axis=1)] if query else df
        st.dataframe(view, use_container_width=True, height=300, hide_index=True)

        sel = st.selectbox("Select a template to inspect", view["template"].tolist())
        if sel:
            t = templates[sel]
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Datapoints — {sel}**")
                try:
                    dp = get_datapoints(annotated_dir, t["workbook"], sel)
                    dprows = [{"row": r["row"], "metric": r["metric"],
                               **{k.split(':')[-1]: v for k, v in r["members"].items()}}
                              for r in dp["rows"]]
                    st.caption(f"{dp['n_rows']} rows · dimensions: {', '.join(dp['dimensions'][:12])}")
                    st.dataframe(pd.DataFrame(dprows), use_container_width=True, height=360, hide_index=True)
                except Exception as e:
                    st.warning(f"Could not read datapoints: {e}")
            with c2:
                st.markdown(f"**Relevant validation rules — {t['n_rules']}**")
                rr = [{"rule": rc, "class": rules[rc]["klass"],
                       "expression": rules[rc]["expr"][:160]} for rc in t["rule_codes"]]
                st.dataframe(pd.DataFrame(rr), use_container_width=True, height=360, hide_index=True)
    else:
        st.info("Set the folders in the sidebar, then click **Analyze package**.")

# ================================================================== GENERATE tab
with tab_generate:
    st.caption("Generates a random-valued instance, solves the business rules, and "
               "validates with Arelle. (Currently sample-backed; sample-free generation "
               "is being added — Phase 3.)")
    samples = sorted(Path(samples_dir).glob("*.xbrl")) if Path(samples_dir).exists() else []
    labels = {sweep.module_of(p.name): p for p in samples}
    colA, colB, colC = st.columns(3)
    module = colA.selectbox("Module", sorted(labels.keys()))
    seed = colB.number_input("Random seed", value=1, step=1)
    rounds = colC.number_input("Solver rounds", value=10, step=1)
    do_validate = st.checkbox("Validate with Arelle after solving (slow for big modules)", value=True)

    if st.button("Generate", type="primary") and module:
        sample = labels[module]
        Path(OUT).mkdir(parents=True, exist_ok=True)
        gen_path = f"{OUT}\\{module}.gen.xbrl"
        out_path = f"{OUT}\\{module}.xbrl"
        val_dir, fw = sweep.val_dir_for(str(sample))
        with st.status(f"Generating {module} [{fw}]…", expanded=True) as status:
            st.write("Cloning sample + randomizing values…")
            model = gen_mod.load_model(DEF_MODEL)
            gstats = gen_mod.generate(str(sample), gen_path, model, seed=int(seed))
            st.write(f"Generated {gstats['facts']} facts.")
            st.write("Parsing framework rules…")
            cache = f"{OUT}\\rules_{fw}.pkl"
            rules = solve_all.parse_all_rules(str(val_dir), cache=cache) if val_dir else []
            st.write(f"Loaded {len(rules)} rules. Solving…")
            defaults = json.loads(Path(DEF_DEFAULTS).read_text(encoding="utf-8"))
            inst = Instance(gen_path)
            sstats = solve_mod.solve(inst, rules, defaults, random.Random(int(seed)), rounds=int(rounds))
            inst.write(out_path)
            st.write(f"Solve: {sstats}")
            viol = None
            if do_validate:
                st.write("Validating with Arelle (this can take minutes)…")
                vlog = f"{OUT}\\{module}.validate.log"
                t0 = time.time()
                solve_loop.run_arelle(out_path, pkg, vlog)
                viol = len(solve_loop.parse_violations(vlog))
                st.write(f"Validation done in {time.time()-t0:.0f}s.")
            status.update(label=f"{module} done", state="complete")

        if viol is not None:
            (st.success if viol == 0 else st.warning)(f"Business-rule violations: {viol}")
        st.write("Solve stats:", sstats)
        data = Path(out_path).read_bytes()
        st.download_button("Download instance", data, file_name=f"{module}.xbrl",
                           mime="application/xml")
