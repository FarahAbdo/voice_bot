import streamlit as st
import os
import asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
import base64

# 1. PAGE CONFIG
st.set_page_config(page_title="Jordanian AI", page_icon="🇯🇴")
st.title("🇯🇴 Jordanian AI Assistant")
st.write("Native Streamlit Version - Works perfectly on Cloud")

# 2. SETUP API KEY
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY. Please add it to Secrets.")
    st.stop()

# 3. SYSTEM PROMPT
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. BE FRIENDLY and helpful. "
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب', 'يا زلمة'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Respond immediately."
)

# 4. ASYNC FUNCTION TO TALK TO GEMINI
async def get_gemini_response(audio_bytes):
    """
    Sends audio to Gemini Live API and gathers the audio response.
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    # Configure the voice and instructions
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        )
    )

    model_id = "gemini-2.0-flash-exp"
    audio_data = b""

    # Connect to Gemini
    async with client.aio.live.connect(model=model_id, config=config) as session:
        # Send the recorded audio
        # Note: st.audio_input returns WAV, Gemini handles it if we specify mime_type
        await session.send(
            input={"data": audio_bytes, "mime_type": "audio/wav"}, 
            end_of_turn=True
        )

        # Receive the audio response
        async for response in session.receive():
            if response.server_content and response.server_content.model_turn:
                for part in response.server_content.model_turn.parts:
                    if part.inline_data:
                        audio_data += part.inline_data.data
            
            # Stop when turn is complete
            if response.server_content and response.server_content.turn_complete:
                break
                
    return audio_data

# 5. UI: NATIVE AUDIO INPUT
# This widget is native to Streamlit and is NOT blocked by firewalls
audio_value = st.audio_input("Click to speak 🎤")

if audio_value:
    with st.spinner("🇯🇴 Thinking..."):
        # Read the file bytes
        input_bytes = audio_value.read()
        
        # Run the async Gemini function
        try:
            output_audio = asyncio.run(get_gemini_response(input_bytes))
            
            if output_audio:
                # Auto-play the audio using base64 injection
                # (Standard st.audio doesn't always auto-play)
                b64 = base64.b64encode(output_audio).decode()
                md = f"""
                    <audio controls autoplay>
                    <source src="data:audio/mp3;base64,{b64}" type="audio/mp3">
                    </audio>
                    """
                st.markdown(md, unsafe_allow_html=True)
                st.success("Reply generated!")
            else:
                st.warning("No audio response received.")
                
        except Exception as e:
            st.error(f"Error connecting to Gemini: {e}")
