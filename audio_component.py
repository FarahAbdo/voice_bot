import streamlit.components.v1 as components
import json
import base64

def audio_component(audio_output_base64=None, key=None):
    """
    Custom Streamlit component for turn-based audio interaction.
    - Records audio until silence is detected.
    - Sends audio to Python backend.
    - Plays audio received from Python backend.
    """
    
    component_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                padding: 10px;
                font-family: sans-serif;
                background: transparent;
                color: white;
            }}
            #status {{
                padding: 10px;
                margin-bottom: 10px;
                border-radius: 5px;
                font-size: 14px;
                text-align: center;
            }}
            #visualizer {{
                width: 100%;
                height: 60px;
                background: #1E1E1E;
                border-radius: 5px;
                margin-top: 10px;
            }}
            .status-listening {{ background: #FFA500; color: white; animation: pulse 2s infinite; }}
            .status-processing {{ background: #2196F3; color: white; }}
            .status-playing {{ background: #4CAF50; color: white; }}
            .status-error {{ background: #f44336; color: white; }}
            
            @keyframes pulse {{
                0% {{ opacity: 1; }}
                50% {{ opacity: 0.6; }}
                100% {{ opacity: 1; }}
            }}
        </style>
    </head>
    <body>
        <div id="status" class="status-listening">Initializing...</div>
        <canvas id="visualizer"></canvas>
        
        <script>
            // Streamlit communication helper
            function sendMessageToStreamlit(data) {{
                window.parent.postMessage({{
                    type: "streamlit:setComponentValue",
                    value: data,
                    dataType: "json"
                }}, "*");
            }}

            const statusDiv = document.getElementById('status');
            const canvas = document.getElementById('visualizer');
            const canvasCtx = canvas.getContext('2d');
            
            let audioContext;
            let mediaStream;
            let analyser;
            let processor;
            let audioInputData = [];
            let isRecording = false;
            let silenceStart = null;
            let silenceThreshold = 0.02; // Adjust for sensitivity
            let silenceDuration = 1500; // 1.5 seconds of silence to stop
            
            // Audio output from Python
            const audioOutputBase64 = "{audio_output_base64 or ''}";
            
            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = className;
            }}
            
            async function initAudio() {{
                try {{
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    
                    // Get microphone
                    mediaStream = await navigator.mediaDevices.getUserMedia({{
                        audio: {{
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }}
                    }});
                    
                    const source = audioContext.createMediaStreamSource(mediaStream);
                    analyser = audioContext.createAnalyser();
                    analyser.fftSize = 2048;
                    source.connect(analyser);
                    
                    // Visualizer
                    visualize();
                    
                    // If we have audio to play, play it first
                    if (audioOutputBase64) {{
                        playAudioResponse(audioOutputBase64);
                    }} else {{
                        startRecording();
                    }}
                    
                }} catch (error) {{
                    updateStatus('❌ Microphone access denied', 'status-error');
                    console.error(error);
                }}
            }}
            
            function startRecording() {{
                if (isRecording) return;
                
                audioInputData = [];
                isRecording = true;
                silenceStart = null;
                updateStatus('🎤 Listening...', 'status-listening');
                
                // Use ScriptProcessor for raw audio access (simpler than AudioWorklet for this)
                processor = audioContext.createScriptProcessor(4096, 1, 1);
                const source = audioContext.createMediaStreamSource(mediaStream);
                source.connect(processor);
                processor.connect(audioContext.destination);
                
                processor.onaudioprocess = (e) => {{
                    if (!isRecording) return;
                    
                    const inputData = e.inputBuffer.getChannelData(0);
                    
                    // Check for silence
                    let sum = 0;
                    for (let i = 0; i < inputData.length; i++) {{
                        sum += inputData[i] * inputData[i];
                    }}
                    const rms = Math.sqrt(sum / inputData.length);
                    
                    if (rms < silenceThreshold) {{
                        if (!silenceStart) silenceStart = Date.now();
                        else if (Date.now() - silenceStart > silenceDuration) {{
                            // Silence detected for long enough
                            stopRecordingAndSend();
                        }}
                    }} else {{
                        silenceStart = null; // Reset silence timer
                    }}
                    
                    // Downsample and store data (simple decimation)
                    // Browser is usually 44.1k or 48k, we want ~16k for efficiency
                    const ratio = Math.floor(audioContext.sampleRate / 16000);
                    for (let i = 0; i < inputData.length; i += ratio) {{
                        audioInputData.push(inputData[i]);
                    }}
                }};
            }}
            
            function stopRecordingAndSend() {{
                if (!isRecording) return;
                isRecording = false;
                
                if (processor) {{
                    processor.disconnect();
                    processor.onaudioprocess = null;
                }}
                
                updateStatus('🤖 Processing...', 'status-processing');
                
                // Convert float array to base64 PCM (16-bit)
                const pcmData = new Int16Array(audioInputData.length);
                for (let i = 0; i < audioInputData.length; i++) {{
                    // Clamp and scale
                    let s = Math.max(-1, Math.min(1, audioInputData[i]));
                    pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                }}
                
                // Convert to binary string then base64
                let binary = '';
                const bytes = new Uint8Array(pcmData.buffer);
                const len = bytes.byteLength;
                for (let i = 0; i < len; i++) {{
                    binary += String.fromCharCode(bytes[i]);
                }}
                const base64Data = btoa(binary);
                
                // Send to Python
                sendMessageToStreamlit(base64Data);
            }}
            
            async function playAudioResponse(base64Audio) {{
                updateStatus('🔊 Speaking...', 'status-playing');
                
                try {{
                    // Decode base64
                    const binaryString = atob(base64Audio);
                    const len = binaryString.length;
                    const bytes = new Uint8Array(len);
                    for (let i = 0; i < len; i++) {{
                        bytes[i] = binaryString.charCodeAt(i);
                    }}
                    
                    // Decode audio data (assuming WAV or compatible format from Gemini)
                    // Note: Gemini sends raw PCM usually, but we'll handle WAV container in Python
                    const audioBuffer = await audioContext.decodeAudioData(bytes.buffer);
                    
                    const source = audioContext.createBufferSource();
                    source.buffer = audioBuffer;
                    source.connect(audioContext.destination);
                    
                    source.onended = () => {{
                        // Start listening again after speaking
                        startRecording();
                    }};
                    
                    source.start(0);
                    
                }} catch (e) {{
                    console.error("Playback error", e);
                    // If decode fails (raw PCM?), try raw playback or just restart recording
                    startRecording();
                }}
            }}
            
            function visualize() {{
                const bufferLength = analyser.frequencyBinCount;
                const dataArray = new Uint8Array(bufferLength);
                
                canvas.width = canvas.offsetWidth;
                canvas.height = canvas.offsetHeight;
                
                function draw() {{
                    requestAnimationFrame(draw);
                    analyser.getByteTimeDomainData(dataArray);
                    
                    canvasCtx.fillStyle = '#1E1E1E';
                    canvasCtx.fillRect(0, 0, canvas.width, canvas.height);
                    
                    canvasCtx.lineWidth = 2;
                    canvasCtx.strokeStyle = isRecording ? '#FFA500' : '#4CAF50';
                    canvasCtx.beginPath();
                    
                    const sliceWidth = canvas.width / bufferLength;
                    let x = 0;
                    
                    for (let i = 0; i < bufferLength; i++) {{
                        const v = dataArray[i] / 128.0;
                        const y = v * canvas.height / 2;
                        
                        if (i === 0) canvasCtx.moveTo(x, y);
                        else canvasCtx.lineTo(x, y);
                        
                        x += sliceWidth;
                    }}
                    
                    canvasCtx.lineTo(canvas.width, canvas.height / 2);
                    canvasCtx.stroke();
                }}
                draw();
            }}
            
            // Start
            initAudio();
            
        </script>
    </body>
    </html>
    """
    
    return components.html(component_html, height=120)
