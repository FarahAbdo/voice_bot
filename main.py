import os
import asyncio
import pyaudio
import sys
import logging
import traceback
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
    def __init__(self):
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.audio = pyaudio.PyAudio()
        self.input_stream = None
        self.output_stream = None
        self.is_running = True

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
        print("🎤 Mic active. Speak now...")
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
                print(f"\n❌ Send Error: {e}")

    async def receive_audio_loop(self, session):
        """Receives audio and plays it."""
        print("\n🎧 Ready to speak...")
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
                                    print(f"🤖 Bot: ", end="", flush=True)
                                    first_part = False
                                print(f"\033[92m{part.text}\033[0m", end="", flush=True)

                    # Turn Complete (Newline)
                    if server_content.turn_complete:
                        print("\n")
                        first_part = True
                        
        except Exception as e:
            if self.is_running:
                print(f"\n❌ Receive Error: {e}")

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
        print(f"Connecting to {model_id}...")

        try:
            async with self.client.aio.live.connect(model=model_id, config=config) as session:
                print("✅ Connected! (Jordanian Mode)")
                
                await asyncio.gather(
                    self.send_audio_loop(session),
                    self.receive_audio_loop(session)
                )
        except Exception as e:
            traceback.print_exc()
            print(f"Connection Failed: {e}")
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

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    bot = GeminiLiveBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\n👋 Closing...")
        bot.cleanup()
