import streamlit as st

from db.schema import init_db
from db import queries
from tasks.merge_detector import run_merge_detection

init_db()

st.title("Data")
st.markdown("Manage asset data quality and merge duplicate entries.")

# ── Manual scan button ────────────────────────────────────────────────────────
if st.button("Scan for Duplicates"):
    count = run_merge_detection()
    if count:
        st.success(f"Found {count} new merge suggestion(s).")
    else:
        st.info("No new duplicates detected.")
    st.rerun()

# ── Pending merge suggestions ────────────────────────────────────────────────
st.subheader("Merge Suggestions")
st.caption("Assets that appear to be duplicates across assessments. Merging combines them into one entry in the portfolio chart.")

pending = queries.get_pending_merge_suggestions()

if not pending:
    st.info("No pending merge suggestions. Run an assessment or click **Scan for Duplicates** above.")
else:
    for suggestion in pending:
        s = dict(suggestion)
        sid = s["id"]
        name_a = s["asset_name_a"]
        name_b = s["asset_name_b"]
        ticker_a = s.get("ticker_a") or ""
        ticker_b = s.get("ticker_b") or ""
        reason = s.get("reason", "")

        display_a = f"{name_a} ({ticker_a})" if ticker_a else name_a
        display_b = f"{name_b} ({ticker_b})" if ticker_b else name_b

        with st.container(border=True):
            st.markdown(f"**{display_a}** and **{display_b}**")
            st.caption(f"Reason: {reason}")

            col_merge_a, col_merge_b, col_dismiss = st.columns(3)
            with col_merge_a:
                if st.button(f"Keep \"{name_a}\"", key=f"merge_a_{sid}"):
                    queries.add_asset_merge(
                        canonical_name=name_a, canonical_ticker=ticker_a,
                        variant_name=name_b, variant_ticker=ticker_b,
                    )
                    queries.update_merge_suggestion_status(sid, "merged")
                    st.rerun()
            with col_merge_b:
                if st.button(f"Keep \"{name_b}\"", key=f"merge_b_{sid}"):
                    queries.add_asset_merge(
                        canonical_name=name_b, canonical_ticker=ticker_b,
                        variant_name=name_a, variant_ticker=ticker_a,
                    )
                    queries.update_merge_suggestion_status(sid, "merged")
                    st.rerun()
            with col_dismiss:
                if st.button("Dismiss", key=f"dismiss_{sid}"):
                    queries.update_merge_suggestion_status(sid, "dismissed")
                    st.rerun()

st.divider()

# ── Manual merge ──────────────────────────────────────────────────────────────
st.subheader("Manual Merge")
st.caption("Pick two assets from the portfolio chart legend and merge them into one.")

all_assets = queries.get_all_unique_assets()
asset_options = []
asset_lookup = {}
for a in all_assets:
    ad = dict(a)
    name = ad.get("asset_name") or ""
    ticker = (ad.get("ticker") or "").strip()
    display = f"{name} ({ticker})" if ticker else name
    if display and display not in asset_lookup:
        asset_options.append(display)
        asset_lookup[display] = {"name": name, "ticker": ticker}

if len(asset_options) >= 2:
    col_pick1, col_pick2 = st.columns(2)
    with col_pick1:
        pick_a = st.selectbox("Asset A", asset_options, index=0, key="manual_merge_a")
    with col_pick2:
        filtered_b = [o for o in asset_options if o != pick_a]
        pick_b = st.selectbox("Asset B", filtered_b, index=0, key="manual_merge_b")

    info_a = asset_lookup[pick_a]
    info_b = asset_lookup[pick_b]

    col_keep_a, col_keep_b = st.columns(2)
    with col_keep_a:
        if st.button(f"Merge: keep \"{info_a['name']}\"", key="manual_keep_a"):
            queries.add_asset_merge(
                canonical_name=info_a["name"], canonical_ticker=info_a["ticker"],
                variant_name=info_b["name"], variant_ticker=info_b["ticker"],
            )
            st.rerun()
    with col_keep_b:
        if st.button(f"Merge: keep \"{info_b['name']}\"", key="manual_keep_b"):
            queries.add_asset_merge(
                canonical_name=info_b["name"], canonical_ticker=info_b["ticker"],
                variant_name=info_a["name"], variant_ticker=info_a["ticker"],
            )
            st.rerun()
else:
    st.info("Not enough assets to merge. Run an assessment first.")

st.divider()

# ── Active merges ─────────────────────────────────────────────────────────────
st.subheader("Active Merges")
st.caption("These rules are applied to the portfolio chart. The variant is displayed as the canonical name.")

merges = queries.get_all_asset_merges()

if not merges:
    st.info("No active merge rules.")
else:
    for merge in merges:
        m = dict(merge)
        mid = m["id"]
        canonical = f"{m['canonical_name']} ({m['canonical_ticker']})" if m.get("canonical_ticker") else m["canonical_name"]
        variant = f"{m['variant_name']} ({m['variant_ticker']})" if m.get("variant_ticker") else m["variant_name"]

        col_info, col_undo = st.columns([5, 1])
        with col_info:
            st.markdown(f"**{variant}** → **{canonical}**")
        with col_undo:
            if st.button("Undo", key=f"undo_merge_{mid}"):
                queries.delete_asset_merge(mid)
                st.rerun()

st.divider()

# ── Past suggestions (dismissed/merged) ───────────────────────────────────────
all_suggestions = queries.get_all_merge_suggestions()
past = [dict(s) for s in all_suggestions if s["status"] != "pending"]

if past:
    with st.expander(f"Past Suggestions ({len(past)})"):
        for s in past:
            name_a = s["asset_name_a"]
            name_b = s["asset_name_b"]
            status_icon = ":green[merged]" if s["status"] == "merged" else ":gray[dismissed]"
            st.caption(f"{name_a} / {name_b} — {status_icon}")
