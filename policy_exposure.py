"""
Static sector/industry -> policy-lever mapping. yfinance's sector/industry
fields (already used throughout fundamentals.py) are cross-referenced here
against curated policy levers particular to that industry, so a macro/
regulatory news match can be judged "relevant to this company" instead of
a blanket macro net over every stock regardless of what it actually does.

Curated by hand from general knowledge of Indian regulatory bodies/policy
levers per sector -- this is a living list, not a one-time snapshot;
sectors move in and out of policy focus (new PLI schemes, new regulators,
new subsidy regimes) over time, and coverage here is necessarily partial.
The "keywords" per entry are also added to config.py's MACRO_KEYWORDS so
matching news actually gets captured and stored, not just listed here as
a lever with nothing behind it.
"""

# Keyed on a case-insensitive substring match against yfinance's `industry`
# field -- more specific than sector, so checked first.
INDUSTRY_POLICY_LEVERS = {
    "bank": {
        "levers": ["RBI repo rate/monetary policy", "NPA/asset quality norms", "priority sector lending rules", "capital adequacy (Basel) norms"],
        "keywords": ["repo rate", "monetary policy", "priority sector lending", "basel", "casa"],
    },
    "credit services": {
        "levers": ["RBI NBFC regulations", "co-lending norms", "repo rate", "liquidity/refinancing windows"],
        "keywords": ["nbfc regulation", "co-lending", "repo rate"],
    },
    "insurance": {
        "levers": ["IRDAI regulations", "FDI limit in insurance", "surrender value/commission norms"],
        "keywords": ["irdai", "fdi limit in insurance"],
    },
    "capital markets": {
        "levers": ["SEBI mutual fund/brokerage regulations", "expense ratio caps"],
        "keywords": ["sebi circular", "sebi order", "expense ratio cap"],
    },
    "drug manufacturers": {
        "levers": ["USFDA inspections/approvals", "NPPA drug price caps", "PLI scheme for pharma"],
        "keywords": ["usfda", "nppa", "drug price cap", "pli scheme", "warning letter", "import alert"],
    },
    "diagnostics": {
        "levers": ["NPPA/health ministry pricing caps", "clinical establishment regulations"],
        "keywords": ["nppa", "clinical establishment regulation"],
    },
    "medical": {
        "levers": ["NPPA device price caps", "CDSCO approvals"],
        "keywords": ["nppa", "cdsco"],
    },
    "aerospace & defense": {
        "levers": ["defense budget allocation", "Atmanirbhar Bharat/indigenization policy", "defense export policy", "DAC order approvals"],
        "keywords": ["defense budget", "atmanirbhar", "dac approval", "defense export policy"],
    },
    "oil & gas": {
        "levers": ["crude oil price/subsidy policy", "windfall tax", "fuel pricing deregulation", "LPG/PDS subsidy"],
        "keywords": ["windfall tax", "fuel subsidy", "opec"],
    },
    "utilities": {
        "levers": ["state electricity regulatory commission tariff orders", "power purchase agreements", "renewable purchase obligation (RPO)", "coal linkage policy"],
        "keywords": ["tariff order", "electricity regulatory commission", "renewable purchase obligation", "coal linkage"],
    },
    "telecom services": {
        "levers": ["TRAI tariff/interconnect regulations", "spectrum auction/pricing", "AGR dues ruling", "PLI for telecom equipment"],
        "keywords": ["trai", "spectrum auction", "agr dues", "adjusted gross revenue"],
    },
    "real estate": {
        "levers": ["RERA regulations", "home loan interest rates", "stamp duty changes", "affordable housing scheme policy"],
        "keywords": ["rera", "stamp duty", "affordable housing scheme"],
    },
    "steel": {
        "levers": ["import/export duty on steel", "anti-dumping duty", "PLI for specialty steel", "iron ore export policy"],
        "keywords": ["anti-dumping duty", "iron ore export policy", "steel import duty", "steel export duty"],
    },
    "tobacco": {
        "levers": ["GST/excise duty on tobacco", "health ministry packaging regulations"],
        "keywords": ["excise duty", "health warning regulation"],
    },
    "airlines": {
        "levers": ["ATF (jet fuel) pricing/duty", "UDAN regional connectivity scheme", "airport slot/landing fee regulation"],
        "keywords": ["atf price", "udan scheme", "airport landing fee"],
    },
    "agricultural inputs": {
        "levers": ["fertilizer subsidy policy", "MSP (minimum support price) announcements"],
        "keywords": ["fertilizer subsidy", "minimum support price"],
    },
    "farm products": {
        "levers": ["MSP announcements", "export/import duty on agri commodities"],
        "keywords": ["minimum support price", "agri export duty", "agri import duty"],
    },
}

# Fallback when no industry-level entry matches -- broader, sector-level.
SECTOR_POLICY_LEVERS = {
    "Financial Services": {"levers": ["RBI monetary policy", "SEBI regulations"], "keywords": ["repo rate", "sebi circular"]},
    "Energy": {"levers": ["crude oil pricing policy", "fuel subsidy"], "keywords": ["windfall tax", "fuel subsidy"]},
    "Utilities": {"levers": ["state tariff regulation"], "keywords": ["tariff order"]},
    "Healthcare": {"levers": ["USFDA/drug pricing regulation"], "keywords": ["usfda", "nppa"]},
    "Communication Services": {"levers": ["TRAI/spectrum policy"], "keywords": ["trai", "spectrum auction"]},
    "Real Estate": {"levers": ["RERA/interest rate policy"], "keywords": ["rera"]},
}


def get_policy_exposure(sector, industry):
    """
    Returns {"levers": [...], "keywords": [...]} of policy exposure
    relevant to this sector/industry, or an empty dict if nothing curated
    matches. Industry match (more specific) wins over the sector fallback.
    """
    industry_lower = (industry or "").lower()
    for key, exposure in INDUSTRY_POLICY_LEVERS.items():
        if key in industry_lower:
            return exposure
    return SECTOR_POLICY_LEVERS.get(sector, {})


ALL_POLICY_KEYWORDS = sorted({
    kw
    for exposure in list(INDUSTRY_POLICY_LEVERS.values()) + list(SECTOR_POLICY_LEVERS.values())
    for kw in exposure["keywords"]
})
