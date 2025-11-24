import os
import asyncio
import logging
import threading
import queue
import time

import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av
import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. CONFIGURATION & LOGGING
logging.basicConfig(level=logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

# Try loading from .env, otherwise check Streamlit secrets
load_dotenv()
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY and "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

if not GEMINI_API_KEY:
    st.error("Missing GEMINI_API_KEY. Please set it in .env or Streamlit secrets.")
    st.stop()

# Audio Constants
GEMINI_INPUT_RATE = 16000
GEMINI_OUTPUT_RATE = 24000
WEBRTC_RATE = 48000  # Browsers usually send 48k
CHUNK_SIZE = 512

# System Prompt
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant. BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

# 2. THREAD-SAFE QUEUES
# We need to bridge the Sync WebRTC thread and the Async Gemini thread
audio_in_queue = queue.Queue()  # Mic -> Gemini
audio_out_queue = queue.Queue() # Gemini -> Speaker

# 3. GEMINI ASYNC WORKER
# This runs in a background thread to handle the WebSocket connection
async def gemini_loop():
    client = genai.Client(api_key=GEMINI_API_KEY)
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
    
    async with client.aio.live.connect(model=model_id, config=config) as session:
        print("✅ Connected to Gemini Live")
        
        async def send_audio():
            while True:
                try:
                    # Non-blocking get from queue
                    data = await asyncio.to_thread(audio_in_queue.get)
                    if data is None: break # Exit signal
                    
                    # Send to Gemini
                    await session.send(input={"data": data, "mime_type": "audio/pcm;rate=16000"}, end_of_turn=False)
                except Exception as e:
                    print(f"Send Error: {e}")

        async def receive_audio():
            while True:
                try:
                    async for response in session.receive():
                        if response.server_content and response.server_content.model_turn:
                            for part in response.server_content.model_turn.parts:
                                if part.inline_data:
                                    # Put raw PCM data into output queue
                                    audio_out_queue.put(part.inline_data.data)
                except Exception as e:
                    print(f"Receive Error: {e}")
                    break

        await asyncio.gather(send_audio(), receive_audio())

def start_gemini_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(gemini_loop())

# 4. WEBRTC AUDIO PROCESSOR
class GeminiAudioProcessor(AudioProcessorBase):
    def __init__(self):
        self.resampler_in = av.AudioResampler(format='s16', layout='mono', rate=GEMINI_INPUT_RATE)
        self.resampler_out = av.AudioResampler(format='s16', layout='stereo', rate=WEBRTC_RATE)
        
        # Start Gemini in a separate thread if not running
        if not hasattr(st.session_state, "gemini_thread_started"):
            t = threading.Thread(target=start_gemini_thread, daemon=True)
            t.start()
            st.session_state["gemini_thread_started"] = True

    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        # 1. PROCESS INPUT (Mic -> Gemini)
        # Resample 48k (WebRTC) -> 16k (Gemini)
        raw_samples = frame.to_ndarray()
        
        # Perform resampling using PyAV
        # We re-wrap the numpy array into an AV frame to resample it
        try:
            # Convert to 16k mono for Gemini
            packets = self.resampler_in.resample(frame)
            for packet in packets:
                # Convert to bytes and send to queue
                pcm_bytes = packet.to_ndarray().tobytes()
                audio_in_queue.put(pcm_bytes)
        except Exception as e:
            print(f"Input Processing Error: {e}")

        # 2. PROCESS OUTPUT (Gemini -> Speaker)
        # We need to return an AudioFrame to WebRTC
        # Check if we have audio from Gemini in the queue
        try:
            # Get data from Gemini (non-blocking, grab chunks if available)
            # We construct a silence frame by default
            output_data = np.zeros((frame.samples, 2), dtype=np.int16)
            
            if not audio_out_queue.empty():
                chunk = audio_out_queue.get_nowait()
                # Convert bytes back to numpy
                gemini_audio = np.frombuffer(chunk, dtype=np.int16)
                
                # Gemini sends 24k. We simply create a frame from it
                # Ideally we should resample properly, but for simplicity in streaming:
                # We create a temporary frame and resample it back to 48k for the browser
                
                # Create frame from Gemini data (Mono, 24k)
                temp_frame = av.AudioFrame.from_ndarray(gemini_audio.reshape(1, -1), format='s16', layout='mono')
                temp_frame.sample_rate = GEMINI_OUTPUT_RATE
                
                # Resample to 48k Stereo for Browser
                out_packets = self.resampler_out.resample(temp_frame)
                
                # Just take the first packet for low latency (simplified)
                if out_packets:
                    output_data = out_packets[0].to_ndarray()

            # Create final frame to send back to browser
            new_frame = av.AudioFrame.from_ndarray(output_data, format='s16', layout='stereo')
            new_frame.sample_rate = WEBRTC_RATE
            return new_frame
            
        except Exception as e:
            print(f"Output Processing Error: {e}")
            return frame

# 5. STREAMLIT UI
st.title("🇯🇴 Jordanian AI Voice Assistant")
st.write("Click 'Start' and speak. The AI speaks Ammani dialect.")

# WebRTC Streamer
webrtc_ctx = webrtc_streamer(
    key="gemini-voice",
    mode=WebRtcMode.SENDRECV,
    audio_processor_factory=GeminiAudioProcessor,
    media_stream_constraints={"video": False, "audio": True},
    rtc_configuration={
        "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
    }
)

if webrtc_ctx.state.playing:
    st.success("Listening... Speak now!")
