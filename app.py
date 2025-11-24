import os
import asyncio
import logging
import streamlit as st
import base64
import wave
import io
from dotenv import load_dotenv
from google import genai
from google.genai import types
from audio_component import audio_component

# SETUP
logging.basicConfig(level=logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    # Try getting from Streamlit secrets
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        st.error("Missing GEMINI_API_KEY. Please add it to .env or Streamlit secrets.")
        st.stop()

# SYSTEM PROMPT (Jordanian Dialect)
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

class GeminiBot:
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.chat = self.client.chats.create(
            model="gemini-2.0-flash-exp",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name="Charon"
                        )
                    )
                )
            )
        )

    def process_audio(self, audio_bytes):
        """Send audio to Gemini and get audio response"""
        try:
            # Send audio part
            response = self.chat.send_message(
                message=types.Part(
                    inline_data=types.Blob(
                        data=audio_bytes,
                        mime_type="audio/pcm"
                    )
                )
            )
            
            # Extract audio from response
            for part in response.parts:
                if part.inline_data:
                    return part.inline_data.data
            return None
            
        except Exception as e:
            st.error(f"Gemini Error: {e}")
            return None

def pcm_to_wav(pcm_data, sample_rate=24000):
    """Convert raw PCM to WAV for browser playback"""
    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return wav_io.getvalue()

# Streamlit UI
st.set_page_config(page_title="Gemini Voice Assistant", page_icon="🎤", layout="wide")
st.title("🎤 Gemini Voice Assistant (Jordanian Dialect)")
st.caption("Running entirely on Streamlit Cloud (Turn-Based Mode)")

# Initialize session state
if 'bot' not in st.session_state:
    st.session_state.bot = GeminiBot()
if 'audio_response' not in st.session_state:
    st.session_state.audio_response = None

# Audio Component
# This component handles recording and playback
# It returns the recorded audio data (base64) when silence is detected
audio_input_base64 = audio_component(
    audio_output_base64=st.session_state.audio_response,
    key="audio_comp"
)

# Process Input
if audio_input_base64:
    # Decode base64 PCM from browser
    try:
        audio_bytes = base64.b64decode(audio_input_base64)
        
        # Send to Gemini
        with st.spinner("🤖 Thinking..."):
            response_pcm = st.session_state.bot.process_audio(audio_bytes)
        
        if response_pcm:
            # Convert Gemini's PCM (24kHz) to WAV for browser
            wav_data = pcm_to_wav(response_pcm, sample_rate=24000)
            wav_base64 = base64.b64encode(wav_data).decode('utf-8')
            
            # Update state to trigger playback in component
            st.session_state.audio_response = wav_base64
            st.rerun()
            
    except Exception as e:
        st.error(f"Processing Error: {e}")

# Reset audio response after it's been sent to component
# This prevents infinite loops of playback
if st.session_state.audio_response and audio_input_base64 is None:
    st.session_state.audio_response = None
