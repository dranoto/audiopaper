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

document.getElementById('prev').addEventListener('click', () => {
    if (pageNum <= 1) return;
    pageNum--;
    queueRenderPage(pageNum);
});

document.getElementById('next').addEventListener('click', () => {
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

    sidebarToggle.addEventListener('click', () => {
        sidebar.classList.toggle('collapsed');
        appContainer.classList.toggle('sidebar-collapsed');
    });

    fileList.addEventListener('click', (event) => {
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

        const userMessage = chatInput.value.trim();
        if (!userMessage) return;

        chatInput.value = '';
        chatInput.disabled = true;
        chatForm.querySelector('button[type="submit"]').disabled = true;

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
            chatInput.disabled = false;
            chatForm.querySelector('button[type="submit"]').disabled = false;
            chatInput.focus();
        }
    }

    chatForm.addEventListener('submit', handleChatSubmit);

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
});
