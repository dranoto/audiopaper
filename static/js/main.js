if (typeof pdfjsLib !== 'undefined') {
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js';
}

let currentFileId = null;
let chatHistory = [];
let activePollers = {};
let pdfDoc = null;
let pageNum = 1;
let pageRendering = false;
let pageNumPending = null;
const scale = 1.5;
const canvas = document.getElementById('pdf-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;
const audioPlayer = document.getElementById('audio-player');
const converter = new showdown.Converter();

// --- PDF Rendering ---
function renderPage(num) {
    if (!canvas || !ctx) return;  // Guard against missing canvas

    pageRendering = true;
    pdfDoc.getPage(num).then(function(page) {
        const viewport = page.getViewport({scale: scale});
        canvas.height = viewport.height;
        canvas.width = viewport.width;

        const renderContext = {
            canvasContext: ctx,
            viewport: viewport
        };
        const renderTask = page.render(renderContext);

        renderTask.promise.then(function() {
            pageRendering = false;
            if (pageNumPending !== null) {
                renderPage(pageNumPending);
                pageNumPending = null;
            }
        });
    });

    const pageNumEl = document.getElementById('page_num');
    if (pageNumEl) pageNumEl.textContent = num;
}

function queueRenderPage(num) {
    if (pageRendering) {
        pageNumPending = num;
    } else {
        renderPage(num);
    }
}

document.getElementById('prev')?.addEventListener('click', () => {
    if (pageNum <= 1) return;
    pageNum--;
    queueRenderPage(pageNum);
});

document.getElementById('next')?.addEventListener('click', () => {
    if (pageNum >= pdfDoc.numPages) return;
    pageNum++;
    queueRenderPage(pageNum);
});


// --- Main Content Loading ---

function viewPdf(url, fileId, filename) {
    currentFileId = fileId;
    chatHistory = []; // Reset on new file load
    document.getElementById('chat-messages').innerHTML = '<div class="text-center text-muted">Ask a question to get started.</div>';


    document.getElementById('main-content-title').textContent = filename;
    document.getElementById('myTab').style.display = 'flex';

    document.getElementById('summary-content').innerHTML = '<p>No summary generated yet.</p>';
    document.getElementById('transcript-content').innerHTML = '<p>No transcript generated yet.</p>';
    document.getElementById('figures-container').innerHTML = '<p>Loading figures...</p>';
    audioPlayer.src = '';

    pdfjsLib.getDocument(url).promise.then(function(pdfDoc_) {
        pdfDoc = pdfDoc_;
        document.getElementById('page_count').textContent = pdfDoc.numPages;
        pageNum = 1;
        renderPage(pageNum);
        document.getElementById('pagination-controls').style.display = 'block';
    });

    fetch(`/file_details/${fileId}`)
        .then(response => response.json())
        .then(data => {
            const figuresContainer = document.getElementById('figures-container');
            figuresContainer.innerHTML = '';
            if (data.elements && data.elements.length > 0) {
                data.elements.forEach(element => {
                    const col = document.createElement('div');
                    col.className = 'col-lg-6 col-md-12 mb-4'; // Wider for tables

                    const card = document.createElement('div');
                    card.className = 'card h-100';

                    const cardBody = document.createElement('div');
                    cardBody.className = 'card-body d-flex flex-column';

                    const contentWrapper = document.createElement('div');
                    contentWrapper.className = 'mb-auto'; // Pushes caption to the bottom

                    if (element.type === 'figure') {
                        const img = document.createElement('img');
                        img.src = element.path;
                        img.className = 'card-img-top';
                        contentWrapper.appendChild(img);
                    } else if (element.type === 'table') {
                        const table = createTableElement(element.data);
                        contentWrapper.appendChild(table);
                    }

                    const caption = document.createElement('p');
                    caption.className = 'card-text mt-2'; // Margin top for spacing
                    caption.textContent = element.caption;

                    cardBody.appendChild(contentWrapper);
                    cardBody.appendChild(caption);
                    card.appendChild(cardBody);
                    col.appendChild(card);
                    figuresContainer.appendChild(col);
                });
            } else {
                figuresContainer.innerHTML = '<p>No captioned figures or tables found in this document.</p>';
            }
        });

    updateFileContent(fileId);
}

function createTableElement(data) {
    if (!data) return null;

    const table = document.createElement('table');
    table.className = 'table table-bordered table-sm'; // Bootstrap classes

    const thead = document.createElement('thead');
    const tbody = document.createElement('tbody');

    // Assume first row is the header
    const headerRow = data.length > 0 ? data[0] : [];
    const trHead = document.createElement('tr');
    headerRow.forEach(cellText => {
        const th = document.createElement('th');
        th.textContent = cellText || '';
        trHead.appendChild(th);
    });
    thead.appendChild(trHead);

    // Process body rows
    for (let i = 1; i < data.length; i++) {
        const rowData = data[i];
        const tr = document.createElement('tr');
        rowData.forEach(cellText => {
            const td = document.createElement('td');
            td.textContent = cellText || '';
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    }

    table.appendChild(thead);
    table.appendChild(tbody);

    const tableContainer = document.createElement('div');
    tableContainer.className = 'table-responsive';
    tableContainer.appendChild(table);

    return tableContainer;
}

function updateFileContent(fileId) {
    fetch(`/file_content/${fileId}`)
        .then(response => response.json())
        .then(data => {
            if (data.summary) {
                const summaryHtml = converter.makeHtml(data.summary);
                document.getElementById('summary-content').innerHTML = summaryHtml;
            }
            if (data.transcript) {
                const transcriptHtml = converter.makeHtml(data.transcript);
                document.getElementById('transcript-content').innerHTML = transcriptHtml;
                const transcriptButton = document.querySelector(`#file-item-${fileId} [data-action="generateTranscript"]`);
                if(transcriptButton) {
                    transcriptButton.textContent = 'Re-generate Transcript';
                    transcriptButton.classList.remove('btn-outline-primary');
                    transcriptButton.classList.add('btn-outline-success');
                }
                const podcastButton = document.querySelector(`#file-item-${fileId} .podcast-button`);
                if(podcastButton) podcastButton.disabled = false;
            }
            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
                 const podcastButton = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
                if(podcastButton) {
                    podcastButton.textContent = 'Re-generate Podcast';
                    podcastButton.classList.remove('btn-outline-secondary');
                    podcastButton.classList.add('btn-outline-success');
                }
            }
            if (data.chat_history && data.chat_history.length > 0) {
                chatHistory = data.chat_history;
                const chatMessages = document.getElementById('chat-messages');
                chatMessages.innerHTML = ''; // Clear existing messages
                chatHistory.forEach(item => {
                    // Adapt the old format to the new one for display
                    const sender = item.role === 'model' ? 'assistant' : 'user';
                    const message = Array.isArray(item.parts) ? item.parts.join(' ') : item.parts;
                    appendChatMessage(message, sender);
                });
            }
        });
}

function showLoading(element, message) {
    element.innerHTML = `<div class="d-flex align-items-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span><span>${message}</span></div>`;
}

// --- Notifications ---
function requestNotificationPermission() {
    if (Notification.permission === 'default') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                showNotification('Success!', 'You will now be notified when tasks are complete.');
            }
        });
    }
}

function showNotification(title, body) {
    if (Notification.permission === 'granted') {
        new Notification(title, { body: body });
    }
}


// --- Content Generation Functions ---

function pollTaskStatus(taskUrl, fileId, type) {
    // If a poller for this file already exists, clear it before starting a new one.
    if (activePollers[fileId]) {
        clearInterval(activePollers[fileId]);
    }

    const interval = setInterval(() => {
        fetch(taskUrl)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'complete') {
                    clearInterval(interval);
                    delete activePollers[fileId];
                    removePendingTask(fileId);
                    updateFileContent(fileId);
                    showNotification(`${type} Generation Complete`, `The ${type.toLowerCase()} for your file is ready.`);
                    if (type === 'Summary') {
                        const fileItem = document.getElementById(`file-item-${fileId}`);
                        if (fileItem) {
                            const button = fileItem.querySelector('[data-action="summarizeFile"]');
                            button.textContent = 'Re-summarize';
                            button.classList.remove('btn-outline-secondary');
                            button.classList.add('btn-outline-success');
                        }
                    } else if (type === 'Transcript') {
                         const fileItem = document.getElementById(`file-item-${fileId}`);
                        if (fileItem) {
                            const button = fileItem.querySelector('[data-action="generateTranscript"]');
                            button.textContent = 'Re-generate Transcript';
                            button.classList.remove('btn-outline-primary');
                            button.classList.add('btn-outline-success');
                            // Also enable the podcast button
                            const podcastButton = fileItem.querySelector('.podcast-button');
                            if (podcastButton) podcastButton.disabled = false;
                        }
                    } else if (type === 'Podcast') {
                        const fileItem = document.getElementById(`file-item-${fileId}`);
                        if (fileItem) {
                            const button = fileItem.querySelector('[data-action="generatePodcast"]');
                            button.textContent = 'Re-generate Podcast';
                            button.classList.remove('btn-outline-secondary');
                            button.classList.add('btn-outline-success');
                        }
                    }
                } else if (data.status === 'error') {
                    clearInterval(interval);
                    delete activePollers[fileId];
                    removePendingTask(fileId);
                    let contentEl;
                    if (type === 'Summary') {
                        contentEl = document.getElementById('summary-content');
                    } else if (type === 'Transcript') {
                        contentEl = document.getElementById('transcript-content');
                    } else if (type === 'Podcast') {
                        const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
                        if (button) {
                            button.innerHTML = 'Podcast';
                            button.disabled = false;
                        }
                    }
                    if (contentEl) {
                        contentEl.innerHTML = `<p class="text-danger">Error: ${data.result.error}</p>`;
                    }
                    const errorMessage = (data.result && data.result.error) ? data.result.error : 'Unknown error';
                    showNotification(`${type} Generation Failed`, `There was an error generating the ${type.toLowerCase()}: ${errorMessage}`);
                }
                // If 'processing', do nothing and wait for the next poll
            })
            .catch(err => {
                clearInterval(interval);
                delete activePollers[fileId];

                let contentEl;
                if (type === 'Summary') {
                    contentEl = document.getElementById('summary-content');
                } else if (type === 'Transcript') {
                    contentEl = document.getElementById('transcript-content');
                } else if (type === 'Podcast') {
                    showNotification('Polling Error', `An error occurred while checking the podcast status: ${err.message}`);
                    const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
                    if (button) {
                        button.innerHTML = 'Podcast';
                        button.disabled = false;
                    }
                }

                if (contentEl) {
                    contentEl.innerHTML = `<p class="text-danger">Error polling for status: ${err.message}. Please reload the page to retry.</p>`;
                }
            });
    }, 2000); // Poll every 2 seconds

    activePollers[fileId] = interval;
}


function summarizeFile(fileId) {
    showLoading(document.getElementById('summary-content'), 'Generating summary... This may take a moment.');
    new bootstrap.Tab(document.getElementById('summary-tab')).show();
    requestNotificationPermission();

    fetch(`/summarize_file/${fileId}`, { method: 'POST' })
        .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start summary generation.');
            }
        })
        .then(data => {
            const taskUrl = `/summarize_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Summary' });
            pollTaskStatus(taskUrl, fileId, 'Summary');
        })
        .catch(err => {
            document.getElementById('summary-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        });
}

function generateTranscript(fileId) {
    showLoading(document.getElementById('transcript-content'), 'Generating transcript... This may take a moment.');
    new bootstrap.Tab(document.getElementById('transcript-tab')).show();
    requestNotificationPermission();

    fetch(`/generate_transcript/${fileId}`, { method: 'POST' })
         .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start transcript generation.');
            }
        })
        .then(data => {
            const taskUrl = `/transcript_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Transcript' });
            pollTaskStatus(taskUrl, fileId, 'Transcript');
        })
        .catch(err => {
            document.getElementById('transcript-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        });
}

function generatePodcast(fileId) {
    const button = document.querySelector(`#file-item-${fileId} [data-action="generatePodcast"]`);
    button.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...`;
    button.disabled = true;
    requestNotificationPermission();

    fetch(`/generate_podcast/${fileId}`, { method: 'POST' })
        .then(response => {
            if (response.status === 202) {
                return response.json();
            } else {
                throw new Error('Failed to start podcast generation.');
            }
        })
        .then(data => {
            const taskUrl = `/podcast_status/${data.task_id}`;
            savePendingTask(fileId, { taskUrl: taskUrl, type: 'Podcast' });
            pollTaskStatus(taskUrl, fileId, 'Podcast');
        })
        .catch(err => {
            showNotification('Podcast Error', 'Error starting podcast generation: ' + err.message);
            button.innerHTML = 'Podcast';
            button.disabled = false;
        });
}

// --- File & Folder Management ---

function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file? This action cannot be undone.')) {
        return;
    }
    fetch(`/delete_file/${fileId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById(`file-item-${fileId}`)?.remove();
            } else {
                alert('Error deleting file: ' + data.error);
            }
        })
        .catch(err => alert('An error occurred: ' + err.message));
}

function renameFile(fileId, oldFilename) {
    const newFilename = prompt('Enter new filename:', oldFilename);
    if (newFilename && newFilename !== oldFilename) {
        fetch(`/rename_file/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_filename: newFilename })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const fileItemElement = document.getElementById(`file-item-${fileId}`);
                if (fileItemElement) {
                    const span = fileItemElement.querySelector('span.file-filename');
                    if (span) span.textContent = data.new_filename;

                    const viewDiv = fileItemElement.querySelector('.file-item');
                    if (viewDiv) {
                        viewDiv.dataset.filename = data.new_filename;
                        viewDiv.dataset.url = data.new_url;
                    }

                    const renameButton = fileItemElement.querySelector('[data-action="renameFile"]');
                    if (renameButton) {
                        renameButton.dataset.filename = data.new_filename;
                    }
                }
            } else {
                alert('Error renaming file: ' + data.error);
            }
        })
        .catch(err => alert('An error occurred: ' + err.message));
    }
}

function moveFile(fileId) {
    const folderId = prompt('Enter the ID of the folder to move this file to (or "root" for no folder):');
    if (folderId) {
        fetch(`/move_file/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_folder_id: folderId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const fileElement = document.getElementById(`file-item-${fileId}`);
                if (fileElement) {
                    const targetListId = (folderId === 'root') ? 'root-file-list' : `folder-list-${folderId}`;
                    const targetList = document.getElementById(targetListId);
                    if (targetList) {
                        targetList.appendChild(fileElement);
                    } else {
                        alert('Error: Target folder not found in the UI.');
                    }
                }
            } else {
                alert('Error moving file: ' + data.error);
            }
        })
        .catch(err => alert('An error occurred: ' + err.message));
    }
}

function deleteFolder(folderId) {
    if (!confirm('Are you sure you want to delete this folder? It must be empty.')) {
        return;
    }
    fetch(`/delete_folder/${folderId}`, { method: 'DELETE' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.getElementById(`folder-item-${folderId}`)?.remove();
            } else {
                alert('Error deleting folder: ' + data.error);
            }
        })
        .catch(err => alert('An error occurred: ' + err.message));
}

function renameFolder(folderId, oldName) {
    const newName = prompt('Enter new folder name:', oldName);
    if (newName && newName !== oldName) {
        fetch(`/rename_folder/${folderId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_name: newName })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const folderItem = document.getElementById(`folder-item-${folderId}`);
                if (folderItem) {
                    folderItem.querySelector('strong').textContent = data.new_name;
                    const renameButton = folderItem.querySelector('[data-action="renameFolder"]');
                    if (renameButton) {
                        renameButton.dataset.name = newName;
                    }
                }
            } else {
                alert('Error renaming folder: ' + data.error);
            }
        })
        .catch(err => alert('An error occurred: ' + err.message));
    }
}

// --- Event Listeners ---

// --- Task Persistence ---
function getPendingTasks() {
    return JSON.parse(localStorage.getItem('pendingTasks') || '{}');
}

function savePendingTask(fileId, task) {
    const tasks = getPendingTasks();
    tasks[fileId] = task;
    localStorage.setItem('pendingTasks', JSON.stringify(tasks));
}

function removePendingTask(fileId) {
    const tasks = getPendingTasks();
    delete tasks[fileId];
    localStorage.setItem('pendingTasks', JSON.stringify(tasks));
}


document.addEventListener('DOMContentLoaded', () => {
    // Resume polling for any pending tasks on page load
    const pendingTasks = getPendingTasks();
    for (const fileId in pendingTasks) {
        const task = pendingTasks[fileId];
        pollTaskStatus(task.taskUrl, fileId, task.type);
    }

    const sidebar = document.getElementById('left-column');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const fileList = document.getElementById('file-list');
    const appContainer = document.getElementById('app-container');

    sidebarToggle?.addEventListener('click', () => {
        sidebar?.classList.toggle('collapsed');
        appContainer?.classList.toggle('sidebar-collapsed');
    });

    fileList?.addEventListener('click', (event) => {
        const folderToggle = event.target.closest('.folder-toggle');
        const fileItem = event.target.closest('.file-item');
        const actionButton = event.target.closest('.file-action-button, .folder-action-button');

        if (folderToggle) {
            event.preventDefault();
            const folderContainer = folderToggle.closest('.folder-container');
            const sublist = folderContainer.querySelector('.nav');
            folderToggle.classList.toggle('collapsed');
            new bootstrap.Collapse(sublist, {
              toggle: true
            });
        }
        else if (actionButton) {
            event.preventDefault(); // Prevent default link behavior
            const { action, id, filename, name } = actionButton.dataset;

            switch (action) {
                case 'renameFile':
                    renameFile(id, filename);
                    break;
                case 'moveFile':
                    moveFile(id);
                    break;
                case 'deleteFile':
                    deleteFile(id);
                    break;
                case 'summarizeFile':
                    summarizeFile(id);
                    break;
                case 'generateTranscript':
                    generateTranscript(id);
                    break;
                case 'generatePodcast':
                    generatePodcast(id);
                    break;
                case 'renameFolder':
                    renameFolder(id, name);
                    break;
                case 'deleteFolder':
                    deleteFolder(id);
                    break;
            }
        } else if (fileItem) {
            const { url, id, filename } = fileItem.dataset;
            viewPdf(url, id, filename);
        }
    });

    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    function appendChatMessage(message, sender) {
        // Clear initial message if it exists
        const initialMessage = chatMessages.querySelector('.text-muted');
        if (initialMessage) {
            initialMessage.remove();
        }

        const messageWrapper = document.createElement('div');
        messageWrapper.classList.add('chat-message', `${sender}-message`, 'mb-3', 'd-flex');

        const icon = document.createElement('div');
        icon.classList.add('me-2');
        icon.innerHTML = sender === 'user' ? '<i class="bi bi-person-circle"></i>' : '<i class="bi bi-robot"></i>';

        const content = document.createElement('div');
        content.classList.add('message-content');

        // Use showdown to convert markdown to HTML for assistant messages
        if (sender === 'assistant') {
            content.innerHTML = converter.makeHtml(message);
        } else {
            // Treat user input as plain text to prevent XSS.
            // The `textContent` property automatically escapes HTML entities.
            content.textContent = message;
            // Use CSS `white-space` to preserve newlines and wrap text.
            content.style.whiteSpace = 'pre-wrap';
        }

        messageWrapper.appendChild(icon);
        messageWrapper.appendChild(content);

        chatMessages.appendChild(messageWrapper);
        chatMessages.scrollTop = chatMessages.scrollHeight; // Scroll to bottom
        return content; // Return the content div to update it while streaming
    }

    async function handleChatSubmit(event) {
        event.preventDefault();
        if (!currentFileId) {
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

        // Show thinking indicator
        const assistantMessageContent = appendChatMessage('<span class="thinking"></span>', 'assistant');

        try {
            const response = await fetch(`/chat/${currentFileId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: userMessage
                }),
            });

            const data = await response.json();

            if (!response.ok) {
                const errorMsg = data.error || `HTTP error! status: ${response.status}`;
                throw new Error(errorMsg);
            }

            const assistantResponse = data.message;
            assistantMessageContent.innerHTML = converter.makeHtml(assistantResponse);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // History is now managed on the backend, but we can push to the local
            // copy to keep the UI in sync without another fetch.
            chatHistory.push({ role: 'user', parts: [userMessage] });
            chatHistory.push({ role: 'model', parts: [assistantResponse] });

        } catch (error) {
            console.error('Chat error:', error);
            assistantMessageContent.innerHTML = `<span class="text-danger">Error: ${error.message}</span>`;
        } finally {
            if (chatInput) {
                chatInput.disabled = false;
                chatInput.focus();
            }
            chatForm?.querySelector('button[type="submit"]')?.disabled = false;
        }
    }

    chatForm?.addEventListener('submit', handleChatSubmit);

    // --- Settings Page Specific Logic ---
    if (document.querySelector('body.settings-page')) {
        let currentAudio = null;
        const playIconClass = 'bi bi-volume-up-fill';
        const stopIconClass = 'bi bi-stop-circle-fill';
        const loadingIconClass = 'spinner-border spinner-border-sm';

        function stopCurrentSample() {
            if (currentAudio) {
                currentAudio.pause();
                currentAudio.currentTime = 0;
            }
            const previousButton = document.querySelector('.playing');
            if (previousButton) {
                resetButtonState(previousButton);
            }
            currentAudio = null;
        }

        function resetButtonState(button) {
            button.classList.remove('playing');
            button.querySelector('i').className = playIconClass;
            button.disabled = false;
        }

        function playSample(button, voice) {
            const icon = button.querySelector('i');
            icon.className = loadingIconClass;
            button.disabled = true;

            fetch('/play_voice_sample', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ voice: voice }),
            })
            .then(response => {
                if (!response.ok) throw new Error('Network response was not ok');
                return response.json();
            })
            .then(data => {
                currentAudio = new Audio(data.audio_url);
                button.classList.add('playing');
                icon.className = stopIconClass;
                button.disabled = false;

                currentAudio.play();

                currentAudio.addEventListener('ended', () => {
                    resetButtonState(button);
                    currentAudio = null;
                });
            })
            .catch(error => {
                console.error('Error playing voice sample:', error);
                alert('Failed to play voice sample. See console for details.');
                resetButtonState(button);
            });
        }

        const playButtons = document.querySelectorAll('.play-sample-button');
        playButtons.forEach(button => {
            button.addEventListener('click', () => {
                const wasPlaying = button.classList.contains('playing');

                stopCurrentSample();

                if (!wasPlaying) {
                    const targetId = button.dataset.targetSelect;
                    const select = document.getElementById(targetId);
                    const voice = select.value;
                    playSample(button, voice);
                }
            });
        });
    }

    // ==================== Global State ====================
    
    window.window.globalInlineMode = new URL(window.location).searchParams.get('inline') === 'true';
    let isGenerating = false;
    let currentEventSource = null;
    let currentTaskInterval = null;

    // ==================== Sidebar Toggle ====================
    
    window.toggleSidebar = function() {
        const sidebar = document.getElementById('sidebar');
        const mainContent = document.getElementById('main-content');
        sidebar?.classList.toggle('collapsed');
        mainContent?.classList.toggle('sidebar-collapsed');
    };

    const taskStepMap = {
        'summary': { step: 2, name: 'Summary', icon: 'bi-card-text' },
        'transcript': { step: 3, name: 'Script', icon: 'bi-chat-dots' },
        'podcast': { step: 4, name: 'Audio', icon: 'bi-headphones' }
    };

    window.streamSummary = function() {
        if (isGenerating) return;
        isGenerating = true;

        const btn = document.getElementById('btn-generate-summary');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
        }

        window.globalInlineMode = true;
        showLoading('Generating summary...');
        
        if (currentEventSource) {
            currentEventSource.close();
        }
        
        const statusEl = document.getElementById('progress-status-text');
        const barEl = document.getElementById('inline-progress-bar');
        let fullText = '';
        
        const fileId = window.CURRENT_FILE_ID;
        currentEventSource = new EventSource(`/summarize_stream/${fileId}`);
        
        currentEventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            if (data.type === 'token') {
                fullText += data.content;
                if (barEl && fullText.length > 50) {
                    const progress = Math.min(10 + (fullText.length / 10), 90);
                    barEl.style.width = progress + '%';
                }
                if (statusEl) {
                    statusEl.textContent = `Generating... ${fullText.length} chars`;
                }
            } else if (data.type === 'complete') {
                currentEventSource.close();
                currentEventSource = null;
                if (barEl) {
                    barEl.className = 'progress-bar success';
                    barEl.style.width = '100%';
                }
                if (statusEl) statusEl.textContent = 'Complete! Loading...';
                setTimeout(() => window.location.reload(), 1000);
            } else if (data.type === 'error') {
                currentEventSource.close();
                currentEventSource = null;
                isGenerating = false;
                resetGenerateButton('summary');
                showInlineError('summary', data.error);
            }
        };
        
        currentEventSource.onerror = function() {
            currentEventSource.close();
            currentEventSource = null;
            showInlineError('summary', 'Connection error');
        };
    };

    window.streamTranscript = function() {
        if (isGenerating) return;
        isGenerating = true;

        const btn = document.getElementById('btn-generate-transcript');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
        }

        window.globalInlineMode = true;
        showLoading('Creating podcast script...', 'transcript');
        
        if (currentEventSource) {
            currentEventSource.close();
        }
        
        const statusEl = document.getElementById('progress-status-text');
        const barEl = document.getElementById('inline-progress-bar');
        let fullText = '';
        
        const fileId = window.CURRENT_FILE_ID;
        currentEventSource = new EventSource(`/transcript_stream/${fileId}`);
        
        currentEventSource.onmessage = function(event) {
            const data = JSON.parse(event.data);
            
            if (data.type === 'token') {
                fullText += data.content;
                if (barEl && fullText.length > 50) {
                    const progress = Math.min(10 + (fullText.length / 10), 90);
                    barEl.style.width = progress + '%';
                }
                if (statusEl) {
                    statusEl.textContent = `Generating script... ${fullText.length} chars`;
                }
            } else if (data.type === 'complete') {
                currentEventSource.close();
                currentEventSource = null;
                if (barEl) {
                    barEl.className = 'progress-bar success';
                    barEl.style.width = '100%';
                }
                if (statusEl) statusEl.textContent = 'Complete! Loading...';
                setTimeout(() => window.location.reload(), 1000);
            } else if (data.type === 'error') {
                currentEventSource.close();
                currentEventSource = null;
                isGenerating = false;
                resetGenerateButton('transcript');
                showInlineError('transcript', data.error);
            }
        };

        currentEventSource.onerror = function() {
            currentEventSource.close();
            currentEventSource = null;
            isGenerating = false;
            resetGenerateButton('transcript');
            showInlineError('transcript', 'Connection error');
        };
    };

    window.resetGenerateButton = function(type) {
        let btnId = null;
        if (type === 'summary') btnId = 'btn-generate-summary';
        else if (type === 'transcript') btnId = 'btn-generate-transcript';
        else if (type === 'podcast') btnId = 'btn-generate-audio';

        if (btnId) {
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.disabled = false;
                if (type === 'summary') {
                    btn.innerHTML = '<i class="bi bi-lightning"></i> Generate Summary';
                } else if (type === 'transcript') {
                    btn.innerHTML = '<i class="bi bi-chat-dots"></i> Generate Podcast Script';
                } else if (type === 'podcast') {
                    btn.innerHTML = '<i class="bi bi-play-circle"></i> Generate Audio';
                }
            }
        }
        isGenerating = false;
    };

    window.generateSummary = function() {
        streamSummary();
    };

    window.generatePodcast = function() {
        if (isGenerating) return;
        isGenerating = true;

        const btn = document.getElementById('btn-generate-audio');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating...';
        }

        window.globalInlineMode = true;
        showLoading('Generating podcast audio...', 'podcast');

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);

        const fileId = window.CURRENT_FILE_ID;
        fetch(`/generate_podcast/${fileId}`, {
            method: 'POST',
            signal: controller.signal
        })
        .then(r => {
            clearTimeout(timeoutId);
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(data => pollTask(data.task_id, 'podcast', true))
        .catch(err => {
            clearTimeout(timeoutId);
            console.error('Generate podcast error:', err);
            isGenerating = false;
            resetGenerateButton('podcast');
            alert('Error: ' + err.message);
        });
    };

    window.generateTranscript = function() {
        streamTranscript();
    };

    window.regenerateSummary = function() {
        if (!confirm('Regenerate summary?')) return;
        streamSummary();
    };

    window.regenerateTranscript = function() {
        if (!confirm('Regenerate podcast script?')) return;
        streamTranscript();
    };

    window.deleteFile = function(fileId) {
        if (!confirm('Delete this paper? This will remove the summary, transcript, and any generated audio.')) return;
        
        fetch(`/delete_file/${fileId}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => {
                if (data.error) {
                    alert('Error: ' + data.error);
                } else {
                    window.location.href = '/';
                }
            })
            .catch(err => alert('Error: ' + err));
    };

    window.showSummary = function() {
        const el = document.getElementById('summary-text');
        if (el && typeof marked !== 'undefined') {
            el.innerHTML = marked.parse(el.textContent || el.innerText);
        }
        document.getElementById('summary-modal').style.display = 'flex';
    };

    window.showOriginalText = function() {
        document.getElementById('original-text-modal').style.display = 'flex';
    };

    window.showTranscript = function() {
        document.getElementById('transcript-modal').style.display = 'flex';
    };

    window.saveAndGenerate = function() {
        const transcript = document.getElementById('transcript-edit').value;
        
        const fileId = window.CURRENT_FILE_ID;
        fetch(`/save_transcript/${fileId}`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ transcript: transcript })
        })
        .then(r => r.json())
        .then(data => {
            closeModal('transcript-modal');
            generatePodcast();
        })
        .catch(err => {
            alert('Error saving transcript: ' + err);
        });
    };

    window.closeModal = function(id) {
        document.getElementById(id).style.display = 'none';
    };

    window.showProgressModal = function(taskType, message) {
        if (window.globalInlineMode) {
            const inlineDiv = document.getElementById('inline-progress');
            if (inlineDiv !== null) {
                showLoading(message, taskType);
                return;
            }
        }
        
        const modal = document.getElementById('progress-modal');
        const title = document.getElementById('progress-title');
        const subtitle = document.getElementById('progress-subtitle');
        const icon = document.getElementById('progress-icon');
        const bar = document.getElementById('progress-bar');
        const status = document.getElementById('progress-status');
        const cancelBtn = document.getElementById('progress-cancel');
        const steps = document.querySelectorAll('.progress-step');

        const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType, icon: 'bi-gear' };

        title.textContent = message || `Generating ${taskInfo.name}...`;
        subtitle.textContent = taskInfo.name;

        icon.className = 'progress-icon processing';
        icon.innerHTML = `<i class="bi ${taskInfo.icon}"></i>`;

        bar.className = 'progress-bar';
        bar.style.width = '10%';

        steps.forEach((s, i) => {
            s.className = 'progress-step';
            if (i + 1 < taskInfo.step) {
                s.classList.add('completed');
            } else if (i + 1 === taskInfo.step) {
                s.classList.add('active');
            }
        });

        status.textContent = `Step ${taskInfo.step} of 4`;
        cancelBtn.style.display = 'inline-flex';

        modal.classList.remove('hidden');
    };

    window.updateProgress = function(taskType, progress, message) {
        const bar = document.getElementById('progress-bar');
        const title = document.getElementById('progress-title');
        const status = document.getElementById('progress-status');

        if (progress !== undefined) {
            bar.style.width = progress + '%';
        }
        if (message) {
            title.textContent = message;
        }
    };

    window.showProgressSuccess = function(taskType) {
        const modal = document.getElementById('progress-modal');
        const title = document.getElementById('progress-title');
        const subtitle = document.getElementById('progress-subtitle');
        const icon = document.getElementById('progress-icon');
        const bar = document.getElementById('progress-bar');
        const cancelBtn = document.getElementById('progress-cancel');

        const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType };

        title.textContent = `${taskInfo.name} Complete!`;
        subtitle.textContent = 'Redirecting...';
        icon.className = 'progress-icon success';
        icon.innerHTML = '<i class="bi bi-check-lg"></i>';
        bar.className = 'progress-bar success';
        bar.style.width = '100%';
        cancelBtn.style.display = 'none';

        setTimeout(() => {
            modal.classList.add('hidden');
            const url = new URL(window.location);
            const fileId = url.searchParams.get('file');
            const newUrl = fileId ? `/?file=${fileId}` : '/';
            window.location.href = newUrl;
        }, 1500);
    };

    window.showProgressError = function(taskType, error) {
        const modal = document.getElementById('progress-modal');
        const title = document.getElementById('progress-title');
        const subtitle = document.getElementById('progress-subtitle');
        const icon = document.getElementById('progress-icon');
        const bar = document.getElementById('progress-bar');
        const cancelBtn = document.getElementById('progress-cancel');

        const taskInfo = taskStepMap[taskType] || { step: 1, name: taskType };

        title.textContent = 'Error';
        subtitle.textContent = error || 'An error occurred';
        icon.className = 'progress-icon error';
        icon.innerHTML = '<i class="bi bi-exclamation-lg"></i>';
        bar.className = 'progress-bar error';
        bar.style.width = '100%';
        cancelBtn.textContent = 'Close';
        cancelBtn.onclick = () => modal.classList.add('hidden');
    };

    window.hideProgressModal = function() {
        document.getElementById('progress-modal').classList.add('hidden');
    };

    window.showInlineSuccess = function(type) {
        const barEl = document.getElementById('inline-progress-bar');
        const statusEl = document.getElementById('progress-status-text');
        if (barEl) {
            barEl.className = 'progress-bar success';
            barEl.style.width = '100%';
        }
        if (statusEl) statusEl.textContent = 'Complete! Loading...';
        isGenerating = false;
        setTimeout(() => window.location.reload(), 1000);
    };

    window.showInlineError = function(type, error) {
        const barEl = document.getElementById('inline-progress-bar');
        const statusEl = document.getElementById('progress-status-text');
        if (barEl) {
            barEl.className = 'progress-bar error';
            barEl.style.width = '100%';
        }
        if (statusEl) statusEl.textContent = 'Error: ' + error;
        resetGenerateButton(type);
    };

    window.showLoading = function(text, type = 'summary') {
        const inlineDiv = document.getElementById('inline-progress');
        const hasInlineElements = inlineDiv !== null;
        const useInline = window.globalInlineMode && hasInlineElements;

        if (useInline) {
            const stepNumEl = document.getElementById('progress-step-num');
            const titleEl = document.getElementById('progress-title-text');
            const statusEl = document.getElementById('progress-status-text');
            const barEl = document.getElementById('inline-progress-bar');

            const taskInfo = taskStepMap[type] || { step: 2, name: type };

            if (stepNumEl) stepNumEl.textContent = taskInfo.step;
            if (titleEl) titleEl.textContent = text;
            if (statusEl) statusEl.textContent = 'Please wait...';
            if (barEl) {
                barEl.classList.remove('success', 'error');
                barEl.style.width = '10%';
            }

            if (inlineDiv) {
                inlineDiv.style.display = 'block';
            }

            const modal = document.getElementById('progress-modal');
            if (modal) modal.classList.add('hidden');
            return;
        }

        showProgressModal(type, text);
    };

    window.showWorkflowSteps = function() {
        const workflowSteps = document.getElementById('workflow-steps-container');
        if (workflowSteps) workflowSteps.style.display = 'block';
    };

    window.hideLoading = function() {};

    window.cancelCurrentTask = function() {
        if (currentTaskInterval) {
            clearInterval(currentTaskInterval);
            currentTaskInterval = null;
        }
        hideProgressModal();
    };

    window.pollTask = function(taskId, type, inline = null) {
        if (inline === null) {
            inline = window.globalInlineMode;
        }
        
        const statusType = (type === 'summary') ? 'summarize' : type;
        
        const hasInlineElements = document.getElementById('inline-progress') !== null;
        if (inline && !hasInlineElements) {
            inline = false;
        }

        if (inline) {
            const inlineDiv = document.getElementById('inline-progress');
            if (inlineDiv) inlineDiv.style.display = 'block';

            const stepNumEl = document.getElementById('progress-step-num');
            const taskInfo = taskStepMap[type] || { step: 2, name: type };
            if (stepNumEl) stepNumEl.textContent = taskInfo.step;

            const titleEl = document.getElementById('progress-title-text');
            const statusEl = document.getElementById('progress-status-text');
            const barEl = document.getElementById('inline-progress-bar');
            if (titleEl) titleEl.textContent = `Generating ${taskStepMap[type]?.name || type}...`;
            if (statusEl) statusEl.textContent = 'Please wait while we analyze the paper...';
            if (barEl) barEl.style.width = '10%';
        } else {
            showProgressModal(type, `Generating ${taskStepMap[type]?.name || type}...`);
        }

        currentTaskInterval = setInterval(() => {
            fetch('/' + statusType + '_status/' + taskId)
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'complete') {
                        clearInterval(currentTaskInterval);
                        currentTaskInterval = null;
                        if (inline) {
                            showInlineSuccess(type);
                        } else {
                            showProgressSuccess(type);
                        }
                    } else if (data.status === 'error') {
                        clearInterval(currentTaskInterval);
                        currentTaskInterval = null;
                        if (inline) {
                            showInlineError(type, data.result?.error || 'Unknown error');
                        } else {
                            showProgressError(type, data.result?.error || 'Unknown error');
                        }
                    } else {
                        if (inline) {
                            const barEl = document.getElementById('inline-progress-bar');
                            const current = parseInt(barEl?.style.width) || 10;
                            if (barEl && current < 85) {
                                barEl.style.width = (current + 15) + '%';
                            }
                        }
                    }
                });
        }, 2000);
    };

    // ==================== Chat Functions ====================
    
    window.openChat = function() {
        document.getElementById('chat-modal').style.display = 'flex';
        loadRagflowDatasetsForChat();
    };

    function loadRagflowDatasetsForChat() {
        fetch('{{ url_for("ragflow.ragflow_datasets") }}')
            .then(r => r.json())
            .then(data => {
                const select = document.getElementById('ragflow-dataset');
                if (select && data.datasets) {
                    select.innerHTML = '<option value="">Default dataset</option>' +
                        data.datasets.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
                }
            });
    }

    window.sendChat = function() {
        const input = document.getElementById('chat-input');
        const message = input.value.trim();
        if (!message) return;

        const fileId = window.CURRENT_FILE_ID;
        const useRagflow = document.getElementById('ragflow-toggle')?.checked || false;
        const ragflowDatasetId = document.getElementById('ragflow-dataset')?.value || '';

        const messagesContainer = document.getElementById('chat-messages');
        
        // Add user message
        const userMsg = document.createElement('div');
        userMsg.className = 'chat-message user';
        userMsg.innerHTML = `<p>${escapeHtml(message)}</p>`;
        messagesContainer.appendChild(userMsg);

        // Add thinking message
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

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ==================== Task Status Functions ====================
    
    window.loadTaskStatus = function(fileId) {
        const section = document.getElementById('task-status-section');
        const list = document.getElementById('task-list');
        
        if (!section || !list) return;
        
        fetch(`/ragflow/tasks?file_id=${fileId}`)
            .then(r => r.json())
            .then(data => {
                const tasks = data.tasks || [];
                
                if (tasks.length === 0) {
                    section.style.display = 'none';
                    return;
                }
                
                section.style.display = 'block';
                
                list.innerHTML = tasks.map(task => {
                    const statusIcon = {
                        'pending': '<i class="bi bi-clock"></i>',
                        'queued': '<i class="bi bi-clock"></i>',
                        'processing': '<i class="bi bi-arrow-repeat"></i>',
                        'complete': '<i class="bi bi-check-circle"></i>',
                        'error': '<i class="bi bi-exclamation-circle"></i>',
                        'retrying': '<i class="bi bi-arrow-repeat"></i>'
                    }[task.status] || '<i class="bi bi-question-circle"></i>';
                    
                    const retryBtn = task.status === 'error' 
                        ? `<button class="btn btn-sm btn-outline" onclick="retryTask('${task.id}')">
                            <i class="bi bi-arrow-repeat"></i> Retry
                           </button>`
                        : '';
                    
                    return `
                        <div class="task-item ${task.status}">
                            <div class="task-icon">${statusIcon}</div>
                            <div class="task-info">
                                <div class="task-type">${task.task_type || 'Task'}</div>
                                <div class="task-status">${task.status}</div>
                                ${task.error ? `<div class="task-error">${escapeHtml(task.error)}</div>` : ''}
                            </div>
                            <div class="task-retry">${retryBtn}</div>
                        </div>
                    `;
                }).join('');
            })
            .catch(err => console.error('Failed to load tasks:', err));
    };

    window.refreshTaskStatus = function() {
        const fileId = window.CURRENT_FILE_ID;
        if (fileId) {
            window.loadTaskStatus(fileId);
        }
    };

    window.retryTask = function(taskId) {
        fetch(`/ragflow/task/${taskId}/retry`, { method: 'POST' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    window.refreshTaskStatus();
                } else {
                    alert('Failed to retry task: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
    };

    // Load task status on page load if file is selected
    if (window.CURRENT_FILE_ID) {
        setTimeout(() => window.loadTaskStatus(window.CURRENT_FILE_ID), 1000);
    }
    
    // Show task section if requested via URL param
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('show_tasks') === 'true') {
        const section = document.getElementById('task-status-section');
        if (section) {
            section.style.display = 'block';
        }
        if (window.CURRENT_FILE_ID) {
            window.loadTaskStatus(window.CURRENT_FILE_ID);
        }
    }
});
