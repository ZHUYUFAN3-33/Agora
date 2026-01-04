// Global state
let currentRoomId = null;
// Auto-detect port from current location
const API_BASE = `${window.location.protocol}//${window.location.host}/api`;

// DOM elements
const chatMessages = document.getElementById('chatMessages');
const messageInput = document.getElementById('messageInput');
const sendButton = document.getElementById('sendButton');
const startButton = document.getElementById('startButton');
const clearButton = document.getElementById('clearButton');
const loadingOverlay = document.getElementById('loadingOverlay');
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

// Agent colors and icons
const agentConfig = {
    'A': { color: '#ff6b6b', icon: '🔥', name: 'ChatbotA', description: '兴奋急躁的朋友' },
    'B': { color: '#4ecdc4', icon: '🧠', name: 'ChatbotB', description: '冷静分析型顾问' },
    'C': { color: '#ffd93d', icon: '🛡️', name: 'ChatbotC', description: '怀疑节俭的风险守卫' },
    'user': { color: '#667eea', icon: '👤', name: 'You' }
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
        showLoading();
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
        
        hideLoading();
    } catch (error) {
        console.error('Error starting chat:', error);
        alert('启动对话失败，请检查服务器是否运行');
        hideLoading();
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
    showLoading();
    
    try {
        const response = await fetch(`${API_BASE}/message`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                room_id: currentRoomId,
                message: message
            })
        });
        
        const data = await response.json();
        
        // Add agent responses
        if (data.responses && data.responses.length > 0) {
            data.responses.forEach(response => {
                const agentKey = response.agent_key;
                addMessage(agentKey, response.message, 'agent');
            });
        }
        
    } catch (error) {
        console.error('Error sending message:', error);
        addMessage('system', '发送消息失败，请重试', 'system');
    } finally {
        messageInput.disabled = false;
        sendButton.disabled = false;
        hideLoading();
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
    
    // Create SVG icon based on agent
    let iconSvg = '';
    if (type === 'agent') {
        if (agentKey === 'A') {
            iconSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4 12H2M6.314 6.314l2.828 2.828M14.858 14.858l2.828 2.828M6.314 17.686l2.828-2.828M14.858 9.142l2.828-2.828M22 12h-2M17.686 6.314l-2.828 2.828M9.142 14.858l-2.828 2.828M17.686 17.686l-2.828-2.828M9.142 9.142l-2.828-2.828"/></svg>';
        } else if (agentKey === 'B') {
            iconSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44L2 22h14.5a2.5 2.5 0 0 0 2.5-2.5v-15a2.5 2.5 0 0 0-2.5-2.5h-5z"/><path d="M12 7v6"/></svg>';
        } else if (agentKey === 'C') {
            iconSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/></svg>';
        }
    } else {
        iconSvg = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    }
    
    messageDiv.innerHTML = `
        <div class="message-bubble">
            <div class="message-header">
                ${iconSvg}
                <span>${type === 'agent' ? config.name : config.name}</span>
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
    return text
        .replace(/\n/g, '<br>')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// Add welcome message
function addWelcomeMessage() {
    const welcomeDiv = document.createElement('div');
    welcomeDiv.className = 'welcome-message';
    welcomeDiv.innerHTML = `
        <h2>对话已开始！</h2>
        <p>请描述您的需求，三个AI代理将为您提供建议。</p>
    `;
    chatMessages.appendChild(welcomeDiv);
}

// Clear chat
function clearChat() {
    if (confirm('确定要清空当前对话吗？')) {
        chatMessages.innerHTML = '';
        addWelcomeMessage();
        currentRoomId = null;
        sessionInfo.style.display = 'none';
        startButton.style.display = 'inline-block';
        clearButton.style.display = 'none';
        messageInput.disabled = true;
        sendButton.disabled = true;
    }
}

// Load chat history
async function loadHistory() {
    if (!currentRoomId) return;
    
    try {
        showLoading();
        const response = await fetch(`${API_BASE}/history/${currentRoomId}`);
        const data = await response.json();
        
        chatMessages.innerHTML = '';
        data.history.forEach(msg => {
            const agentKey = getAgentKey(msg.character);
            const type = msg.character === 'user' ? 'user' : 'agent';
            addMessage(agentKey, msg.txt, type);
        });
        
        hideLoading();
    } catch (error) {
        console.error('Error loading history:', error);
        alert('加载历史记录失败');
        hideLoading();
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
function showLoading() {
    loadingOverlay.style.display = 'flex';
    loadingOverlay.style.opacity = '0';
    anime({
        targets: loadingOverlay,
        opacity: [0, 1],
        duration: 300,
        easing: 'easeOutQuad'
    });
}

function hideLoading() {
    anime({
        targets: loadingOverlay,
        opacity: [1, 0],
        duration: 300,
        easing: 'easeInQuad',
        complete: function() {
            loadingOverlay.style.display = 'none';
        }
    });
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
        alert('无法连接到服务器，请确保后端服务正在运行 (http://localhost:5000)');
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
        { percent: 20, status: '正在加载配置...' },
        { percent: 40, status: '正在初始化代理...' },
        { percent: 60, status: '正在连接服务器...' },
        { percent: 80, status: '正在准备界面...' },
        { percent: 100, status: '加载完成！' }
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
                            
                            // Start page animations
                            initPageAnimations();
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
    // Animate header
    anime({
        targets: 'header h1',
        translateY: [-30, 0],
        opacity: [0, 1],
        duration: 800,
        easing: 'spring(1, 80, 10, 0)'
    });
    
    anime({
        targets: 'header .subtitle',
        translateY: [-20, 0],
        opacity: [0, 1],
        duration: 800,
        easing: 'spring(1, 80, 10, 0)',
        delay: 200
    });
    
    // Animate agent cards
    anime({
        targets: '.agent-card',
        translateX: [-30, 0],
        opacity: [0, 1],
        duration: 600,
        easing: 'spring(1, 80, 10, 0)',
        delay: anime.stagger(100)
    });
    
    // Animate welcome message
    anime({
        targets: '.welcome-message',
        scale: [0.9, 1],
        opacity: [0, 1],
        duration: 600,
        easing: 'spring(1, 80, 10, 0)',
        delay: 500
    });
    
    // Animate start button
    anime({
        targets: startButton,
        scale: [0.8, 1],
        opacity: [0, 1],
        duration: 600,
        easing: 'spring(1, 80, 10, 0)',
        delay: 700
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

