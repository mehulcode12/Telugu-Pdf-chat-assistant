import os
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai
import base64
from datetime import datetime, timedelta
import logging
import json
import hashlib

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

# Cost tracking - Updated for 300-page PDF with accurate Gemini 2.0 Flash pricing
# 300 pages × 1,290 tokens per page = 387,000 tokens
PDF_TOKENS = 387000  # 300-page PDF tokens
INPUT_COST_PER_1M_TOKENS = 0.15  # For prompts > 128K tokens
OUTPUT_COST_PER_1M_TOKENS = 0.60  # For prompts > 128K tokens
CONTEXT_CACHING_COST_PER_1M_TOKENS = 0.0375  # For prompts > 128K tokens (75% discount)
CONTEXT_CACHING_STORAGE_PER_HOUR = 0.01875  # Per 1M tokens per hour

# Cost breakdown for 300-page PDF
INITIAL_UPLOAD_COST = (PDF_TOKENS / 1_000_000) * INPUT_COST_PER_1M_TOKENS  # $0.05805
STORAGE_COST_PER_HOUR = (PDF_TOKENS / 1_000_000) * CONTEXT_CACHING_STORAGE_PER_HOUR  # $0.00725625
CACHED_CONTENT_COST_PER_QUERY = (PDF_TOKENS / 1_000_000) * CONTEXT_CACHING_COST_PER_1M_TOKENS  # $0.0145125

# Global cache settings - Extended TTL for shared usage
GLOBAL_CACHE_DURATION_HOURS = 24  # 24 hours for global cache
CACHE_STATUS_FILE = "global_cache_status.json"

# Initialize session state
if "total_input_tokens" not in st.session_state:
    st.session_state.total_input_tokens = 0
if "total_output_tokens" not in st.session_state:
    st.session_state.total_output_tokens = 0
if "total_cost" not in st.session_state:
    st.session_state.total_cost = 0.0
if "global_cache_creation_cost" not in st.session_state:
    st.session_state.global_cache_creation_cost = 0.0

def load_cache_status():
    """Load global cache status from file"""
    try:
        if os.path.exists(CACHE_STATUS_FILE):
            with open(CACHE_STATUS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading cache status: {e}")
    return None

def save_cache_status(cache_name, created_at, pdf_hash):
    """Save global cache status to file"""
    try:
        status = {
            "cache_name": cache_name,
            "created_at": created_at.isoformat(),
            "pdf_hash": pdf_hash,
            "ttl_hours": GLOBAL_CACHE_DURATION_HOURS
        }
        with open(CACHE_STATUS_FILE, 'w') as f:
            json.dump(status, f)
    except Exception as e:
        logger.error(f"Error saving cache status: {e}")

def get_pdf_hash():
    """Get hash of the PDF file to detect changes"""
    pdf_path = "Document.pdf"
    if not os.path.exists(pdf_path):
        return None
    
    with open(pdf_path, "rb") as file:
        content = file.read()
        return hashlib.md5(content).hexdigest()

def is_global_cache_valid():
    """Check if global cache is still valid"""
    status = load_cache_status()
    if not status:
        return False, None
    
    # Check if PDF has changed
    current_pdf_hash = get_pdf_hash()
    if current_pdf_hash != status.get("pdf_hash"):
        logger.info("PDF has changed, cache invalid")
        return False, None
    
    # Check if cache has expired
    created_at = datetime.fromisoformat(status["created_at"])
    elapsed = datetime.now() - created_at
    if elapsed.total_seconds() > (GLOBAL_CACHE_DURATION_HOURS * 3600):
        logger.info("Global cache expired")
        return False, None
    
    return True, status["cache_name"]

def get_global_cache_status():
    """Get status of global cache for display"""
    is_valid, cache_name = is_global_cache_valid()
    if not is_valid:
        return "No global cache", "red"
    
    status = load_cache_status()
    if status:
        created_at = datetime.fromisoformat(status["created_at"])
        elapsed = datetime.now() - created_at
        remaining = (GLOBAL_CACHE_DURATION_HOURS * 3600) - elapsed.total_seconds()
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return f"Global cache valid ({hours}h {minutes}m)", "green"
    
    return "Global cache error", "red"

def calculate_cost(input_tokens, output_tokens, operation_type="query", cache_hours=0):
    """
    Calculate cost based on operation type and token usage
    operation_type: "initial_upload", "query", "storage"
    """
    if operation_type == "initial_upload":
        # Initial PDF upload cost
        return INITIAL_UPLOAD_COST
    
    elif operation_type == "query":
        # Query cost: cached content + new input + output
        cached_content_cost = CACHED_CONTENT_COST_PER_QUERY
        
        # New input cost (user question)
        if input_tokens <= 128000:
            input_cost = (input_tokens / 1_000_000) * 0.075  # Standard rate for ≤128K
        else:
            input_cost = (input_tokens / 1_000_000) * INPUT_COST_PER_1M_TOKENS
        
        # Output cost
        if output_tokens <= 128000:
            output_cost = (output_tokens / 1_000_000) * 0.30  # Standard rate for ≤128K
        else:
            output_cost = (output_tokens / 1_000_000) * OUTPUT_COST_PER_1M_TOKENS
        
        return cached_content_cost + input_cost + output_cost
    
    elif operation_type == "storage":
        # Storage cost per hour
        return cache_hours * STORAGE_COST_PER_HOUR
    
    return 0.0

def log_api_call(operation, input_tokens, output_tokens, operation_type="query", cache_hours=0):
    cost = calculate_cost(input_tokens, output_tokens, operation_type, cache_hours)
    st.session_state.total_input_tokens += input_tokens
    st.session_state.total_output_tokens += output_tokens
    st.session_state.total_cost += cost
    
    # Log to file
    log_message = f"""
    API Call: {operation}
    - Operation Type: {operation_type}
    - Input Tokens: {input_tokens:,}
    - Output Tokens: {output_tokens:,}
    - Cache Hours: {cache_hours}
    - Cost: ${cost:.6f}
    - Running Total: ${st.session_state.total_cost:.6f}
    """
    logger.info(log_message)
    
    # Print to terminal
    print(f"💰 Cost: ${cost:.6f} | Total: ${st.session_state.total_cost:.6f}")
    
    # Display in Streamlit
    st.info(f"""
    📊 **API Call: {operation}**
    - Operation: {operation_type}
    - Input Tokens: {input_tokens:,}
    - Output Tokens: {output_tokens:,}
    - Cache Hours: {cache_hours}
    - Cost: ${cost:.6f}
    - **Running Total: ${st.session_state.total_cost:.6f}**
    """)

def load_stored_pdf():
    """Load the pre-stored PDF file from the project directory"""
    pdf_path = "Document.pdf"
    if not os.path.exists(pdf_path):
        st.error(f"❌ Document.pdf not found in the project directory!")
        return None
    
    with open(pdf_path, "rb") as file:
        return file.read()

def create_global_pdf_cache():
    """Create global cache from the pre-stored PDF file"""
    file_bytes = load_stored_pdf()
    if file_bytes is None:
        return None
        
    pdf_base64 = base64.b64encode(file_bytes).decode('utf-8')
    pdf_hash = get_pdf_hash()
    
    # Add additional text to meet minimum token requirement (4096 tokens)
    additional_text = "Please analyze this PDF document thoroughly. " * 2  # Add context to meet minimum tokens
    
    pdf_content = {
        "role": "user",
        "parts": [
            {"text": f"Here is the PDF document to analyze: {additional_text}"},
            {"inline_data": {"mime_type": "application/pdf", "data": pdf_base64}}
        ]
    }
    
    # Create unique cache name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cache_name = f"global_pdf_cache_{timestamp}"
    
    cache = genai.caching.CachedContent.create(
        model="models/gemini-2.0-flash-001",
        display_name=cache_name,
        system_instruction="You are an expert document analyzer with proficiency in both English and Telugu. Answer user questions based on the PDF document you have access to. Always provide responses in both formal English and formal Telugu when requested.",
        contents=[pdf_content],
        ttl=timedelta(hours=GLOBAL_CACHE_DURATION_HOURS),
    )
    
    # Save cache status
    save_cache_status(cache.name, datetime.now(), pdf_hash)
    
    # Log initial upload cost
    log_api_call("Global Cache Creation", PDF_TOKENS, 0, "initial_upload", GLOBAL_CACHE_DURATION_HOURS)
    st.session_state.global_cache_creation_cost = INITIAL_UPLOAD_COST
    
    return cache

def get_or_create_global_cache():
    """Get existing global cache or create new one"""
    is_valid, cache_name = is_global_cache_valid()
    
    if is_valid and cache_name:
        # Try to retrieve existing cache
        try:
            cache = genai.caching.CachedContent.get(cache_name)
            logger.info(f"Using existing global cache: {cache_name}")
            return cache
        except Exception as e:
            logger.error(f"Error retrieving cache {cache_name}: {e}")
            # Fall through to create new cache
    
    # Create new global cache
    logger.info("Creating new global cache")
    return create_global_pdf_cache()

def get_token_count(text):
    """Get accurate token count using Gemini API"""
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-001')
        # Use count_tokens method if available
        if hasattr(model, 'count_tokens'):
            result = model.count_tokens(text)
            return result.total_tokens
        else:
            # Fallback to approximation
            return len(text) // 4
    except Exception as e:
        logger.warning(f"Could not get exact token count: {e}")
        return len(text) // 4

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
    
    English (Formal):
    [Your detailed answer in formal English]
    
    Telugu (Formal):
    [Your detailed answer in formal Telugu]
    
    Make sure both responses are comprehensive and professional and complete.
    """
    
    conversation.append(bilingual_prompt)
    
    response = model.generate_content(conversation)
    
    # Get accurate token counts
    input_tokens = get_token_count(bilingual_prompt)
    output_tokens = get_token_count(response.text)
    
    log_api_call("Question Answering", input_tokens, output_tokens, "query")
    
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
st.title("Indiramma Indlu Scheme – Ask a Question")
st.markdown("Ask your query about the Indiramma Indlu Scheme and let our AI assist you with instant answers.")
st.markdown("If you want the response in a specific format (e.g., summary, list, step-by-step), just mention it in your message.")

# Display global cache status
cache_status, status_color = get_global_cache_status()
# st.markdown(f"""
# <div style="padding: 10px; background-color: {'#d4edda' if status_color == 'green' else '#f8d7da'}; 
#             border: 1px solid {'#c3e6cb' if status_color == 'green' else '#f5c6cb'}; 
#             border-radius: 4px; margin: 10px 0;">
#     <strong>🔄 Global Cache Status:</strong> {cache_status}
# </div>
# """, unsafe_allow_html=True)

# Calculate daily costs for different user scenarios
def calculate_daily_cost(num_users, queries_per_user=10):
    """Calculate daily cost for given number of users"""
    # Storage cost per day (24 hours)
    daily_storage = STORAGE_COST_PER_HOUR * 24  # $0.17415
    
    # Per query cost (cached content + typical input/output)
    # Assuming 100 tokens input and 300 tokens output per query
    input_tokens_per_query = 100
    output_tokens_per_query = 300
    
    # Input cost (≤128K rate)
    input_cost_per_query = (input_tokens_per_query / 1_000_000) * 0.075  # $0.0000075
    
    # Output cost (≤128K rate)
    output_cost_per_query = (output_tokens_per_query / 1_000_000) * 0.30  # $0.00009
    
    # Total per query cost
    total_per_query = CACHED_CONTENT_COST_PER_QUERY + input_cost_per_query + output_cost_per_query  # $0.01461
    
    # Daily query cost
    total_queries = num_users * queries_per_user
    daily_query_cost = total_queries * total_per_query
    
    # Total daily cost
    total_daily_cost = daily_storage + daily_query_cost
    
    return {
        'users': num_users,
        'queries_per_user': queries_per_user,
        'total_queries': total_queries,
        'daily_storage': daily_storage,
        'daily_query_cost': daily_query_cost,
        'total_daily_cost': total_daily_cost,
        'cost_per_user': total_daily_cost / num_users if num_users > 0 else 0
    }

# Calculate costs for different scenarios
scenarios = [10, 20, 50, 70, 100]
cost_breakdowns = [calculate_daily_cost(users) for users in scenarios]

# Log cost breakdown to file (not displayed in Streamlit)
def log_cost_breakdown():
    """Log cost breakdown to a separate file for analysis"""
    cost_analysis = f"""
=== GEMINI API COST ANALYSIS FOR 300-PAGE PDF ===
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

COST BREAKDOWN:
• Initial Upload: $0.05805 (one-time)
• Storage: $0.00725625/hour ($0.17415/day)
• Per Query: $0.0145125 (cached) + input/output costs

DAILY COST ESTIMATES (10 queries per user):
"""
    
    for breakdown in cost_breakdowns:
        cost_analysis += f"""
Users: {breakdown['users']}
- Total Queries: {breakdown['total_queries']}
- Storage Cost: ${breakdown['daily_storage']:.5f}
- Query Cost: ${breakdown['daily_query_cost']:.2f}
- Total Daily: ${breakdown['total_daily_cost']:.2f}
- Cost/User: ${breakdown['cost_per_user']:.4f}
"""
    
    cost_analysis += f"""
COST EFFICIENCY INSIGHTS:
• Higher user counts reduce per-user cost due to shared storage
• 100 users: ~$0.1478 per user per day
• 10 users: ~$0.1619 per user per day
• Global caching saves ~96% compared to individual caches

STORAGE SHARING BENEFITS:
• Fixed storage cost ($0.17415/day) shared across all users
• More users = lower per-user storage cost
• Economies of scale with global caching
"""
    
    # Write to cost analysis file
    with open('cost_analysis.txt', 'w') as f:
        f.write(cost_analysis)
    
    # Also log to main log file
    logger.info("Cost analysis written to cost_analysis.txt")

# Generate cost analysis file
log_cost_breakdown()

# Reset button in header
col1, col2, col3 = st.columns([1, 1, 1])
with col2:
   pass

# Empty sidebar - clean and minimal
with st.sidebar:
    pass

# Initialize session state
if "global_pdf_cache" not in st.session_state:
    st.session_state.global_pdf_cache = None
if "session_started" not in st.session_state:
    st.session_state.session_started = False
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Start Session Section
if not st.session_state.session_started:
    # Check if global cache is already valid
    is_valid, _ = is_global_cache_valid()
    
    if is_valid:
        # Auto-start session if global cache is valid
        with st.spinner("⏳ Loading global cache..."):
            st.session_state.global_pdf_cache = get_or_create_global_cache()
            if st.session_state.global_pdf_cache:
                st.session_state.session_started = True
                st.rerun()
    else:
        # Show start button only if no valid cache exists
        st.markdown("Click the button below to initialize the AI assistant with the document.")
        
        col1, col2, col3 = st.columns([2, 1, 2])
        with col2:
            if st.button("🚀 Start Session", type="primary", use_container_width=True):
                with st.spinner("⏳ Loading document and creating global cache..."):
                    st.session_state.global_pdf_cache = get_or_create_global_cache()
                    if st.session_state.global_pdf_cache:
                        st.session_state.session_started = True
                        st.rerun()
else:
    # Check if global cache is still valid
    is_valid, _ = is_global_cache_valid()
    if not is_valid:
        st.warning("⚠️ Global cache expired or invalid. Refreshing...")
        with st.spinner("⏳ Refreshing global cache..."):
            st.session_state.global_pdf_cache = get_or_create_global_cache()
            if not st.session_state.global_pdf_cache:
                st.session_state.session_started = False
                st.rerun()

# Chat Interface
if st.session_state.session_started and st.session_state.global_pdf_cache:
    #st.markdown("Ask your questions")
    
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
            question = st.text_input("Ask a question:", placeholder="Type your question here...", key="question_input")
        with col2:
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)  # Add some spacing
            send_button = st.button("Send", type="primary", use_container_width=True)
        
        if send_button and question.strip():
            with st.spinner("🤔 Generating answer..."):
                answer = ask_question(st.session_state.global_pdf_cache, st.session_state.chat_history, question)
            st.session_state.chat_history.append((question, answer))
            st.rerun()

elif st.session_state.session_started and not st.session_state.global_pdf_cache:
    # This case is handled above in the Start Session Section
    pass
