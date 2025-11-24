import os
import asyncio
import logging
import threading
import queue
import time
import sys

import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. SETUP & LOGGING
# We suppress the specific errors that caused your previous crash
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
# specific suppressions for webrtc/asyncio noise
logging.getLogger("aioice").setLevel(logging.ERROR)
logging.getLogger("aiortc").setLevel(logging.ERROR)

load_dotenv()

# Get API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY. Add it to .env or Streamlit Secrets.")
    st.stop()

# 2. AUDIO CONSTANTS (Same as your local config)
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
BROWSER_RATE = 48000 # Browsers standard
CHUNK_SIZE = 512 

# 3. SYSTEM PROMPT (Your Jordanian Prompt)
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

# 4. THE BRIDGE: Connects Browser (WebRTC) to Gemini (Async)
# We use a Session State class so the connection survives Streamlit re-runs
if "gemini_bridge" not in st.session_state:
    class GeminiBridge:
        def __init__(self):
            self.input_queue = queue.Queue() # Mic -> Gemini
            self.output_queue = queue.Queue() # Gemini -> Speaker
            self.stop_event = threading.Event()
            self.thread = threading.Thread(target=self.run_gemini_thread, daemon=True)
            self.thread.start()

        def run_gemini_thread(self):
            """Background thread that handles the Gemini Connection"""
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
                        
                        # Task 1: Send Audio to Gemini
                        async def send_task():
                            while not self.stop_event.is_set():
                                try:
                                    if not self.input_queue.empty():
                                        audio_data = self.input_queue.get()
                                        await session.send(input={"data": audio_data, "mime_type": "audio/pcm;rate=16000"}, end_of_turn=False)
                                    else:
                                        await asyncio.sleep(0.01)
                                except Exception as e:
                                    print(f"Send Error: {e}")
                                    break

                        # Task 2: Receive Audio from Gemini
                        async def recv_task():
                            while not self.stop_event.is_set():
                                try:
                                    async for response in session.receive():
                                        if response.server_content and response.server_content.model_turn:
                                            for part in response.server_content.model_turn.parts:
                                                if part.inline_data:
                                                    self.output_queue.put(part.inline_data.data)
                                except Exception as e:
                                    print(f"Receive Error: {e}")
                                    break

                        await asyncio.gather(send_task(), recv_task())
                except Exception as e:
                    print(f"Connection Error: {e}")

            loop.run_until_complete(gemini_session())

    st.session_state["gemini_bridge"] = GeminiBridge()

bridge = st.session_state["gemini_bridge"]

# 5. WEBRTC AUDIO PROCESSOR (The "Sound Card" for the Browser)
class AudioRelay(AudioProcessorBase):
    def __init__(self):
        # Resamplers: Browser(48k) <-> Gemini(16k/24k)
        self.in_resampler = av.AudioResampler(format='s16', layout='mono', rate=GEMINI_INPUT_RATE)
        self.out_resampler = av.AudioResampler(format='s16', layout='stereo', rate=BROWSER_RATE)

    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        # --- 1. HANDLE MIC INPUT ---
        try:
            # Resample 48k -> 16k for Gemini
            packets = self.in_resampler.resample(frame)
            for packet in packets:
                bridge.input_queue.put(packet.to_ndarray().tobytes())
        except Exception:
            pass # Drop bad frames

        # --- 2. HANDLE SPEAKER OUTPUT ---
        # Create a silent frame by default (size matches input frame)
        output_samples = np.zeros((frame.samples, 2), dtype=np.int16)
        
        try:
            # Check if Gemini sent us audio
            if not bridge.output_queue.empty():
                # Get raw PCM (24k mono)
                pcm_data = bridge.output_queue.get_nowait()
                gemini_array = np.frombuffer(pcm_data, dtype=np.int16)
                
                # Create a frame to resample it
                temp_frame = av.AudioFrame.from_ndarray(gemini_array.reshape(1, -1), format='s16', layout='mono')
                temp_frame.sample_rate = GEMINI_OUTPUT_RATE
                
                # Resample 24k -> 48k Stereo
                out_packets = self.out_resampler.resample(temp_frame)
                
                if out_packets:
                    # Take the first packet
                    resampled_data = out_packets[0].to_ndarray()
                    
                    # Safety: Ensure lengths match (Pad or Crop)
                    current_len = len(resampled_data)
                    target_len = len(output_samples)
                    
                    if current_len < target_len:
                        output_samples[:current_len] = resampled_data
                    else:
                        output_samples[:] = resampled_data[:target_len]

        except Exception:
            pass

        # Return the audio frame to the browser
        new_frame = av.AudioFrame.from_ndarray(output_samples, format='s16', layout='stereo')
        new_frame.sample_rate = BROWSER_RATE
        return new_frame

# 6. UI LAYOUT
st.title("🇯🇴 Jordanian AI - Realtime")
st.write("Ensure your browser allows microphone access.")

webrtc_streamer(
    key="jordan-voice",
    mode=WebRtcMode.SENDRECV,
    audio_processor_factory=AudioRelay,
    rtc_configuration={
        "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
    },
    media_stream_constraints={"video": False, "audio": True},
)
