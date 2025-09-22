import streamlit as st
import pandas as pd
import plotly.express as px
import re

# -------------------------------
# Global CSS: Force light theme
# -------------------------------
st.markdown(
    """
    <style>
        body { color: #000000; background-color: #ffffff; }
        html, body, #root, .appview-container, section.main, .block-container {
            margin-top: 0 !important; padding-top: 0 !important;
        }
        .block-container {
            padding-top: 1rem !important; padding-bottom: 1rem;
            padding-left: 2rem; padding-right: 2rem;
            max-width: 1200px; margin: auto;
        }
        div > div > svg { width: 100% !important; height: auto !important; }
        div[data-baseweb="select"] { max-width: 300px; min-width: 150px; }
        div[data-baseweb="select"] svg { width: 14px !important; height: 14px !important; padding: 2px !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# Sidebar: cache clear for fresh data loads
#if st.sidebar.button("🔄 Refresh data (clear cache)"):
#    st.cache_data.clear()
#    st.rerun()

# -------------------------------
# Plotly helpers for mobile-friendly legends
# -------------------------------
def style_plotly(fig):
    """Apply consistent mobile-friendly legend styling across all charts."""
    fig.update_layout(
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.3,            # show legend below chart; tweak if overlapping
            xanchor="center",
            x=0.5,
            font=dict(size=10),
            bgcolor="rgba(255,255,255,0.6)"
        ),
        margin=dict(t=40, b=80)
    )
    return fig

def show_chart(fig):
    """Wrapper to style + display plotly figs consistently."""
    fig = style_plotly(fig)
    st.plotly_chart(fig, use_container_width=True)

# -------------------------------
# Data loaders
# -------------------------------
@st.cache_data
def get_data():
    df = pd.read_csv("assets/oic_dashboard.csv")
    df['year_month'] = pd.to_datetime(df['year_month']).dt.to_period('M').dt.to_timestamp()
    return df

@st.cache_data
def get_source_data():
    df = pd.read_csv("assets/oic_claims_source.csv")
    df["year_month"] = pd.to_datetime(df["year_month"] + "-01")
    return df

@st.cache_data
def get_tariff_data():
    df = pd.read_csv("assets/tariff_breakdown.csv")
    df['year_month'] = pd.to_datetime(df['year'].astype(str) + '-' + df['month'] + '-01')
    return df

@st.cache_data
def get_tariffplus_data():
    df = pd.read_csv("assets/tariffplus_breakdown.csv")
    df['year_month'] = pd.to_datetime(df['year'].astype(str) + '-' + df['month'] + '-01')
    return df

# -------------------------------
# Period parser & coercers
# -------------------------------
def _parse_period_to_ts_mmm_yy(s: pd.Series) -> pd.Series:
    clean = (
        s.astype(str)
         .str.replace("\u00A0", " ", regex=False)  # NBSP
         .str.replace("–", "-", regex=False)       # en-dash
         .str.replace("—", "-", regex=False)       # em-dash
         .str.strip()
         .str.replace(r"\bSept\b", "Sep", regex=True)
    )
    dt = pd.to_datetime(clean, format="%b-%y", errors="coerce")
    return dt.dt.to_period("M").dt.to_timestamp()

def _coerce_money(x):
    if pd.isna(x):
        return 0.0
    return float(str(x).replace("£", "").replace(",", "").strip())

def _clean_int_series(s: pd.Series) -> pd.Series:
    cleaned = (
        s.astype(str)
         .str.replace("\u00A0", " ", regex=False)
         .str.replace("\u202F", " ", regex=False)
         .str.replace("\u2009", " ", regex=False)
         .str.replace(",", "", regex=False)
         .str.strip()
         .replace({"": "0", "-": "0"})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0).astype(int)

# -------------------------------
# Claims Portal loaders
# -------------------------------
@st.cache_data
def load_portal_csv(path: str, lob: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={c: c.strip().lower().replace(" ", "_") for c in df.columns})

    col_map = {
        "stage1_exit": "stage_1_exit",
        "stage2_exit": "stage_2_exit",
        "courtpack": "court_pack",
        "gd": "general_damages",
        "general_damage": "general_damages",
        "settled": "settled_claims",
        "settled_claim": "settled_claims",
        "new_cnf": "new_claim",
        "new_cnfs": "new_claim",
    }
    for src, dst in col_map.items():
        if src in df.columns and dst not in df.columns:
            df = df.rename(columns={src: dst})

    if "period" not in df.columns:
        raise ValueError(f"{path}: expected 'period' column in MMM-YY format.")
    df["year_month"] = _parse_period_to_ts_mmm_yy(df["period"])

    num_cols = ["new_claim","stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]
    for c in num_cols:
        if c not in df.columns:
            df[c] = 0
        df[c] = _clean_int_series(df[c])

    if "general_damages" not in df.columns:
        df["general_damages"] = 0.0
    else:
        df["general_damages"] = df["general_damages"].apply(_coerce_money)

    df["lob"] = lob
    df = df.dropna(subset=["year_month"]).sort_values("year_month").reset_index(drop=True)
    return df

@st.cache_data
def get_el_portal(): return load_portal_csv("assets/el_portal.csv", "EL")

@st.cache_data
def get_pl_portal(): return load_portal_csv("assets/pl_portal.csv", "PL")

@st.cache_data
def get_motor_portal(): return load_portal_csv("assets/motor_portal.csv", "Motor")

@st.cache_data
def get_portal_all():
    el = get_el_portal()
    pl = get_pl_portal()
    mot = get_motor_portal()
    all_df = pd.concat([el, pl, mot], ignore_index=True)
    return all_df.sort_values(["lob", "year_month"]).reset_index(drop=True)

# Duplicate-safe month completion per LoB
def _complete_months_per_lob(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure each LoB has one row per month and a continuous monthly index.
    - Collapse duplicates per (lob, year_month) by summing counts and weighted-averaging general_damages.
    - Reindex to complete monthly range per LoB.
    """
    if df.empty:
        return df

    pieces = []
    sum_cols_all = ["new_claim","stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]

    for lob, g in df.groupby("lob", group_keys=False):
        g = g.copy()
        g["year_month"] = pd.to_datetime(g["year_month"]).dt.to_period("M").dt.to_timestamp()

        sum_cols = [c for c in sum_cols_all if c in g.columns]
        agg_map = {c: "sum" for c in sum_cols}

        have_gd = "general_damages" in g.columns
        have_settled = "settled_claims" in g.columns
        if have_gd and have_settled:
            g["_gd_total"] = pd.to_numeric(g["general_damages"], errors="coerce").fillna(0.0) * \
                             pd.to_numeric(g["settled_claims"], errors="coerce").fillna(0)
            agg_map["_gd_total"] = "sum"

        g = g.groupby("year_month", as_index=False).agg(agg_map)

        if have_gd and have_settled:
            denom = g["settled_claims"].replace(0, pd.NA)
            g["general_damages"] = (g["_gd_total"] / denom).fillna(0.0)
            g = g.drop(columns=["_gd_total"])

        months = pd.date_range(g["year_month"].min(), g["year_month"].max(), freq="MS")
        g = g.set_index("year_month").reindex(months).rename_axis("year_month").reset_index()

        for c in sum_cols:
            g[c] = pd.to_numeric(g[c], errors="coerce").fillna(0).astype(int)
        if have_gd and "general_damages" in g.columns:
            g["general_damages"] = pd.to_numeric(g["general_damages"], errors="coerce").fillna(0.0)

        g["lob"] = lob
        g["period"] = g["year_month"].dt.strftime("%b-%y")
        pieces.append(g)

    return pd.concat(pieces, ignore_index=True)

# -------------------------------
# Header renderer
# -------------------------------
def render_header(page_title):
    try:
        with open("assets/injuryiq.svg", "r") as file:
            svg_content = file.read()
    except Exception:
        svg_content = ""
    st.markdown(
        f"""
        <div style="position: sticky; top: 0; background-color: white; z-index: 100; padding-top: 10px; padding-bottom: 10px; border-bottom: 1px solid #ddd;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h1 style="margin: 0;">{page_title}</h1>
                <div style="width: 150px; height: auto;">{svg_content}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# -------------------------------
# Filters UI
# -------------------------------
def filters_ui(df):
    representation_options = sorted(df['representation_status'].unique().tolist())
    representation_options.insert(0, "Combined")
    filter_col1, filter_col2 = st.columns([1, 3])

    with filter_col1:
        selected_rep = st.multiselect(
            "Representation",
            options=representation_options,
            default=["Represented", "Unrepresented"],
            help="Select one or more representation statuses. Select 'Combined' for combined totals."
        )
    combined = "Combined" in selected_rep

    with filter_col2:
        min_date = df['year_month'].min().date()
        max_date = df['year_month'].max().date()

        quick_pick = st.radio(
            "Quick Date Range",
            options=["Custom", "Last 12 months", "Last 24 months", "Last 36 months"],
            horizontal=True,
            index=0
        )

        if quick_pick == "Custom":
            selected_date = st.slider(
                "Date Range",
                min_value=min_date,
                max_value=max_date,
                value=(min_date, max_date),
                format="MMM YYYY"
            )
        else:
            today = pd.Timestamp(max_date)
            if quick_pick == "Last 12 months":
                start = (today - pd.DateOffset(months=12)).to_pydatetime().date()
            elif quick_pick == "Last 24 months":
                start = (today - pd.DateOffset(months=24)).to_pydatetime().date()
            elif quick_pick == "Last 36 months":
                start = (today - pd.DateOffset(months=36)).to_pydatetime().date()
            else:
                start = min_date
            if start < min_date:
                start = min_date
            selected_date = (start, max_date)

            st.slider(
                "Date Range", min_value=min_date, max_value=max_date,
                value=selected_date, format="MMM YYYY", disabled=True
            )

    start_date = pd.to_datetime(selected_date[0]).to_period('M').to_timestamp()
    end_date = pd.to_datetime(selected_date[1]).to_period('M').to_timestamp()
    return selected_rep, combined, start_date, end_date

# -------------------------------
# Plotting helper (uses show_chart)
# -------------------------------
def plot_multiline(df, y_column, title, start_date, end_date):
    filtered = df[(df['year_month'] >= start_date) & (df['year_month'] <= end_date)]
    if 'representation_status' in filtered.columns:
        fig = px.line(filtered, x='year_month', y=y_column, color='representation_status', title=title, markers=True)
    else:
        fig = px.line(filtered, x='year_month', y=y_column, title=title, markers=True)
    fig.update_layout(xaxis_title="Month", yaxis_title=y_column.replace("_", " ").title())
    show_chart(fig)

# -------------------------------
# PAGES: OIC (Home)
# -------------------------------
def home_page():
    df = get_data()
    render_header("OIC Portal Data")
    selected_rep, combined, start_date, end_date = filters_ui(df)

    if combined or len(selected_rep) == 0:
        filtered_df = df.copy()
        filtered_df = filtered_df.groupby('year_month', as_index=False).agg({
            'claims_volume': 'sum',
            'settlement_volume': 'sum',
            'total_settlement_value': 'sum',
        })
        filtered_df = filtered_df[(filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)]
        date_range = pd.date_range(start=start_date, end=end_date, freq='MS').to_period('M').to_timestamp()
        filtered_df = filtered_df.set_index('year_month').reindex(date_range, fill_value=0).rename_axis('year_month').reset_index()
        filtered_df['weighted_avg_settlement'] = filtered_df.apply(
            lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
            axis=1
        )
        plot_df = filtered_df.copy()
    else:
        filtered_df = df[df['representation_status'].isin(selected_rep)]
        filtered_df = filtered_df[(filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)]
        agg_df = filtered_df.groupby(['year_month', 'representation_status'], as_index=False).agg({
            'claims_volume': 'sum',
            'settlement_volume': 'sum',
            'total_settlement_value': 'sum',
        })
        date_range = pd.date_range(start=start_date, end=end_date, freq='MS').to_period('M').to_timestamp()
        full_index = pd.MultiIndex.from_product([date_range, selected_rep], names=['year_month', 'representation_status'])
        agg_df = agg_df.set_index(['year_month', 'representation_status']).reindex(full_index, fill_value=0).reset_index()
        agg_df['weighted_avg_settlement'] = agg_df.apply(
            lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
            axis=1
        )
        plot_df = agg_df.copy()

    st.subheader("Summary")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Claims", f"{filtered_df['claims_volume'].sum():,}")
    with col2:
        st.metric("Total Settled Claims", f"{int(filtered_df['settlement_volume'].sum()):,}")
    with col3:
        st.metric("Total Settlement Value", f"£{filtered_df['total_settlement_value'].sum():,.0f}")
    with col4:
        avg_settlement = filtered_df['total_settlement_value'].sum() / filtered_df['settlement_volume'].sum() if filtered_df['settlement_volume'].sum() > 0 else 0
        st.metric("Average Settlement Amount", f"£{avg_settlement:,.2f}")

    col1, col2 = st.columns(2)
    with col1:
        plot_multiline(plot_df, 'claims_volume', 'New Claims', start_date, end_date)
    with col2:
        plot_multiline(plot_df, 'settlement_volume', 'Settled Claims', start_date, end_date)

    col3, col4 = st.columns(2)
    with col3:
        plot_multiline(plot_df, 'total_settlement_value', 'Total Settlement Value', start_date, end_date)
    with col4:
        plot_multiline(plot_df, 'weighted_avg_settlement', 'Average Settlement', start_date, end_date)

# -------------------------------
# PAGES: New Claim Analysis
# -------------------------------
def new_claim_analysis_page():
    df = get_data()
    render_header("New Claim Analysis")
    selected_rep, combined, start_date, end_date = filters_ui(df)

    # Source data (represented only chart)
    source_df = get_source_data()
    end_date_next_month = end_date + pd.offsets.MonthBegin(1)
    source_df = source_df[(source_df["year_month"] >= start_date) & (source_df["year_month"] < end_date_next_month)]

    represented_types = [t for t in selected_rep if t not in ["Unrepresented", "Combined"]]

    st.subheader("Source of New Claims (Represented Only)")
    if represented_types:
        filtered_source_df = source_df[source_df["organisation_type"].isin([
            "Alternative Business Structure", "Claims Management Company", "Other", "UK Law Firm"
        ])].copy()

        source_fig = px.bar(
            filtered_source_df, x="year_month", y="claims_volume",
            color="organisation_type", barmode="stack",
            labels={"year_month": "Date", "claims_volume": "Claim Volume", "organisation_type": "Organisation Type"},
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        all_months = pd.date_range(start=start_date, end=end_date, freq='MS')
        source_fig.update_xaxes(tickvals=all_months, tickformat="%d %b", tickmode='array')
        source_fig.update_layout(margin=dict(l=40, r=40, t=40, b=40), legend_title_text=None)
        source_fig.update_traces(hovertemplate='%{y:,}<extra></extra>')
        show_chart(source_fig)
    else:
        st.info("This chart is only visible when a represented type is selected.")

    # Injury breakdown (only when 'Combined' is selected)
    st.subheader("Injury Type Breakdown")
    if combined:
        injury_df = pd.read_csv("assets/injury_breakdown.csv")
        injury_df["year_month"] = pd.to_datetime(injury_df["year"].astype(str) + "-" + injury_df["month"] + "-01")
        injury_df = injury_df[(injury_df["year_month"] >= start_date) & (injury_df["year_month"] <= end_date)]
        totals = injury_df.groupby("year_month")["claims_volume"].sum().reset_index(name="total_volume")
        merged_df = pd.merge(injury_df, totals, on="year_month")
        merged_df["percentage"] = (merged_df["claims_volume"] / merged_df["total_volume"]).mul(100).fillna(0)
        merged_df["label"] = merged_df["injury_group"] + " (" + merged_df["injury_type"] + ")"

        view_option = st.radio("View as:", ["Chart", "Data"], horizontal=True, index=0)
        if view_option == "Chart":
            fig = px.line(
                merged_df, x="year_month", y="percentage", color="label", markers=True,
                title="Injury Breakdown Over Time (% of Total Claims)"
            )
            fig.update_layout(yaxis_tickformat=".1f", hovermode="x unified", height=500, legend_title_text=None)
            show_chart(fig)
        else:
            st.dataframe(
                merged_df[["year_month", "injury_group", "injury_type", "claims_volume", "percentage"]],
                use_container_width=True
            )
    else:
        st.info("This chart is only visible when 'Combined' is selected.")

# -------------------------------
# PAGES: Settlement Analysis
# -------------------------------
def settlement_analysis_page():
    df = get_data()
    render_header("Settlement Analysis")
    selected_rep, combined, start_date, end_date = filters_ui(df)

    st.markdown("## Claim Volumes and Averages by Injury Type")
    chart_df = df if combined else df[df['representation_status'].isin(selected_rep)]
    chart_df = chart_df[(chart_df['year_month'] >= start_date) & (chart_df['year_month'] <= end_date)]
    group_cols = ['year_month'] if combined else ['year_month', 'representation_status']
    grouped = chart_df.groupby(group_cols, as_index=False).agg({
        'vol_tariff_amount': 'sum', 'avg_tariff_amount': 'mean',
        'vol_non_tariff': 'sum', 'avg_non_tariff': 'mean',
        'vol_tariff_uplift': 'sum', 'avg_tariff_uplift': 'mean'
    })
    metric_labels = {
        'vol_tariff_amount': 'Tariff Volume',
        'avg_tariff_amount': 'Tariff Average (£)',
        'vol_non_tariff': 'Non-Tariff Volume',
        'avg_non_tariff': 'Non-Tariff Average (£)',
        'vol_tariff_uplift': 'Tariff Uplift Volume',
        'avg_tariff_uplift': 'Tariff Uplift Average (£)'
    }

    for vol_metric, avg_metric in [
        ('vol_tariff_amount', 'avg_tariff_amount'),
        ('vol_non_tariff', 'avg_non_tariff'),
        ('vol_tariff_uplift', 'avg_tariff_uplift')
    ]:
        col1, col2 = st.columns(2)
        with col1:
            fig_vol = px.line(
                grouped, x='year_month', y=vol_metric,
                color=None if combined else 'representation_status',
                title=metric_labels[vol_metric], markers=True
            )
            fig_vol.update_layout(margin=dict(t=40, b=40, l=40, r=40))
            show_chart(fig_vol)
        with col2:
            fig_avg = px.line(
                grouped, x='year_month', y=avg_metric,
                color=None if combined else 'representation_status',
                title=metric_labels[avg_metric], markers=True
            )
            fig_avg.update_layout(margin=dict(t=40, b=40, l=40, r=40))
            show_chart(fig_avg)

    st.markdown("## Tariff Recovery Duration Month on Month")
    whiplash_df = get_tariff_data()
    whiplashplus_df = get_tariffplus_data()
    whiplash_df = whiplash_df[(whiplash_df['year_month'] >= start_date) & (whiplash_df['year_month'] <= end_date)]
    whiplashplus_df = whiplashplus_df[(whiplashplus_df['year_month'] >= start_date) & (whiplashplus_df['year_month'] <= end_date)]

    def prepare_percent_df(df_in):
        pivot_df = df_in.pivot_table(
            index='year_month', columns='injury_duration',
            values='settlement_volume', aggfunc='sum', fill_value=0
        )
        duration_order = ['0-3 Mths', '3-6 Mths', '6-9 Mths', '9-12 Mths', '12-15 Mths', '15-18 Mths', '18-24 Mths']
        pivot_df = pivot_df.reindex(columns=duration_order, fill_value=0)
        percent_df = pivot_df.div(pivot_df.sum(axis=1), axis=0).fillna(0)
        return percent_df

    whiplash_percent = prepare_percent_df(whiplash_df)
    whiplashplus_percent = prepare_percent_df(whiplashplus_df)

    col1, col2 = st.columns(2)
    with col1:
        fig1 = px.bar(
            whiplash_percent, x=whiplash_percent.index, y=whiplash_percent.columns,
            title="Tariff Recovery Duration - Whiplash Only (100% Stacked)",
            labels={"value": "Percentage of Settlements", "year_month": "Month"},
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        fig1.update_layout(barmode='stack', xaxis=dict(tickformat="%b %Y", tickangle=45, dtick="M1"),
                           yaxis=dict(tickformat=".0%"), legend_title_text="Duration Band", margin=dict(t=40, b=100))
        show_chart(fig1)
    with col2:
        fig2 = px.bar(
            whiplashplus_percent, x=whiplashplus_percent.index, y=whiplashplus_percent.columns,
            title="Tariff Recovery Duration - Whiplash Plus (100% Stacked)",
            labels={"value": "Percentage of Settlements", "year_month": "Month"},
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        fig2.update_layout(barmode='stack', xaxis=dict(tickformat="%b %Y", tickangle=45, dtick="M1"),
                           yaxis=dict(tickformat=".0%"), legend_title_text="Duration Band", margin=dict(t=40, b=100))
        show_chart(fig2)

# -------------------------------
# PAGES: Litigation Analysis
# -------------------------------
def Litigation_analysis_page():
    df = get_data()
    render_header("Litigation Analysis")
    selected_rep, combined, start_date, end_date = filters_ui(df)
    st.subheader("Litigated Claims v Settlements")

    if combined or len(selected_rep) == 0:
        grouped = df.copy()
        grouped = grouped.groupby("year_month", as_index=False).agg({
            "settlement_volume": "sum", "exit_court": "sum"
        })
        grouped["litigation_pct"] = grouped.apply(
            lambda row: row["exit_court"] / (row["exit_court"] + row["settlement_volume"])
            if (row["exit_court"] + row["settlement_volume"]) > 0 else 0, axis=1
        )
        grouped = grouped[(grouped["year_month"] >= start_date) & (grouped["year_month"] <= end_date)]
        grouped = grouped.set_index("year_month").reindex(
            pd.date_range(start_date, end_date, freq="MS").to_period("M").to_timestamp(), fill_value=0
        ).rename_axis("year_month").reset_index()
    else:
        grouped = df[df["representation_status"].isin(selected_rep)]
        grouped = grouped[(grouped["year_month"] >= start_date) & (grouped["year_month"] <= end_date)]
        grouped = grouped.groupby(["year_month", "representation_status"], as_index=False).agg({
            "settlement_volume": "sum", "exit_court": "sum"
        })
        grouped["litigation_pct"] = grouped.apply(
            lambda row: row["exit_court"] / (row["exit_court"] + row["settlement_volume"])
            if (row["exit_court"] + row["settlement_volume"]) > 0 else 0, axis=1
        )
        full_index = pd.MultiIndex.from_product(
            [pd.date_range(start_date, end_date, freq="MS").to_period("M").to_timestamp(), selected_rep],
            names=["year_month", "representation_status"]
        )
        grouped = grouped.set_index(["year_month", "representation_status"]).reindex(full_index, fill_value=0).reset_index()

    fig = px.line(
        grouped, x="year_month", y="litigation_pct",
        color=None if combined else "representation_status",
        labels={"year_month": "Date", "litigation_pct": "Litigation %"},
        title="Litigation % Over Time",
        markers=True
    )
    fig.update_layout(yaxis_tickformat=".1%", hovermode="x unified", margin=dict(t=40, b=40, l=40, r=40))
    show_chart(fig)

    grouped['year_month_str'] = grouped['year_month'].dt.strftime('%b %Y')
    category_order = grouped.sort_values('year_month')['year_month_str'].unique()

    st.subheader("Litigated Claim Volume Over Time")
    fig_bar = px.bar(
        grouped, x="year_month_str", y="exit_court",
        color=None if combined else "representation_status",
        barmode="group", labels={"year_month_str": "Date", "exit_court": "Litigated Volume"},
        title="Litigated Claims Volume (Monthly)", color_discrete_sequence=px.colors.qualitative.Safe
    )
    fig_bar.update_layout(hovermode="x unified", margin=dict(t=40, b=40, l=40, r=40))
    fig_bar.update_xaxes(type='category', categoryorder='array', categoryarray=category_order)
    fig_bar.update_traces(hovertemplate='%{y:,}<extra></extra>')
    show_chart(fig_bar)

# -------------------------------
# PAGES: Claims Portal (EL/PL/Motor)
# -------------------------------
def claims_portal_page():
    dfp = get_portal_all()
    render_header("Claims Portal (EL / PL / Motor)")

    lob_options = dfp["lob"].unique().tolist()
    selected_lobs = st.multiselect("Line(s) of Business", lob_options, default=lob_options)

    min_date = dfp["year_month"].min().date()
    max_date = dfp["year_month"].max().date()

    quick = st.radio("Quick Date Range", ["Custom","Last 12 months","Last 24 months","Last 36 months"],
                     horizontal=True, index=1)
    if quick == "Custom":
        start_date, end_date = st.slider("Date Range", min_value=min_date, max_value=max_date,
                                         value=(min_date, max_date), format="MMM YYYY")
    else:
        months = {"Last 12 months":12, "Last 24 months":24, "Last 36 months":36}[quick]
        end_date = max_date
        start_dt = (pd.Timestamp(end_date) - pd.DateOffset(months=months)).to_period("M").to_timestamp()
        start_date = max(min_date, start_dt.date())
        st.slider("Date Range", min_value=min_date, max_value=max_date,
                  value=(start_date, end_date), format="MMM YYYY", disabled=True)

    mask = (
        dfp["lob"].isin(selected_lobs)
        & (dfp["year_month"] >= pd.to_datetime(start_date))
        & (dfp["year_month"] <= pd.to_datetime(end_date))
    )
    view = dfp.loc[mask].copy().sort_values(["lob", "year_month"])
    view = _complete_months_per_lob(view)

    # KPIs
    st.subheader("Summary")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("New CNFs", f"{int(view['new_claim'].sum()):,}")
    with k2:
        st.metric("Settled (in Portal)", f"{int(view['settled_claims'].sum()):,}")
    with k3:
        denom = view["settled_claims"].sum()
        avg_gd = (view["general_damages"] * view["settled_claims"]).sum() / denom if denom else 0
        st.metric("Avg General Damages", f"£{avg_gd:,.0f}")
    with k4:
        exits = view[["stage_1_exit","stage_2_exit","exit_process","court_pack"]].sum()
        total_outcomes = view["settled_claims"].sum() + exits.sum()
        lit_pct = (exits["court_pack"] / total_outcomes) if total_outcomes else 0
        st.metric("Litigation % (of outcomes)", f"{lit_pct:.1%}")

    # Charts
    c1, c2 = st.columns(2)
    with c1:
        fig = px.line(view, x="year_month", y="new_claim", color="lob", markers=True, title="New Claims (CNFs Sent)")
        fig.update_layout(yaxis_title="CNFs", xaxis_title="Month")
        show_chart(fig)
    with c2:
        fig = px.line(view, x="year_month", y="settled_claims", color="lob", markers=True, title="Settled Claims (in Portal)")
        fig.update_layout(yaxis_title="Settled", xaxis_title="Month")
        show_chart(fig)

    c3, c4 = st.columns(2)
    with c3:
        fig = px.line(view, x="year_month", y="general_damages", color="lob", markers=True, title="Average General Damages (Portal)")
        fig.update_layout(yaxis_title="£", xaxis_title="Month")
        show_chart(fig)
    with c4:
        grp = view.groupby(["year_month","lob"], as_index=False)[
            ["stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]
        ].sum()
        grp = grp.sort_values(["lob", "year_month"])
        for col in ["stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]:
            grp[col] = grp[col].fillna(0)
        grp["total_outcomes"] = grp[["stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]].sum(axis=1)
        for col in ["stage_1_exit","stage_2_exit","exit_process","court_pack","settled_claims"]:
            grp[col] = grp[col] / grp["total_outcomes"].replace(0, pd.NA)

        melt = grp.melt(
            id_vars=["year_month","lob"],
            value_vars=["settled_claims","stage_1_exit","stage_2_exit","exit_process","court_pack"],
            var_name="outcome", value_name="pct"
        ).fillna(0)
        outcome_order = ["settled_claims","stage_1_exit","stage_2_exit","exit_process","court_pack"]
        melt["outcome"] = pd.Categorical(melt["outcome"], categories=outcome_order, ordered=True)

        fig = px.bar(
            melt, x="year_month", y="pct", color="outcome",
            facet_col="lob", facet_col_wrap=1, barmode="stack",
            title="Outcome Mix (as % of outcomes)", category_orders={"outcome": outcome_order}
        )
        fig.update_layout(yaxis_tickformat=".0%", xaxis_title="Month", legend_title_text="Outcome")
        show_chart(fig)

    st.caption("Notes: ‘Outcome Mix’ uses portal outcomes only (settlements + exits). Court Pack is a proxy for litigation outside the portal.")

# -------------------------------
# NAVIGATION
# -------------------------------
page = st.sidebar.radio(
    "Select Page",
    ["Home", "New Claim Analysis", "Settlement Analysis", "Litigation Analysis", "Claims Portal (EL/PL/Motor)"]
)
if page == "Home":
    home_page()
elif page == "New Claim Analysis":
    new_claim_analysis_page()
elif page == "Settlement Analysis":
    settlement_analysis_page()
elif page == "Litigation Analysis":
    Litigation_analysis_page()
else:
    claims_portal_page()

# -------------------------------
# Footer
# -------------------------------
st.markdown("""
<hr style="margin-top: 3rem; margin-bottom: 1rem;">
<footer style="font-size: 0.8rem; color: #666; text-align: center; padding-bottom: 1rem;">
    Data sourced from <a href="https://www.officialinjuryclaim.org.uk/resources-for-professionals/data/" target="_blank" rel="noopener noreferrer">Official Injury Claim</a> and the Claims Portal (EL/PL/Motor) | Dashboard by <strong>InjuryIQ</strong>
</footer>
""", unsafe_allow_html=True)
