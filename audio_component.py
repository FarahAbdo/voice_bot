import streamlit.components.v1 as components

def audio_component(ws_url, key=None):
    """
    Custom Streamlit component for real-time audio streaming via WebSocket.
    
    Args:
        ws_url: WebSocket URL to connect to for bidirectional audio streaming
        key: Optional unique key for the component
    """
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                padding: 10px;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: transparent;
            }}
            #status {{
                padding: 12px;
                margin-bottom: 15px;
                border-radius: 8px;
                font-size: 14px;
                text-align: center;
                font-weight: 500;
            }}
            #visualizer {{
                width: 100%;
                height: 80px;
                background: #1E1E1E;
                border-radius: 8px;
                margin-top: 10px;
            }}
            .status-connecting {{
                background: #9E9E9E;
                color: white;
            }}
            .status-ready {{
                background: #4CAF50;
                color: white;
            }}
            .status-streaming {{
                background: #2196F3;
                color: white;
                animation: pulse 2s infinite;
            }}
            .status-error {{
                background: #f44336;
                color: white;
            }}
            @keyframes pulse {{
                0%, 100% {{ opacity: 1; }}
                50% {{ opacity: 0.7; }}
            }}
        </style>
    </head>
    <body>
        <div id="status" class="status-connecting">Initializing...</div>
        <canvas id="visualizer"></canvas>

        <script>
            const statusDiv = document.getElementById('status');
            const canvas = document.getElementById('visualizer');
            const canvasCtx = canvas.getContext('2d');

            let audioContext;
            let mediaStream;
            let analyser;
            let processor;
            let ws;
            let isStreaming = false;
            let nextPlayTime = 0;

            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = className;
            }}

            async function initAudio(wsUrl) {{
                try {{
                    updateStatus('🎤 Requesting microphone access...', 'status-connecting');

                    // Use default sample rate for lowest latency
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();

                    mediaStream = await navigator.mediaDevices.getUserMedia({{
                        audio: {{
                            echoCancellation: true,
                            noiseSuppression: true,
                            autoGainControl: true
                        }}
                    }});

                    const source = audioContext.createMediaStreamSource(mediaStream);
                    analyser = audioContext.createAnalyser();
                    analyser.fftSize = 1024;  // Smaller FFT for lower overhead
                    source.connect(analyser);

                    visualize();
                    await connectWebSocket(wsUrl);

                }} catch (error) {{
                    updateStatus('❌ Microphone access denied', 'status-error');
                    console.error('Audio init error:', error);
                }}
            }}

            async function connectWebSocket(wsUrl) {{
                try {{
                    updateStatus('🔌 Connecting to server...', 'status-connecting');

                    ws = new WebSocket(wsUrl);
                    ws.binaryType = 'arraybuffer';

                    ws.onopen = () => {{
                        updateStatus('✅ Connected - Streaming audio...', 'status-streaming');
                        startMicrophoneStreaming();
                    }};

                    ws.onmessage = (event) => {{
                        if (event.data instanceof ArrayBuffer) {{
                            playAudioChunk(event.data);
                        }}
                    }};

                    ws.onerror = () => {{
                        updateStatus('❌ Connection error', 'status-error');
                    }};

                    ws.onclose = () => {{
                        updateStatus('🔌 Disconnected', 'status-error');
                        isStreaming = false;
                        if (processor) {{
                            processor.disconnect();
                        }}
                    }};

                }} catch (error) {{
                    updateStatus('❌ Connection failed', 'status-error');
                }}
            }}

            function startMicrophoneStreaming() {{
                if (isStreaming) return;
                isStreaming = true;

                // Ultra-low latency: 256 samples (smallest recommended size)
                processor = audioContext.createScriptProcessor(256, 1, 1);
                
                const source = audioContext.createMediaStreamSource(mediaStream);
                source.connect(processor);
                processor.connect(audioContext.destination);

                processor.onaudioprocess = (e) => {{
                    if (!isStreaming || ws.readyState !== WebSocket.OPEN) return;

                    const inputData = e.inputBuffer.getChannelData(0);
                    const pcm16Data = downsampleAndConvert(inputData, audioContext.sampleRate, 16000);
                    
                    // Send immediately (no try-catch overhead)
                    ws.send(pcm16Data.buffer);
                }};
            }}

            function downsampleAndConvert(inputBuffer, inputRate, outputRate) {{
                const ratio = inputRate / outputRate;
                const outputLength = Math.floor(inputBuffer.length / ratio);
                const output = new Int16Array(outputLength);

                // Optimized conversion loop
                for (let i = 0; i < outputLength; i++) {{
                    const srcIndex = Math.floor(i * ratio);
                    const sample = Math.max(-1, Math.min(1, inputBuffer[srcIndex]));
                    output[i] = sample < 0 ? sample * 32768 : sample * 32767;
                }}

                return output;
            }}

            function playAudioChunk(arrayBuffer) {{
                const pcm16 = new Int16Array(arrayBuffer);
                const float32 = new Float32Array(pcm16.length);
                
                // Optimized conversion
                for (let i = 0; i < pcm16.length; i++) {{
                    float32[i] = pcm16[i] / (pcm16[i] < 0 ? 32768 : 32767);
                }}

                const audioBuffer = audioContext.createBuffer(1, float32.length, 24000);
                audioBuffer.getChannelData(0).set(float32);

                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioContext.destination);

                const currentTime = audioContext.currentTime;
                
                // Smart scheduling for smooth playback
                if (nextPlayTime < currentTime) {{
                    nextPlayTime = currentTime + 0.01;  // Small buffer to prevent glitches
                }}

                source.start(nextPlayTime);
                nextPlayTime += audioBuffer.duration;
            }}

            function visualize() {{
                const bufferLength = analyser.frequencyBinCount;
                const dataArray = new Uint8Array(bufferLength);

                canvas.width = canvas.offsetWidth;
                canvas.height = canvas.offsetHeight;

                let frameCount = 0;
                function draw() {{
                    requestAnimationFrame(draw);
                    
                    // Only update visualizer every 3 frames to reduce overhead
                    if (++frameCount % 3 !== 0) return;
                    
                    analyser.getByteTimeDomainData(dataArray);

                    canvasCtx.fillStyle = '#1E1E1E';
                    canvasCtx.fillRect(0, 0, canvas.width, canvas.height);

                    canvasCtx.lineWidth = 2;
                    canvasCtx.strokeStyle = isStreaming ? '#2196F3' : '#4CAF50';
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

            // Initialize when page loads
            initAudio('{ws_url}');
        </script>
    </body>
    </html>
    """
    
    # Render the HTML component
    components.html(html_code, height=160, scrolling=False)


