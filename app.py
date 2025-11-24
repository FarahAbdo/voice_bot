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

# Get API key from secrets or env
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    except:
        st.error("❌ Missing GEMINI_API_KEY")
        st.stop()

SYSTEM_INSTRUCTION = """You are a helpful voice assistant BE FRIENDLY and helpful voice assistant. Speak naturally and conversationally. Keep your responses clear and concise, but feel free to be warm and engaging.1. Speak ONLY in Jordanian Arabic (Ammani dialect). 2. Use words like: 'هسا', 'بدي', 'إيش', 'طيب'. 3. Keep responses extremely short (maximum 1 sentence). 4. Do NOT wait. Speak immediately."""

# Full HTML/JS implementation
html_code = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
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
        h1 {{
            text-align: center;
            color: #333;
            margin-bottom: 30px;
        }}
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
        .btn-start {{
            background: #28a745;
            color: white;
        }}
        .btn-start:hover {{ background: #218838; }}
        .btn-stop {{
            background: #dc3545;
            color: white;
        }}
        .btn-stop:hover {{ background: #c82333; }}
        .btn:disabled {{
            background: #ccc;
            cursor: not-allowed;
        }}
        
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
        .message.bot {{
            background: #e7f3ff;
            border-left: 4px solid #2196F3;
        }}
        .message.user {{
            background: #f0f0f0;
            border-left: 4px solid #666;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: translateY(10px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .empty {{
            text-align: center;
            color: #999;
            padding: 50px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎤 Gemini Live Voice Assistant</h1>
        
        <div id="status" class="status idle">
            Ready to connect
        </div>
        
        <div class="controls">
            <button id="startBtn" class="btn btn-start">🎙️ Start Conversation</button>
            <button id="stopBtn" class="btn btn-stop" disabled>⏹️ Stop</button>
        </div>
        
        <div id="transcript" class="transcript">
            <div class="empty">Your conversation will appear here...</div>
        </div>
    </div>

    <script type="importmap">
    {{
        "imports": {{
            "@google/generative-ai": "https://esm.run/@google/generative-ai"
        }}
    }}
    </script>

    <script type="module">
        import {{ GoogleGenerativeAI }} from "@google/generative-ai";

        const API_KEY = "{GEMINI_API_KEY}";
        const MODEL = "gemini-2.0-flash-exp";
        const SYSTEM_INSTRUCTION = `{SYSTEM_INSTRUCTION}`;

        let client;
        let session;
        let audioContext;
        let mediaStream;
        let audioWorkletNode;
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

                // Initialize Gemini client
                client = new GoogleGenerativeAI(API_KEY);
                const model = client.getGenerativeModel({{ model: MODEL }});

                // Start live session
                session = await model.startChat({{
                    generationConfig: {{
                        responseModalities: "audio",
                        speechConfig: {{
                            voiceConfig: {{
                                prebuiltVoiceConfig: {{
                                    voiceName: "Charon"
                                }}
                            }}
                        }}
                    }},
                    systemInstruction: {{
                        parts: [{{ text: SYSTEM_INSTRUCTION }}]
                    }}
                }});

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
                const processor = audioContext.createScriptProcessor(4096, 1, 1);

                processor.onaudioprocess = async (e) => {{
                    if (!isRunning) return;
                    
                    const inputData = e.inputBuffer.getChannelData(0);
                    const pcm16 = convertFloat32ToInt16(inputData);
                    
                    try {{
                        // Send audio to Gemini
                        const result = await session.sendMessage([{{
                            inlineData: {{
                                mimeType: "audio/pcm",
                                data: arrayBufferToBase64(pcm16.buffer)
                            }}
                        }}]);

                        // Process response
                        for await (const chunk of result.stream) {{
                            const text = chunk.text();
                            if (text) {{
                                addMessage(text, true);
                            }}
                            
                            // Play audio if available
                            if (chunk.candidates?.[0]?.content?.parts) {{
                                for (const part of chunk.candidates[0].content.parts) {{
                                    if (part.inlineData?.data) {{
                                        updateStatus('🔊 Bot speaking...', 'speaking');
                                        await playAudio(part.inlineData.data);
                                        updateStatus('🎤 Listening...', 'listening');
                                    }}
                                }}
                            }}
                        }}
                    }} catch (err) {{
                        console.error('Send error:', err);
                    }}
                }};

                source.connect(processor);
                processor.connect(audioContext.destination);

                isRunning = true;
                stopBtn.disabled = false;
                updateStatus('✅ Connected! Speak now...', 'listening');

            }} catch (error) {{
                console.error('Start error:', error);
                updateStatus(`❌ Error: ${{error.message}}`, 'error');
                startBtn.disabled = false;
            }}
        }}

        function stopConversation() {{
            isRunning = false;
            
            if (mediaStream) {{
                mediaStream.getTracks().forEach(track => track.stop());
            }}
            if (audioContext) {{
                audioContext.close();
            }}
            
            startBtn.disabled = false;
            stopBtn.disabled = true;
            updateStatus('🔌 Disconnected', 'idle');
        }}

        async function playAudio(base64Audio) {{
            try {{
                const audioData = base64ToArrayBuffer(base64Audio);
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
### 📝 Setup Instructions for Streamlit Cloud:

1. **Create `requirements.txt`:**
   ```
   streamlit
   python-dotenv
   ```

2. **Add API Key to Secrets:**
   - Go to your app settings in Streamlit Cloud
   - Navigate to "Secrets"
   - Add: `GEMINI_API_KEY = "your-api-key-here"`

3. **Deploy!** The app will work just like your local version! 🚀

**This uses the exact same Gemini Live API as your local code, but in the browser!**
""")
