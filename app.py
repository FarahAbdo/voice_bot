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

# AUDIO CONFIGURATION (Matching local bot)
INPUT_RATE = 16000
OUTPUT_RATE = 24000
CHUNK_SIZE = 512  # Small chunks for low latency

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

class GeminiStreamingBot:
    def __init__(self, log_queue):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.is_running = True
        self.log_queue = log_queue
        self.websocket_clients = set()
        self.gemini_session = None
        self.server = None

    def log(self, message):
        """Send log messages to queue for Streamlit UI (non-blocking)"""
        if self.log_queue:
            try:
                self.log_queue.put_nowait(message)
            except:
                pass

    async def handle_websocket_client(self, websocket):
        """Handle bidirectional audio streaming with browser"""
        self.websocket_clients.add(websocket)
        self.log(f"🔌 Browser connected")
        
        try:
            # Send audio from browser to Gemini (minimal overhead)
            async def send_to_gemini():
                async for audio_chunk in websocket:
                    if isinstance(audio_chunk, bytes) and self.gemini_session:
                        try:
                            # Send immediately without buffering
                            await self.gemini_session.send(
                                input={"data": audio_chunk, "mime_type": "audio/pcm;rate=16000"},
                                end_of_turn=False
                            )
                        except Exception:
                            # Silent error to avoid logging overhead
                            pass
            
            # Receive audio from Gemini and send to browser (optimized)
            async def receive_from_gemini():
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
                                    # Priority 1: Stream audio immediately (no await overhead)
                                    if part.inline_data:
                                        try:
                                            await websocket.send(part.inline_data.data)
                                        except:
                                            return  # Exit if websocket closed
                                    
                                    # Priority 2: Log text (can be delayed)
                                    if part.text and first_part:
                                        self.log(f"🤖 Bot: {part.text}")
                                        first_part = False

                            # Turn Complete
                            if server_content.turn_complete:
                                first_part = True
                except Exception as e:
                    if self.is_running:
                        self.log(f"❌ Receive Error: {e}")
            
            # Run both directions simultaneously (full-duplex, optimized)
            try:
                await asyncio.gather(
                    send_to_gemini(),
                    receive_from_gemini()
                )
            except asyncio.CancelledError:
                pass
                        
        except websockets.exceptions.ConnectionClosed:
            self.log("🔌 Browser disconnected")
        except Exception as e:
            self.log(f"❌ WebSocket error: {e}")
        finally:
            self.websocket_clients.discard(websocket)

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
                
                # Keep session alive while server is running
                while self.is_running:
                    await asyncio.sleep(1)
                    
        except Exception as e:
            self.log(f"❌ Gemini connection failed: {e}")
            import traceback
            self.log(traceback.format_exc())

    async def start_websocket_server(self, port=8765):
        """Start WebSocket server for browser connections"""
        self.log(f"🌐 Starting WebSocket server on port {port}...")
        
        try:
            # Start WebSocket server
            server = await websockets.serve(
                self.handle_websocket_client,
                "localhost",
                port,
                reuse_address=True
            )
            self.server = server
            self.log(f"✅ WebSocket server running on ws://localhost:{port}")
            
            # Start Gemini session in parallel
            await self.start_gemini_session()
            
        except Exception as e:
            self.log(f"❌ Server error: {e}")
        finally:
            if self.server:
                self.server.close()
                await self.server.wait_closed()

    def cleanup(self):
        """Clean up resources"""
        self.is_running = False
        self.gemini_session = None
        
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
            try:
                bot.log_queue.put_nowait(f"Error: {e}")
                import traceback
                bot.log_queue.put_nowait(traceback.format_exc())
            except:
                pass

# Streamlit UI
st.set_page_config(page_title="Gemini Voice Assistant", page_icon="🎤", layout="wide")
st.title("🎤 Gemini Voice Assistant (Jordanian Dialect)")
st.caption("Real-time voice chat with low latency")

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
if 'ws_port' not in st.session_state:
    st.session_state.ws_port = find_free_port()

# Control buttons
col1, col2 = st.columns(2)

with col1:
    if st.button("▶️ Start Bot", disabled=st.session_state.is_running):
        # Create log queue for thread-safe communication
        st.session_state.log_queue = queue_module.Queue()
        
        # Create bot instance with log queue
        st.session_state.bot = GeminiStreamingBot(log_queue=st.session_state.log_queue)
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
    ws_url = f"ws://localhost:{st.session_state.ws_port}"
    st.success(f"✅ Bot is running. Allow microphone access in your browser...")
    st.info(f"WebSocket: {ws_url}")
    
    # Embed audio component with WebSocket URL
    st.subheader("Audio Interface")
    audio_component(ws_url)
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

# Auto-refresh while bot is running (minimal refresh for log updates only)
if st.session_state.is_running:
    import time
    time.sleep(2)  # Slow refresh, audio streams independently
    st.rerun()
