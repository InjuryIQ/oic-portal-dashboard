import streamlit as st
import pandas as pd
import plotly.express as px

# Load data from CSV instead of database (SD - easier at this stage)
@st.cache_data
def get_data():
    df = pd.read_csv("assets/oic_dashboard.csv")
    df['year_month'] = pd.to_datetime(df['year_month']).dt.to_period('M').dt.to_timestamp()
    return df

# Reduce horizontal whitespace
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 2rem;
            padding-right: 2rem;
            max-width: 1200px;
            margin: auto;
        }
    </style>
""", unsafe_allow_html=True)

# Load SVG logo content from assets folder
with open("assets/injuryiq.svg", "r") as file:
    svg_content = file.read()

# Sticky Header with logo and title
st.markdown(
    f"""
    <div style="position: sticky; top: 0; background-color: white; z-index: 100; padding-top: 10px; padding-bottom: 10px; border-bottom: 1px solid #ddd;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <h1 style="margin: 0;">OIC Portal Data</h1>
            <div style="width: 150px; height: auto;">
                {svg_content}
            </div>
        </div>
    </div>
    <style>
        div > div > svg {{
            width: 100% !important;
            height: auto !important;
        }}
    </style>
    """,
    unsafe_allow_html=True,
)

# CSS adjustments for dropdown sizing and clear icon
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

df = get_data()
# Ensure 'year_month' is normalized to first day of month
df['year_month'] = pd.to_datetime(df['year_month']).dt.to_period('M').dt.to_timestamp()
df['year_month_date'] = df['year_month'].dt.date

# Add Filters on same row to save space
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

with filter_col2:
    min_date = df['year_month_date'].min()
    max_date = df['year_month_date'].max()
    selected_date = st.slider(
        "Date Range",
        min_value=min_date,
        max_value=max_date,
        value=(min_date, max_date),
        format="MMM YYYY"
    )

start_date = pd.to_datetime(selected_date[0]).to_period('M').to_timestamp()
end_date = pd.to_datetime(selected_date[1]).to_period('M').to_timestamp()
date_range = pd.date_range(start=start_date, end=end_date, freq='MS').to_period('M').to_timestamp()

# Filter data based on selections and reindex to full date range
if "Combined" in selected_rep or len(selected_rep) == 0:
    filtered_df = df.copy()
    filtered_df = filtered_df.groupby('year_month', as_index=False).agg({
        'claims_volume': 'sum',
        'settlement_volume': 'sum',
        'total_settlement_value': 'sum',
    })

    filtered_df = filtered_df[
        (filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)
    ]

    # Reindex by full monthly range and fill missing with zeros
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

    # Create full MultiIndex for all months × selected reps
    reps = selected_rep if "Combined" not in selected_rep else representation_options[1:]  # exclude 'Combined'

    full_index = pd.MultiIndex.from_product(
        [date_range, reps],
        names=['year_month', 'representation_status']
    )

    agg_df = agg_df.set_index(['year_month', 'representation_status']).reindex(full_index, fill_value=0).reset_index()

    agg_df['weighted_avg_settlement'] = agg_df.apply(
        lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
        axis=1
    )
    plot_df = agg_df.copy()

# Summary section (no raw div wrappers)
st.subheader("Summary")

total_claims = filtered_df['claims_volume'].sum()
total_settled = filtered_df['settlement_volume'].sum()
total_settlement_value = filtered_df['total_settlement_value'].sum()
avg_settlement_amount = (
    total_settlement_value / total_settled if total_settled > 0 else 0
)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Claims", f"{total_claims:,}")
with col2:
    st.metric("Total Settled Claims", f"{int(total_settled):,}")
with col3:
    st.metric("Total Settlement Value", f"£{total_settlement_value:,.0f}")
with col4:
    st.metric("Average Settlement Amount", f"£{avg_settlement_amount:,.2f}")

# Function to plot multi-line chart using Plotly Express
def plot_multiline(df, y_col, title):
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

    # Force x-axis range to the selected date range, so all months are visible
    fig.update_xaxes(range=[start_date, end_date], constrain='domain')

    # Format hover to use comma separators and no decimals
    for trace in fig.data:
        trace.hovertemplate = '%{y:,.0f}<extra></extra>'

    st.plotly_chart(fig, use_container_width=True)

# Layout: 2x2 grid for graphs
col1, col2 = st.columns(2)
with col1:
    st.subheader("New Claims Over Time")
    plot_multiline(plot_df, 'claims_volume', 'New Claims Total')

with col2:
    st.subheader("Settled Claims Over Time")
    plot_multiline(plot_df, 'settlement_volume', 'Settled Claims Total')

col3, col4 = st.columns(2)
with col3:
    st.subheader("Total Settlement Value Over Time")
    plot_multiline(plot_df, 'total_settlement_value', 'Total Settlement Value')

with col4:
    st.subheader("Average Settlement Amount Over Time")
    plot_multiline(plot_df, 'weighted_avg_settlement', 'Average Settlement Amount')

st.markdown(
    """
    <hr style="margin-top: 3rem; margin-bottom: 1rem;">
    <footer style="font-size: 0.8rem; color: #666; text-align: center; padding-bottom: 1rem;">
        Data sourced from <a href="https://www.officialinjuryclaim.org.uk/resources-for-professionals/data/" target="_blank" rel="noopener noreferrer">Official Injury Claim</a> | Dashboard by <strong>InjuryIQ</strong>
    </footer>
    """,
    unsafe_allow_html=True,
)
