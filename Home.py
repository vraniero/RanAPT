import streamlit as st
from db.schema import init_db

st.set_page_config(
    page_title="RanAPT",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize DB on every cold start
init_db()

# Initialize session state for thread tracking
if "active_threads" not in st.session_state:
    st.session_state.active_threads = {}

st.title("📊 RanAPT")
st.markdown(
    "**Portfolio Assessment Platform** — powered by Claude AI agents.\n\n"
    "Use the sidebar to navigate:\n"
    "- **New Assessment** — upload documents and run the analysis pipeline\n"
    "- **History** — browse past assessments and download PDF reports\n"
    "- **Agents** — create custom financial agents with their own goals and schedules\n"
    "- **Watch List** — calendar of upcoming market events from the Global Intelligence agent\n"
    "- **Data** — manage asset duplicates and merge rules\n"
    "- **Settings** — configure your API key and preferences"
)

st.info("Select a page from the sidebar to get started.")
