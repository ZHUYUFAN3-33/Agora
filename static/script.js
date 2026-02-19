// Global state
let currentRoomId = null;
let selectedScene = null;
let scenesData = null;
// Auto-detect port from current location
const API_BASE = `${window.location.protocol}//${window.location.host}/api`;

// ─── Emotion Mode State ────────────────────────────────────────────────────
let emotionModeOn = false;
let currentEmotionTag = null;   // "joy" | "anger" | "fear" | "sadness" | "surprise" | "disgust"
let emotionTarget = 'all';      // "all" | "A" | "B" | "C"
let emotionSliderDebounce = null;

const EMOTION_EMOJI = {
    joy:      '😄',
    anger:    '😠',
    fear:     '😨',
    sadness:  '😢',
    surprise: '😲',
    disgust:  '🤢',
    neutral:  '😐',
};

const EMOTION_COLORS = {
    joy:      '#ffd93d',
    anger:    '#ff6b6b',
    fear:     '#a855f7',
    sadness:  '#4ecdc4',
    surprise: '#f97316',
    disgust:  '#84cc16',
};

function toggleEmotionMode() {
    emotionModeOn = document.getElementById('emotionModeToggle').checked;
    const controls = document.getElementById('emotionControls');

    if (emotionModeOn) {
        controls.classList.add('active');
        // Trigger initial analysis with neutral text
        onSliderChange();
    } else {
        controls.classList.remove('active');
        currentEmotionTag = null;
        resetEmotionBadge();
    }
}

function onTargetChange() {
    emotionTarget = document.getElementById('emotionTargetSelect').value;
}

function resetEmotionBadge() {
    document.getElementById('emotionEmoji').textContent = '😐';
    document.getElementById('emotionName').textContent  = 'Off';
    document.getElementById('emotionConfidence').textContent = '–';
    // Reset bars
    document.querySelectorAll('.prob-bar-fill').forEach(b => b.style.width = '0%');
    document.querySelectorAll('.prob-bar-row').forEach(r => r.classList.remove('active-emotion'));
}

function onSliderChange() {
    const v = document.getElementById('valenceSlider').value / 100;
    const a = document.getElementById('arousalSlider').value / 100;
    const c = document.getElementById('controlSlider').value / 100;

    document.getElementById('valenceVal').textContent = v.toFixed(2);
    document.getElementById('arousalVal').textContent = a.toFixed(2);
    document.getElementById('controlVal').textContent = c.toFixed(2);

    if (!emotionModeOn) return;

    // Debounce API call
    clearTimeout(emotionSliderDebounce);
    emotionSliderDebounce = setTimeout(() => {
        const text = (document.getElementById('emotionTextInput') || {}).value || '';
        fetchEmotionAnalysis(text, v, a, c);
    }, 120);
}

async function fetchEmotionAnalysis(text, v, a, c) {
    try {
        const res = await fetch(`${API_BASE}/emotion/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, valence: v, arousal: a, control: c }),
        });
        if (!res.ok) return;
        const data = await res.json();
        updateEmotionUI(data);
    } catch (_) { /* server not ready */ }
}

function updateEmotionUI(data) {
    currentEmotionTag = data.emotion_tag;
    const emoji = EMOTION_EMOJI[currentEmotionTag] || '😐';
    const color = EMOTION_COLORS[currentEmotionTag] || '#888';
    const conf  = Math.round(data.confidence * 100);

    document.getElementById('emotionEmoji').textContent = emoji;
    document.getElementById('emotionName').textContent  =
        currentEmotionTag.charAt(0).toUpperCase() + currentEmotionTag.slice(1);
    document.getElementById('emotionConfidence').textContent = `${conf}%`;

    const badge = document.getElementById('emotionBadge');
    badge.style.borderColor = color;
    badge.style.background  = color + '18';

    // Update prob bars (only in sidebar emotion section, not customizer)
    const probs = data.probabilities || {};
    document.querySelectorAll('#emotionProbBars .prob-bar-row').forEach(row => {
        const em   = row.dataset.emotion;
        const fill = row.querySelector('.prob-bar-fill');
        const pct  = Math.round((probs[em] || 0) * 100);
        fill.style.width = pct + '%';
        row.classList.toggle('active-emotion', em === currentEmotionTag);
    });

    // Show example utterances
    showEmotionExamples(currentEmotionTag);
}
// ──────────────────────────────────────────────────────────────────────────────

// DOM elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const startButton = document.getElementById('startButton');
const clearButton = document.getElementById('clearButton');
const sessionInfo = document.getElementById('sessionInfo');
const roomIdSpan = document.getElementById('roomId');

// Add scrolling class when scrolling for better scrollbar visibility
let scrollTimeout;
function handleScroll(element) {
    element.classList.add('scrolling');
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
        element.classList.remove('scrolling');
    }, 1000);
}

// ─── Agent Display Names (user-editable) ──────────────────────────────────
const DEFAULT_AGENT_NAMES = { A: 'ChatbotA', B: 'ChatbotB', C: 'ChatbotC' };
let agentDisplayNames = { ...DEFAULT_AGENT_NAMES };

function openNicknameSettings() {
    document.getElementById('nicknameA').value = agentDisplayNames.A;
    document.getElementById('nicknameB').value = agentDisplayNames.B;
    document.getElementById('nicknameC').value = agentDisplayNames.C;
    document.getElementById('nicknameModal').classList.add('open');
    document.getElementById('nicknameModalOverlay').classList.add('open');
}

function closeNicknameSettings() {
    document.getElementById('nicknameModal').classList.remove('open');
    document.getElementById('nicknameModalOverlay').classList.remove('open');
}

function resetNickname(key) {
    document.getElementById(`nickname${key}`).value = DEFAULT_AGENT_NAMES[key];
}

function saveNicknameSettings() {
    agentDisplayNames.A = document.getElementById('nicknameA').value.trim() || DEFAULT_AGENT_NAMES.A;
    agentDisplayNames.B = document.getElementById('nicknameB').value.trim() || DEFAULT_AGENT_NAMES.B;
    agentDisplayNames.C = document.getElementById('nicknameC').value.trim() || DEFAULT_AGENT_NAMES.C;
    updateAllDisplayNames();
    closeNicknameSettings();
}

function updateAllDisplayNames() {
    const { A, B, C } = agentDisplayNames;
    // 1. Sidebar agent cards
    const elA = document.getElementById('agentDisplayName-A');
    const elB = document.getElementById('agentDisplayName-B');
    const elC = document.getElementById('agentDisplayName-C');
    if (elA) elA.textContent = A;
    if (elB) elB.textContent = B;
    if (elC) elC.textContent = C;

    // 2. Emotion dropdown options
    const optEA = document.getElementById('emotionOption-A');
    const optEB = document.getElementById('emotionOption-B');
    const optEC = document.getElementById('emotionOption-C');
    if (optEA) optEA.textContent = A;
    if (optEB) optEB.textContent = B;
    if (optEC) optEC.textContent = C;

    // 3. Decision dropdown options
    const optDA = document.getElementById('decisionOption-A');
    const optDB = document.getElementById('decisionOption-B');
    const optDC = document.getElementById('decisionOption-C');
    if (optDA) optDA.textContent = A;
    if (optDB) optDB.textContent = B;
    if (optDC) optDC.textContent = C;

    // 4. agentConfig (used in chat bubbles)
    if (agentConfig.A) agentConfig.A.name = A;
    if (agentConfig.B) agentConfig.B.name = B;
    if (agentConfig.C) agentConfig.C.name = C;

    // 5. Update existing chat bubbles on screen
    document.querySelectorAll('.message-agent-name[data-agent-key]').forEach(el => {
        const key = el.dataset.agentKey;
        if (agentDisplayNames[key]) el.textContent = agentDisplayNames[key];
    });
}
// ──────────────────────────────────────────────────────────────────────────────

// Agent colors and icons
const agentConfig = {
    'A': { 
        color: '#ff6b6b', 
        icon: '<img src="/Assets/AgentA.png" alt="Agent A" width="28" height="28" style="border-radius: 50%;">', 
        name: 'ChatbotA', 
        description: 'Enthusiastic Advisor' 
    },
    'B': { 
        color: '#4ecdc4', 
        icon: '<img src="/Assets/AgentB.png" alt="Agent B" width="28" height="28" style="border-radius: 50%;">', 
        name: 'ChatbotB', 
        description: 'Analytical Consultant' 
    },
    'C': { 
        color: '#ffd93d', 
        icon: '<img src="/Assets/AgentC.png" alt="Agent C" width="28" height="28" style="border-radius: 50%;">', 
        name: 'ChatbotC', 
        description: 'Skeptical Risk Guard' 
    },
    'user': { 
        color: '#667eea', 
        icon: '<img src="/Assets/YOU.png" alt="You" width="28" height="28" style="border-radius: 50%; object-fit: cover;">', 
        name: 'You' 
    }
};

// Agent configurations (stored in memory)
let agentConfigs = {
    'A': {
        temperature: 0.7,
        maxTokens: 700,
        style: 'concise',
        additionalRules: ''
    },
    'B': {
        temperature: 0.7,
        maxTokens: 700,
        style: 'balanced',
        additionalRules: ''
    },
    'C': {
        temperature: 0.7,
        maxTokens: 700,
        style: 'concise',
        additionalRules: ''
    }
};

// Store default prompts
let defaultPrompts = {
    'A': '',
    'B': '',
    'C': ''
};

let currentEditingAgent = null;

// Start a new chat session with anime.js animations
async function startChat() {
    try {
        const response = await fetch(`${API_BASE}/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const data = await response.json();
        currentRoomId = data.room_id;
        
        // Animate start button out
        anime({
            targets: startButton,
            scale: [1, 0.8],
            opacity: [1, 0],
            duration: 300,
            easing: 'easeInOutQuad',
            complete: function() {
                startButton.style.display = 'none';
            }
        });
        
        // Update UI
        chatMessages.innerHTML = '';
        addWelcomeMessage();
        messageInput.disabled = false;
        sendButton.disabled = false;
        clearButton.style.display = 'inline-block';
        
        // Animate clear button in
        anime({
            targets: clearButton,
            scale: [0.8, 1],
            opacity: [0, 1],
            duration: 400,
            easing: 'spring(1, 80, 10, 0)',
            delay: 200
        });
        
        // Show session info with animation
        sessionInfo.style.display = 'block';
        roomIdSpan.textContent = currentRoomId;
        anime({
            targets: sessionInfo,
            translateX: [-20, 0],
            opacity: [0, 1],
            duration: 500,
            easing: 'spring(1, 80, 10, 0)',
            delay: 300
        });
        
        // Animate input field
        anime({
            targets: messageInput,
            scale: [0.95, 1],
            opacity: [0.5, 1],
            duration: 400,
            easing: 'spring(1, 80, 10, 0)',
            delay: 400,
            complete: function() {
                messageInput.focus();
            }
        });
    } catch (error) {
        console.error('Error starting chat:', error);
        alert('Failed to start chat. Please check if the server is running.');
    }
}

// Send a message
async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message || !currentRoomId) return;
    
    // Add user message to UI immediately
    addMessage('user', message, 'user');
    messageInput.value = '';
    messageInput.disabled = true;
    sendButton.disabled = true;
    
    // Show typing indicator instead of full screen loading
    showTypingIndicator();
    
    try {
        // If emotion mode is on, re-analyze with actual message text before sending
        if (emotionModeOn) {
            const v = document.getElementById('valenceSlider').value / 100;
            const a = document.getElementById('arousalSlider').value / 100;
            const c = document.getElementById('controlSlider').value / 100;
            try {
                const eRes = await fetch(`${API_BASE}/emotion/analyze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message, valence: v, arousal: a, control: c }),
                });
                if (eRes.ok) {
                    const eData = await eRes.json();
                    updateEmotionUI(eData);
                }
            } catch (_) {}
        }

        // Build per-agent emotion overrides from customizer settings
        const agentEmotionOverrides = {};
        ['A','B','C'].forEach(k => {
            const s = agentCustomSettings[k];
            if (s.emotionOn && s.emotionTag) {
                agentEmotionOverrides[k] = s.emotionTag;
            }
        });

        // Sidebar emotion takes precedence if enabled (applies to target)
        let finalEmotionTag    = emotionModeOn ? currentEmotionTag : null;
        let finalEmotionTarget = emotionModeOn ? emotionTarget : null;

        const response = await fetch(`${API_BASE}/message`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                room_id: currentRoomId,
                message: message,
                emotion_tag:           finalEmotionTag,
                emotion_target:        finalEmotionTarget,
                agent_emotion_overrides: agentEmotionOverrides,
                additional_rules: {
                    A: agentCustomSettings.A.additionalPrompt,
                    B: agentCustomSettings.B.additionalPrompt,
                    C: agentCustomSettings.C.additionalPrompt,
                },
            })
        });
        
        const data = await response.json();
        
        // Hide typing indicator
        hideTypingIndicator();
        
        // Add agent responses with staggered animation
        // Backend returns all responses at once, we display them one by one
        if (data.responses && data.responses.length > 0) {
            for (let i = 0; i < data.responses.length; i++) {
                // Add delay between each message (except the first one)
                if (i > 0) {
                    await new Promise(resolve => setTimeout(resolve, 1500)); // 1.5 second delay
                }
                
                const response = data.responses[i];
                const agentKey = response.agent_key;
                addMessage(agentKey, response.message, 'agent');
            }
        }
        
    } catch (error) {
        console.error('Error sending message:', error);
        hideTypingIndicator();
        addMessage('system', '发送消息失败，请重试', 'system');
    } finally {
        messageInput.disabled = false;
        sendButton.disabled = false;
        messageInput.focus();
    }
}

// Add a message to the chat with anime.js animation
function addMessage(agentKey, text, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message message-${type}`;
    messageDiv.style.opacity = '0';
    messageDiv.style.transform = 'translateY(20px) scale(0.95)';
    
    if (type === 'agent') {
        messageDiv.setAttribute('data-agent', agentKey);
    }
    
    const config = agentConfig[agentKey] || agentConfig['user'];
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    
    // Use icon from agentConfig (now contains img tags for PNG files)
    const iconHtml = config.icon || '';
    
    const nameAttr = type === 'agent' ? `class="message-agent-name" data-agent-key="${agentKey}"` : '';
    messageDiv.innerHTML = `
        <div class="message-bubble">
            <div class="message-header">
                ${iconHtml}
                <span ${nameAttr}>${config.name}</span>
                <span class="message-time">${time}</span>
            </div>
            <div class="message-content">${formatMessage(text)}</div>
        </div>
    `;
    
    chatMessages.appendChild(messageDiv);
    
    // Animate message appearance with anime.js
    anime({
        targets: messageDiv,
        opacity: [0, 1],
        translateY: [20, 0],
        scale: [0.95, 1],
        duration: 600,
        easing: 'spring(1, 80, 10, 0)',
        complete: function() {
            scrollToBottom();
        }
    });
    
    // Highlight active agent with animation
    if (type === 'agent') {
        highlightAgent(agentKey);
    }
}

// Format message text (preserve line breaks)
function formatMessage(text) {
    // First, escape HTML special characters
    let formatted = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
    
    // Then convert newlines to <br> (won't be escaped)
    formatted = formatted.replace(/\n/g, '<br>');
    
    // Convert escaped <br> tags back to actual <br> (for backend-generated <br>)
    formatted = formatted.replace(/&lt;br&gt;/gi, '<br>');
    formatted = formatted.replace(/&lt;br\/&gt;/gi, '<br>');
    formatted = formatted.replace(/&lt;br\s*\/&gt;/gi, '<br>');
    
    return formatted;
}

// Add welcome message
function addWelcomeMessage() {
    const welcomeDiv = document.createElement('div');
    welcomeDiv.className = 'welcome-message';
    welcomeDiv.innerHTML = `
        <h2>Chat Started!</h2>
        <p>Describe your needs, and three AI agents will provide advice.</p>
    `;
    chatMessages.appendChild(welcomeDiv);
}

// Clear chat
function clearChat() {
    if (confirm('Are you sure you want to clear the current conversation?')) {
        chatMessages.innerHTML = '';
        addWelcomeMessage();
        currentRoomId = null;
        sessionInfo.style.display = 'none';
        
        // Reset and show start button with animation
        startButton.style.display = 'inline-block';
        anime({
            targets: startButton,
            scale: [0.8, 1],
            opacity: [0, 1],
            duration: 400,
            easing: 'spring(1, 80, 10, 0)'
        });
        
        // Hide clear button
        clearButton.style.display = 'none';
        
        // Disable input
        messageInput.disabled = true;
        sendButton.disabled = true;
    }
}

// Load chat history
async function loadHistory() {
    if (!currentRoomId) return;
    
    try {
        const response = await fetch(`${API_BASE}/history/${currentRoomId}`);
        const data = await response.json();
        
        chatMessages.innerHTML = '';
        data.history.forEach(msg => {
            const agentKey = getAgentKey(msg.character);
            const type = msg.character === 'user' ? 'user' : 'agent';
            addMessage(agentKey, msg.txt, type);
        });
    } catch (error) {
        console.error('Error loading history:', error);
        alert('Failed to load chat history.');
    }
}

// Get agent key from agent name
function getAgentKey(name) {
    if (name === 'ChatbotA') return 'A';
    if (name === 'ChatbotB') return 'B';
    if (name === 'ChatbotC') return 'C';
    return 'user';
}

// Highlight active agent with anime.js animation
function highlightAgent(agentKey) {
    document.querySelectorAll('.agent-card').forEach(card => {
        card.classList.remove('active');
    });
    const agentCard = document.querySelector(`[data-agent="${agentKey}"]`);
    if (agentCard) {
        agentCard.classList.add('active');
        
        // Animate agent card highlight
        anime({
            targets: agentCard,
            scale: [1, 1.05, 1],
            duration: 600,
            easing: 'spring(1, 80, 10, 0)',
            complete: function() {
                setTimeout(() => {
                    anime({
                        targets: agentCard,
                        scale: 1,
                        duration: 300,
                        easing: 'easeOutQuad',
                        complete: function() {
                            agentCard.classList.remove('active');
                        }
                    });
                }, 1500);
            }
        });
    }
}

// Scroll to bottom
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Show/hide loading overlay with anime.js animation
function showTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.style.display = 'flex';
        // Scroll to bottom to show typing indicator
        chatMessages.scrollTop = chatMessages.scrollHeight;
        
        anime({
            targets: typingIndicator,
            opacity: [0, 1],
            translateY: [10, 0],
            duration: 300,
            easing: 'easeOutQuad'
        });
    }
}

function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        anime({
            targets: typingIndicator,
            opacity: [1, 0],
            translateY: [0, -10],
            duration: 300,
            easing: 'easeInQuad',
            complete: function() {
                typingIndicator.style.display = 'none';
            }
        });
    }
}

// Enter key to send message
messageInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter' && !sendButton.disabled) {
        // Animate button press
        anime({
            targets: sendButton,
            scale: [1, 0.95, 1],
            duration: 200,
            easing: 'easeOutQuad'
        });
        sendMessage();
    }
});

// Add button click animations
sendButton.addEventListener('click', function() {
    anime({
        targets: sendButton,
        scale: [1, 0.95, 1],
        duration: 200,
        easing: 'spring(1, 80, 10, 0)'
    });
});

startButton.addEventListener('click', function() {
    anime({
        targets: startButton,
        scale: [1, 0.95, 1],
        duration: 200,
        easing: 'spring(1, 80, 10, 0)'
    });
});

// Check API health on load
async function checkHealth() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        const data = await response.json();
        console.log('API Health:', data);
    } catch (error) {
        console.error('API not available:', error);
        alert('Cannot connect to server. Please ensure the backend service is running.');
    }
}

// Page animations are now handled by initPageAnimations() after loader completes

// Agent Configuration Functions
async function openAgentConfig(agentKey) {
    currentEditingAgent = agentKey;
    const config = agentConfigs[agentKey];
    const agent = agentConfig[agentKey];
    
    // Update modal title
    document.getElementById('modalAgentName').textContent = `${agent.name} - ${agent.description}`;
    
    // Load current config
    document.getElementById('paramTemperature').value = config.temperature * 100;
    document.getElementById('tempValue').textContent = config.temperature.toFixed(2);
    document.getElementById('paramMaxTokens').value = config.maxTokens;
    document.getElementById('paramStyle').value = config.style;
    document.getElementById('agentAdditionalRules').value = config.additionalRules || '';
    
    // Load default prompt if not already loaded
    if (!defaultPrompts[agentKey]) {
        try {
            const response = await fetch(`${API_BASE}/agent-prompt/${agentKey}`);
            if (response.ok) {
                const data = await response.json();
                defaultPrompts[agentKey] = data.prompt || '';
            }
        } catch (error) {
            console.error('Error loading default prompt:', error);
        }
    }
    
    // Update preview
    updatePromptPreview();
    
    // Show modal with animation
    const modal = document.getElementById('agentModal');
    modal.style.display = 'flex';
    anime({
        targets: '.agent-modal-content',
        scale: [0.9, 1],
        opacity: [0, 1],
        duration: 300,
        easing: 'spring(1, 80, 10, 0)'
    });
    
    // Update temperature display on slider change
    const tempSlider = document.getElementById('paramTemperature');
    tempSlider.oninput = function(e) {
        const value = e.target.value / 100;
        document.getElementById('tempValue').textContent = value.toFixed(2);
        updatePromptPreview();
    };
    
    // Update preview when additional rules change
    document.getElementById('agentAdditionalRules').addEventListener('input', updatePromptPreview);
    document.getElementById('paramMaxTokens').addEventListener('input', updatePromptPreview);
    document.getElementById('paramStyle').addEventListener('change', updatePromptPreview);
}

function closeAgentConfig() {
    const modal = document.getElementById('agentModal');
    anime({
        targets: '.agent-modal-content',
        scale: [1, 0.9],
        opacity: [1, 0],
        duration: 200,
        easing: 'easeInQuad',
        complete: function() {
            modal.style.display = 'none';
            currentEditingAgent = null;
        }
    });
}

function updatePromptPreview() {
    if (!currentEditingAgent) return;
    
    const defaultPrompt = defaultPrompts[currentEditingAgent] || '';
    const additionalRules = document.getElementById('agentAdditionalRules').value.trim();
    const maxTokens = document.getElementById('paramMaxTokens').value;
    const style = document.getElementById('paramStyle').value;
    
    let fullPrompt = defaultPrompt;
    
    if (additionalRules) {
        fullPrompt += '\n\n============================================================\n';
        fullPrompt += '12. Additional rules\n';
        fullPrompt += '============================================================\n';
        fullPrompt += additionalRules;
    }
    
    // Add configuration notes
    fullPrompt += '\n\n[Configuration]';
    fullPrompt += `\nMax Tokens: ${maxTokens}`;
    fullPrompt += `\nResponse Style: ${style}`;
    
    document.getElementById('fullPromptPreview').value = fullPrompt;
}

function saveAgentConfig() {
    if (!currentEditingAgent) return;
    
    const config = agentConfigs[currentEditingAgent];
    config.temperature = parseFloat(document.getElementById('paramTemperature').value) / 100;
    config.maxTokens = parseInt(document.getElementById('paramMaxTokens').value);
    config.style = document.getElementById('paramStyle').value;
    config.additionalRules = document.getElementById('agentAdditionalRules').value;
    
    // Show success message
    const saveBtn = event.target;
    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = '<span>✓ 已保存</span>';
    saveBtn.style.background = '#4ecdc4';
    
    setTimeout(() => {
        saveBtn.innerHTML = originalText;
        saveBtn.style.background = '';
        closeAgentConfig();
    }, 1000);
}

function clearAdditionalRules() {
    if (!currentEditingAgent) return;
    document.getElementById('agentAdditionalRules').value = '';
    updatePromptPreview();
}

function loadExampleRules() {
    if (!currentEditingAgent) return;
    const examples = {
        'A': '- 每次回复必须包含一个具体的产品推荐\n- 使用至少2个感叹号来表达兴奋\n- 不要提及价格超过用户预算的选项',
        'B': '- 每次回复必须包含至少一个权衡分析\n- 使用数据或事实来支持观点\n- 如果信息不足，必须提出1-2个问题',
        'C': '- 每次回复必须包含至少一个质疑或担忧\n- 强调成本效益分析\n- 建议用户考虑二手或翻新选项'
    };
    document.getElementById('agentAdditionalRules').value = examples[currentEditingAgent] || '';
    updatePromptPreview();
}

// Close modal on outside click
document.addEventListener('click', function(e) {
    const modal = document.getElementById('agentModal');
    if (e.target === modal) {
        closeAgentConfig();
    }
});

// Startup Loading Animation
async function initStartupLoader() {
    const loader = document.getElementById('startupLoader');
    const progressLine = document.querySelector('.progress-line');
    const progressPercent = document.getElementById('progressPercent');
    const progressStatus = document.getElementById('progressStatus');
    
    if (!loader || !progressLine) return;
    
    // Wait for animejs advanced API to load
    let animeAdvanced = null;
    try {
        if (window.animeAdvanced) {
            animeAdvanced = window.animeAdvanced;
        } else {
            // Try to load it
            const module = await import('https://esm.sh/animejs');
            animeAdvanced = {
                animate: module.animate,
                svg: module.svg,
                stagger: module.stagger
            };
        }
    } catch (e) {
        console.log('Advanced animejs API not available, using fallback');
    }
    
    // Start SVG line drawing animation
    // Wait a bit for the module to fully load
    setTimeout(() => {
        if (animeAdvanced && animeAdvanced.svg && animeAdvanced.animate) {
            try {
                const lineElement = document.querySelector('.progress-line.line');
                if (lineElement) {
                    // Use the new anime.js SVG API
                    const drawable = animeAdvanced.svg.createDrawable(lineElement);
                    animeAdvanced.animate(drawable, {
                        draw: ['0 0', '0 1', '1 1'],
                        ease: 'inOutQuad',
                        duration: 2000,
                        loop: true
                    });
                }
            } catch (e) {
                console.log('SVG draw animation error:', e);
                // Fallback: use stroke-dashoffset animation
                anime({
                    targets: '.progress-line',
                    strokeDashoffset: [400, 0],
                    duration: 2000,
                    easing: 'inOutQuad',
                    loop: true,
                    direction: 'alternate'
                });
            }
        } else {
            // Fallback: use stroke-dashoffset animation
            anime({
                targets: '.progress-line',
                strokeDashoffset: [400, 0],
                duration: 2000,
                easing: 'inOutQuad',
                loop: true,
                direction: 'alternate'
            });
        }
    }, 100);
    
    // Simulate loading progress
    let progress = 0;
    const steps = [
        { percent: 20, status: 'Loading configuration...' },
        { percent: 40, status: 'Initializing agents...' },
        { percent: 60, status: 'Connecting to server...' },
        { percent: 80, status: 'Preparing interface...' },
        { percent: 100, status: 'Complete!' }
    ];
    
    let currentStep = 0;
    
    const updateProgress = () => {
        if (currentStep < steps.length) {
            const step = steps[currentStep];
            progress = step.percent;
            
            // Update progress bar with smooth animation
            const offset = 400 - (400 * progress / 100);
            // Use anime.js to animate the progress
            const currentOffset = parseFloat(progressLine.style.strokeDashoffset) || 400;
            anime({
                targets: progressLine,
                strokeDashoffset: [currentOffset, offset],
                duration: 500,
                easing: 'easeOutQuad'
            });
            
            // Update text
            anime({
                targets: [progressPercent, progressStatus],
                opacity: [0.5, 1],
                duration: 200,
                complete: function() {
                    progressPercent.textContent = `${progress}%`;
                    progressStatus.textContent = step.status;
                }
            });
            
            currentStep++;
            
            if (currentStep < steps.length) {
                setTimeout(updateProgress, 600);
            } else {
                // Complete loading
                setTimeout(() => {
                    // Fade out loader
                    anime({
                        targets: loader,
                        opacity: [1, 0],
                        duration: 500,
                        easing: 'easeOutQuad',
                        complete: function() {
                            loader.classList.add('hidden');
                            document.body.classList.remove('loading');
                            
                            // Show scene selector instead of going directly to chat
                            showSceneSelector();
                        }
                    });
                }, 500);
            }
        }
    };
    
    // Start loading animation
    setTimeout(updateProgress, 300);
}

function initPageAnimations() {
    // 页面初始化动画已移除 - 元素直接显示
    // Page initialization animations removed - elements show directly
    // ページ初期化アニメーションを削除 - 要素は直接表示
}

// Scene Selector Functions
async function loadScenes() {
    try {
        const response = await fetch('/scenes_config.json');
        if (!response.ok) {
            throw new Error('Failed to load scenes');
        }
        scenesData = await response.json();
        return scenesData;
    } catch (error) {
        console.error('Error loading scenes:', error);
        // Fallback to default scene
        return {
            scenes: [{
                id: 'laptop_purchase',
                title: 'Laptop Purchase Advisory',
                description: 'Professional advice for Black Friday laptop shopping',
                icon: '💻',
                color: '#667eea'
            }]
        };
    }
}

function renderSceneCards(scenes) {
    const grid = document.getElementById('sceneCardsGrid');
    if (!grid) return;
    
    grid.innerHTML = '';
    
    scenes.forEach((scene, index) => {
        const card = document.createElement('div');
        card.className = 'scene-card';
        card.style.setProperty('--scene-color', scene.color);
        card.style.setProperty('--scene-color-alpha', scene.color + '33');
        card.dataset.sceneId = scene.id;
        
        card.innerHTML = `
            <div class="scene-icon">${scene.icon}</div>
            <div class="scene-title">${scene.title}</div>
            <div class="scene-description">${scene.description}</div>
        `;
        
        card.addEventListener('click', () => selectScene(scene));
        grid.appendChild(card);
    });
}

async function showSceneSelector() {
    // Load scenes first
    const data = await loadScenes();
    renderSceneCards(data.scenes);
    
    const sceneSelector = document.getElementById('sceneSelector');
    if (!sceneSelector) return;
    
    sceneSelector.classList.add('active');
    const cards = sceneSelector.querySelectorAll('.scene-card');
    
    // Fade in scene selector background
    anime({
        targets: sceneSelector,
        opacity: [0, 1],
        duration: 500,
        easing: 'easeOutQuad'
    });
    
    // Animate scene cards simultaneously with stagger - smoother!
    anime({
        targets: cards,
        opacity: [0, 1],
        translateY: [40, 0],
        scale: [0.95, 1],
        delay: anime.stagger(80, {start: 300}),
        duration: 500,
        easing: 'spring(1, 80, 10, 0)',
        complete: () => {
            // Enable hover transitions after animation
            cards.forEach(card => card.classList.add('animated'));
        }
    });
}

function selectScene(scene) {
    selectedScene = scene;
    console.log('Selected scene:', scene);
    
    const sceneSelector = document.getElementById('sceneSelector');
    const card = document.querySelector(`.scene-card[data-scene-id="${scene.id}"]`);
    
    if (card) {
        // Mark card as selected
        card.classList.add('selected');
        
        // Scale up and glow effect
        anime({
            targets: card,
            scale: [1, 1.1],
            duration: 300,
            easing: 'easeOutQuad'
        });
    }
    
    // Wait a bit, then transition to chat interface
    setTimeout(() => {
        // Fade out all other cards
        const allCards = document.querySelectorAll('.scene-card');
        anime({
            targets: Array.from(allCards).filter(c => c !== card),
            opacity: [1, 0],
            scale: [1, 0.9],
            duration: 400,
            easing: 'easeInQuad'
        });
        
        // Fade out scene selector
        anime({
            targets: sceneSelector,
            opacity: [1, 0],
            duration: 600,
            delay: 200,
            easing: 'easeInQuad',
            complete: () => {
                sceneSelector.classList.remove('active');
                sceneSelector.style.display = 'none';
                
                // Show agent customizer instead of chat directly
                showAgentCustomizer();
            }
        });
    }, 800);
}

// ─── Emotion Text Input (debounce) ────────────────────────────────────────────
let emotionTextDebounce = null;

function onEmotionTextChange() {
    clearTimeout(emotionTextDebounce);
    emotionTextDebounce = setTimeout(() => {
        if (!emotionModeOn) return;
        const text = document.getElementById('emotionTextInput').value;
        const v = document.getElementById('valenceSlider').value / 100;
        const a = document.getElementById('arousalSlider').value / 100;
        const c = document.getElementById('controlSlider').value / 100;
        fetchEmotionAnalysis(text, v, a, c);
    }, 400);
}

function showEmotionExamples(tag) {
    const examples = EMOTION_EXAMPLES[tag] || [];
    const container = document.getElementById('emotionExamples');
    const list = document.getElementById('emotionExampleList');
    if (!container || !list) return;
    if (examples.length === 0) { container.style.display = 'none'; return; }
    list.innerHTML = examples.map(e => `<li>"${e}"</li>`).join('');
    container.style.display = 'block';
}

// ─── Sidebar Collapse ──────────────────────────────────────────────────────────
let sidebarCollapsed = false;
let sidebarAnimating = false;

function toggleSidebar() {
    if (sidebarAnimating) return;
    sidebarAnimating = true;

    const sidebar    = document.getElementById('sidebar');
    const inner      = document.getElementById('sidebarInner');
    const expandBtn  = document.getElementById('sidebarExpandBtn');
    const container  = document.getElementById('chatContainer');

    if (!sidebarCollapsed) {
        // ── CLOSE ──────────────────────────────────────────────
        // 1. Fade out content immediately (150ms)
        inner.style.transition = 'opacity 0.15s ease';
        inner.style.opacity = '0';
        inner.style.pointerEvents = 'none';

        // 2. After content fades, collapse width (280ms)
        setTimeout(() => {
            sidebar.classList.add('collapsed');
            container.classList.add('sidebar-hidden');
        }, 120);

        // 3. Show expand button after sidebar starts closing
        setTimeout(() => {
            expandBtn.classList.add('visible');
            sidebarCollapsed = true;
            sidebarAnimating = false;
        }, 300);

    } else {
        // ── OPEN ───────────────────────────────────────────────
        // 1. Hide expand button
        expandBtn.classList.remove('visible');

        // 2. Expand width immediately (280ms)
        sidebar.classList.remove('collapsed');
        container.classList.remove('sidebar-hidden');
        inner.style.opacity = '0';
        inner.style.transition = 'none'; // hold at 0 while width opens

        // 3. After width is mostly open, fade in content
        setTimeout(() => {
            inner.style.transition = 'opacity 0.2s ease';
            inner.style.opacity = '1';
            inner.style.pointerEvents = '';
        }, 180);

        setTimeout(() => {
            sidebarCollapsed = false;
            sidebarAnimating = false;
        }, 400);
    }
}

// ─── Decision Mode ─────────────────────────────────────────────────────────────
let decisionModeOn = false;
let decisionTriggerTurns = 5;
let decisionStyle = 'brief';
let decisionAgent = 'auto';
let chatTurnsSinceDecision = 0;

function toggleDecisionMode() {
    decisionModeOn = document.getElementById('decisionModeToggle').checked;
    const controls = document.getElementById('decisionControls');
    if (decisionModeOn) {
        controls.classList.add('active');
    } else {
        controls.classList.remove('active');
    }
}

function onDecisionTriggerChange() {
    const v = document.getElementById('decisionTriggerSlider').value;
    document.getElementById('decisionTriggerVal').textContent = `${v} turns`;
    decisionTriggerTurns = parseInt(v);
}

// ─── Agent Customizer ──────────────────────────────────────────────────────────
const EMOTION_EXAMPLES = {
    joy:      ["Nice! I love that direction.", "This could turn out really well.", "Awesome—let's build on that.", "That sounds exciting!", "Yes! That's the energy."],
    anger:    ["No. That's not the right move.", "Stop hesitating and act.", "This is inefficient—fix it now.", "You already know what needs to happen.", "Act. Don't overthink it."],
    fear:     ["I'm not fully comfortable with that yet.", "What if this goes wrong?", "Maybe we should double-check first.", "There's uncertainty here.", "Can we reduce the risk?"],
    sadness:  ["That feels heavy…", "Let's slow down.", "We don't need to rush.", "One small step at a time.", "It's okay to move gently."],
    surprise: ["Wait—really?", "That wasn't expected.", "Wow, that changes things.", "Interesting twist.", "Okay, that's new."],
    disgust:  ["That doesn't feel right.", "I wouldn't go near that.", "This feels off.", "Let's not entertain that.", "No. Drop it."],
};

// Per-agent settings set in the customizer
let agentCustomSettings = {
    A: { emotionOn: false, emotionTag: null, valence: 0.5, arousal: 0.5, control: 0.5, additionalPrompt: '', decisionOn: false, decisionTrigger: 5, decisionStyle: 'brief' },
    B: { emotionOn: false, emotionTag: null, valence: 0.5, arousal: 0.5, control: 0.5, additionalPrompt: '', decisionOn: false, decisionTrigger: 5, decisionStyle: 'brief' },
    C: { emotionOn: false, emotionTag: null, valence: 0.5, arousal: 0.5, control: 0.5, additionalPrompt: '', decisionOn: false, decisionTrigger: 5, decisionStyle: 'brief' },
};
let custDebounces = { A: null, B: null, C: null };
let custCardOpen = { A: false, B: false, C: false };

function showAgentCustomizer() {
    const customizer = document.getElementById('agentCustomizer');
    customizer.style.display = 'flex';
    // Sync display names
    ['A','B','C'].forEach(k => {
        document.getElementById(`custName-${k}`).value = agentDisplayNames[k];
        document.getElementById(`custCardName-${k}`).textContent = agentDisplayNames[k];
    });
    anime({
        targets: customizer,
        opacity: [0, 1],
        translateY: [30, 0],
        duration: 600,
        easing: 'easeOutCubic'
    });
}

function backToScenes() {
    const customizer = document.getElementById('agentCustomizer');
    const sceneSelector = document.getElementById('sceneSelector');
    anime({
        targets: customizer,
        opacity: [1, 0],
        duration: 400,
        easing: 'easeInQuad',
        complete: () => {
            customizer.style.display = 'none';
            sceneSelector.style.display = '';
            sceneSelector.classList.add('active');
            anime({ targets: sceneSelector, opacity: [0, 1], duration: 400, easing: 'easeOutQuad' });
        }
    });
}

function startChatFromCustomizer() {
    // Save customizer settings
    ['A','B','C'].forEach(k => {
        const name = document.getElementById(`custName-${k}`).value.trim();
        if (name) agentDisplayNames[k] = name;
        agentCustomSettings[k].additionalPrompt = document.getElementById(`custPrompt-${k}`).value.trim();
        agentCustomSettings[k].decisionStyle = document.getElementById(`custDecisionStyle-${k}`).value;
    });
    updateAllDisplayNames();

    const customizer = document.getElementById('agentCustomizer');
    anime({
        targets: customizer,
        opacity: [1, 0],
        duration: 400,
        easing: 'easeInQuad',
        complete: () => {
            customizer.style.display = 'none';
            showChatInterface();
        }
    });
}

function toggleCustCard(key) {
    const body = document.getElementById(`custBody-${key}`);
    const chevron = document.getElementById(`custChevron-${key}`);
    custCardOpen[key] = !custCardOpen[key];
    if (custCardOpen[key]) {
        body.classList.add('open');
        chevron.style.transform = 'rotate(180deg)';
    } else {
        body.classList.remove('open');
        chevron.style.transform = 'rotate(0deg)';
    }
}

function onCustNameChange(key) {
    const name = document.getElementById(`custName-${key}`).value;
    document.getElementById(`custCardName-${key}`).textContent = name || `Chatbot${key}`;
}

function toggleCustEmotion(key) {
    const on = document.getElementById(`custEmotionToggle-${key}`).checked;
    agentCustomSettings[key].emotionOn = on;
    const body = document.getElementById(`custEmotionBody-${key}`);
    if (on) {
        body.classList.add('active');
        onCustSliderChange(key);
    } else {
        body.classList.remove('active');
        agentCustomSettings[key].emotionTag = null;
    }
}

function onCustEmotionTextChange(key) {
    clearTimeout(custDebounces[key]);
    custDebounces[key] = setTimeout(() => {
        if (!agentCustomSettings[key].emotionOn) return;
        const text = document.getElementById(`custEmotionText-${key}`).value;
        const v = document.getElementById(`custValence-${key}`).value / 100;
        const a = document.getElementById(`custArousal-${key}`).value / 100;
        const c = document.getElementById(`custControl-${key}`).value / 100;
        fetchCustEmotionAnalysis(key, text, v, a, c);
    }, 400);
}

function onCustSliderChange(key) {
    const v = document.getElementById(`custValence-${key}`).value / 100;
    const a = document.getElementById(`custArousal-${key}`).value / 100;
    const c = document.getElementById(`custControl-${key}`).value / 100;
    document.getElementById(`custValenceVal-${key}`).textContent = v.toFixed(2);
    document.getElementById(`custArousalVal-${key}`).textContent = a.toFixed(2);
    document.getElementById(`custControlVal-${key}`).textContent = c.toFixed(2);
    agentCustomSettings[key].valence = v;
    agentCustomSettings[key].arousal = a;
    agentCustomSettings[key].control = c;
    if (!agentCustomSettings[key].emotionOn) return;
    clearTimeout(custDebounces[key]);
    custDebounces[key] = setTimeout(() => {
        const text = document.getElementById(`custEmotionText-${key}`).value;
        fetchCustEmotionAnalysis(key, text, v, a, c);
    }, 120);
}

async function fetchCustEmotionAnalysis(key, text, v, a, c) {
    try {
        const res = await fetch(`${API_BASE}/emotion/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, valence: v, arousal: a, control: c }),
        });
        if (!res.ok) return;
        const data = await res.json();
        agentCustomSettings[key].emotionTag = data.emotion_tag;
        // Update badge
        const emoji = EMOTION_EMOJI[data.emotion_tag] || '😐';
        document.getElementById(`custEmotionEmoji-${key}`).textContent = emoji;
        document.getElementById(`custEmotionName-${key}`).textContent =
            data.emotion_tag.charAt(0).toUpperCase() + data.emotion_tag.slice(1);
        const conf = Math.round(data.confidence * 100);
        document.getElementById(`custEmotionConf-${key}`).textContent = `${conf}%`;
        const color = EMOTION_COLORS[data.emotion_tag] || '#888';
        const badge = document.getElementById(`custEmotionBadge-${key}`);
        badge.style.borderColor = color;
        badge.style.background = color + '18';
        // Show examples
        const examples = EMOTION_EXAMPLES[data.emotion_tag] || [];
        const exContainer = document.getElementById(`custEmotionExamples-${key}`);
        const exList = document.getElementById(`custEmotionExampleList-${key}`);
        if (examples.length > 0) {
            exList.innerHTML = examples.map(e => `<li>"${e}"</li>`).join('');
            exContainer.style.display = 'block';
        } else {
            exContainer.style.display = 'none';
        }
    } catch (_) {}
}

function toggleCustDecision(key) {
    const on = document.getElementById(`custDecisionToggle-${key}`).checked;
    agentCustomSettings[key].decisionOn = on;
    const body = document.getElementById(`custDecisionBody-${key}`);
    if (on) { body.classList.add('active'); }
    else { body.classList.remove('active'); }
}

function onCustDecisionChange(key) {
    const v = document.getElementById(`custDecisionTrigger-${key}`).value;
    document.getElementById(`custDecisionTriggerVal-${key}`).textContent = `${v} turns`;
    agentCustomSettings[key].decisionTrigger = parseInt(v);
}

function showChatInterface() {
    const container = document.querySelector('.container');
    const header = document.querySelector('header');
    const sidebar = document.querySelector('.sidebar');
    const chatMain = document.querySelector('.chat-main');
    
    document.body.style.overflow = 'hidden';
    
    // Set initial opacity for child elements
    if (header) header.style.opacity = '0';
    if (sidebar) sidebar.style.opacity = '0';
    if (chatMain) chatMain.style.opacity = '0';
    
    // Animate container - fade in and slide up
    anime({
        targets: container,
        opacity: [0, 1],
        translateY: [50, 0],
        duration: 800,
        easing: 'easeOutCubic'
    });
    
    // Animate child elements with delay - stagger effect
    anime({
        targets: [header, sidebar, chatMain],
        opacity: [0, 1],
        translateY: [30, 0],
        delay: anime.stagger(150, {start: 400}),
        duration: 700,
        easing: 'easeOutCubic'
    });
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', function() {
    document.body.classList.add('loading');
    initStartupLoader();
    
    // Apply scroll handler to scrollable elements
    setTimeout(() => {
        const scrollableElements = document.querySelectorAll('.chat-messages, .agent-modal-body');
        scrollableElements.forEach(el => {
            if (el) {
                el.addEventListener('scroll', () => handleScroll(el));
            }
        });
    }, 1000);
});

// Initialize
checkHealth();

