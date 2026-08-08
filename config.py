"""
Configuration constants for Weekly Equity Report Generator
"""

import os

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(SCRIPT_DIR, "template.docx")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")   # structured historical cache root

# Technical indicators
EMA_PERIODS = [9, 21, 50, 100, 200]

# Display names (as they appear in report)
INDEX_NAMES = [
    "NIFTY 50", "BANK NIFTY", "FINNIFTY", "NIFTYNEXT50",
    "MIDCAP SELECT", "SENSEX", "VIX"
]

SECTOR_NAMES = [
    "NIFTY AUTO", "NIFTY FMCG", "NIFTY IT", "NIFTY METAL",
    "NIFTYPHARM", "NIFTY PSE", "NIFTYPSUBANK", "NIFTYPVTBANK",
    "NIFTY REALTY", "NIFTY MEDIA", "NIFTYINDDEFENCE",
    "NIFTYMIDCAP", "NIFTYSMLCAP"
]

EMA_NAMES = ["NIFTY", "BANK NIFTY", "FINNIFTY"]

# Formatting colors
COLOR_GREEN = "00B050"
COLOR_RED = "FF0000"

# NSE allIndices live name → our display name mapping
NSE_NAME_MAP = {
    "NIFTY 50":                 "NIFTY 50",
    "NIFTY BANK":               "BANK NIFTY",
    "NIFTY FIN SERVICE":        "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "NIFTY NEXT 50":            "NIFTYNEXT50",
    "NIFTY MIDCAP SELECT":      "MIDCAP SELECT",
    "INDIA VIX":                "VIX",
    "NIFTY AUTO":               "NIFTY AUTO",
    "NIFTY FMCG":               "NIFTY FMCG",
    "NIFTY IT":                 "NIFTY IT",
    "NIFTY METAL":              "NIFTY METAL",
    "NIFTY PHARMA":             "NIFTYPHARM",
    "NIFTY PSE":                "NIFTY PSE",
    "NIFTY PSU BANK":           "NIFTYPSUBANK",
    "NIFTY PRIVATE BANK":       "NIFTYPVTBANK",
    "NIFTY REALTY":             "NIFTY REALTY",
    "NIFTY MEDIA":              "NIFTY MEDIA",
    "NIFTY INDIA DEFENCE":      "NIFTYINDDEFENCE",
    "NIFTY MIDCAP 100":         "NIFTYMIDCAP",
    "NIFTY SMALLCAP 100":       "NIFTYSMLCAP",
}

# Yahoo Finance ticker symbols (primary + fallbacks)
# Only confirmed working symbols included
YF_SYMBOLS = {
    # Main indices
    "NIFTY 50":          ["^NSEI"],
    "BANK NIFTY":        ["^NSEBANK"],
    "FINNIFTY":          ["NIFTY_FIN_SERVICE.NS", "^CNXFIN"],
    "NIFTYNEXT50":       ["^NSMIDCP"],
    "MIDCAP SELECT":     [],  # Use nselib fallback
    "SENSEX":            ["^BSESN"],
    "VIX":               ["^INDIAVIX"],

    # Sectors
    "NIFTY AUTO":        ["^CNXAUTO"],
    "NIFTY FMCG":        ["^CNXFMCG"],
    "NIFTY IT":          ["^CNXIT"],
    "NIFTY METAL":       ["^CNXMETAL"],
    "NIFTYPHARM":        ["^CNXPHARMA"],
    "NIFTY PSE":         ["^CNXPSE"],
    "NIFTYPSUBANK":      ["^CNXPSUBANK"],
    "NIFTYPVTBANK":      [],  # Use nselib fallback (NIFTY PRIVATE BANK)
    "NIFTY REALTY":      ["^CNXREALTY"],
    "NIFTY MEDIA":       ["^CNXMEDIA"],
    "NIFTYINDDEFENCE":   [],  # Use nselib fallback (NIFTY INDIA DEFENCE)
    "NIFTYMIDCAP":       [],  # Use nselib fallback (NIFTY MIDCAP 100)
    "NIFTYSMLCAP":       [],  # Use nselib fallback (NIFTY SMALLCAP 100)

    # EMA alias
    "NIFTY":             ["^NSEI"],
}

# nselib fallback mappings
NSELIB_MAP = {
    # Indices
    "FINNIFTY": "NIFTY FINANCIAL SERVICES",
    "NIFTYNEXT50": "NIFTY NEXT 50",
    "MIDCAP SELECT": "NIFTY MIDCAP SELECT",
    
    # Sectors
    "NIFTY AUTO": "NIFTY AUTO",
    "NIFTY FMCG": "NIFTY FMCG",
    "NIFTY IT": "NIFTY IT",
    "NIFTY METAL": "NIFTY METAL",
    "NIFTYPHARM": "NIFTY PHARMA",
    "NIFTY PSE": "NIFTY PSE",
    "NIFTYPSUBANK": "NIFTY PSU BANK",
    "NIFTYPVTBANK": "NIFTY PRIVATE BANK",
    "NIFTY REALTY": "NIFTY REALTY",
    "NIFTY MEDIA": "NIFTY MEDIA",
    "NIFTYINDDEFENCE": "NIFTY INDIA DEFENCE",
    "NIFTYSMLCAP": "NIFTY SMALLCAP 100",
    "NIFTYMIDCAP": "NIFTY MIDCAP 100",
}

# Bhavcopy index close map — maps display names to bhavcopy TckrSymb.
# The UndrlygPric column in the derivatives Bhavcopy holds the spot close
# for each underlying index and is available in the locally committed
# data/YYYY/YYYYMMDD/bhavcopy.csv files, making it the most reliable fallback
# on cloud environments (Streamlit Cloud) where NSE APIs are blocked.
BHAVCOPY_INDEX_MAP = {
    "NIFTY 50":      "NIFTY",
    "BANK NIFTY":    "BANKNIFTY",
    "FINNIFTY":      "FINNIFTY",
    "MIDCAP SELECT": "MIDCPNIFTY",
    "NIFTYNEXT50":   "NIFTYNXT50",
}

# Historical data fetch windows (in calendar days)
# 1200 days ≈ 830 trading days ≈ 200-week EMA requires ~400 trading days
LONG_HISTORY_DAYS = 1200  # For EMA-200 calculation
SHORT_HISTORY_DAYS = 30   # For indices without EMA requirement

# Indices requiring long history for EMA calculation
LONG_WINDOW_INDICES = {"NIFTY 50", "BANK NIFTY", "FINNIFTY"}

# Support/Resistance calculation parameters
SR_S1_FACTOR = 0.985   # Support 1: -1.5% from close
SR_R1_FACTOR = 1.015   # Resistance 1: +1.5% from close
SR_S2_FACTOR = 0.975   # Support 2: -2.5% from close
SR_R2_FACTOR = 1.025   # Resistance 2: +2.5% from close

# Rounding rules for S/R levels
SR_ROUNDING_RULES = {
    "NIFTY": 100,        # Round to nearest 100
    "BANK NIFTY": 500,   # Round to nearest 500 (reference report uses 500)
    "FINNIFTY": 100,     # Round to nearest 100
}

# Per-index S/R percentage factors
SR_FACTORS = {
    "NIFTY":      {"s1": 0.976, "s2": 0.968, "r1": 1.022, "r2": 1.031},
    "BANK NIFTY": {"s1": 0.976, "s2": 0.968, "r1": 1.022, "r2": 1.031},
    "FINNIFTY":   {"s1": 0.976, "s2": 0.968, "r1": 1.022, "r2": 1.031},
}

# Network timeouts (seconds)
NSE_TIMEOUT = 15
YF_RETRY_COUNT = 3
YF_RETRY_DELAY = 2  # seconds
YF_CALL_TIMEOUT = 15   # hard per-call timeout for a single yfinance request
YF_POOL_TIMEOUT = 90   # backstop: max time to wait for ALL parallel symbol fetches

# Report structure validation
EXPECTED_LEFT_CELL_PARAS_MIN = 10  # Minimum paragraphs in WGB section
EXPECTED_RIGHT_CELL_TABLES = 3     # Indices, Sectors, FII/DII tables
EXPECTED_TOP_LEVEL_TABLES = 5      # Total tables in document

# ═══════════════════════════════════════════════════════════════════
# PAGE 2 — TECHNICAL OUTLOOK CONFIGURATION
# ═══════════════════════════════════════════════════════════════════

# Chart generation
CHART_INDICES = {
    "NIFTY": {"data_name": "NIFTY 50", "sr_name": "NIFTY", "is_benchmark": True},
    "BANKNIFTY": {"data_name": "BANK NIFTY", "sr_name": "BANK NIFTY", "is_benchmark": False},
    "FINNIFTY": {"data_name": "FINNIFTY", "sr_name": "FINNIFTY", "is_benchmark": False},
}
CHART_WEEKS = 30  # Number of weekly candles to display

# ─── DOCX Layout Constants (measured from reference document) ───

# Section 2 (page 2) margins in EMU
PAGE2_LEFT_MARGIN = 502920
PAGE2_RIGHT_MARGIN = 411480
PAGE2_TOP_MARGIN = 795655
PAGE2_BOTTOM_MARGIN = 494030

# "TECHNICAL OUTLOOK" heading
# Style: MHeading2, spacing.before=0, font size=26 half-pts (13pt), color=#1F497D
HEADING_STYLE = "MHeading2"
HEADING_COLOR = "1F497D"
HEADING_FONT_SIZE_HALFPTS = 26  # 13pt

# Chart + Commentary table (Table 3 in reference)
# Total width: 10683 dxa, layout: fixed
# Border: single, sz=4, color=#3C9114 (green), on all sides + insideH/V
CHART_TABLE_WIDTH = 10683         # dxa
CHART_TABLE_COL0_WIDTH = 6858     # dxa — chart column
CHART_TABLE_COL1_WIDTH = 3825     # dxa — commentary column
CHART_TABLE_BORDER_COLOR = "3C9114"
CHART_TABLE_BORDER_SZ = 4         # border thickness (1/8 pt)

# Row heights (dxa) — atLeast mode; 4400 × 3 fills Page 2 evenly
CHART_TABLE_ROW_HEIGHTS = [4400, 4400, 4400]

# Chart image dimensions in EMU (English Metric Units)
# 1 inch = 914400 EMU
# Column 0 = 6858 dxa − 2×57 cell margin = 6744 dxa ≈ 4,282,440 EMU max.
# Use 4,200,000 to fill column width with minimal gap.
CHART_IMG_CX = 4200000            # width EMU  (~4.59 inches — fills chart column)
# Per-row image heights — ~2:1.3 landscape ratio (wider feel)
CHART_IMG_CY = {
    "NIFTY": 2700000,
    "BANK NIFTY": 2700000,
    "FINNIFTY": 2700000,
}

# Commentary paragraph spacing
# Heading: style MHeading2, spacing.before=0
# Bullets: style MBullet (inherits numPr from style), spacing.after=120
# Last bullet: bold text for S/R levels
COMMENTARY_BULLET_STYLE = "MBullet"
COMMENTARY_BULLET_SPACING_AFTER = 120

# ─── Contact Section ───

# "EQUITY RESEARCH TEAM" heading
# Style: Normal override, font size=26 half-pts (13pt), bold, color=#1F497D
# spacing.after=120
ERT_FONT_SIZE_HALFPTS = 26
ERT_COLOR = "1F497D"

# Contact table (no borders, width=100% / 5000 pct)
# Grid columns: 1679, 4354, 2929, 1505 (dxa)
# Cell widths must equal the grid columns — a table's tcW and tblGrid
# have to agree on the same unit/scale, or renderers size columns far
# too narrow and header text (Name/Designation/Email/Landline No.)
# overflows into the next cell. (Previously these were mistakenly set
# to a leftover percentage-split (802/2080/1399/719, summing to 5000
# ie. 100.00%) applied with w:type="dxa" — about half the real width.)
# Font size: 16 half-pts (8pt)
CONTACT_TABLE_GRID_COLS = [1679, 4354, 2929, 1505]
CONTACT_TABLE_CELL_WIDTHS = [1679, 4354, 2929, 1505]
CONTACT_TABLE_FONT_SIZE = 16  # half-pts
CONTACT_TABLE_ROW1_HEIGHT = 310  # dxa

RESEARCH_TEAM = [
    {
        "name": "Ketan Kaushik",
        "designation": "Derivative Analyst",
        "email": "ketan.kaushik@mnclgroup.com",
        "phone": "0141-4007235",
    }
]

# ─── Disclaimer ───
DISCLAIMER_TEXT = "For Disclaimer & Risk factors please click here"
COMPANY_TEXT = (
    "Monarch Networth Capital Ltd. (www.mnclgroup.com) "
    "Office: - 9th Floor, Atlanta Centre, Sonawala Lane, "
    "Opp. Udyog Bhavan, Goregaon (E), Mumbai 400 063. "
    "Tel No.: 022 62021604"
)
COMPANY_TEXT_FONT_SIZE = 13  # half-pts (6.5pt)