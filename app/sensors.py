"""Sensor metadata for the NASA C-MAPSS FD001 dataset.

We use C-MAPSS turbofan degradation data as a stand-in for gas turbine
telemetry at a power station. Names and descriptions follow the original
C-MAPSS documentation (Saxena et al., 2008).
"""

RAW_COLUMNS = ["unit", "cycle", "op1", "op2", "op3"] + [f"s{i}" for i in range(1, 22)]

SENSOR_META = {
    "s1": ("T2", "Total temperature at fan inlet", "degR"),
    "s2": ("T24", "Total temperature at LPC outlet", "degR"),
    "s3": ("T30", "Total temperature at HPC outlet", "degR"),
    "s4": ("T50", "Total temperature at LPT outlet", "degR"),
    "s5": ("P2", "Pressure at fan inlet", "psia"),
    "s6": ("P15", "Total pressure in bypass duct", "psia"),
    "s7": ("P30", "Total pressure at HPC outlet", "psia"),
    "s8": ("Nf", "Physical fan speed", "rpm"),
    "s9": ("Nc", "Physical core speed", "rpm"),
    "s10": ("epr", "Engine pressure ratio", "-"),
    "s11": ("Ps30", "Static pressure at HPC outlet", "psia"),
    "s12": ("phi", "Ratio of fuel flow to Ps30", "pps/psi"),
    "s13": ("NRf", "Corrected fan speed", "rpm"),
    "s14": ("NRc", "Corrected core speed", "rpm"),
    "s15": ("BPR", "Bypass ratio", "-"),
    "s16": ("farB", "Burner fuel-air ratio", "-"),
    "s17": ("htBleed", "Bleed enthalpy", "-"),
    "s18": ("Nf_dmd", "Demanded fan speed", "rpm"),
    "s19": ("PCNfR_dmd", "Demanded corrected fan speed", "rpm"),
    "s20": ("W31", "HPT coolant bleed", "lbm/s"),
    "s21": ("W32", "LPT coolant bleed", "lbm/s"),
}

# Sensors that are constant (or nearly) in FD001 are dropped.
FEATURES = ["s2", "s3", "s4", "s7", "s8", "s9", "s11", "s12",
            "s13", "s14", "s15", "s17", "s20", "s21"]


def label(sensor: str) -> str:
    """'s3' -> 'T30 (Total temperature at HPC outlet)'."""
    code, desc, _ = SENSOR_META[sensor]
    return f"{code} ({desc})"


def asset_name(unit: int) -> str:
    return f"GT-{int(unit):02d}"
