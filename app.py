import os
import asyncio
import pyaudio
import sys
import logging
import traceback
import threading
import queue
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. SETUP & LOGGING CLEANUP
# Hides the messy internal logs
logging.basicConfig(level=logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError('Missing GEMINI_API_KEY in .env file.')

# 2. AUDIO CONFIGURATION (Optimized for Realtime)
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_SIZE = 512  # Small buffer = Low Latency

# 3. SYSTEM PROMPT (Jordanian Dialect)
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging."
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

class GeminiLiveBot:
    def __init__(self, log_queue):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.audio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_running = True
        self.log_queue = log_queue

    def log(self, message):
        """Send log messages to queue for Streamlit UI"""
        if self.log_queue:
            self.log_queue.put(message)

    def setup_audio(self):
        # Mic Input
        self.input_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=INPUT_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        # Speaker Output
        self.output_stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=OUTPUT_RATE,
            output=True,
            frames_per_buffer=CHUNK_SIZE
        )

    async def send_audio_loop(self, session):
        """Reads mic and sends to Gemini with Voice Activity Detection."""
        self.log("🎤 Mic active. Speak now...")
        loop = asyncio.get_running_loop()
        try:
            while self.is_running:
                # Read Audio (Non-blocking)
                data = await loop.run_in_executor(None, self.input_stream.read, CHUNK_SIZE, False)

                # SEND TO GEMINI
                try:
                    await session.send(input={"data": data, "mime_type": "audio/pcm;rate=16000"}, end_of_turn=False)
                except Exception:
                    # Fallback if syntax changes
                    await session.send_realtime_input(data=data, mime_type="audio/pcm;rate=16000")
                    
        except Exception as e:
            if self.is_running:
                self.log(f"\n❌ Send Error: {e}")

    async def receive_audio_loop(self, session):
        """Receives audio and plays it."""
        self.log("\n🎧 Ready to speak...")
        loop = asyncio.get_running_loop()
        first_part = True
        try:
            while self.is_running:
                async for response in session.receive():
                    server_content = response.server_content
                    
                    if server_content is None:
                        continue

                    model_turn = server_content.model_turn
                    if model_turn:
                        for part in model_turn.parts:
                            # 1. Play Audio (Non-blocking)
                            if part.inline_data:
                                await loop.run_in_executor(None, self.output_stream.write, part.inline_data.data)
                            
                            # 2. Print Text Transcript with label
                            if part.text:
                                if first_part:
                                    self.log(f"🤖 Bot: {part.text}")
                                    first_part = False
                                else:
                                    self.log(part.text)

                    # Turn Complete (Newline)
                    if server_content.turn_complete:
                        self.log("")
                        first_part = True
                        
        except Exception as e:
            if self.is_running:
                self.log(f"\n❌ Receive Error: {e}")

    async def run(self):
        self.setup_audio()
        
        # CONFIGURATION (Fixed deprecation warning)
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
        self.log(f"Connecting to {model_id}...")

        try:
            async with self.client.aio.live.connect(model=model_id, config=config) as session:
                self.log("✅ Connected! (Jordanian Mode)")
                
                await asyncio.gather(
                    self.send_audio_loop(session),
                    self.receive_audio_loop(session)
                )
        except Exception as e:
            traceback.print_exc()
            self.log(f"Connection Failed: {e}")
        finally:
            self.cleanup()

    def cleanup(self):
        self.is_running = False
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
        if self.output_stream:
            self.output_stream.stop_stream()
            self.output_stream.close()
        self.audio.terminate()

def run_bot_in_thread(bot):
    """Run the async bot in a separate thread"""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(bot.run())
    except Exception as e:
        if bot.log_queue:
            bot.log_queue.put(f"Error: {e}")
            traceback_str = traceback.format_exc()
            bot.log_queue.put(traceback_str)

# Streamlit UI
st.set_page_config(page_title="Gemini Voice Assistant", page_icon="🎤")
st.title("🎤 Gemini Voice Assistant (Jordanian Dialect)")

# Initialize session state
if 'bot' not in st.session_state:
    st.session_state.bot = None
if 'bot_thread' not in st.session_state:
    st.session_state.bot_thread = None
if 'log_queue' not in st.session_state:
    st.session_state.log_queue = None
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'is_running' not in st.session_state:
    st.session_state.is_running = False

# Control buttons
col1, col2 = st.columns(2)

with col1:
    if st.button("▶️ Start Bot", disabled=st.session_state.is_running):
        # Create log queue for thread-safe communication
        st.session_state.log_queue = queue.Queue()
        
        # Create bot instance with log queue
        st.session_state.bot = GeminiLiveBot(log_queue=st.session_state.log_queue)
        st.session_state.is_running = True
        st.session_state.logs = []
        
        # Start bot in a separate thread
        st.session_state.bot_thread = threading.Thread(
            target=run_bot_in_thread, 
            args=(st.session_state.bot,),
            daemon=True
        )
        st.session_state.bot_thread.start()
        st.rerun()

with col2:
    if st.button("⏹️ Stop Bot", disabled=not st.session_state.is_running):
        if st.session_state.bot:
            st.session_state.bot.cleanup()
            st.session_state.is_running = False
            st.session_state.bot = None
            st.rerun()

# Display status
if st.session_state.is_running:
    st.success("✅ Bot is running. Speak into your microphone...")
else:
    st.info("Press 'Start Bot' to begin")

# Poll the queue for new log messages
if st.session_state.log_queue:
    try:
        while True:
            message = st.session_state.log_queue.get_nowait()
            st.session_state.logs.append(message)
    except queue.Empty:
        pass

# Display logs
st.subheader("Conversation Log")
log_container = st.container()

with log_container:
    if st.session_state.logs:
        for log in st.session_state.logs:
            st.write(log)
    else:
        st.write("No conversation yet. Start the bot to begin.")

# Auto-refresh while bot is running
if st.session_state.is_running:
    import time
    time.sleep(0.5)
    st.rerun()
