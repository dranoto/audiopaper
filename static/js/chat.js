// chat.js - Chat functionality

let chatHistory = [];

function appendChatMessage(message, sender) {
    const chatMessages = document.getElementById('chat-messages');
    if (!chatMessages) return;

    const initialMessage = chatMessages.querySelector('.text-muted');
    if (initialMessage) {
        initialMessage.remove();
    }

    const converter = new showdown.Converter();

    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('chat-message', `${sender}-message`, 'mb-3', 'd-flex');

    const icon = document.createElement('div');
    icon.classList.add('me-2');
    icon.innerHTML = sender === 'user' ? '<i class="bi bi-person-circle"></i>' : '<i class="bi bi-robot"></i>';

    const content = document.createElement('div');
    content.classList.add('message-content');

    if (sender === 'assistant') {
        content.innerHTML = converter.makeHtml(message);
    } else {
        content.textContent = message;
        content.style.whiteSpace = 'pre-wrap';
    }

    messageWrapper.appendChild(icon);
    messageWrapper.appendChild(content);

    chatMessages.appendChild(messageWrapper);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return content;
}

function handleChatSubmit(event) {
    event.preventDefault();
    const chatInput = document.getElementById('chat-input');
    const chatForm = document.getElementById('chat-form');

    if (!window.currentFileId) {
        alert('Please select a file first.');
        return;
    }

    if (!chatInput || !chatForm) return;

    const userMessage = chatInput.value.trim();
    if (!userMessage) return;

    chatInput.value = '';
    chatInput.disabled = true;
    const submitBtn = chatForm.querySelector('button[type="submit"]');
    if (submitBtn) submitBtn.disabled = true;

    appendChatMessage(userMessage, 'user');

    const assistantMessageContent = appendChatMessage('<span class="thinking"></span>', 'assistant');

    const converter = new showdown.Converter();

    fetch(`/chat/${window.currentFileId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: userMessage
        }),
    })
    .then(response => response.json())
    .then(data => {
        if (!response.ok) {
            const errorMsg = data.error || `HTTP error! status: ${response.status}`;
            throw new Error(errorMsg);
        }

        const assistantResponse = data.message;
        assistantMessageContent.innerHTML = converter.makeHtml(assistantResponse);
        document.getElementById('chat-messages').scrollTop = document.getElementById('chat-messages').scrollHeight;

        chatHistory.push({ role: 'user', parts: [userMessage] });
        chatHistory.push({ role: 'model', parts: [assistantResponse] });
    })
    .catch(error => {
        console.error('Chat error:', error);
        assistantMessageContent.innerHTML = `<span class="text-danger">Error: ${error.message}</span>`;
    })
    .finally(() => {
        if (chatInput) {
            chatInput.disabled = false;
            chatInput.focus();
        }
        if (chatForm) {
            const submitBtn = chatForm.querySelector('button[type="submit"]');
            if (submitBtn) submitBtn.disabled = false;
        }
    });
}

function initChat() {
    const chatForm = document.getElementById('chat-form');
    chatForm?.addEventListener('submit', handleChatSubmit);
}

function openChat() {
    document.getElementById('chat-modal').style.display = 'flex';
    loadRagflowDatasetsForChat();
}

function loadRagflowDatasetsForChat() {
    const url = window.ragflowDatasetsUrl || '/ragflow/datasets';
    fetch(url)
        .then(r => r.json())
        .then(data => {
            const select = document.getElementById('ragflow-dataset');
            if (select && data.datasets) {
                select.innerHTML = '<option value="">Default dataset</option>' +
                    data.datasets.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
            }
        });
}

function sendChat() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    const fileId = window.CURRENT_FILE_ID;
    const useRagflow = document.getElementById('ragflow-toggle')?.checked || false;
    const ragflowDatasetId = document.getElementById('ragflow-dataset')?.value || '';

    const messagesContainer = document.getElementById('chat-messages');

    const userMsg = document.createElement('div');
    userMsg.className = 'chat-message user';
    userMsg.innerHTML = `<p>${escapeHtml(message)}</p>`;
    messagesContainer.appendChild(userMsg);

    const thinkingMsg = document.createElement('div');
    thinkingMsg.className = 'chat-message assistant typing';
    thinkingMsg.innerHTML = '<p>Thinking...</p>';
    messagesContainer.appendChild(thinkingMsg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    input.value = '';

    fetch(`/chat/${fileId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message: message,
            use_ragflow: useRagflow,
            ragflow_dataset_id: ragflowDatasetId
        })
    })
    .then(r => r.json())
    .then(data => {
        thinkingMsg.remove();
        if (data.error) {
            const errorMsg = document.createElement('div');
            errorMsg.className = 'chat-message assistant';
            errorMsg.innerHTML = `<p class="text-danger">${escapeHtml(data.error)}</p>`;
            messagesContainer.appendChild(errorMsg);
        } else {
            const assistantMsg = document.createElement('div');
            assistantMsg.className = 'chat-message assistant';
            assistantMsg.innerHTML = `<p>${data.message}</p>`;
            messagesContainer.appendChild(assistantMsg);
        }
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    })
    .catch(err => {
        thinkingMsg.remove();
        const errorMsg = document.createElement('div');
        errorMsg.className = 'chat-message assistant';
        errorMsg.innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        messagesContainer.appendChild(errorMsg);
    });
}

// Expose to window
window.appendChatMessage = appendChatMessage;
window.initChat = initChat;
window.openChat = openChat;
window.sendChat = sendChat;
window.handleChatSubmit = handleChatSubmit;
window.loadRagflowDatasetsForChat = loadRagflowDatasetsForChat;
