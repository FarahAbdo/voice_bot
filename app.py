import streamlit as st
import streamlit.components.v1 as components
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Gemini Live Voice",
    page_icon="🎤",
    layout="wide"
)

# Get API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    except:
        st.error("❌ Missing GEMINI_API_KEY")
        st.stop()

SYSTEM_INSTRUCTION = "You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. Speak naturally and conversationally. Keep your responses clear and concise, but feel free to be warm and engaging.1. Speak ONLY in Jordanian Arabic (Ammani dialect). 2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. 3. Keep responses extremely short (maximum 1 sentence). 4. Do NOT wait. Speak immediately."

# Correct WebSocket implementation
html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        .container {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 800px;
            width: 100%;
        }}
        h1 {{ text-align: center; color: #333; margin-bottom: 30px; }}
        .status {{
            text-align: center;
            padding: 15px;
            margin: 20px 0;
            border-radius: 10px;
            font-size: 18px;
            font-weight: bold;
        }}
        .status.idle {{ background: #f5f5f5; color: #666; }}
        .status.connecting {{ background: #fff3cd; color: #856404; }}
        .status.connected {{ background: #d4edda; color: #155724; }}
        .status.listening {{ background: #d1ecf1; color: #0c5460; }}
        .status.speaking {{ background: #cce5ff; color: #004085; }}
        .status.error {{ background: #f8d7da; color: #721c24; }}
        .controls {{
            display: flex;
            gap: 10px;
            justify-content: center;
            margin: 20px 0;
        }}
        .btn {{
            padding: 15px 30px;
            font-size: 16px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.3s;
        }}
        .btn-start {{ background: #28a745; color: white; }}
        .btn-start:hover {{ background: #218838; }}
        .btn-stop {{ background: #dc3545; color: white; }}
        .btn-stop:hover {{ background: #c82333; }}
        .btn:disabled {{ background: #ccc; cursor: not-allowed; }}
        .transcript {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 10px;
            padding: 20px;
            min-height: 300px;
            max-height: 400px;
            overflow-y: auto;
            margin: 20px 0;
        }}
        .message {{
            margin: 10px 0;
            padding: 10px 15px;
            border-radius: 8px;
            animation: fadeIn 0.3s;
        }}
        .message.bot {{ background: #e7f3ff; border-left: 4px solid #2196F3; }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .empty {{ text-align: center; color: #999; padding: 50px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎤 Gemini Live Voice Assistant</h1>
        <div id="status" class="status idle">Ready to connect</div>
        <div class="controls">
            <button id="startBtn" class="btn btn-start">🎙️ Start Conversation</button>
            <button id="stopBtn" class="btn btn-stop" disabled>⏹️ Stop</button>
        </div>
        <div id="transcript" class="transcript">
            <div class="empty">Your conversation will appear here...</div>
        </div>
    </div>

    <script>
        const API_KEY = "{GEMINI_API_KEY}";
        const WS_URL = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContent?key=${{API_KEY}}`;
        const SYSTEM_INSTRUCTION = `{SYSTEM_INSTRUCTION}`;
        
        let ws = null;
        let audioContext = null;
        let mediaStream = null;
        let processor = null;
        let isRunning = false;
        
        const statusDiv = document.getElementById('status');
        const transcriptDiv = document.getElementById('transcript');
        const startBtn = document.getElementById('startBtn');
        const stopBtn = document.getElementById('stopBtn');
        
        function updateStatus(text, className) {{
            statusDiv.textContent = text;
            statusDiv.className = `status ${{className}}`;
        }}
        
        function addMessage(text, isBot = false) {{
            if (transcriptDiv.querySelector('.empty')) {{
                transcriptDiv.innerHTML = '';
            }}
            const msg = document.createElement('div');
            msg.className = `message ${{isBot ? 'bot' : 'user'}}`;
            msg.textContent = `${{isBot ? '🤖 Bot: ' : '👤 You: '}}${{text}}`;
            transcriptDiv.appendChild(msg);
            transcriptDiv.scrollTop = transcriptDiv.scrollHeight;
        }}
        
        async function startConversation() {{
            try {{
                updateStatus('🔄 Connecting to Gemini...', 'connecting');
                startBtn.disabled = true;
                
                // Create WebSocket connection
                ws = new WebSocket(WS_URL);
                
                ws.onopen = async () => {{
                    console.log('WebSocket connected');
                    
                    // Send setup message
                    const setupMessage = {{
                        setup: {{
                            model: "models/gemini-2.0-flash-exp",
                            generationConfig: {{
                                responseModalities: ["AUDIO"]
                            }},
                            systemInstruction: {{
                                parts: [{{ text: SYSTEM_INSTRUCTION }}]
                            }},
                            speechConfig: {{
                                voiceConfig: {{
                                    prebuiltVoiceConfig: {{
                                        voiceName: "Charon"
                                    }}
                                }}
                            }}
                        }}
                    }};
                    
                    ws.send(JSON.stringify(setupMessage));
                    console.log('Setup message sent');
                    
                    // Setup microphone
                    await setupAudio();
                    
                    updateStatus('✅ Connected! Speak now...', 'listening');
                    stopBtn.disabled = false;
                    isRunning = true;
                }};
                
                ws.onmessage = async (event) => {{
                    const response = JSON.parse(event.data);
                    console.log('Received:', response);
                    
                    if (response.serverContent) {{
                        const serverContent = response.serverContent;
                        
                        if (serverContent.modelTurn) {{
                            for (const part of serverContent.modelTurn.parts) {{
                                // Handle text
                                if (part.text) {{
                                    addMessage(part.text, true);
                                }}
                                
                                // Handle audio
                                if (part.inlineData) {{
                                    updateStatus('🔊 Bot speaking...', 'speaking');
                                    await playAudio(part.inlineData.data, part.inlineData.mimeType);
                                    updateStatus('🎤 Listening...', 'listening');
                                }}
                            }}
                        }}
                    }}
                }};
                
                ws.onerror = (error) => {{
                    console.error('WebSocket error:', error);
                    updateStatus('❌ Connection error', 'error');
                    stopConversation();
                }};
                
                ws.onclose = () => {{
                    console.log('WebSocket closed');
                    stopConversation();
                }};
                
            }} catch (error) {{
                console.error('Start error:', error);
                updateStatus(`❌ Error: ${{error.message}}`, 'error');
                startBtn.disabled = false;
            }}
        }}
        
        async function setupAudio() {{
            // Request microphone
            mediaStream = await navigator.mediaDevices.getUserMedia({{
                audio: {{
                    channelCount: 1,
                    sampleRate: 16000,
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }}
            }});
            
            // Setup audio context
            audioContext = new (window.AudioContext || window.webkitAudioContext)({{
                sampleRate: 16000
            }});
            
            const source = audioContext.createMediaStreamSource(mediaStream);
            processor = audioContext.createScriptProcessor(4096, 1, 1);
            
            processor.onaudioprocess = (e) => {{
                if (!isRunning || !ws || ws.readyState !== WebSocket.OPEN) return;
                
                const inputData = e.inputBuffer.getChannelData(0);
                const pcm16 = convertFloat32ToInt16(inputData);
                const base64Audio = arrayBufferToBase64(pcm16.buffer);
                
                // Send audio using realtimeInput
                const message = {{
                    realtimeInput: {{
                        mediaChunks: [{{
                            mimeType: "audio/pcm;rate=16000",
                            data: base64Audio
                        }}]
                    }}
                }};
                
                ws.send(JSON.stringify(message));
            }};
            
            source.connect(processor);
            processor.connect(audioContext.destination);
        }}
        
        function stopConversation() {{
            isRunning = false;
            
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
            if (ws) {{
                ws.close();
                ws = null;
            }}
            
            startBtn.disabled = false;
            stopBtn.disabled = true;
            updateStatus('🔌 Disconnected', 'idle');
        }}
        
        async function playAudio(base64Data, mimeType) {{
            try {{
                const audioData = base64ToArrayBuffer(base64Data);
                const playContext = new (window.AudioContext || window.webkitAudioContext)({{
                    sampleRate: 24000
                }});
                const audioBuffer = await playContext.decodeAudioData(audioData);
                const source = playContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(playContext.destination);
                
                return new Promise((resolve) => {{
                    source.onended = () => {{
                        playContext.close();
                        resolve();
                    }};
                    source.start(0);
                }});
            }} catch (err) {{
                console.error('Play audio error:', err);
            }}
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
        
        startBtn.onclick = startConversation;
        stopBtn.onclick = stopConversation;
    </script>
</body>
</html>
"""

components.html(html_code, height=700, scrolling=False)

st.markdown("---")
st.info("""
### 📝 Setup Instructions:

**requirements.txt:**
```
streamlit
python-dotenv
```

**Streamlit Secrets (Settings → Secrets):**
```
GEMINI_API_KEY = "your-api-key-here"
```

✅ Uses the **correct WebSocket API** endpoint
✅ Sends audio via `realtimeInput` with `mediaChunks`
✅ Real-time bidirectional streaming
✅ Same as your PyAudio local code!
""")
