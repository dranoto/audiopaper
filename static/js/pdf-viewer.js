// pdf-viewer.js - PDF rendering and viewer functionality

let pdfDoc = null;
let pageNum = 1;
let pageRendering = false;
let pageNumPending = null;
const scale = 1.5;

const canvas = document.getElementById('pdf-canvas');
const ctx = canvas ? canvas.getContext('2d') : null;

// Expose to window for use by other modules
window.initPdfControls = initPdfControls;
window.viewPdf = viewPdf;
window.updateFileContent = updateFileContent;

function renderPage(num) {
    if (!canvas || !ctx) return;

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

function initPdfControls() {
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
}

function viewPdf(url, fileId, filename) {
    window.currentFileId = fileId;
    window.chatHistory = [];
    document.getElementById('chat-messages').innerHTML = '<div class="text-center text-muted">Ask a question to get started.</div>';

    document.getElementById('main-content-title').textContent = filename;
    document.getElementById('myTab').style.display = 'flex';

    document.getElementById('summary-content').innerHTML = '<p>No summary generated yet.</p>';
    document.getElementById('transcript-content').innerHTML = '<p>No transcript generated yet.</p>';
    document.getElementById('figures-container').innerHTML = '<p>Loading figures...</p>';
    const audioPlayer = document.getElementById('audio-player');
    if (audioPlayer) audioPlayer.src = '';

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
                    col.className = 'col-lg-6 col-md-12 mb-4';

                    const card = document.createElement('div');
                    card.className = 'card h-100';

                    const cardBody = document.createElement('div');
                    cardBody.className = 'card-body d-flex flex-column';

                    const contentWrapper = document.createElement('div');
                    contentWrapper.className = 'mb-auto';

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
                    caption.className = 'card-text mt-2';
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

function updateFileContent(fileId) {
    const converter = new showdown.Converter();
    const audioPlayer = document.getElementById('audio-player');

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
                window.chatHistory = data.chat_history;
                const chatMessages = document.getElementById('chat-messages');
                chatMessages.innerHTML = '';
                data.chat_history.forEach(item => {
                    const sender = item.role === 'model' ? 'assistant' : 'user';
                    const message = Array.isArray(item.parts) ? item.parts.join(' ') : item.parts;
                    window.appendChatMessage(message, sender);
                });
            }
        });
}
