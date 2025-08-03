import os
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import base64
from datetime import datetime, timedelta
import logging

# Load API Key
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    st.error("❌ GEMINI_API_KEY not found in .env file")
    st.stop()

genai.configure(api_key=API_KEY)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('api_calls.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Cost tracking - Updated to match actual Google AI Studio pricing
INPUT_COST_PER_1M_TOKENS = 0.35  # Paid level for text input
OUTPUT_COST_PER_1M_TOKENS = 1.50  # Paid level for text output
CONTEXT_CACHING_COST_PER_1M_TOKENS = 0.025  # Context caching for text/image/video
CONTEXT_CACHING_STORAGE_PER_HOUR = 1.00  # Mass storage per hour
PDF_COST_PER_FILE = 0.10  # Enter price for text/image/video

CACHE_DURATION_MINUTES = 10

# Initialize session state
if "total_input_tokens" not in st.session_state:
    st.session_state.total_input_tokens = 0
if "total_output_tokens" not in st.session_state:
    st.session_state.total_output_tokens = 0
if "total_cost" not in st.session_state:
    st.session_state.total_cost = 0.0
if "cache_creation_cost" not in st.session_state:
    st.session_state.cache_creation_cost = 0.0
if "cache_created_at" not in st.session_state:
    st.session_state.cache_created_at = None

def is_cache_expired():
    if st.session_state.cache_created_at is None:
        return True
    elapsed = datetime.now() - st.session_state.cache_created_at
    return elapsed.total_seconds() > (CACHE_DURATION_MINUTES * 60)

def get_cache_status():
    if st.session_state.cache_created_at is None:
        return "No cache", "red"
    if is_cache_expired():
        return "Cache expired", "red"
    elapsed = datetime.now() - st.session_state.cache_created_at
    remaining = (CACHE_DURATION_MINUTES * 60) - elapsed.total_seconds()
    minutes = int(remaining // 60)
    seconds = int(remaining % 60)
    return f"Cache valid ({minutes}:{seconds:02d})", "green"

def calculate_cost(input_tokens, output_tokens, pdf_count=0, cache_tokens=0, cache_hours=0):
    input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_1M_TOKENS
    output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_1M_TOKENS
    pdf_cost = pdf_count * PDF_COST_PER_FILE
    cache_cost = (cache_tokens / 1_000_000) * CONTEXT_CACHING_COST_PER_1M_TOKENS
    storage_cost = cache_hours * CONTEXT_CACHING_STORAGE_PER_HOUR
    return input_cost + output_cost + pdf_cost + cache_cost + storage_cost

def log_api_call(operation, input_tokens, output_tokens, pdf_count=0, cache_tokens=0, cache_hours=0):
    cost = calculate_cost(input_tokens, output_tokens, pdf_count, cache_tokens, cache_hours)
    st.session_state.total_input_tokens += input_tokens
    st.session_state.total_output_tokens += output_tokens
    st.session_state.total_cost += cost
    
    # Log to file
    log_message = f"""
    API Call: {operation}
    - Input Tokens: {input_tokens:,}
    - Output Tokens: {output_tokens:,}
    - PDFs: {pdf_count}
    - Cache Tokens: {cache_tokens:,}
    - Cache Hours: {cache_hours}
    - Cost: ${cost:.4f}
    - Running Total: ${st.session_state.total_cost:.4f}
    """
    logger.info(log_message)
    
    # Print to terminal
    print(f"💰 Cost: ${cost:.4f} | Total: ${st.session_state.total_cost:.4f}")
    
    # Display in Streamlit
    st.info(f"""
    📊 **API Call: {operation}**
    - Input Tokens: {input_tokens:,}
    - Output Tokens: {output_tokens:,}
    - PDFs: {pdf_count}
    - Cache Tokens: {cache_tokens:,}
    - Cache Hours: {cache_hours}
    - Cost: {cost:.4f}
    - **Running Total: {st.session_state.total_cost:.4f}**
    """)

def create_pdf_cache(file_bytes):
    pdf_base64 = base64.b64encode(file_bytes).decode('utf-8')
    
    # Add additional text to meet minimum token requirement (4096 tokens)
    additional_text = "Please analyze this PDF document thoroughly. " * 200  # Add context to meet minimum tokens
    
    pdf_content = {
        "role": "user",
        "parts": [
            {"text": f"Here is the PDF document to analyze: {additional_text}"},
            {"inline_data": {"mime_type": "application/pdf", "data": pdf_base64}}
        ]
    }
    
    cache = genai.caching.CachedContent.create(
        model="models/gemini-2.0-flash-001",
        display_name="pdf_document_cache",
        system_instruction="You are an expert document analyzer with proficiency in both English and Telugu. Answer user questions based on the PDF document you have access to. Always provide responses in both formal English and formal Telugu when requested.",
        contents=[pdf_content],
        ttl=timedelta(minutes=CACHE_DURATION_MINUTES),
    )
    
    st.session_state.cache_created_at = datetime.now()
    
    estimated_input_tokens = len(pdf_base64) // 4
    text_tokens = len("Here is the PDF document:") // 4
    
    cache_cost = calculate_cost(
        input_tokens=estimated_input_tokens + text_tokens,
        output_tokens=0,
        pdf_count=1,
        cache_tokens=estimated_input_tokens + text_tokens,
        cache_hours=CACHE_DURATION_MINUTES/60
    )
    
    log_api_call("Cache Creation", estimated_input_tokens + text_tokens, 0, 1, estimated_input_tokens + text_tokens, CACHE_DURATION_MINUTES/60)
    st.session_state.cache_creation_cost = cache_cost
    
    return cache

def ask_question(cache, history, question):
    model = genai.GenerativeModel.from_cached_content(cached_content=cache)
    
    conversation = []
    for q, a in history:
        conversation.append(q)
        conversation.append(a)
    
    # Create prompt for bilingual response
    bilingual_prompt = f"""
    Please answer the following question in TWO languages:
    
    Question: {question}
    
    Please provide your response in the following format:
    
    **English (Formal):**
    [Your detailed answer in formal English]
    
    **Telugu (Formal):**
    [Your detailed answer in formal Telugu]
    
    Make sure both responses are comprehensive and professional.
    """
    
    conversation.append(bilingual_prompt)
    
    response = model.generate_content(conversation)
    
    input_text = bilingual_prompt + " ".join([q + " " + a for q, a in history])
    input_tokens = len(input_text) // 4
    output_tokens = len(response.text) // 4
    
    log_api_call("Question Answering", input_tokens, output_tokens)
    
    return response.text

# Streamlit UI
st.set_page_config(
    page_title="PDF Chat Assistant Telugu", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Force light mode with better contrast
st.markdown("""
<style>
    .stApp {
        background-color: white;
    }
    .main .block-container {
        background-color: white;
    }
    .stSidebar {
        background-color: white;
    }
    .stTextInput > div > div > input {
        background-color: white;
        border: 1px solid #ddd;
    }
    .stButton > button {
        background-color: #ff4b4b;
        color: white;
        border: none;
        border-radius: 4px;
        padding: 8px 16px;
    }
    
    /* Improve text contrast */
    h1, h2, h3, h4, h5, h6 {
        color: #1f1f1f !important;
        font-weight: 600 !important;
    }
    
    /* Make info boxes more readable */
    .stAlert {
        background-color: #e8f4fd !important;
        border: 1px solid #b3d9ff !important;
        color: #1f1f1f !important;
    }
    
    /* Improve success/warning messages */
    .stSuccess {
        background-color: #d4edda !important;
        border: 1px solid #c3e6cb !important;
        color: #155724 !important;
    }
    
    .stWarning {
        background-color: #fff3cd !important;
        border: 1px solid #ffeaa7 !important;
        color: #856404 !important;
    }
    
    .stError {
        background-color: #f8d7da !important;
        border: 1px solid #f5c6cb !important;
        color: #721c24 !important;
    }
    
    /* File uploader styling */
    .stFileUploader > div > div {
        border: 2px dashed #ddd !important;
        background-color: #f8f9fa !important;
        color: #1f1f1f !important;
    }
    
    /* Chat bubbles */
    .chat-user {
        background-color: #e3f2fd !important;
        border: 1px solid #bbdefb !important;
        color: #1f1f1f !important;
    }
    
    .chat-assistant {
        background-color: #f3e5f5 !important;
        border: 1px solid #e1bee7 !important;
        color: #1f1f1f !important;
    }
</style>
""", unsafe_allow_html=True)

# Main chat interface
st.title("💬 PDF Chat Assistant")
st.markdown("---")

# Reset button in header
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
    if st.button("🔄 Reset Session", type="secondary", use_container_width=True):
        # Clear all session state
        st.session_state.pdf_cache = None
        st.session_state.pdf_uploaded = False
        st.session_state.chat_history = []
        st.session_state.total_input_tokens = 0
        st.session_state.total_output_tokens = 0
        st.session_state.total_cost = 0.0
        st.session_state.cache_creation_cost = 0.0
        st.session_state.cache_created_at = None
        # Clear file uploader by resetting the key
        st.session_state.file_uploader_key = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info("Session reset by user - ready for new PDF upload")
        st.rerun()

# Empty sidebar - clean and minimal
with st.sidebar:
    pass

# Initialize session state
if "pdf_cache" not in st.session_state:
    st.session_state.pdf_cache = None
if "pdf_uploaded" not in st.session_state:
    st.session_state.pdf_uploaded = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "file_uploader_key" not in st.session_state:
    st.session_state.file_uploader_key = datetime.now().strftime("%Y%m%d_%H%M%S")

# PDF Upload Section
with st.container():
    uploaded_pdf = st.file_uploader("📄 Upload PDF Document", type=["pdf"], key=st.session_state.file_uploader_key)
    
    if uploaded_pdf and not st.session_state.pdf_uploaded:
        with st.spinner("⏳ Processing PDF and creating cache..."):
            st.session_state.pdf_cache = create_pdf_cache(uploaded_pdf.read())
            st.session_state.pdf_uploaded = True
        st.success("✅ PDF cached successfully! You can now chat with it.")
        st.warning(f"⚠️ Cache expires in {CACHE_DURATION_MINUTES} minutes. Re-upload if needed.")

# Chat Interface
if st.session_state.pdf_cache and not is_cache_expired():
    st.markdown("### 💬 Chat with your PDF")
    
    # Display chat history in a chat-like format
    for i, (q, a) in enumerate(st.session_state.chat_history):
        with st.container():
            # User message
            st.markdown(f"""
            <div class="chat-user" style="padding: 12px; border-radius: 12px; margin: 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <strong style="color: #1976d2;">🧑 You:</strong><br>
                <span style="color: #1f1f1f;">{q}</span>
            </div>
            """, unsafe_allow_html=True)
            
            # Assistant message
            st.markdown(f"""
            <div class="chat-assistant" style="padding: 12px; border-radius: 12px; margin: 8px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                <strong style="color: #7b1fa2;">🤖 Assistant:</strong><br>
                <span style="color: #1f1f1f;">{a}</span>
            </div>
            """, unsafe_allow_html=True)
    
    # Chat input
    with st.container():
        # Create a better layout for input and button
        st.markdown("""
        <style>
        .chat-input-container {
            display: flex;
            align-items: end;
            gap: 10px;
            margin-top: 20px;
        }
        .chat-input-container .stTextInput {
            flex: 1;
        }
        .chat-input-container .stButton {
            margin-top: 0;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Use columns with better proportions
        col1, col2 = st.columns([5, 1])
        with col1:
            question = st.text_input("Ask a question about the PDF:", placeholder="Type your question here...", key="question_input")
        with col2:
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)  # Add some spacing
            send_button = st.button("Send", type="primary", use_container_width=True)
        
        if send_button and question.strip():
            with st.spinner("🤔 Generating answer..."):
                answer = ask_question(st.session_state.pdf_cache, st.session_state.chat_history, question)
            st.session_state.chat_history.append((question, answer))
            st.rerun()

elif st.session_state.pdf_cache and is_cache_expired():
    st.error("❌ Cache has expired. Please re-upload the PDF to continue.")
    st.session_state.pdf_uploaded = False
    st.session_state.pdf_cache = None
else:
    st.info("📄 Please upload a PDF document to start chatting!")
