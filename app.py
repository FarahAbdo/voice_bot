import streamlit as st
import os
import asyncio
import numpy as np
import scipy.io.wavfile as wav
import scipy.signal
import io
import logging

# Set up logging to ignore the warnings you saw
logging.basicConfig(level=logging.ERROR)

from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. SETUP PAGE
st.set_page_config(page_title="Jordanian AI", page_icon="🇯🇴")
st.title("🇯🇴 Jordanian AI Assistant")
st.caption("Ammani Dialect • Works on Streamlit Cloud")

# 2. LOAD API KEY
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY in Streamlit Secrets!")
    st.stop()

# 3. AUDIO PROCESSING HELPER (Prevents 'Invalid Frame' errors)
def fix_audio_for_gemini(audio_bytes):
    try:
        # Load WAV from browser
        original_rate, data = wav.read(io.BytesIO(audio_bytes))
        
        # Convert Stereo to Mono
        if len(data.shape) > 1:
            data = data.mean(axis=1)

        # Resample to 16,000 Hz (Gemini Standard)
        target_rate = 16000
        if original_rate != target_rate:
            number_of_samples = round(len(data) * float(target_rate) / original_rate)
            data = scipy.signal.resample(data, number_of_samples)
        
        # Convert to Int16
        data = data.astype(np.int16)
        
        return data.tobytes()
    except Exception as e:
        st.error(f"Audio Error: {e}")
        return None

# 4. GEMINI ASYNC FUNCTION
async def get_gemini_response(pcm_data):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # SYSTEM PROMPT
    sys_msg = (
        "You are a friendly Jordanian guy from Amman. "
        "Speak ONLY in Jordanian dialect (Ammani). "
        "Use words like: 'يا زلمة', 'هسا', 'بدي', 'ع راسي'. "
        "Keep it very short (1 sentence)."
    )

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=sys_msg)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        )
    )

    accumulated_audio = b""

    # Connect to Gemini
    async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
        # Send your voice (using send_realtime_input to avoid deprecation warnings)
        await session.send_realtime_input(
            data=pcm_data, 
            mime_type="audio/pcm;rate=16000"
        )
        # Tell Gemini we are done talking
        await session.send(input={}, end_of_turn=True)

        # Receive Audio
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data:
                        accumulated_audio += part.inline_data.data
            
            if response.server_content and response.server_content.turn_complete:
                break
    
    return accumulated_audio

# 5. THE INTERFACE (NO WEBRTC = NO ERRORS)
audio_input = st.audio_input("🎤 Record your message")

if audio_input:
    with st.spinner("🇯🇴 Thinking..."):
        # 1. Read File
        raw_bytes = audio_input.read()
        
        # 2. Fix Format
        clean_pcm = fix_audio_for_gemini(raw_bytes)
        
        if clean_pcm:
            try:
                # 3. Get Reply
                ai_audio = asyncio.run(get_gemini_response(clean_pcm))
                
                if ai_audio:
                    st.success("Reply:")
                    # Play the Audio
                    st.audio(ai_audio, format="audio/wav", sample_rate=24000)
                else:
                    st.warning("No audio response.")
            except Exception as e:
                st.error(f"Connection Failed: {e}")
