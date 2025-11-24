import os
import asyncio
import logging
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
import websockets
import threading
import queue as queue_module
import socket
from audio_component import audio_component

# SETUP & LOGGING CLEANUP
logging.basicConfig(level=logging.ERROR)
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"

load_dotenv()

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError('Missing GEMINI_API_KEY in .env file.')

# AUDIO CONFIGURATION
INPUT_RATE = 16000  # Browser captures at 16kHz
OUTPUT_RATE = 24000  # Gemini outputs at 24kHz

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

class GeminiWebSocketBot:
    def __init__(self, log_queue):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.is_running = True
        self.log_queue = log_queue
        self.websocket_clients = set()
        self.gemini_session = None
        self.server = None

    def log(self, message):
        """Send log messages to queue for Streamlit UI"""
        if self.log_queue:
            self.log_queue.put(message)

    async def handle_websocket_client(self, websocket):
        """Handle incoming WebSocket connection from browser"""
        self.websocket_clients.add(websocket)
        self.log(f"🔌 Browser connected")
        
        try:
            async for message in websocket:
                # Received audio data from browser
                if isinstance(message, bytes) and self.gemini_session:
                    # Forward to Gemini
                    try:
                        await self.gemini_session.send(
                            input={"data": message, "mime_type": "audio/pcm;rate=16000"},
                            end_of_turn=False
                        )
                    except Exception as e:
                        self.log(f"⚠️ Send error: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            self.log("🔌 Browser disconnected")
        finally:
            self.websocket_clients.discard(websocket)

    async def receive_gemini_audio(self):
        """Receive audio from Gemini and broadcast to all browser clients"""
        first_part = True
        try:
            while self.is_running and self.gemini_session:
                async for response in self.gemini_session.receive():
                    server_content = response.server_content
                    
                    if server_content is None:
                        continue

                    model_turn = server_content.model_turn
                    if model_turn:
                        for part in model_turn.parts:
                            # 1. Send audio to all connected browsers
                            if part.inline_data and self.websocket_clients:
                                # Broadcast to all connected clients
                                websockets.broadcast(self.websocket_clients, part.inline_data.data)
                            
                            # 2. Log text transcript
                            if part.text:
                                if first_part:
                                    self.log(f"🤖 Bot: {part.text}")
                                    first_part = False
                                else:
                                    self.log(part.text)

                    # Turn Complete
                    if server_content.turn_complete:
                        self.log("")
                        first_part = True
                        
        except Exception as e:
            if self.is_running:
                self.log(f"\n❌ Receive Error: {e}")

    async def start_gemini_session(self):
        """Initialize Gemini connection"""
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
                self.gemini_session = session
                self.log("✅ Connected to Gemini! (Jordanian Mode)")
                
                # Start receiving audio from Gemini
                await self.receive_gemini_audio()
                
        except Exception as e:
            self.log(f"❌ Gemini connection failed: {e}")
            import traceback
            self.log(traceback.format_exc())

    async def start_websocket_server(self, port=8765):
        """Start WebSocket server for browser connections"""
        self.log(f"🌐 Starting WebSocket server on port {port}...")
        
        # Create server with reuse_address enabled to avoid port binding issues
        server = await websockets.serve(
            self.handle_websocket_client, 
            "localhost", 
            port,
            reuse_address=True
        )
        self.server = server
        self.log(f"✅ WebSocket server running on ws://localhost:{port}")
        
        # Start Gemini session
        await self.start_gemini_session()
        
        # Close server when done
        server.close()
        await server.wait_closed()

    def cleanup(self):
        """Clean up resources"""
        self.is_running = False
        self.gemini_session = None
        
        # Close server if it exists
        if self.server:
            self.server.close()
        
        # Close all websocket clients
        for ws in list(self.websocket_clients):
            try:
                asyncio.create_task(ws.close())
            except:
                pass
        
        self.websocket_clients.clear()

def run_bot_in_thread(bot, port):
    """Run the async bot in a separate thread"""
    async def main():
        await bot.start_websocket_server(port)
    
    try:
        asyncio.run(main())
    except Exception as e:
        if bot.log_queue:
            bot.log_queue.put(f"Error: {e}")
            import traceback
            bot.log_queue.put(traceback.format_exc())

# Streamlit UI
st.set_page_config(page_title="Gemini Voice Assistant", page_icon="🎤", layout="wide")
st.title("🎤 Gemini Voice Assistant (Jordanian Dialect)")
st.caption("Cloud-ready browser-based voice assistant")

# Detect deployment environment
def is_cloud_deployment():
    """Check if running on Streamlit Cloud"""
    return os.getenv('STREAMLIT_SHARING_MODE') is not None

# Get WebSocket configuration  
def get_websocket_config():
    """Get WebSocket URL and port - works for both local and cloud"""
    # Use environment variable for port if available (cloud deployment)
    port = int(os.getenv('WS_PORT', find_free_port()))
    
    # For cloud, use the app's own hostname; for local, use localhost
    if is_cloud_deployment():
        # On Streamlit Cloud, WebSocket server runs on same host
        hostname = os.getenv('STREAMLIT_SERVER_HEADLESS', 'localhost')
        ws_url = f"ws://{hostname}:{port}"
    else:
        ws_url = f"ws://localhost:{port}"
    
    return ws_url, port

def find_free_port(start_port=8765):
    """Find an available port starting from start_port"""
    port = start_port
    while port < start_port + 100:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            port += 1
    return start_port  # Fallback

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
if 'ws_url' not in st.session_state:
    st.session_state.ws_url = None
if 'ws_port' not in st.session_state:
    st.session_state.ws_port = None

# Get WebSocket configuration
ws_url, ws_port = get_websocket_config()
st.session_state.ws_url = ws_url
st.session_state.ws_port = ws_port

# Show deployment info
if is_cloud_deployment():
    st.info("🌐 Running on Streamlit Cloud")
else:
    st.info("💻 Running locally")

# Control buttons
col1, col2 = st.columns(2)

with col1:
    if st.button("▶️ Start Bot", disabled=st.session_state.is_running):
        # Create log queue for thread-safe communication
        st.session_state.log_queue = queue_module.Queue()
        
        # Create bot instance with log queue
        st.session_state.bot = GeminiWebSocketBot(log_queue=st.session_state.log_queue)
        st.session_state.is_running = True
        st.session_state.logs = []
        
        # Start bot in a separate thread
        st.session_state.bot_thread = threading.Thread(
            target=run_bot_in_thread,
            args=(st.session_state.bot, st.session_state.ws_port),
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
    st.success("✅ Bot is running. Allow microphone access in your browser...")
    
    # Embed audio component
    st.subheader("Audio Interface")
    audio_component(st.session_state.ws_url)
else:
    st.info("Press 'Start Bot' to begin")

# Poll the queue for new log messages
if st.session_state.log_queue:
    try:
        while True:
            message = st.session_state.log_queue.get_nowait()
            st.session_state.logs.append(message)
    except queue_module.Empty:
        pass

# Display logs
st.subheader("Conversation Log")
log_container = st.container()

with log_container:
    if st.session_state.logs:
        # Show last 20 messages for performance
        for log in st.session_state.logs[-20:]:
            st.write(log)
    else:
        st.write("No conversation yet. Start the bot to begin.")

# Auto-refresh while bot is running
if st.session_state.is_running:
    import time
    time.sleep(0.3)  # Faster refresh for lower perceived latency
    st.rerun()
