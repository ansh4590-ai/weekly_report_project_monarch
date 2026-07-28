"""
Weekly Equity Report Generator — Streamlit UI
==============================================================
Monarch Networth Capital

Run with:  streamlit run streamlit_app.py

Workflow
--------
1. Enter the report's end Sunday date.
2. Click "Fetch Market Data" — runs all automated data fetching (indices,
   sectors, EMA, FII/DII, constituents, global markets, derivatives).
3. Review / edit the auto-calculated Support & Resistance levels for
   NIFTY, BANK NIFTY, and FINNIFTY.
4. Click "Generate Weekly Report" — builds the narrative, charts, and
   fills the .docx template.
5. Download the finished report.

Manual inputs:  Date (End Sunday) and S/R overrides only.
FII/DII:        Fully automated — cache-first, live-scrape fallback.
Derivatives:    Fully automated — BhavCopy, then live option chain fallback.
"""

import os
import sys
import tempfile
from datetime import date, timedelta

import pandas as pd
import streamlit as st

# ── Ensure local imports work regardless of CWD ──────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TEMPLATE_PATH, SR_ROUNDING_RULES
from validation import validate_end_sunday, get_friday_dates
from data_sources import (
    get_fii_dii_data,
    fetch_constituents,
    fetch_global_markets,
    parse_bhavcopy_derivatives,
    fetch_option_chain_live,
)
import chart_generator
from weekly_equity_report import (
    fetch_all_market_data,
    build_narrative,
    fill_docx_document,
)


# ═════════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION
# ═════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Weekly Equity Report · Monarch Networth Capital",
    page_icon="📈",
    layout="centered",
)


# ═════════════════════════════════════════════════════════════════════
# SESSION STATE — all keys initialised once, never lost across reruns
# ═════════════════════════════════════════════════════════════════════

_DEFAULTS = {
    "mkt_data":         None,
    "fii_dii":          None,
    "fii_dii_daily":    None,   # per-day DataFrame from get_fii_dii_data()
    "constituents":     None,
    "global_mkts":      None,
    "derivatives_data": None,
    "start_date":       None,
    "end_date":         None,
    "report_path":      None,
    "pdf_path":         None,   # PDF conversion output (None if unavailable)
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ═════════════════════════════════════════════════════════════════════
# SILENT AUTO-CAPTURE
#
# Fires once per browser session, the moment the page loads.
# On weekdays it calls get_fii_dii_data(yesterday, today) which
# will scrape NSE live if today isn't already cached.
# Silently no-ops on weekends. Never blocks the page.
# ═════════════════════════════════════════════════════════════════════

if "auto_capture_done" not in st.session_state:
    st.session_state.auto_capture_done = True
    try:
        _today = date.today()
        if _today.weekday() < 5:  # Mon–Fri
            get_fii_dii_data(_today - timedelta(days=1), _today)
    except Exception:
        pass  # never block the UI for background capture


# ═════════════════════════════════════════════════════════════════════
# HEADER
# ═════════════════════════════════════════════════════════════════════

st.markdown("<h1 style='font-size: 2.4rem;'>📈 Weekly Equity Report Generator</h1>", unsafe_allow_html=True)
st.caption("Monarch Networth Capital — automated weekly report pipeline")

# Guard: template must exist
if not os.path.exists(TEMPLATE_PATH):
    st.error(
        f"❌ Template not found at `{TEMPLATE_PATH}`. "
        "Ensure `template.docx` is in the project folder."
    )
    st.stop()


# ═════════════════════════════════════════════════════════════════════
# STEP 1 — DATE INPUT + AUTOMATED FETCH
# ═════════════════════════════════════════════════════════════════════

st.header("Step 1 · Report Week")
with st.container(border=True):
    st.write(
        "Weekly reports run **Sunday to Sunday**. "
        "Enter the **last** Sunday of the report week."
    )

    col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
    with col1:
        end_date_val = st.date_input(
            "End Sunday",
            value=None,
            format="DD-MM-YYYY",
            help="The report covers the 7-day window ending on this Sunday.",
        )
        end_str = end_date_val.strftime("%d-%m-%Y") if end_date_val else ""
    with col2:
        fetch_btn = st.button("🔄 Fetch Market Data", type="primary", disabled=not end_str, use_container_width=True)

if fetch_btn:
    # ── Validate ──
    try:
        start_date, end_date = validate_end_sunday(end_str)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    # ── Reset downstream state ──
    st.session_state.update({
        "start_date":  start_date,
        "end_date":    end_date,
        "report_path": None,
        "pdf_path":    None,   # clear old PDF so stale file never appears
    })

    with st.status(
        f"Fetching data for {start_date:%d %b %Y} → {end_date:%d %b %Y} …",
        expanded=True,
    ) as progress:
        try:
            # 1) Indices, sectors, EMA, S/R
            progress.write("📊  Downloading indices, sectors & EMA history …")
            mkt_data = fetch_all_market_data(start_date, end_date)
            st.session_state.mkt_data = mkt_data

            # 2) FII/DII (cache-first, live-scrape fallback)
            progress.write("💰  Fetching FII/DII figures (cache → live) …")
            prev_friday, curr_friday = get_friday_dates(start_date, end_date)

            # Determine expected trading days from Nifty history
            expected_days = 5
            nifty_df = mkt_data.get("yf_cache", {}).get("NIFTY 50")
            if nifty_df is not None and not nifty_df.empty:
                mask = (nifty_df.index > pd.Timestamp(prev_friday)) & (
                    nifty_df.index <= pd.Timestamp(curr_friday)
                )
                actual_days = len(nifty_df[mask])
                if actual_days > 0:
                    expected_days = actual_days

            fii_dii_daily = get_fii_dii_data(prev_friday, curr_friday)
            st.session_state.fii_dii_daily = fii_dii_daily

            # Aggregate into the weekly dict that build_narrative() expects
            trading_rows = fii_dii_daily[fii_dii_daily["status"] != "weekend"]
            available = trading_rows.dropna(subset=["fii", "dii"])
            days_covered = len(available)
            is_complete = days_covered >= expected_days and days_covered > 0

            if days_covered > 0:
                fii_dii = {
                    "fii":           int(available["fii"].sum()),
                    "dii":           int(available["dii"].sum()),
                    "is_weekly":     True,
                    "days_covered":  days_covered,
                    "expected_days": expected_days,
                    "is_complete":   is_complete,
                }
                missing = trading_rows[trading_rows["fii"].isna()]["date"].tolist()
                if missing:
                    progress.write(
                        "⚠️  FII/DII missing for: "
                        + ", ".join(d.strftime("%d-%b") for d in missing)
                        + f" — using {days_covered}/{expected_days} available days."
                    )
            else:
                fii_dii = {
                    "fii": None, "dii": None,
                    "is_weekly": False, "days_covered": 0,
                    "expected_days": expected_days, "is_complete": False,
                }
                progress.write("⚠️  No FII/DII data available for any day this week.")
            st.session_state.fii_dii = fii_dii

            # 3) Index constituents (top gainers / losers)
            progress.write("📋  Fetching index constituents …")
            try:
                constituents = fetch_constituents(prev_friday, curr_friday)
            except Exception as e:
                progress.write(f"⚠️  Constituents: {e}")
                constituents = None
            st.session_state.constituents = constituents

            # 4) Global markets (DJIA, STOXX 600)
            progress.write("🌍  Fetching global markets …")
            try:
                prev_fri_tgt, curr_fri_tgt = mkt_data["target_fridays"]
                global_mkts = fetch_global_markets(prev_fri_tgt, curr_fri_tgt)
            except Exception as e:
                progress.write(f"⚠️  Global markets: {e}")
                global_mkts = None

            # Snapshot fallback: if live fetch gave wrong-sign or missing values,
            # use the pre-validated snapshot (computed locally, committed to git).
            try:
                import json as _json, os as _os
                _snap_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "market_snapshot.json")
                if _os.path.exists(_snap_path):
                    _snap = _json.load(open(_snap_path))
                    _snap_week_end = _snap.get("week_end")
                    _snap_gmkts = _snap.get("global_mkts")
                    if _snap_week_end == end_date.isoformat() and _snap_gmkts:
                        # Use snapshot if live result is missing or has wrong sign
                        _live_ok = (global_mkts and
                                    global_mkts.get("djia") is not None and
                                    global_mkts.get("stoxx") is not None and
                                    (global_mkts["djia"] >= 0) == (_snap_gmkts["djia"] >= 0) and
                                    (global_mkts["stoxx"] >= 0) == (_snap_gmkts["stoxx"] >= 0))
                        if not _live_ok:
                            global_mkts = _snap_gmkts
                            progress.write("ℹ️  Global markets: using pre-validated snapshot values")
            except Exception:
                pass  # snapshot check never crashes the app

            st.session_state.global_mkts = global_mkts

            # 5) Derivatives (BhavCopy → live option chain fallback)
            progress.write("📉  Fetching derivatives data …")
            _, curr_friday_actual = mkt_data["actual_fridays"]
            derivatives_data = parse_bhavcopy_derivatives(end_date, curr_friday_actual)
            if not derivatives_data:
                derivatives_data = fetch_option_chain_live(end_date, curr_friday_actual)
            st.session_state.derivatives_data = derivatives_data or {}
            if not derivatives_data:
                progress.write(
                    "⚠️  Derivatives could not be automated — "
                    "that section will be left blank in the report."
                )

            progress.update(label="✅  Market data fetched successfully", state="complete")

        except Exception as exc:
            progress.update(label="❌  Fetch failed", state="error")
            st.exception(exc)
            st.stop()


# ═════════════════════════════════════════════════════════════════════
# FII/DII TRANSPARENCY PANEL (read-only, after fetch)
# ═════════════════════════════════════════════════════════════════════

if st.session_state.fii_dii_daily is not None:
    with st.expander("💰 FII/DII — day-by-day breakdown", expanded=False):
        df_display = st.session_state.fii_dii_daily.copy()
        df_display["date"] = df_display["date"].apply(
            lambda d: d.strftime("%d-%b-%Y (%a)")
        )
        # Format FII/DII columns — show NaN as "—"
        for col in ("fii", "dii"):
            df_display[col] = df_display[col].apply(
                lambda v: "—" if pd.isna(v) else f"{int(v):,} Cr"
            )
        st.dataframe(df_display, hide_index=True, use_container_width=True)
        st.caption(
            "**cached** = read from fii_dii_history.csv · "
            "**live** = scraped from NSE just now & saved · "
            "**missing** = not cached and not today (can't auto-fetch retroactively) · "
            "**weekend** = markets closed"
        )

        # Show weekly totals if available
        fii_dii = st.session_state.fii_dii
        if fii_dii and fii_dii.get("fii") is not None:
            col1, col2, col3 = st.columns(3)
            col1.metric("Weekly FII", f"₹{fii_dii['fii']:,} Cr")
            col2.metric("Weekly DII", f"₹{fii_dii['dii']:,} Cr")
            col3.metric("Days Covered", f"{fii_dii['days_covered']}/{fii_dii.get('expected_days', 5)}")


# ═════════════════════════════════════════════════════════════════════
# STEP 2 — SUPPORT / RESISTANCE OVERRIDE + GENERATE
# ═════════════════════════════════════════════════════════════════════

if st.session_state.mkt_data is not None:
    st.header("Step 2 · Support & Resistance")
    st.caption(
        "Auto-calculated levels are pre-filled. "
        "Edit any value, or leave as-is. Set to **0** to leave a field blank in the report."
    )

    sr_rows = st.session_state.mkt_data["sr"]
    sr_inputs = {}

    for row in sr_rows:
        name = row["name"]
        close = row.get("close")
        # Use index-specific step sizes that match actual strike intervals
        step = SR_ROUNDING_RULES.get(name, 100)

        close_str = f"{close:,.0f}" if close else "N/A"
        st.subheader(f"{name}  ·  Close: {close_str}")

        cols = st.columns(4)
        s2 = cols[0].number_input("S2", value=int(row.get("s2") or 0), step=step, key=f"s2_{name}")
        s1 = cols[1].number_input("S1", value=int(row.get("s1") or 0), step=step, key=f"s1_{name}")
        r1 = cols[2].number_input("R1", value=int(row.get("r1") or 0), step=step, key=f"r1_{name}")
        r2 = cols[3].number_input("R2", value=int(row.get("r2") or 0), step=step, key=f"r2_{name}")
        sr_inputs[name] = {"s2": s2, "s1": s1, "r1": r1, "r2": r2}

    st.divider()

    # ── GENERATE REPORT ──────────────────────────────────────────────
    if st.button("📄 Generate Weekly Report", type="primary"):
        import copy

        # CRITICAL: deep-copy so we never mutate the session-state object.
        # Mutating mkt_data["sr"] in-place corrupts all future "Generate" clicks.
        mkt_data = copy.deepcopy(st.session_state.mkt_data)

        # Apply S/R overrides from the number_input widgets.
        # A widget value of 0 means "leave blank" only when the user deliberately
        # set it to 0.  We use the pre-filled auto value (stored in mkt_data["sr"])
        # as the fallback so a widget that was never touched still uses auto data.
        for row in mkt_data["sr"]:
            ov = sr_inputs.get(row["name"], {})
            for key in ("s2", "s1", "r1", "r2"):
                widget_val = ov.get(key)
                auto_val   = row.get(key)
                # Only blank the field when the widget is explicitly 0 AND
                # the auto-calculated value was non-zero (meaning user cleared it).
                if widget_val is not None and widget_val != 0:
                    row[key] = widget_val
                elif widget_val == 0 and auto_val:
                    row[key] = None   # user explicitly cleared it
                # else: widget is 0 and auto was also 0/None — leave auto value
            if not any(row.get(k) for k in ("s1", "s2", "r1", "r2")):
                row["bias"] = ""

        start_date = st.session_state.start_date
        end_date = st.session_state.end_date
        fii_dii = st.session_state.fii_dii
        constituents = st.session_state.constituents
        global_mkts = st.session_state.global_mkts
        derivatives_data = st.session_state.derivatives_data

        with st.status("Generating report …", expanded=True) as progress:
            try:
                # 1) Narrative
                progress.write("✍️  Building narrative text …")
                narrative = build_narrative(
                    mkt_data, fii_dii, constituents, global_mkts,
                    start_date, end_date, derivatives_data,
                )

                # 2) Output path (ephemeral temp directory)
                output_dir = tempfile.mkdtemp(prefix="weekly_report_")
                output_filename = (
                    f"Weekly_Equity_Report_{start_date:%d%b%Y}_to_{end_date:%d%b%Y}.docx"
                )
                output_path = os.path.join(output_dir, output_filename)

                # 3) Charts + technical outlook
                progress.write("📊  Generating charts & technical outlook …")
                yf_cache = mkt_data.get("yf_cache", {})
                # Build resolved_closes so chart generator uses the correct
                # authoritative close for indices like FINNIFTY where Yahoo
                # Finance returns Close=NaN for the current Friday.
                resolved_closes = {
                    row["name"]: row["close"]
                    for row in mkt_data.get("indices", [])
                    if row.get("close") is not None
                }
                try:
                    chart_paths = chart_generator.generate_all_charts(
                        yf_cache, end_date, resolved_closes=resolved_closes
                    )
                    tech_outlook = chart_generator.generate_all_technical_data(
                        yf_cache=yf_cache,
                        sr_rows=mkt_data["sr"],
                        indices_data=mkt_data["indices"],
                        end_date=end_date,
                        resolved_closes=resolved_closes,
                    )
                except Exception as e:
                    progress.write(f"⚠️  Charts/outlook generation failed: {e}")
                    chart_paths, tech_outlook = None, None

                # 4) Fill DOCX template
                progress.write("📝  Filling document template …")
                fill_docx_document(
                    mkt_data=mkt_data,
                    fii_dii=fii_dii,
                    narrative=narrative,
                    start_date=start_date,
                    end_date=end_date,
                    output_path=output_path,
                    tech_outlook=tech_outlook,
                    chart_paths=chart_paths,
                )

                st.session_state.report_path = output_path
                
                progress.write("📄  Converting to PDF …")
                pdf_path = output_path.replace(".docx", ".pdf")
                pdf_ok = False

                # ── Method 1: docx2pdf (Windows with MS Word installed) ──
                try:
                    from docx2pdf import convert
                    convert(output_path, pdf_path)
                    if os.path.exists(pdf_path):
                        pdf_ok = True
                        progress.write("📄  PDF created successfully.")
                except Exception as _d2p_err:
                    progress.write(f"⚠️  docx2pdf: {_d2p_err}")

                # ── Method 2: LibreOffice fallback (Linux / Streamlit Cloud) ──
                if not pdf_ok:
                    try:
                        import subprocess, shutil
                        lo_bin = shutil.which("libreoffice") or shutil.which("soffice")
                        if lo_bin:
                            result = subprocess.run(
                                [
                                    lo_bin, "--headless", "--convert-to", "pdf",
                                    "--outdir", os.path.dirname(output_path),
                                    output_path,
                                ],
                                capture_output=True, text=True, timeout=60,
                            )
                            if result.returncode == 0 and os.path.exists(pdf_path):
                                pdf_ok = True
                                progress.write("📄  PDF created via LibreOffice.")
                    except Exception as _lo_err:
                        progress.write(f"⚠️  LibreOffice: {_lo_err}")

                st.session_state.pdf_path = pdf_path if pdf_ok else None
                if not pdf_ok:
                    progress.write("⚠️  PDF conversion unavailable — download the .docx file instead.")

                progress.update(label="✅  Report generated successfully", state="complete")

            except Exception as exc:
                progress.update(label="❌  Generation failed", state="error")
                st.exception(exc)
                st.stop()


# ═════════════════════════════════════════════════════════════════════
# STEP 3 — DOWNLOAD
# ═════════════════════════════════════════════════════════════════════

if st.session_state.report_path and os.path.exists(st.session_state.report_path):
    st.header("Step 3 · Download")
    st.success("✅ Your report has been generated successfully!")

    with st.container(border=True):
        with open(st.session_state.report_path, "rb") as f:
            report_bytes = f.read()

        dl_col1, dl_col2 = st.columns(2)
        
        with dl_col1:
            st.download_button(
                "⬇️  Download Weekly Report (.docx)",
                data=report_bytes,
                file_name=os.path.basename(st.session_state.report_path),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                type="primary",
                use_container_width=True,
            )

        if st.session_state.get("pdf_path") and os.path.exists(st.session_state.pdf_path):
            with open(st.session_state.pdf_path, "rb") as f:
                pdf_bytes = f.read()
            
            with dl_col2:
                st.download_button(
                    "⬇️  Download Weekly Report (.pdf)",
                    data=pdf_bytes,
                    file_name=os.path.basename(st.session_state.pdf_path),
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )

    # ── Data quality summary ──
    dq = st.session_state.mkt_data["data_quality"]
    fii_dii = st.session_state.fii_dii

    if fii_dii.get("is_complete") and fii_dii.get("is_weekly"):
        fii_status = f"Complete ({fii_dii.get('expected_days', 5)}-day weekly sum)"
    elif fii_dii.get("is_weekly"):
        fii_status = (
            f"Partial ({fii_dii.get('days_covered')}/{fii_dii.get('expected_days', 5)} days)"
        )
    elif fii_dii.get("fii") is not None:
        fii_status = "Single-day snapshot"
    else:
        fii_status = "Unavailable"

    with st.expander("📊 Data Quality Report"):
        st.write(f"**Indices:** {dq['indices_ok']}/{dq['indices_total']} fetched successfully")
        st.write(f"**Sectors:** {dq['sectors_ok']}/{dq['sectors_total']} fetched successfully")
        st.write(f"**FII/DII Data:** {fii_status}")
        st.write(f"**Global Markets:** {'Available ✓' if st.session_state.global_mkts else 'Unavailable ✗'}")
