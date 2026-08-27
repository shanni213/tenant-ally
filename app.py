#pip install streamlit
#streamlit run app.py
import os
import streamlit as st
from main import run_agent_loop

# Configure the browser tab title, icon, and alignment setup
st.set_page_config(
    page_title="Tenant Ally - Lease Auditor", page_icon="⚖️", layout="centered"
)
st.markdown(
    """
    <style>
        /* יישור כל עמודת התצוגה והווידג'טים מימין לשמאל */
        .stApp {
            direction: rtl;
        }
        /* יישור תוויות מעל שדות קלט (כמו text_area ו-file_uploader) */
        label, .stTextArea label, .stFileUploader label {
            text-align: right !important;
            direction: rtl !important;
            display: block;
        }
        /* כיווניות טקסט בתוך תיבות הקלט עצמן */
        textarea, input {
            direction: rtl !important;
            text-align: right !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# Render RTL-compatible HTML headers for the Hebrew user interface
st.markdown(
    "<h1 style='text-align: right;'>⚖️ Tenant Ally - עוזר השכירות שלך</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align: right;'>העלה את חוזה השכירות שלך או שאל שאלה כדי לבדוק חוקיות ותקינות מול חוק שכירות הוגנת בישראל.</p>",
    unsafe_allow_html=True,
)

# Text input area for free-form user queries or special instructions
user_query = st.text_area(
    "מה ברצונך לבדוק?",
    placeholder="לדוגמה: בעל הדירה דורש ערבות של 20,000 שח על שכירות של 4,000 שח, האם זה חוקי?",
    help="You can type a standalone question or add specific audit requests alongside a PDF upload.",
)

# File uploader widget restricting input strictly to PDF format
uploaded_file = st.file_uploader(
    "העלה חוזה שכירות בפורמט PDF (אופציונלי)", type=["pdf"]
)

# Execution trigger button
if st.button("הפעל ניתוח אייגנט"):
    # Enforce validation boundary: at least one input medium must be provided
    if not user_query and not uploaded_file:
        st.warning("אנא הקלד שאלה או העלה קובץ חוזה כדי להתחיל.")
    else:
        # Display an active loading indicator while the background agent processes tools
        with st.spinner(
            "האייגנט מנתח את הנתונים ומפעיל כלים משפטיים... אנא המתן."
        ):

            pdf_temp_path = None

            # Streamlit streams files into memory; persist locally so main.py can resolve the file path
            if uploaded_file is not None:
                pdf_temp_path = f"temp_{uploaded_file.name}"
                with open(pdf_temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

            # Fallback default prompt if the user uploads a document without typing instructions
            final_query = (
                user_query
                if user_query
                else "אנא נתח את חוזה השכירות המצורף, סכם אותו והצבע על ליקויים."
            )

            try:
                # Dispatch execution to the deterministic core agent loop
                result = run_agent_loop(
                    user_input=final_query, pdf_path=pdf_temp_path, max_steps=5
                )

                # Render the final model response back onto the user interface
                st.markdown(
                    "<h3 style='text-align: right;'>📋 תוצאות הניתוח:</h3>",
                    unsafe_allow_html=True,
                )
                st.info(result)

            except Exception as e:
                st.error(f"חלה שגיאה בהרצת האייגנט: {e}")

            finally:
                # Cleanup phase: remove volatile temporary files from local storage
                if pdf_temp_path and os.path.exists(pdf_temp_path):
                    os.remove(pdf_temp_path)
