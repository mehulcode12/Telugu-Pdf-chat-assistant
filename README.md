# 💬 PDF Chat Assistant with Telugu Support

A Streamlit application that allows users to chat with PDF documents using Google's Gemini AI model, with bilingual responses in English and Telugu.

## 🌟 Features

- **📄 PDF Processing**: Direct PDF upload and caching
- **🌐 Bilingual Support**: Responses in both English and Telugu
- **💾 Context Caching**: Efficient document caching for cost optimization
- **💰 Cost Tracking**: Real-time API cost monitoring
- **🎨 Professional UI**: Clean, modern interface
- **🔄 Session Reset**: Easy session management

## 🚀 Quick Start

### Local Development
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Create `.env` file with your API key:
   ```
   GEMINI_API_KEY=your-api-key-here
   ```
4. Run: `streamlit run main.py`

### Cloud Deployment
See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed deployment instructions.

## 🔐 Security

- **API Key Protection**: Environment variables for secure key management
- **No Hardcoded Secrets**: All sensitive data stored securely
- **Git Ignore**: Sensitive files excluded from version control

## 📊 Cost Optimization

- **Context Caching**: Reduces API costs for repeated queries
- **10-minute TTL**: Optimal cache duration for cost efficiency
- **Token Tracking**: Real-time cost monitoring
- **Direct PDF Processing**: No OCR dependencies

## 🛠️ Technical Stack

- **Streamlit**: Web application framework
- **Google Generative AI**: Gemini 2.0 Flash model
- **Context Caching**: Efficient document storage
- **Python**: Backend processing

## 📁 Project Structure

```
├── main.py                 # Main Streamlit application
├── requirements.txt        # Python dependencies
├── .streamlit/
│   └── config.toml       # Streamlit configuration
├── .gitignore            # Git ignore rules
├── DEPLOYMENT.md         # Deployment guide
└── README.md             # This file
```

## 🔧 Configuration

### Environment Variables
- `GEMINI_API_KEY`: Your Google AI Studio API key

### Streamlit Configuration
- **Theme**: Light mode with custom styling
- **Upload Limit**: 200MB per file
- **CORS**: Disabled for security

## 📈 Monitoring

- **File Logging**: `api_calls.log` for API call tracking
- **Terminal Output**: Real-time cost display
- **Streamlit Cloud**: Built-in monitoring dashboard

## 🆘 Support

For deployment issues, see [DEPLOYMENT.md](DEPLOYMENT.md).
For technical questions, check the Streamlit documentation.

## 📄 License

This project is open source and available under the MIT License. 