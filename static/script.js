document.addEventListener('DOMContentLoaded', () => {
    // Session management
    let currentSessionId = getSessionIdFromURL();
    let isConversationActive = false;
    let isRecording = false;
    let pendingRecording = false;

    // UI Elements
    const mainRecordBtn = document.getElementById('mainRecordBtn');
    const recordIcon = document.getElementById('recordIcon');
    const chatStatus = document.getElementById('chatStatus');
    const chatResponseAudio = document.getElementById('chatResponseAudio');
    const chatVisualizer = document.getElementById('chatVisualizer');
    const chatCanvasCtx = chatVisualizer.getContext('2d');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    const pulseRings = [
        document.getElementById('pulseRing1'),
        document.getElementById('pulseRing2'),
        document.getElementById('pulseRing3')
    ];

    // Audio recording variables
    let chatMediaRecorder, chatAudioChunks = [], chatAudioContext, chatAnalyser,
        chatDataArray, chatSource, chatAnimationId;

    // Initialize session
    if (!currentSessionId) {
        createNewSession();
    } else {
        loadChatHistory();
    }

    function getSessionIdFromURL() {
        const urlParams = new URLSearchParams(window.location.search);
        return urlParams.get('session_id');
    }

    function updateURLWithSession(sessionId) {
        const url = new URL(window.location);
        url.searchParams.set('session_id', sessionId);
        window.history.pushState({}, '', url);
    }

    async function createNewSession() {
        try {
            const response = await fetch('/agent/session/new', { method: 'POST' });
            const data = await response.json();
            currentSessionId = data.session_id;
            updateURLWithSession(currentSessionId);
            console.log('New session created:', currentSessionId);
        } catch (error) {
            console.error('Failed to create session:', error);
            currentSessionId = 'session-' + Math.random().toString(36).substr(2, 9);
            updateURLWithSession(currentSessionId);
        }
    }

    async function loadChatHistory() {
        try {
            const response = await fetch(`/agent/chat/${currentSessionId}/history`);
            const data = await response.json();
            displayChatHistory(data.chat_history);
        } catch (error) {
            console.error('Failed to load chat history:', error);
        }
    }

    function displayChatHistory(history) {
        const chatHistoryDiv = document.getElementById('chatHistory');
        
        if (history && history.length > 0) {
            chatHistoryDiv.innerHTML = '';
            history.forEach(message => {
                const messageDiv = document.createElement('div');
                messageDiv.className = message.role === 'user'
                    ? 'mb-4 p-4 bg-blue-500/20 rounded-xl border-l-4 border-blue-400 chat-message'
                    : 'mb-4 p-4 bg-purple-500/20 rounded-xl border-l-4 border-purple-400 chat-message';
                
                const roleSpan = document.createElement('div');
                roleSpan.className = 'font-semibold text-sm text-white/80 uppercase mb-2';
                roleSpan.textContent = message.role === 'user' ? '🗣️ You' : '🤖 Assistant';
                
                const contentP = document.createElement('div');
                contentP.className = 'text-white leading-relaxed';
                contentP.textContent = message.content;
                
                messageDiv.appendChild(roleSpan);
                messageDiv.appendChild(contentP);
                chatHistoryDiv.appendChild(messageDiv);
            });
            
            chatHistoryDiv.scrollTop = chatHistoryDiv.scrollHeight;
        } else {
            chatHistoryDiv.innerHTML = `
                <div class="text-white/60 italic text-center flex items-center justify-center h-20">
                    <div class="text-lg">Start a conversation by pressing the record button below</div>
                </div>
            `;
        }
    }

    function updateRecordButton(state) {
        switch(state) {
            case 'idle':
                recordIcon.textContent = '🎙️';
                mainRecordBtn.className = 'relative w-32 h-32 bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 text-white rounded-full shadow-2xl transition-all duration-300 transform hover:scale-105 flex items-center justify-center text-2xl font-bold';
                pulseRings.forEach(ring => ring.classList.add('hidden'));
                break;
            case 'recording':
                recordIcon.textContent = '🔴';
                mainRecordBtn.className = 'relative w-32 h-32 bg-gradient-to-r from-red-500 to-pink-600 text-white rounded-full shadow-2xl flex items-center justify-center text-2xl font-bold recording-animation';
                pulseRings.forEach(ring => ring.classList.remove('hidden'));
                break;
            case 'processing':
                recordIcon.textContent = '⏳';
                mainRecordBtn.className = 'relative w-32 h-32 bg-gradient-to-r from-yellow-500 to-orange-600 text-white rounded-full shadow-2xl flex items-center justify-center text-2xl font-bold';
                pulseRings.forEach(ring => ring.classList.add('hidden'));
                break;
        }
    }

    function updateStatus(message) {
        chatStatus.textContent = message;
        chatStatus.classList.remove('hidden');
        if (message.includes('✅')) {
            setTimeout(() => chatStatus.classList.add('hidden'), 3000);
        }
    }

    // Main record button event listener
    mainRecordBtn.addEventListener('click', () => {
        if (!isRecording && !isConversationActive) {
            // Start new conversation
            isConversationActive = true;
            startChatRecording();
        } else if (isRecording) {
            // Stop current recording
            stopChatRecording();
        }
    });

    async function startChatRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            chatMediaRecorder = new MediaRecorder(stream);
            chatAudioChunks = [];
            isRecording = true;

            updateRecordButton('recording');
            updateStatus('🎤 Listening... Click to stop');

            chatMediaRecorder.ondataavailable = e => {
                if (e.data.size > 0) chatAudioChunks.push(e.data);
            };

            chatMediaRecorder.onstop = () => {
                isRecording = false;
                updateRecordButton('processing');
                updateStatus('🔄 Processing your message...');

                const blob = new Blob(chatAudioChunks, { type: 'audio/wav' });
                const formData = new FormData();
                formData.append('file', blob, 'chat_recording.wav');

                fetch(`/agent/chat/${currentSessionId}`, {
                    method: 'POST',
                    body: formData
                })
                .then(res => res.json())
                .then(data => {
                    if (data.audio_url) {
                        displayChatHistory(data.chat_history);
                        chatResponseAudio.src = data.audio_url;
                        chatResponseAudio.play();
                        updateStatus('✅ Response generated!');
                        updateRecordButton('idle');
                        pendingRecording = false;
                    } else {
                        updateStatus(`❌ Error: ${data.error || 'Unknown error'}`);
                        updateRecordButton('idle');
                        isConversationActive = false;
                        pendingRecording = false;
                    }
                })
                .catch(err => {
                    console.error("Chat error:", err);
                    updateStatus('❌ Processing failed');
                    updateRecordButton('idle');
                    isConversationActive = false;
                    pendingRecording = false;
                });
            };

            chatMediaRecorder.start();
            startChatVisualizer(stream);

        } catch (error) {
            alert("Microphone access denied or not supported.");
            console.error(error);
            isConversationActive = false;
            isRecording = false;
            updateRecordButton('idle');
        }
    }

    function stopChatRecording() {
        if (chatMediaRecorder && isRecording) {
            chatMediaRecorder.stop();
            stopChatVisualizer();
        }
    }

    // Auto-restart recording after audio ends
    chatResponseAudio.addEventListener('ended', () => {
        if (isConversationActive && !pendingRecording && !isRecording) {
            setTimeout(() => {
                if (isConversationActive && !isRecording) {
                    pendingRecording = true;
                    updateStatus('🎤 Ready for your next message...');
                    setTimeout(() => {
                        if (isConversationActive && !isRecording) {
                            startChatRecording();
                        }
                    }, 1000);
                }
            }, 1000);
        }
    });

    function startChatVisualizer(stream) {
        chatAudioContext = new (window.AudioContext || window.webkitAudioContext)();
        chatAnalyser = chatAudioContext.createAnalyser();
        chatSource = chatAudioContext.createMediaStreamSource(stream);
        chatSource.connect(chatAnalyser);
        chatAnalyser.fftSize = 256;
        const bufferLength = chatAnalyser.frequencyBinCount;
        chatDataArray = new Uint8Array(bufferLength);
        chatVisualizer.classList.remove('hidden');
        drawChat();

        function drawChat() {
            chatAnimationId = requestAnimationFrame(drawChat);
            chatAnalyser.getByteFrequencyData(chatDataArray);
            chatCanvasCtx.fillStyle = 'rgba(255, 255, 255, 0.1)';
            chatCanvasCtx.fillRect(0, 0, chatVisualizer.width, chatVisualizer.height);
            const barWidth = (chatVisualizer.width / bufferLength) * 2.5;
            let x = 0;
            for (let i = 0; i < bufferLength; i++) {
                const barHeight = chatDataArray[i] / 1.5;
                const gradient = chatCanvasCtx.createLinearGradient(0, chatVisualizer.height, 0, chatVisualizer.height - barHeight);
                gradient.addColorStop(0, '#1045b9ff');
                gradient.addColorStop(0.5, '#3b82f6');
                gradient.addColorStop(1, '#8b5cf6');
                chatCanvasCtx.fillStyle = gradient;
                chatCanvasCtx.fillRect(x, chatVisualizer.height - barHeight, barWidth, barHeight);
                x += barWidth + 1;
            }
        }
    }

    function stopChatVisualizer() {
        if (chatAnimationId) cancelAnimationFrame(chatAnimationId);
        if (chatAudioContext) chatAudioContext.close();
        chatCanvasCtx.clearRect(0, 0, chatVisualizer.width, chatVisualizer.height);
        chatVisualizer.classList.add('hidden');
    }

    // Session control buttons
    newSessionBtn.addEventListener('click', async () => {
        isConversationActive = false;
        isRecording = false;
        pendingRecording = false;
        if (chatMediaRecorder) stopChatRecording();
        await createNewSession();
        displayChatHistory([]);
        updateRecordButton('idle');
        updateStatus('✅ New conversation started!');
    });

    clearHistoryBtn.addEventListener('click', async () => {
        try {
            await fetch(`/agent/chat/${currentSessionId}/history`, { method: 'DELETE' });
            displayChatHistory([]);
            updateStatus('✅ Chat history cleared!');
        } catch (error) {
            console.error('Failed to clear history:', error);
        }
    });
});
