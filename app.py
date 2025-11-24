import os
import asyncio
import logging
import threading
import queue
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types
from twilio.rest import Client

# 1. SETUP & LOGGING
logging.basicConfig(level=logging.ERROR)
logging.getLogger("aioice").setLevel(logging.ERROR)
logging.getLogger("aiortc").setLevel(logging.ERROR)

load_dotenv()

# API KEYS
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY. Add it to .env or Streamlit Secrets.")
    st.stop()

# 2. AUDIO CONSTANTS
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
BROWSER_RATE = 48000
CHUNK_SIZE = 512 

# 3. SYSTEM PROMPT
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

# 4. NETWORK CONFIGURATION (The Fix for "Connection taking too long")
def get_ice_servers():
    """
    Tries to get Twilio TURN servers from secrets.
    Falls back to free Google STUN servers if no secrets found.
    """
    # Check for Twilio Secrets
    twilio_sid = os.getenv("TWILIO_ACCOUNT_SID") or st.secrets.get("TWILIO_ACCOUNT_SID")
    twilio_auth = os.getenv("TWILIO_AUTH_TOKEN") or st.secrets.get("TWILIO_AUTH_TOKEN")

    if twilio_sid and twilio_auth:
        try:
            client = Client(twilio_sid, twilio_auth)
            token = client.tokens.create()
            return token.ice_servers
        except Exception as e:
            st.warning(f"Twilio Error: {e}. Falling back to free STUN.")
    
    # Fallback: Free Google STUN list (Better than just one)
    return [
        {"urls": ["stun:stun.l.google.com:19302"]},
        {"urls": ["stun:stun1.l.google.com:19302"]},
        {"urls": ["stun:stun2.l.google.com:19302"]},
        {"urls": ["stun:stun3.l.google.com:19302"]},
        {"urls": ["stun:stun4.l.google.com:19302"]},
    ]

# 5. GEMINI BRIDGE (Thread Safe)
if "gemini_bridge" not in st.session_state:
    class GeminiBridge:
        def __init__(self):
            self.input_queue = queue.Queue() 
            self.output_queue = queue.Queue() 
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self.run_gemini_thread, daemon=True)
            self.thread.start()

        def run_gemini_thread(self):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            client = genai.Client(api_key=GEMINI_API_KEY)
            config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=types.Content(parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                    )
                )
            )

            async def gemini_session():
                try:
                    async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
                        print("✅ Connected to Gemini")
                        
                        async def send_task():
                            while not self.stop_event.is_set():
                                try:
                                    if not self.input_queue.empty():
                                        audio_data = self.input_queue.get()
                                        await session.send(input={"data": audio_data, "mime_type": "audio/pcm;rate=16000"}, end_of_turn=False)
                                    else:
                                        await asyncio.sleep(0.01)
                                except Exception:
                                    break

                        async def recv_task():
                            while not self.stop_event.is_set():
                                try:
                                    async for response in session.receive():
                                        if response.server_content and response.server_content.model_turn:
                                            for part in response.server_content.model_turn.parts:
                                                if part.inline_data:
                                                    self.output_queue.put(part.inline_data.data)
                                except Exception:
                                    break

                        await asyncio.gather(send_task(), recv_task())
                except Exception as e:
                    print(f"Connection Error: {e}")

            loop.run_until_complete(gemini_session())

    st.session_state["gemini_bridge"] = GeminiBridge()

bridge = st.session_state["gemini_bridge"]

# 6. AUDIO PROCESSOR
class AudioRelay(AudioProcessorBase):
    def __init__(self):
        self.in_resampler = av.AudioResampler(format='s16', layout='mono', rate=GEMINI_INPUT_RATE)
        self.out_resampler = av.AudioResampler(format='s16', layout='stereo', rate=BROWSER_RATE)

    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        # Input
        try:
            packets = self.in_resampler.resample(frame)
            for packet in packets:
                bridge.input_queue.put(packet.to_ndarray().tobytes())
        except Exception:
            pass

        # Output
        output_samples = np.zeros((frame.samples, 2), dtype=np.int16)
        try:
            if not bridge.output_queue.empty():
                pcm_data = bridge.output_queue.get_nowait()
                gemini_array = np.frombuffer(pcm_data, dtype=np.int16)
                temp_frame = av.AudioFrame.from_ndarray(gemini_array.reshape(1, -1), format='s16', layout='mono')
                temp_frame.sample_rate = GEMINI_OUTPUT_RATE
                out_packets = self.out_resampler.resample(temp_frame)
                if out_packets:
                    resampled_data = out_packets[0].to_ndarray()
                    # Safety slicing
                    min_len = min(len(resampled_data), len(output_samples))
                    output_samples[:min_len] = resampled_data[:min_len]
        except Exception:
            pass

        new_frame = av.AudioFrame.from_ndarray(output_samples, format='s16', layout='stereo')
        new_frame.sample_rate = BROWSER_RATE
        return new_frame

# 7. UI
st.title("🇯🇴 Jordanian AI - Realtime")

# Generate ICE servers (STUN or TURN)
ice_servers = get_ice_servers()

webrtc_streamer(
    key="jordan-voice",
    mode=WebRtcMode.SENDRECV,
    audio_processor_factory=AudioRelay,
    rtc_configuration={"iceServers": ice_servers},
    media_stream_constraints={"video": False, "audio": True},
)
