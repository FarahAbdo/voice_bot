import streamlit as st
import streamlit.components.v1 as components
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Gemini Live Voice Assistant",
    page_icon="🎤",
    layout="centered"
)

# Get API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') or st.secrets.get("GEMINI_API_KEY", "")

if not GEMINI_API_KEY:
    st.error("❌ Missing GEMINI_API_KEY. Please add it to Streamlit secrets or .env file.")
    st.stop()

# System prompt
SYSTEM_INSTRUCTION = (
    "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. "
    "Speak naturally and conversationally. "
    "Keep your responses clear and concise, but feel free to be warm and engaging. "
    "1. Speak ONLY in Jordanian Arabic (Ammani dialect). "
    "2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. "
    "3. Keep responses extremely short (maximum 1 sentence). "
    "4. Do NOT wait. Speak immediately."
)

# Title
st.title("🎤 Gemini Live Voice Assistant")
st.markdown("**Real-time Jordanian Arabic Voice Bot** - Just speak and get instant responses!")

# HTML/JavaScript for live audio streaming
html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 600px;
            width: 100%;
        }}
        .status {{
            text-align: center;
            margin: 20px 0;
            font-size: 18px;
            font-weight: bold;
        }}
        .status.idle {{ color: #666; }}
        .status.listening {{ color: #4CAF50; }}
        .status.speaking {{ color: #2196F3; }}
        .status.error {{ color: #f44336; }}
        
        .btn {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 20px 40px;
            font-size: 18px;
            border-radius: 50px;
            cursor: pointer;
            transition: all 0.3s;
            width: 100%;
            margin: 10px 0;
            font-weight: bold;
        }}
        .btn:hover {{
            transform: scale(1.05);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }}
        .btn:disabled {{
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }}
        
        .transcript {{
            background: #f5f5f5;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
            min-height: 100px;
            max-height: 300px;
            overflow-y: auto;
        }}
        .message {{
            margin: 10px 0;
            padding: 10px;
            border-radius: 8px;
        }}
        .user {{ 
            background: #e3f2fd; 
            text-align: right;
        }}
        .bot {{ 
            background: #f1f8e9;
            color: #2e7d32;
            font-weight: bold;
        }}
        
        .pulse {{
            animation: pulse 1.5s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div id="status" class="status idle">🎤 Ready to start</div>
        <div id="transcript" class="transcript">
            <div style="text-align: center; color: #999;">Your conversation will appear here...</div>
        </div>
        <button id="startBtn" class="btn">🎤 Start Conversation</button>
        <button id="stopBtn" class="btn" style="display:none;">⏹️ Stop</button>
    </div>

    <script type="module">
        const API_KEY = '{GEMINI_API_KEY}';
        const MODEL = 'gemini-2.0-flash-exp';
        const SYSTEM_INSTRUCTION = `{SYSTEM_INSTRUCTION}`;
        
        let ws = null;
        let audioContext = null;
        let mediaStream = null;
        let processor = null;
        
        const statusDiv = document.getElementById('status');
        const transcriptDiv = document.getElementById('transcript');
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        
        function updateStatus(message, className) {{
            statusDiv.textContent = message;
            statusDiv.className = `status ${{className}}`;
        }}
        
        function addMessage(text, isBot = false) {{
            const msg = document.createElement('div');
            msg.className = `message ${{isBot ? 'bot' : 'user'}}`;
            msg.textContent = `${{isBot ? '🤖 Bot: ' : '👤 You: '}}${{text}}`;
            transcriptDiv.appendChild(msg);
            transcriptDiv.scrollTop = transcriptDiv.scrollHeight;
        }}
        
        async function startLiveSession() {{
            try {{
                updateStatus('🔄 Connecting...', 'idle');
                
                // Request microphone access
                mediaStream = await navigator.mediaDevices.getUserMedia({{ 
                    audio: {{ 
                        channelCount: 1,
                        sampleRate: 16000,
                        echoCancellation: true,
                        noiseSuppression: true
                    }} 
                }});
                
                // Setup audio context
                audioContext = new AudioContext({{ sampleRate: 16000 }});
                const source = audioContext.createMediaStreamSource(mediaStream);
                processor = audioContext.createScriptProcessor(4096, 1, 1);
                
                // Connect to Gemini WebSocket
                const url = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key=${{API_KEY}}`;
                ws = new WebSocket(url);
                
                ws.onopen = () => {{
                    updateStatus('✅ Connected! Speak now...', 'listening');
                    startBtn.style.display = 'none';
                    stopBtn.style.display = 'block';
                    
                    // Send setup message
                    ws.send(JSON.stringify({{
                        setup: {{
                            model: `models/${{MODEL}}`,
                            generation_config: {{
                                response_modalities: ["AUDIO"],
                                speech_config: {{
                                    voice_config: {{
                                        prebuilt_voice_config: {{
                                            voice_name: "Charon"
                                        }}
                                    }}
                                }}
                            }},
                            system_instruction: {{
                                parts: [{{ text: SYSTEM_INSTRUCTION }}]
                            }}
                        }}
                    }}));
                }};
                
                ws.onmessage = async (event) => {{
                    const response = JSON.parse(event.data);
                    
                    if (response.serverContent) {{
                        const parts = response.serverContent.modelTurn?.parts || [];
                        
                        for (const part of parts) {{
                            // Handle text
                            if (part.text) {{
                                addMessage(part.text, true);
                            }}
                            
                            // Handle audio
                            if (part.inlineData?.data) {{
                                updateStatus('🔊 Bot speaking...', 'speaking');
                                await playAudio(part.inlineData.data);
                                updateStatus('🎤 Listening...', 'listening');
                            }}
                        }}
                    }}
                }};
                
                ws.onerror = (error) => {{
                    updateStatus('❌ Connection error', 'error');
                    console.error('WebSocket error:', error);
                    stopLiveSession();
                }};
                
                ws.onclose = () => {{
                    updateStatus('🔌 Disconnected', 'idle');
                    stopLiveSession();
                }};
                
                // Send audio data
                processor.onaudioprocess = (e) => {{
                    if (ws && ws.readyState === WebSocket.OPEN) {{
                        const inputData = e.inputBuffer.getChannelData(0);
                        const pcm16 = convertFloat32ToInt16(inputData);
                        const base64Audio = arrayBufferToBase64(pcm16.buffer);
                        
                        ws.send(JSON.stringify({{
                            realtimeInput: {{
                                mediaChunks: [{{
                                    data: base64Audio,
                                    mimeType: "audio/pcm"
                                }}]
                            }}
                        }}));
                    }}
                }};
                
                source.connect(processor);
                processor.connect(audioContext.destination);
                
            }} catch (error) {{
                updateStatus('❌ Error: ' + error.message, 'error');
                console.error('Setup error:', error);
            }}
        }}
        
        function stopLiveSession() {{
            if (ws) {{
                ws.close();
                ws = null;
            }}
            if (processor) {{
                processor.disconnect();
                processor = null;
            }}
            if (mediaStream) {{
                mediaStream.getTracks().forEach(track => track.stop());
                mediaStream = null;
            }}
            if (audioContext) {{
                audioContext.close();
                audioContext = null;
            }}
            
            startBtn.style.display = 'block';
            stopBtn.style.display = 'none';
            updateStatus('🎤 Ready to start', 'idle');
        }}
        
        async function playAudio(base64Audio) {{
            const audioData = base64ToArrayBuffer(base64Audio);
            const audioCtx = new AudioContext({{ sampleRate: 24000 }});
            const audioBuffer = await audioCtx.decodeAudioData(audioData);
            const source = audioCtx.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioCtx.destination);
            
            return new Promise((resolve) => {{
                source.onended = () => {{
                    audioCtx.close();
                    resolve();
                }};
                source.start();
            }});
        }}
        
        function convertFloat32ToInt16(buffer) {{
            const int16 = new Int16Array(buffer.length);
            for (let i = 0; i < buffer.length; i++) {{
                const s = Math.max(-1, Math.min(1, buffer[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }}
            return int16;
        }}
        
        function arrayBufferToBase64(buffer) {{
            const bytes = new Uint8Array(buffer);
            let binary = '';
            for (let i = 0; i < bytes.byteLength; i++) {{
                binary += String.fromCharCode(bytes[i]);
            }}
            return btoa(binary);
        }}
        
        function base64ToArrayBuffer(base64) {{
            const binaryString = atob(base64);
            const bytes = new Uint8Array(binaryString.length);
            for (let i = 0; i < binaryString.length; i++) {{
                bytes[i] = binaryString.charCodeAt(i);
            }}
            return bytes.buffer;
        }}
        
        startBtn.onclick = startLiveSession;
        stopBtn.onclick = stopLiveSession;
    </script>
</body>
</html>
"""

# Display the live voice interface
components.html(html_code, height=600, scrolling=False)

# Instructions
st.markdown("---")
with st.expander("ℹ️ How to use"):
    st.markdown("""
    1. Click "Start Conversation" to begin
    2. Allow microphone access when prompted
    3. Speak naturally in Jordanian Arabic
    4. The bot will respond in real-time with audio
    5. Click "Stop" when you're done
    
    **Features:**
    - ✅ Real-time voice streaming (no recording needed)
    - ✅ Instant audio responses
    - ✅ Conversation transcript
    - ✅ Jordanian Arabic dialect
    
    **Note:** Make sure to add your `GEMINI_API_KEY` to Streamlit secrets.
    """)

st.markdown("---")
st.markdown("Built with ❤️ using Streamlit and Google Gemini 2.0")
