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

# --- 1. SETUP & LOGGING SUPPRESSION ---
# Fixes the "ScriptRunContext" warning
logging.getLogger('streamlit.runtime.scriptrunner_utils.script_run_context').setLevel(logging.ERROR)
# Fixes the noisy aioice errors
logging.getLogger("aioice.ice").setLevel(logging.ERROR) 
logging.getLogger("aioice.stun").setLevel(logging.ERROR)

logging.basicConfig(level=logging.WARNING)

load_dotenv()

# Get API Key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("Missing GEMINI_API_KEY.")
    st.stop()

# --- 2. AUDIO CONSTANTS ---
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
WEBRTC_RATE = 48000

# --- 3. GLOBAL SINGLETON FOR GEMINI ---
# This class persists across Streamlit re-runs.
# It prevents "Zombie Threads" from fighting over resources.

class GeminiSessionManager:
    def __init__(self):
        self.audio_in_queue = queue.Queue()
        self.audio_out_queue = queue.Queue()
        self.stop_signal = threading.Event()
        self.thread = None
    
    def start(self):
        if self.thread is not None and self.thread.is_alive():
            return # Already running
        
        self.stop_signal.clear()
        self.thread = threading.Thread(target=self._run_gemini_loop, daemon=True)
        self.thread.start()
        print("✅ Gemini Background Thread Started")

    def _run_gemini_loop(self):
        # Create a NEW event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        SYSTEM_INSTRUCTION = (
            "You are a helpful Jordanian voice assistant. "
            "Speak ONLY in Jordanian Arabic (Ammani dialect). "
            "Keep responses extremely short (max 1 sentence)."
        )

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=types.Content(parts=[types.Part(text=SYSTEM_INSTRUCTION)]),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
                )
            )
        )

        async def gemini_workflow():
            try:
                async with client.aio.live.connect(model="gemini-2.0-flash-exp", config=config) as session:
                    
                    async def send_mic_data():
                        while not self.stop_signal.is_set():
                            try:
                                # Non-blocking check to allow loop to exit
                                if not self.audio_in_queue.empty():
                                    data = self.audio_in_queue.get()
                                    await session.send(input={"data": data, "mime_type": "audio/pcm;rate=16000"}, end_of_turn=False)
                                else:
                                    await asyncio.sleep(0.01)
                            except Exception as e:
                                print(f"Send Error: {e}")
                                break

                    async def receive_ai_audio():
                        while not self.stop_signal.is_set():
                            try:
                                async for response in session.receive():
                                    if self.stop_signal.is_set(): break
                                    if response.server_content and response.server_content.model_turn:
                                        for part in response.server_content.model_turn.parts:
                                            if part.inline_data:
                                                self.audio_out_queue.put(part.inline_data.data)
                            except Exception:
                                break

                    await asyncio.gather(send_mic_data(), receive_ai_audio())

            except Exception as e:
                print(f"Gemini Connection Error: {e}")

        try:
            loop.run_until_complete(gemini_workflow())
        finally:
            loop.close()

# Cache the manager so it doesn't reset on every interaction
@st.cache_resource
def get_gemini_manager():
    return GeminiSessionManager()

gemini_manager = get_gemini_manager()
gemini_manager.start()

# --- 4. WEBRTC AUDIO PROCESSOR ---
class GeminiAudioProcessor(AudioProcessorBase):
    def __init__(self):
        self.resampler_in = av.AudioResampler(format='s16', layout='mono', rate=GEMINI_INPUT_RATE)
        self.resampler_out = av.AudioResampler(format='s16', layout='stereo', rate=WEBRTC_RATE)

    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        # 1. PROCESS INPUT (Mic -> Gemini)
        try:
            # Resample 48k -> 16k
            raw_samples = frame.to_ndarray()
            packets = self.resampler_in.resample(frame)
            for packet in packets:
                gemini_manager.audio_in_queue.put(packet.to_ndarray().tobytes())
        except Exception:
            pass

        # 2. PROCESS OUTPUT (Gemini -> Speaker)
        # Default: Silence
        output_data = np.zeros((frame.samples, 2), dtype=np.int16)
        
        try:
            # Grab data if available
            if not gemini_manager.audio_out_queue.empty():
                chunk = gemini_manager.audio_out_queue.get_nowait()
                gemini_audio = np.frombuffer(chunk, dtype=np.int16)
                
                # Create temporary 24k mono frame
                temp_frame = av.AudioFrame.from_ndarray(gemini_audio.reshape(1, -1), format='s16', layout='mono')
                temp_frame.sample_rate = GEMINI_OUTPUT_RATE
                
                # Resample to 48k stereo
                out_packets = self.resampler_out.resample(temp_frame)
                if out_packets:
                    output_data = out_packets[0].to_ndarray()
                    
                    # Handle frame size mismatch (pad or trim) if necessary
                    if output_data.shape[0] != frame.samples:
                        # Simple resize for stability
                        new_out = np.zeros((frame.samples, 2), dtype=np.int16)
                        min_len = min(output_data.shape[0], frame.samples)
                        new_out[:min_len, :] = output_data[:min_len, :]
                        output_data = new_out

        except Exception:
            pass

        # Return Frame
        new_frame = av.AudioFrame.from_ndarray(output_data, format='s16', layout='stereo')
        new_frame.sample_rate = WEBRTC_RATE
        return new_frame

# --- 5. UI ---
st.title("🇯🇴 Jordanian AI Voice")
st.write("Status: Ready. Click Start to talk.")

ctx = webrtc_streamer(
    key="gemini-live",
    mode=WebRtcMode.SENDRECV,
    audio_processor_factory=GeminiAudioProcessor,
    rtc_configuration={
        "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
    },
    media_stream_constraints={"video": False, "audio": True}
)
