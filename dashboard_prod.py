import streamlit as st
import pandas as pd
import plotly.express as px

# Load data from CSV (cached)
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

# Helper function to render header with logo and title
def render_header(page_title):
    with open("assets/injuryiq.svg", "r") as file:
        svg_content = file.read()

    st.markdown(
        f"""
        <style>
            html, body, #root, .appview-container, section.main, .block-container {{
                margin-top: 0 !important;
                padding-top: 0 !important;
            }}

            .block-container {{
                padding-top: 1rem !important;
                padding-bottom: 1rem;
                padding-left: 2rem;
                padding-right: 2rem;
                max-width: 1200px;
                margin: auto;
            }}

            div > div > svg {{
                width: 100% !important;
                height: auto !important;
            }}
        </style>

        <div style="position: sticky; top: 0; background-color: white; z-index: 100; padding-top: 10px; padding-bottom: 10px; border-bottom: 1px solid #ddd;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h1 style="margin: 0;">{page_title}</h1>
                <div style="width: 150px; height: auto;">
                    {svg_content}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# Filters UI helper (used in multiple pages)
def filters_ui(df):
    representation_options = sorted(df['representation_status'].unique().tolist())
    representation_options.insert(0, "Combined")  # Add 'Combined' at the start

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
        selected_date = st.slider(
            "Date Range",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date),
            format="MMM YYYY"
        )

    start_date = pd.to_datetime(selected_date[0]).to_period('M').to_timestamp()
    end_date = pd.to_datetime(selected_date[1]).to_period('M').to_timestamp()

    return selected_rep, combined, start_date, end_date

# Plot multi-line helper
def plot_multiline(df, y_col, title, start_date, end_date):
    if 'representation_status' in df.columns:
        fig = px.line(
            df,
            x='year_month',
            y=y_col,
            color='representation_status',
            title=title,
            labels={'year_month': 'Date', y_col: title, 'representation_status': 'Representation'}
        )
    else:
        fig = px.line(
            df,
            x='year_month',
            y=y_col,
            title=title,
            labels={'year_month': 'Date', y_col: title}
        )
    fig.update_layout(legend_title_text='Representation Status')
    fig.update_xaxes(range=[start_date, end_date], constrain='domain')
    for trace in fig.data:
        trace.hovertemplate = '%{y:,.0f}<extra></extra>'
    st.plotly_chart(fig, use_container_width=True)

# --- Home Page ---
def home_page():
    df = get_data()
    render_header("OIC Portal Data")

    # CSS for dropdown sizing
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] {
            max-width: 300px;
            min-width: 150px;
        }
        div[data-baseweb="select"] svg {
            width: 14px !important;
            height: 14px !important;
            padding: 2px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    selected_rep, combined, start_date, end_date = filters_ui(df)

    # Filter and aggregate for main charts on Home page
    if combined or len(selected_rep) == 0:
        filtered_df = df.copy()
        filtered_df = filtered_df.groupby('year_month', as_index=False).agg({
            'claims_volume': 'sum',
            'settlement_volume': 'sum',
            'total_settlement_value': 'sum',
        })
        filtered_df = filtered_df[
            (filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)
        ]
        date_range = pd.date_range(start=start_date, end=end_date, freq='MS').to_period('M').to_timestamp()
        filtered_df = filtered_df.set_index('year_month').reindex(date_range, fill_value=0).rename_axis('year_month').reset_index()
        filtered_df['weighted_avg_settlement'] = filtered_df.apply(
            lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
            axis=1
        )
        plot_df = filtered_df.copy()
    else:
        filtered_df = df[df['representation_status'].isin(selected_rep)].copy()
        filtered_df = filtered_df[
            (filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)
        ]
        agg_df = filtered_df.groupby(['year_month', 'representation_status'], as_index=False).agg({
            'claims_volume': 'sum',
            'settlement_volume': 'sum',
            'total_settlement_value': 'sum',
        })
        date_range = pd.date_range(start=start_date, end=end_date, freq='MS').to_period('M').to_timestamp()
        full_index = pd.MultiIndex.from_product(
            [date_range, selected_rep],
            names=['year_month', 'representation_status']
        )
        agg_df = agg_df.set_index(['year_month', 'representation_status']).reindex(full_index, fill_value=0).reset_index()
        agg_df['weighted_avg_settlement'] = agg_df.apply(
            lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
            axis=1
        )
        plot_df = agg_df.copy()

    # Summary
    st.subheader("Summary")
    total_claims = filtered_df['claims_volume'].sum()
    total_settled = filtered_df['settlement_volume'].sum()
    total_settlement_value = filtered_df['total_settlement_value'].sum()
    avg_settlement_amount = total_settlement_value / total_settled if total_settled > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Claims", f"{total_claims:,}")
    with col2:
        st.metric("Total Settled Claims", f"{int(total_settled):,}")
    with col3:
        st.metric("Total Settlement Value", f"£{total_settlement_value:,.0f}")
    with col4:
        st.metric("Average Settlement Amount", f"£{avg_settlement_amount:,.2f}")

    # 2x2 grid main charts
    col1, col2 = st.columns(2)
    with col1:
        #st.subheader("New Claims")
        plot_multiline(plot_df, 'claims_volume', 'New Claims', start_date, end_date)
    with col2:
        #st.subheader("Settled Claims")
        plot_multiline(plot_df, 'settlement_volume', 'Settled Claims', start_date, end_date)

    col3, col4 = st.columns(2)
    with col3:
        #st.subheader("Total Settlement")
        plot_multiline(plot_df, 'total_settlement_value', 'Total Settlement Value', start_date, end_date)
    with col4:
        #st.subheader("Average Settlement")
        plot_multiline(plot_df, 'weighted_avg_settlement', 'Average Settlement', start_date, end_date)

   

# --- NewClaim Analysis Page ---
def new_claim_analysis_page():
    df = get_data()
    render_header("NewClaim Analysis")

    # CSS for dropdown sizing
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] {
            max-width: 300px;
            min-width: 150px;
        }
        div[data-baseweb="select"] svg {
            width: 14px !important;
            height: 14px !important;
            padding: 2px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    selected_rep, combined, start_date, end_date = filters_ui(df)

    # Source of New Claims (Represented Only)
    source_df = get_source_data()
    # Move end_date to first day of next month for inclusive filtering
    end_date_next_month = (end_date + pd.offsets.MonthBegin(1))

    source_df = source_df[
        (source_df["year_month"] >= start_date) & (source_df["year_month"] < end_date_next_month)
    ]
    represented_types = [t for t in selected_rep if t not in ["Unrepresented", "Combined"]]

    st.subheader("Source of New Claims (Represented Only)")
    if represented_types:
        filtered_source_df = source_df[source_df["organisation_type"].isin([
            "Alternative Business Structure", "Claims Management Company", "Other", "UK Law Firm"
        ])]

        source_fig = px.bar(
            filtered_source_df,
            x="year_month",
            y="claims_volume",
            color="organisation_type",
            barmode="stack",
            labels={
                "year_month": "Date",
                "claims_volume": "Claim Volume",
                "organisation_type": "Organisation Type"
            },
            color_discrete_sequence=px.colors.qualitative.Safe
        )
        # --- Fix x-axis ticks here ---
        all_months = pd.date_range(start=start_date, end=end_date, freq='MS')
        source_fig.update_xaxes(
            tickvals=all_months,
            tickformat="%d %b",  # e.g. 01 Apr, 01 May, 01 Jun
            tickmode='array'
        )
        # ---------------------------

        source_fig.update_layout(
            margin=dict(l=40, r=40, t=40, b=40),
            legend_title_text=None,
            xaxis_title=None,
            yaxis_title=None
        )
        source_fig.update_traces(hovertemplate='%{y:,}<extra></extra>')
        st.plotly_chart(source_fig, use_container_width=True)
    else:
        st.info("This chart is only visible when a represented type is selected.")

    # Injury Type Breakdown
    st.subheader("Injury Type Breakdown")
    if combined:
        view_option = st.radio("View as:", ["Chart", "Data"], horizontal=True, key="injury_view")

        injury_df = pd.read_csv("assets/injury_breakdown.csv")
        injury_df["year_month"] = pd.to_datetime(injury_df["year"].astype(str) + "-" + injury_df["month"] + "-01")

        # Filter injury_df based on slider date range
        injury_df = injury_df[(injury_df["year_month"] >= start_date) & (injury_df["year_month"] <= end_date)]

        totals = injury_df.groupby("year_month")["claims_volume"].sum().reset_index(name="total_volume")
        merged_df = pd.merge(injury_df, totals, on="year_month")
        merged_df["percentage"] = (merged_df["claims_volume"] / merged_df["total_volume"]) * 100
        merged_df["label"] = merged_df["injury_group"] + " (" + merged_df["injury_type"] + ")"

        if view_option == "Chart":
            fig = px.line(
                merged_df,
                x="year_month",
                y="percentage",
                color="label",
                markers=True,
                title="Injury Breakdown Over Time (% of Total Claims)",
                labels={"percentage": "Percentage (%)", "year_month": "Month"},
                category_orders={"label": sorted(merged_df["label"].unique())}
            )
            fig.update_layout(
                yaxis_tickformat=".1f",
                xaxis_title="",
                yaxis_title="Percentage (%)",
                legend_title="Injury Type",
                hovermode="x unified",
                height=500
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.dataframe(
                merged_df[["year_month", "injury_group", "injury_type", "claims_volume", "percentage"]],
                use_container_width=True
            )
    else:
        st.info("This chart is only visible when 'Combined' (both represented and unrepresented) is selected.")


# --- Settlement Analysis Page ---
def settlement_analysis_page():
    df = get_data()
    render_header("Settlement Analysis")
    # CSS for dropdown sizing
    st.markdown(
        """
        <style>
        div[data-baseweb="select"] {
            max-width: 300px;
            min-width: 150px;
        }
        div[data-baseweb="select"] svg {
            width: 14px !important;
            height: 14px !important;
            padding: 2px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


    selected_rep, combined, start_date, end_date = filters_ui(df)

    # Claim Volumes and Averages by Injury Type
    st.markdown("## Claim Volumes and Averages by Injury Type")

    if combined or len(selected_rep) == 0:
        chart_df = df.copy()
    else:
        chart_df = df[df['representation_status'].isin(selected_rep)]

    group_cols = ['year_month']
    if not combined:
        group_cols.append('representation_status')

    grouped = chart_df.groupby(group_cols, as_index=False).agg({
        'vol_tariff_amount': 'sum',
        'avg_tariff_amount': 'mean',
        'vol_non_tariff': 'sum',
        'avg_non_tariff': 'mean',
        'vol_tariff_uplift': 'sum',
        'avg_tariff_uplift': 'mean'
    })

    metric_labels = {
        'vol_tariff_amount': 'Tariff Volume',
        'avg_tariff_amount': 'Tariff Average (£)',
        'vol_non_tariff': 'Non-Tariff Volume',
        'avg_non_tariff': 'Non-Tariff Average (£)',
        'vol_tariff_uplift': 'Tariff + Uplift Volume',
        'avg_tariff_uplift': 'Tariff + Uplift Average (£)'
    }

    if not combined and len(selected_rep) == 0:
        st.info("This chart is only visible when a representation type is selected.")
    else:
        for vol_metric, avg_metric in [
            ('vol_tariff_amount', 'avg_tariff_amount'),
            ('vol_non_tariff', 'avg_non_tariff'),
            ('vol_tariff_uplift', 'avg_tariff_uplift')
        ]:
            col1, col2 = st.columns(2)

            with col1:
                fig_vol = px.line(
                    grouped,
                    x='year_month',
                    y=vol_metric,
                    color='representation_status' if not combined else None,
                    title=metric_labels[vol_metric],
                    markers=True,
                    labels={'year_month': 'Month', vol_metric: 'Volume'}
                )
                fig_vol.update_layout(xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_vol, use_container_width=True)

            with col2:
                fig_avg = px.line(
                    grouped,
                    x='year_month',
                    y=avg_metric,
                    color='representation_status' if not combined else None,
                    title=metric_labels[avg_metric],
                    markers=True,
                    labels={'year_month': 'Month', avg_metric: 'Average (£)'}
                )
                fig_avg.update_layout(xaxis_title=None, yaxis_title=None)
                st.plotly_chart(fig_avg, use_container_width=True)

# --- Sidebar navigation ---
page = st.sidebar.radio("Select Page", ["Home", "NewClaim Analysis", "Settlement Analysis"])

if page == "Home":
    home_page()
elif page == "NewClaim Analysis":
    new_claim_analysis_page()
else:
    settlement_analysis_page()


# Footer (displayed on all pages)
st.markdown(
        """
        <hr style="margin-top: 3rem; margin-bottom: 1rem;">
        <footer style="font-size: 0.8rem; color: #666; text-align: center; padding-bottom: 1rem;">
            Data sourced from <a href="https://www.officialinjuryclaim.org.uk/resources-for-professionals/data/" target="_blank" rel="noopener noreferrer">Official Injury Claim</a> | Dashboard by <strong>InjuryIQ</strong>
        </footer>
        """,
        unsafe_allow_html=True,
    )
