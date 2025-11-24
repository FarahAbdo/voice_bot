import streamlit as st
import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
import base64
import io

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Gemini Voice Assistant",
    page_icon="🎤",
    layout="centered"
)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'audio_response' not in st.session_state:
    st.session_state.audio_response = None

# Get API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') or st.secrets.get("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY. Please add it to Streamlit secrets or .env file.")
    st.stop()

# System prompt
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

# Title and description
st.title("🎤 Gemini Voice Assistant")
st.markdown("**Jordanian Arabic Voice Bot** - Record your voice and get responses!")

# Audio input
audio_bytes = st.audio_input("🎙️ Click to record your voice")

if audio_bytes:
    st.audio(audio_bytes, format="audio/wav")
    
    if st.button("🚀 Send to Gemini", type="primary"):
        with st.spinner("Processing your audio..."):
            try:
                # Initialize Gemini client
                client = genai.Client(api_key=GEMINI_API_KEY)
                
                # Read audio bytes
                audio_data = audio_bytes.read()
                
                # Create config
                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_modalities=["TEXT", "AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name="Charon"
                            )
                        )
                    )
                )
                
                # Send audio to Gemini
                response = client.models.generate_content(
                    model="gemini-2.0-flash-exp",
                    contents=[
                        types.Content(
                            parts=[
                                types.Part.from_bytes(
                                    data=audio_data,
                                    mime_type="audio/wav"
                                )
                            ]
                        )
                    ],
                    config=config
                )
                
                # Extract text and audio response
                text_response = ""
                audio_response = None
                
                for part in response.candidates[0].content.parts:
                    if part.text:
                        text_response += part.text
                    if hasattr(part, 'inline_data') and part.inline_data:
                        audio_response = part.inline_data.data
                
                # Display results
                st.success("✅ Response received!")
                
                if text_response:
                    st.markdown("### 🤖 Bot Response:")
                    st.markdown(f"**{text_response}**")
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": text_response
                    })
                
                if audio_response:
                    st.markdown("### 🔊 Audio Response:")
                    # Convert audio bytes to playable format
                    audio_b64 = base64.b64encode(audio_response).decode()
                    audio_html = f'<audio controls autoplay><source src="data:audio/wav;base64,{audio_b64}" type="audio/wav"></audio>'
                    st.markdown(audio_html, unsafe_allow_html=True)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                st.exception(e)

# Display conversation history
if st.session_state.messages:
    st.markdown("---")
    st.markdown("### 💬 Conversation History")
    for msg in st.session_state.messages:
        if msg["role"] == "assistant":
            st.markdown(f"🤖 **Bot:** {msg['content']}")

# Clear history button
if st.button("🗑️ Clear History"):
    st.session_state.messages = []
    st.rerun()

# Instructions
with st.expander("ℹ️ How to use"):
    st.markdown("""
    1. Click on the microphone button to record your voice
    2. Speak in Jordanian Arabic dialect
    3. Click "Send to Gemini" to get a response
    4. Listen to the audio response and read the text
    
    **Note:** Make sure to add your `GEMINI_API_KEY` to Streamlit secrets:
    - Go to your app settings
    - Add to secrets: `GEMINI_API_KEY = "your-key-here"`
    """)

# Footer
st.markdown("---")
st.markdown("Built with ❤️ using Streamlit and Google Gemini")
