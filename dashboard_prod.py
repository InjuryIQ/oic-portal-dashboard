
import streamlit as st
import pandas as pd
import plotly.express as px

# Remove DB secrets — not needed anymore
# Load data from CSV instead of database
@st.cache_data
def get_data():
    df = pd.read_csv("assets/oic_dashboard.csv")
    df['year_month'] = pd.to_datetime(df['year_month'])
    return df



# Reduce horizontal whitespace
st.markdown("""
    <style>
        .block-container {
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
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
            <h1 style="margin: 0;">OIC Portal Dashboard</h1>
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
df['year_month_date'] = df['year_month'].dt.date

# Filters on same row
representation_options = sorted(df['representation_status'].unique().tolist())
representation_options.insert(0, "All")  # Add 'All' at the start

filter_col1, filter_col2 = st.columns([1, 3])
with filter_col1:
    # Multi-select allowing 'All' or multiple representation statuses
    selected_rep = st.multiselect(
        "Representation",
        options=representation_options,
        default=["All"],
        help="Select one or more representation statuses. Select 'All' for combined totals."
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

# Filter data based on selections
if "All" in selected_rep or len(selected_rep) == 0:
    filtered_df = df.copy()
    filtered_df = filtered_df.groupby('year_month', as_index=False).agg({
        'claims_volume': 'sum',
        'settlement_volume': 'sum',
        'total_settlement_value': 'sum',
    })

    start_date = pd.to_datetime(selected_date[0])
    end_date = pd.to_datetime(selected_date[1])
    filtered_df = filtered_df[
        (filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)
    ]

    filtered_df['weighted_avg_settlement'] = filtered_df.apply(
        lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
        axis=1
    )

    plot_df = filtered_df.copy()

else:
    filtered_df = df[df['representation_status'].isin(selected_rep)].copy()

    start_date = pd.to_datetime(selected_date[0])
    end_date = pd.to_datetime(selected_date[1])
    filtered_df = filtered_df[
        (filtered_df['year_month'] >= start_date) & (filtered_df['year_month'] <= end_date)
    ]

    agg_df = filtered_df.groupby(['year_month', 'representation_status'], as_index=False).agg({
        'claims_volume': 'sum',
        'settlement_volume': 'sum',
        'total_settlement_value': 'sum',
    })

    agg_df['weighted_avg_settlement'] = agg_df.apply(
        lambda row: row['total_settlement_value'] / row['settlement_volume'] if row['settlement_volume'] > 0 else 0,
        axis=1
    )
    plot_df = agg_df.copy()

# Summary metrics
st.markdown(
    """
    <div style="position: sticky; top: 90px; background-color: white; z-index: 99; padding-top: 10px; padding-bottom: 10px; border-bottom: 1px solid #eee;">
    """,
    unsafe_allow_html=True
)
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
    st.metric("Total Settled Claims", f"{total_settled:,}")
with col3:
    st.metric("Total Settlement Value", f"£{total_settlement_value:,.0f}")
with col4:
    st.metric("Average Settlement Amount", f"£{avg_settlement_amount:,.2f}")
st.markdown("</div>", unsafe_allow_html=True)

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
    st.plotly_chart(fig, use_container_width=True)

# Layout: 2x2 grid for graphs
col1, col2 = st.columns(2)
with col1:
    st.subheader("New Claims Over Time")
    plot_multiline(plot_df, 'claims_volume', 'New Claims Over Time')

with col2:
    st.subheader("Settled Claims Over Time")
    plot_multiline(plot_df, 'settlement_volume', 'Settled Claims Over Time')

col3, col4 = st.columns(2)
with col3:
    st.subheader("Total Settlement Value Over Time")
    plot_multiline(plot_df, 'total_settlement_value', 'Total Settlement Value Over Time')

with col4:
    st.subheader("Average Settlement Amount Over Time")
    plot_multiline(plot_df, 'weighted_avg_settlement', 'Average Settlement Amount Over Time')
