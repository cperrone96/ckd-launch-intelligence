"""Transparent, cross-sectional CKD indicator definitions.

These functions do not diagnose chronic kidney disease. NHANES is cross-sectional,
so it cannot establish persistence for at least three months. The primary indicator
is restricted to adults and applies the race-free CKD-EPI 2021 creatinine equation
and a spot urine albumin-to-creatinine ratio (UACR).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class CKDDefinition:
    """A documented cross-sectional CKD indicator rule.

    Serum creatinine is expressed in mg/dL, age in years, eGFR in
    mL/min/1.73 m², urine albumin in mg/L, urine creatinine in mg/dL, and
    the derived UACR in mg/g. Missing evidence is represented as unknown.
    """

    name: str
    minimum_age_years: int = 18
    egfr_threshold: float = 60.0
    uacr_threshold: float = 30.0
    include_egfr: bool = True
    include_albuminuria: bool = True

    @classmethod
    def primary(cls) -> CKDDefinition:
        """eGFR <60 OR UACR >=30 among adults, with both tests evaluable."""

        return cls(name="primary_egfr_or_albuminuria")

    @classmethod
    def egfr_only(cls) -> CKDDefinition:
        """Sensitivity definition based only on eGFR <60."""

        return cls(name="sensitivity_egfr_only", include_albuminuria=False)

    @classmethod
    def albuminuria_only(cls) -> CKDDefinition:
        """Sensitivity definition based only on UACR >=30 mg/g."""

        return cls(name="sensitivity_albuminuria_only", include_egfr=False)

    def __post_init__(self) -> None:
        if self.minimum_age_years < 18:
            raise ValueError("minimum_age_years must retain the documented adult restriction")
        if self.egfr_threshold <= 0 or self.uacr_threshold <= 0:
            raise ValueError("clinical thresholds must be positive")
        if not (self.include_egfr or self.include_albuminuria):
            raise ValueError("at least one defining laboratory measure is required")


def calculate_egfr_ckd_epi_2021(
    serum_creatinine_mg_dl: pd.Series, age_years: pd.Series, sex: pd.Series
) -> pd.Series:
    """Calculate race-free 2021 CKD-EPI creatinine eGFR.

    Equation: ``142 * min(Scr/k, 1)^alpha * max(Scr/k, 1)^-1.200 *
    0.9938^Age * 1.012 [if female]`` where k is 0.7 for females and 0.9
    for males, and alpha is -0.241 for females and -0.302 for males.
    """

    creatinine = pd.to_numeric(serum_creatinine_mg_dl, errors="coerce")
    age = pd.to_numeric(age_years, errors="coerce")
    normalized_sex = sex.astype("string").str.strip().str.casefold()
    present_sex = normalized_sex.dropna()
    unsupported = sorted(set(present_sex) - {"female", "male"})
    if unsupported:
        raise ValueError(f"sex contains unsupported values: {', '.join(unsupported)}")
    if bool((creatinine.dropna() <= 0).any()):
        raise ValueError("serum creatinine must be positive when present")
    if bool((age.dropna() < 0).any()):
        raise ValueError("age must be non-negative when present")

    female = normalized_sex.eq("female")
    female_for_equation = female.fillna(False)
    kappa = pd.Series(
        np.where(female_for_equation, 0.7, 0.9), index=creatinine.index, dtype="float64"
    )
    alpha = pd.Series(
        np.where(female_for_equation, -0.241, -0.302),
        index=creatinine.index,
        dtype="float64",
    )
    ratio = creatinine / kappa
    result = (
        142.0
        * np.minimum(ratio, 1.0) ** alpha
        * np.maximum(ratio, 1.0) ** -1.2
        * 0.9938**age
        * np.where(female_for_equation, 1.012, 1.0)
    )
    result = pd.Series(result, index=creatinine.index, dtype="float64")
    return result.where(creatinine.notna() & age.notna() & normalized_sex.notna())


def classify_ckd(frame: pd.DataFrame, definition: CKDDefinition) -> pd.Series:
    """Classify an adult cross-sectional CKD indicator using nullable booleans.

    The primary result requires both eGFR and UACR to be evaluable. Any missing
    defining laboratory measure produces unknown, never a false/zero outcome.
    Known pregnant adults (NHANES RIDEXPRG code 1) are excluded from the standard
    surveillance domain. Code 2 (not pregnant), code 3 (cannot ascertain), and
    missing/not-applicable values remain eligible and are described transparently.
    Single-marker sensitivity definitions require only their named marker.
    """

    required = {"age_years", "sex"}
    if definition.include_egfr:
        required.add("serum_creatinine_mg_dl")
    if definition.include_albuminuria:
        required.update({"urine_albumin_mg_l", "urine_creatinine_mg_dl"})
    missing_columns = sorted(required - set(frame.columns))
    if missing_columns:
        raise ValueError(f"missing CKD definition columns: {', '.join(missing_columns)}")

    age = pd.to_numeric(frame["age_years"], errors="coerce")
    adult = age.ge(definition.minimum_age_years)
    known_pregnant = pd.Series(False, index=frame.index)
    if "pregnancy_status_code" in frame:
        pregnancy = pd.to_numeric(frame["pregnancy_status_code"], errors="coerce")
        invalid_pregnancy = pregnancy.dropna().loc[~pregnancy.dropna().isin([1, 2, 3])]
        if not invalid_pregnancy.empty:
            raise ValueError("pregnancy_status_code must be NHANES code 1, 2, 3, or missing")
        known_pregnant = pregnancy.eq(1).fillna(False)
    eligible = adult & ~known_pregnant
    result = pd.Series(pd.NA, index=frame.index, dtype="boolean", name=definition.name)
    tests: list[tuple[pd.Series, pd.Series]] = []

    if definition.include_egfr:
        egfr = calculate_egfr_ckd_epi_2021(
            frame["serum_creatinine_mg_dl"], frame["age_years"], frame["sex"]
        )
        egfr_available = eligible & egfr.notna()
        tests.append((egfr_available, egfr.lt(definition.egfr_threshold)))

    if definition.include_albuminuria:
        albumin = pd.to_numeric(frame["urine_albumin_mg_l"], errors="coerce")
        urine_creatinine = pd.to_numeric(frame["urine_creatinine_mg_dl"], errors="coerce")
        if bool((albumin.dropna() < 0).any()):
            raise ValueError("urine albumin must be non-negative when present")
        if bool((urine_creatinine.dropna() <= 0).any()):
            raise ValueError("urine creatinine must be positive when present")
        component_available = albumin.notna() & urine_creatinine.notna()
        scaled_albumin = 100.0 * albumin
        scaled_threshold = definition.uacr_threshold * urine_creatinine
        component_positive = scaled_albumin.ge(scaled_threshold) | pd.Series(
            np.isclose(
                scaled_albumin,
                scaled_threshold,
                rtol=1e-12,
                atol=1e-12,
                equal_nan=False,
            ),
            index=frame.index,
        )
        if "uacr_mg_g" in frame:
            uacr_mg_g = pd.to_numeric(frame["uacr_mg_g"], errors="coerce")
            if bool((uacr_mg_g.dropna() < 0).any()):
                raise ValueError("official UACR must be non-negative when present")
            use_fallback = uacr_mg_g.isna()
            uacr_available = eligible & (uacr_mg_g.notna() | component_available)
            albuminuria_positive = uacr_mg_g.ge(definition.uacr_threshold).fillna(False) | (
                use_fallback & component_positive
            )
        else:
            uacr_available = eligible & component_available
            albuminuria_positive = component_positive
        tests.append((uacr_available, albuminuria_positive))

    any_positive = pd.Series(False, index=frame.index)
    all_available = pd.Series(True, index=frame.index)
    for available, positive in tests:
        any_positive |= available & positive
        all_available &= available
    result.loc[eligible & all_available & any_positive] = True
    result.loc[eligible & all_available & ~any_positive] = False
    return result
