"""
Variable -> fact resolver with implicit filtering.

Given a parsed Rule and an Instance, produce a list of BINDINGS. Each binding is one
"evaluation group": a fixed assignment of the dimensions the rule does NOT pin (the
uncovered aspects), within which each rule variable maps to the fact(s) that match its
explicit filters. This mirrors XBRL implicit filtering: variables in an assertion must
agree on aspects none of them filters; the relationship then holds per group.

A binding: {varname: [Fact, ...]}. Non-sequence variables expect 0 or 1 fact (fallback
applies when 0). Sequence variables collect all matching facts in the group.
"""
from __future__ import annotations

from collections import defaultdict


def _concepts_for(rule, var):
    return (rule.common.concepts | var.selector.concepts) or None


def _dim_filters_for(rule, var):
    """Merged explicit-dim filters for a variable: dim -> set(allowed members)."""
    out = {}
    for d, m in rule.common.dims.items():
        out[d] = set(m)
    for d, m in var.selector.dims.items():
        out[d] = (out.get(d, set()) | set(m)) if d in out else set(m)
    return out


def _member_of(fact, d, defaults):
    """Effective explicit-dimension member of a fact: the context member, or the
    dimension default when the context omits the dimension (XBRL default semantics)."""
    if d in fact.dims:
        return fact.dims[d]
    return defaults.get(d)


def _fact_matches(fact, concepts, dim_filters, defaults):
    if concepts is not None and fact.concept not in concepts:
        return False
    for d, allowed in dim_filters.items():
        if not allowed:                      # filter present but no members -> any member
            if d not in fact.dims and d not in fact.typed:
                return False
            continue
        if _member_of(fact, d, defaults) not in allowed:
            return False
    return True


def bind(rule, instance, defaults=None):
    """Return list of bindings (dicts varname -> [facts]) honoring implicit filtering.

    Discriminating aspects (excluded from grouping) are ONLY the dimensions that appear
    in a per-VARIABLE selector — those distinguish v0 from v1. Common (variable-set)
    dimensions stay as grouping aspects so the relationship is checked once per value of
    them (e.g. once per REF member), mirroring Arelle's implicit filtering.
    """
    defaults = defaults or {}
    discriminating = set()
    for v in rule.variables.values():
        discriminating |= set(v.selector.dims) | set(v.selector.typed)

    # candidate facts per variable — restrict to the concept index first (scale: avoids
    # scanning all 60k+ facts per variable; almost every rule pins a metric concept).
    var_candidates = {}
    for name, v in rule.variables.items():
        concepts = _concepts_for(rule, v)
        dim_filters = _dim_filters_for(rule, v)
        if concepts:
            pool = []
            for c in concepts:
                pool.extend(instance.by_concept.get(c, ()))
        else:
            pool = instance.facts
        var_candidates[name] = [f for f in pool
                                if _fact_matches(f, concepts, dim_filters, defaults)]

    # group key = aspects NOT discriminating between variables (common dims + any other
    # context dims), with omitted dims normalized to their default member, + period.
    def group_key(fact):
        unc = tuple(sorted((d, m) for d, m in fact.dims.items()
                           if d not in discriminating))
        unct = tuple(sorted((d, str(t)) for d, t in fact.typed.items()
                            if d not in discriminating))
        per = instance.contexts.get(fact.ctxref, {}).get("period")
        return (unc, unct, per)

    groups = defaultdict(lambda: defaultdict(list))
    for name, facts in var_candidates.items():
        for f in facts:
            groups[group_key(f)][name].append(f)

    bindings = []
    for gkey, varmap in groups.items():
        # only keep groups that have at least the primary variable(s) present
        bindings.append({"key": gkey, "vars": {n: varmap.get(n, []) for n in rule.variables}})
    return bindings
