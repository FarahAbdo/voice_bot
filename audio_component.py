import streamlit.components.v1 as components

def audio_component(websocket_url):
    """
    Custom Streamlit component for browser audio capture and playback
    Uses Web Audio API for low-latency real-time audio streaming
    """
    
    component_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                margin: 0;
                padding: 20px;
                font-family: sans-serif;
                background: transparent;
            }}
            #status {{
                padding: 10px;
                margin-bottom: 10px;
                border-radius: 5px;
                font-size: 14px;
            }}
            #visualizer {{
                width: 100%;
                height: 60px;
                background: #1E1E1E;
                border-radius: 5px;
                margin-top: 10px;
            }}
            .status-connecting {{ background: #FFA500; color: white; }}
            .status-connected {{ background: #4CAF50; color: white; }}
            .status-error {{ background: #f44336; color: white; }}
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
            let audioWorkletNode;
            let websocket;
            let audioQueue = [];
            let isPlaying = false;
            let currentSource = null;
            let nextPlayTime = 0;
            
            // WebSocket connection
            const wsUrl = '{websocket_url}';
            
            function updateStatus(message, className) {{
                statusDiv.textContent = message;
                statusDiv.className = className;
            }}
            
            // Initialize audio context and microphone
            async function initAudio() {{
                try {{
                    // Create audio context with browser's native sample rate (usually 48kHz)
                    audioContext = new (window.AudioContext || window.webkitAudioContext)();
                    console.log('Audio Context Sample Rate:', audioContext.sampleRate);
                    
                    // Get microphone access
                    mediaStream = await navigator.mediaDevices.getUserMedia({{
                        audio: {{
                            echoCancellation: true,
                            noiseSuppression: true,
                            channelCount: 1
                        }}
                    }});
                    
                    const source = audioContext.createMediaStreamSource(mediaStream);
                    const analyser = audioContext.createAnalyser();
                    analyser.fftSize = 2048;
                    source.connect(analyser);
                    
                    // Create processor for capturing audio
                    const processor = audioContext.createScriptProcessor(512, 1, 1);
                    source.connect(processor);
                    processor.connect(audioContext.destination);
                    
                    // Visualizer
                    visualize(analyser);
                    
                    // Send audio to WebSocket
                    processor.onaudioprocess = (e) => {{
                        if (websocket && websocket.readyState === WebSocket.OPEN) {{
                            const inputData = e.inputBuffer.getChannelData(0);
                            
                            // Downsample to 16kHz if needed
                            const targetSampleRate = 16000;
                            const inputSampleRate = audioContext.sampleRate;
                            const ratio = inputSampleRate / targetSampleRate;
                            
                            let outputData;
                            if (ratio > 1) {{
                                // Need to downsample
                                const outputLength = Math.floor(inputData.length / ratio);
                                outputData = new Float32Array(outputLength);
                                for (let i = 0; i < outputLength; i++) {{
                                    const srcIndex = Math.floor(i * ratio);
                                    outputData[i] = inputData[srcIndex];
                                }}
                            }} else {{
                                outputData = inputData;
                            }}
                            
                            // Convert float32 to int16 PCM
                            const pcmData = new Int16Array(outputData.length);
                            for (let i = 0; i < outputData.length; i++) {{
                                pcmData[i] = Math.max(-32768, Math.min(32767, outputData[i] * 32768));
                            }}
                            websocket.send(pcmData.buffer);
                        }}
                    }};
                    
                    updateStatus('🎤 Microphone active - Connecting to server...', 'status-connecting');
                    connectWebSocket();
                    
                }} catch (error) {{
                    updateStatus('❌ Microphone access denied: ' + error.message, 'status-error');
                    console.error('Audio initialization error:', error);
                }}
            }}
            
            // Visualizer
            function visualize(analyser) {{
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
                    canvasCtx.strokeStyle = '#4CAF50';
                    canvasCtx.beginPath();
                    
                    const sliceWidth = canvas.width / bufferLength;
                    let x = 0;
                    
                    for (let i = 0; i < bufferLength; i++) {{
                        const v = dataArray[i] / 128.0;
                        const y = v * canvas.height / 2;
                        
                        if (i === 0) {{
                            canvasCtx.moveTo(x, y);
                        }} else {{
                            canvasCtx.lineTo(x, y);
                        }}
                        
                        x += sliceWidth;
                    }}
                    
                    canvasCtx.lineTo(canvas.width, canvas.height / 2);
                    canvasCtx.stroke();
                }}
                
                draw();
            }}
            
            // WebSocket connection
            function connectWebSocket() {{
                websocket = new WebSocket(wsUrl);
                websocket.binaryType = 'arraybuffer';
                
                websocket.onopen = () => {{
                    updateStatus('✅ Connected - Speak now!', 'status-connected');
                }};
                
                websocket.onmessage = (event) => {{
                    // Receive audio from Gemini
                    playAudio(event.data);
                }};
                
                websocket.onerror = (error) => {{
                    updateStatus('❌ Connection error', 'status-error');
                    console.error('WebSocket error:', error);
                }};
                
                websocket.onclose = () => {{
                    updateStatus('⚠️ Disconnected', 'status-error');
                    setTimeout(connectWebSocket, 3000);  // Reconnect after 3s
                }};
            }}
            
            // Play next audio in queue (sequential playback)
            function playNextInQueue() {{
                if (audioQueue.length === 0) {{
                    isPlaying = false;
                    currentSource = null;
                    return;
                }}
                
                isPlaying = true;
                const audioBuffer = audioQueue.shift();
                
                // Stop any currently playing audio to prevent overlap
                if (currentSource) {{
                    try {{
                        currentSource.stop();
                    }} catch (e) {{
                        // Already stopped or not started
                    }}
                }}
                
                const source = audioContext.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioContext.destination);
                
                currentSource = source;
                
                // When this chunk finishes, play the next one
                source.onended = () => {{
                    playNextInQueue();
                }};
                
                // Schedule playback
                const currentTime = audioContext.currentTime;
                if (nextPlayTime < currentTime) {{
                    nextPlayTime = currentTime;
                }}
                
                source.start(nextPlayTime);
                nextPlayTime += audioBuffer.duration;
            }}
            
            // Play received audio
            async function playAudio(audioData) {{
                try {{
                    if (!audioContext) return;
                    
                    // Gemini sends audio at 24kHz as Int16 PCM
                    const geminiSampleRate = 24000;
                    const pcm16 = new Int16Array(audioData);
                    
                    // Convert Int16 to Float32
                    const sourceFloat32 = new Float32Array(pcm16.length);
                    for (let i = 0; i < pcm16.length; i++) {{
                        sourceFloat32[i] = pcm16[i] / 32768.0;
                    }}
                    
                    // Resample to AudioContext sample rate if needed
                    const targetSampleRate = audioContext.sampleRate;
                    let outputFloat32;
                    let outputLength;
                    
                    if (geminiSampleRate !== targetSampleRate) {{
                        // Need to resample
                        const ratio = targetSampleRate / geminiSampleRate;
                        outputLength = Math.floor(sourceFloat32.length * ratio);
                        outputFloat32 = new Float32Array(outputLength);
                        
                        for (let i = 0; i < outputLength; i++) {{
                            const srcIndex = Math.floor(i / ratio);
                            if (srcIndex < sourceFloat32.length) {{
                                outputFloat32[i] = sourceFloat32[srcIndex];
                            }}
                        }}
                    }} else {{
                        outputFloat32 = sourceFloat32;
                        outputLength = sourceFloat32.length;
                    }}
                    
                    // Create audio buffer at the correct sample rate
                    const audioBuffer = audioContext.createBuffer(1, outputLength, targetSampleRate);
                    audioBuffer.getChannelData(0).set(outputFloat32);
                    
                    // Add to queue instead of playing immediately
                    audioQueue.push(audioBuffer);
                    
                    // Start playing if not already playing
                    if (!isPlaying) {{
                        playNextInQueue();
                    }}
                    
                }} catch (error) {{
                    console.error('Audio playback error:', error);
                }}
            }}
            
            // Start everything
            initAudio();
        </script>
    </body>
    </html>
    """
    
    components.html(component_html, height=120)
