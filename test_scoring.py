"""
Calibration fixtures for the Access Score model (scorer v2.2).

No gold Access Score exists, so these pin the model's anchor semantics:

- 50 is the NEUTRAL / unknown baseline — an all-"NA" (nothing extracted)
  policy stays at 50 (NA never moves the score; guards the v2.0 defect where
  missing data was scored as "no restriction");
- a policy that VERIFIES it is unrestricted ("No" / empty list / confirmed 0)
  earns a small +2-per-axis confirmed-open credit, landing slightly above 50
  (distinguishes verified-open from unextracted);
- a maximally restrictive policy bottoms near 0;
- the most-permissive extractable policy (confirmed-open + age younger than FDA
  + TB waived) reaches the ceiling (~68) — still below the 75 "Preferred" band,
  which is unreachable from the extracted parameters (see ADR-016).

It also locks in the parsing hardening: an upper-bound age ("<18") earns no age
deduction, and reauth casing ("yes") still deducts.

Run directly:  python test_scoring.py
"""

from access_quality_scorer import AccessQualityScorer


def _score(scorer, brand, bs, gs, photo, spec, reauth, ql, tb, age):
    return scorer.calculate_score(
        brand,
        {"brand_steps": bs, "generic_steps": gs, "phototherapy_required": photo},
        {"reauthorization_required": reauth},
        {"quantity_limits": ql},
        {"specialist_types": spec, "tb_test_required": tb},
        {"value": age},
    )["access_quality_score"]


def test_anchor_calibration():
    s = AccessQualityScorer()

    # F1 — all-"NA" (nothing extracted) must stay at the 50 neutral baseline.
    # (Regression guard for the v2.0 'NA == no restriction' defect.)
    all_na = _score(s, "STELARA", "NA", "NA", "NA", "NA", "NA", "NA", "NA", "NA")
    assert 48 <= all_na <= 52, f"all-NA should stay ~50 (neutral), got {all_na}"

    # F2 — confirmed-open at FDA terms (verified no restrictions, TB as FDA
    # expects, age at FDA threshold) → slightly above 50 via the +2 credits,
    # still in the FDA-Parity band.
    confirmed_open = _score(s, "STELARA", 0, 0, "No", [], "No", [], "Yes", ">=6")
    assert 55 <= confirmed_open <= 70, f"confirmed-open should be ~60, got {confirmed_open}"

    # F3 — maximally restrictive → near 0.
    max_restrictive = _score(
        s, "STELARA", 3, 2, "Yes", ["dermatologist"], "Yes", ["1/28d"], "Yes", ">=30"
    )
    assert max_restrictive <= 10, f"max-restrictive should be <=10, got {max_restrictive}"

    # F4 — most-permissive extractable: confirmed-open + younger age + TB waived.
    # Reaches the ceiling (~68): >= 50 but still < 75 (Preferred unreachable).
    most_permissive = _score(s, "STELARA", 0, 0, "No", [], "No", [], "No", ">=4")
    assert most_permissive >= 50, f"most-permissive should be >=50, got {most_permissive}"
    assert most_permissive < 75, f"75 is unreachable from extracted params, got {most_permissive}"

    # F5 — confirmed-open must score ABOVE an all-"NA" policy (verified-open is
    # distinguishable from unextracted).
    assert confirmed_open > all_na, "confirmed-open should beat all-NA"

    # F6 — parsing hardening: an upper-bound age ("<18") earns no age deduction,
    # so an otherwise-unextracted ENBREL row stays at the 50 baseline.
    age_upper = _score(s, "ENBREL", "NA", "NA", "NA", "NA", "NA", "NA", "NA", "<18")
    assert age_upper == 50, f"'<18' upper bound should not deduct; got {age_upper}"

    # F7 — reauth casing: lowercase "yes" must still trigger the -5 deduction.
    reauth_lower = _score(s, "STELARA", "NA", "NA", "NA", "NA", "yes", "NA", "NA", "NA")
    assert reauth_lower == 45, f"lowercase reauth 'yes' should deduct -5; got {reauth_lower}"

    return all_na, confirmed_open, max_restrictive, most_permissive


if __name__ == "__main__":
    na, co, mx, mp = test_anchor_calibration()
    print(
        f"PASS — all-NA={na} (~50), confirmed-open={co} (~60), "
        f"max={mx} (<=10), most-permissive={mp} (>=50,<75)"
    )
