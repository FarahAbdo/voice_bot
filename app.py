import os
import logging
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
import io
import wave
import numpy as np
from audio_recorder_streamlit import audio_recorder

# SETUP & LOGGING
logging.basicConfig(level=logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

load_dotenv()

# Get API key from environment or secrets
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    except:
        pass

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY")
    st.info("Add GEMINI_API_KEY to your .env file (local) or Streamlit secrets (cloud)")
    st.stop()

# SYSTEM PROMPT
SYSTEM_INSTRUCTION = (
    "You are a helpful and friendly voice assistant. "
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use colloquial words like: 'هسا', 'بدي', 'إيش', 'طيب', 'شو', 'كيف'. "
    "3. Keep responses short and conversational (1-2 sentences maximum). "
    "4. Be warm, natural, and immediate in your responses."
)

# Initialize Gemini client
@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

def convert_audio_to_pcm(audio_bytes, target_rate=16000):
    """Convert audio to PCM format for Gemini"""
    try:
        # Try to read as WAV
        audio_io = io.BytesIO(audio_bytes)
        with wave.open(audio_io, 'rb') as wav:
            # Get audio parameters
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            framerate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
            
        # Convert to numpy array
        if sample_width == 2:  # 16-bit
            audio_data = np.frombuffer(frames, dtype=np.int16)
        else:
            audio_data = np.frombuffer(frames, dtype=np.uint8)
            
        # Convert to mono if stereo
        if channels == 2:
            audio_data = audio_data.reshape(-1, 2).mean(axis=1).astype(np.int16)
        
        # Resample if needed
        if framerate != target_rate:
            from scipy import signal
            num_samples = int(len(audio_data) * target_rate / framerate)
            audio_data = signal.resample(audio_data, num_samples).astype(np.int16)
        
        return audio_data.tobytes()
        
    except Exception as e:
        st.error(f"Audio conversion error: {e}")
        return audio_bytes

def send_audio_to_gemini(audio_bytes):
    """Send audio to Gemini and get response"""
    try:
        client = get_gemini_client()
        
        # Configure for audio conversation
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            )
        )
        
        model_id = "gemini-2.0-flash-exp"
        
        # Synchronous conversation
        with client.live.connect(model=model_id, config=config) as session:
            # Send audio
            session.send(
                input={"data": audio_bytes, "mime_type": "audio/pcm;rate=16000"},
                end_of_turn=True
            )
            
            # Collect response
            audio_response = b""
            text_response = ""
            
            for response in session.receive():
                server_content = response.server_content
                
                if server_content and server_content.model_turn:
                    for part in server_content.model_turn.parts:
                        if part.inline_data:
                            audio_response += part.inline_data.data
                        if part.text:
                            text_response += part.text
                
                if server_content and server_content.turn_complete:
                    break
            
            return audio_response, text_response
            
    except Exception as e:
        return None, f"Error: {str(e)}"

# Streamlit UI
st.set_page_config(page_title="Gemini Voice Assistant", page_icon="🎤", layout="wide")

# Header
st.title("🎤 Gemini Voice Assistant")
st.caption("🇯🇴 Jordanian Arabic Dialect | Pure Streamlit - Cloud Ready")

# Deployment info
is_cloud = os.getenv('STREAMLIT_SHARING_MODE') is not None
if is_cloud:
    st.success("☁️ Running on Streamlit Cloud")
else:
    st.info("💻 Running Locally")

# Initialize session state
if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []
if 'audio_responses' not in st.session_state:
    st.session_state.audio_responses = []

# Main interface
st.subheader("🎙️ Record Your Voice")

# Audio recorder
st.info("👇 Click the microphone button below to start recording. Click again to stop.")

audio_bytes = audio_recorder(
    text="",
    recording_color="#e74c3c",
    neutral_color="#3498db",
    icon_name="microphone",
    icon_size="3x",
    pause_threshold=2.0,
    sample_rate=16000,
    key="audio_recorder"
)

# Process recorded audio
if audio_bytes and audio_bytes != st.session_state.get('last_audio'):
    st.session_state.last_audio = audio_bytes
    
    with st.spinner("🤔 Processing your voice..."):
        # Convert audio
        pcm_audio = convert_audio_to_pcm(audio_bytes)
        
        # Send to Gemini
        audio_response, text_response = send_audio_to_gemini(pcm_audio)
        
        # Store in history
        timestamp = st.session_state.get('message_count', 0)
        st.session_state.message_count = timestamp + 1
        
        st.session_state.conversation_history.append({
            'user_audio': audio_bytes,
            'bot_text': text_response,
            'bot_audio': audio_response,
            'timestamp': timestamp
        })
        
        st.rerun()

# Display conversation
st.divider()
st.subheader("💬 Conversation")

if st.session_state.conversation_history:
    # Show most recent conversations (last 5)
    for i, conv in enumerate(reversed(st.session_state.conversation_history[-5:])):
        with st.container():
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.markdown("**👤 You said:**")
                if conv.get('user_audio'):
                    st.audio(conv['user_audio'], format='audio/wav')
            
            with col2:
                st.markdown("**🤖 Bot replied:**")
                if conv.get('bot_text'):
                    st.info(conv['bot_text'])
                if conv.get('bot_audio'):
                    st.audio(conv['bot_audio'], format='audio/pcm')
            
            st.divider()
    
    # Clear button
    if st.button("🗑️ Clear Conversation"):
        st.session_state.conversation_history = []
        st.session_state.audio_responses = []
        st.rerun()
else:
    st.write("_No conversation yet. Record your voice above to start!_")

# Instructions
with st.expander("📖 Instructions & Tips"):
    st.markdown("""
    ### How to Use:
    1. **Click the microphone button** to start recording
    2. **Speak in Jordanian Arabic** (use words like هسا، بدي، إيش)
    3. **Click the microphone again** to stop recording
    4. Wait for the bot's voice response
    5. Your conversation will appear below
    
    ### Tips for Best Results:
    - 🎧 Use headphones to avoid audio feedback
    - 🔊 Speak clearly and at normal volume
    - ⏱️ Keep your messages short (5-10 seconds)
    - 🌐 Ensure stable internet connection
    - 🔒 Allow microphone permissions when prompted
    
    ### Troubleshooting:
    - **No microphone button?** Refresh the page
    - **Recording not working?** Check browser permissions
    - **No audio playback?** Check your device volume
    - **Error messages?** Verify GEMINI_API_KEY is set correctly
    
    ### Cloud Deployment:
    To deploy on Streamlit Cloud:
    1. Push your code to GitHub
    2. Connect to Streamlit Cloud
    3. Add to secrets:
       ```toml
       GEMINI_API_KEY = "your_api_key"
       ```
    4. Deploy!
    """)

# Requirements info
with st.expander("📦 Dependencies"):
    st.markdown("""
    ### Required Python Packages:
    ```txt
    streamlit>=1.31.0
    google-genai>=0.8.0
    python-dotenv>=1.0.0
    audio-recorder-streamlit>=0.0.8
    numpy>=1.24.0
    scipy>=1.10.0
    ```
    
    Install with:
    ```bash
    pip install -r requirements.txt
    ```
    """)

# Footer
st.divider()
cols = st.columns(3)
with cols[0]:
    st.caption("🚀 Powered by Gemini 2.0")
with cols[1]:
    st.caption("🎨 Built with Streamlit")
with cols[2]:
    st.caption(f"{'☁️ Cloud' if is_cloud else '💻 Local'} Mode")
