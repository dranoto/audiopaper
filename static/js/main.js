pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js';

let pdfDoc = null;
let pageNum = 1;
let pageRendering = false;
let pageNumPending = null;
const scale = 1.5;
const canvas = document.getElementById('pdf-canvas');
const ctx = canvas.getContext('2d');

function renderPage(num) {
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

    document.getElementById('page_num').textContent = num;
}

function queueRenderPage(num) {
    if (pageRendering) {
        pageNumPending = num;
    } else {
        renderPage(num);
    }
}

function onPrevPage() {
    if (pageNum <= 1) {
        return;
    }
    pageNum--;
    queueRenderPage(pageNum);
}
document.getElementById('prev').addEventListener('click', onPrevPage);

function onNextPage() {
    if (pageNum >= pdfDoc.numPages) {
        return;
    }
    pageNum++;
    queueRenderPage(pageNum);
}
document.getElementById('next').addEventListener('click', onNextPage);

function viewPdf(url, fileId) {
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
            if (data.figures && data.figures.length > 0) {
                const row = document.createElement('div');
                row.className = 'row';
                data.figures.forEach((figure_path, index) => {
                    const col = document.createElement('div');
                    col.className = 'col-md-4 mb-3';
                    const card = document.createElement('div');
                    card.className = 'card';
                    const img = document.createElement('img');
                    img.src = figure_path;
                    img.className = 'card-img-top';
                    const cardBody = document.createElement('div');
                    cardBody.className = 'card-body';
                    const caption = document.createElement('p');
                    caption.className = 'card-text';
                    caption.textContent = data.captions[index];
                    cardBody.appendChild(caption);
                    card.appendChild(img);
                    card.appendChild(cardBody);
                    col.appendChild(card);
                    row.appendChild(col);
                });
                figuresContainer.appendChild(row);
            } else {
                figuresContainer.innerHTML = '<p>No figures found in this PDF.</p>';
            }
        });
}

function toggleLoading(buttonId, isLoading) {
    if (!buttonId) return;
    const button = document.getElementById(buttonId);
    if (!button) return;
    const spinner = button.querySelector('.loading-spinner');
    button.disabled = isLoading;
    if (spinner) {
        spinner.style.display = isLoading ? 'inline-block' : 'none';
    }
}

function handleError(errorId, error) {
    if (!errorId) {
        alert('An error occurred: ' + error);
        console.error('Error:', error);
        return;
    }
    const errorDiv = document.getElementById(errorId);
    if (errorDiv) {
        errorDiv.textContent = 'An error occurred: ' + error;
        errorDiv.style.display = 'block';
    }
}

function summarizeFile(fileId, buttonId, errorId) {
    if (!buttonId) {
        alert('Generating summary... this may take a moment. You will be redirected when it is complete.');
    }
    toggleLoading(buttonId, true);
    if (errorId) {
        const errorDiv = document.getElementById(errorId);
        if (errorDiv) errorDiv.style.display = 'none';
    }

    fetch(`/summarize_file/${fileId}`, { method: 'POST' })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    throw new Error(errData.error || response.statusText);
                }).catch(() => {
                    throw new Error(`Request failed with status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success && data.redirect_url) {
                window.location.href = data.redirect_url;
            } else {
                throw new Error(data.error || 'An unknown error occurred during summarization.');
            }
        })
        .catch(err => {
            handleError(errorId, err.message);
        })
        .finally(() => toggleLoading(buttonId, false));
}

function generateDialogue(fileId, buttonId, errorId) {
    if (!buttonId) {
        alert('Generating dialogue... this may take a moment.');
    }
    toggleLoading(buttonId, true);
    if (errorId) {
        const errorDiv = document.getElementById(errorId);
        if (errorDiv) errorDiv.style.display = 'none';
    }
    const audioPlayer = document.getElementById('audio-player');

    fetch(`/generate_dialogue/${fileId}`, { method: 'POST' })
        .then(response => {
            if (!response.ok) {
                return response.json().then(errData => {
                    throw new Error(errData.error || response.statusText);
                }).catch(() => {
                    throw new Error(`Request failed with status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.audio_url) {
                if (buttonId) {
                    window.location.reload();
                } else {
                    audioPlayer.src = data.audio_url;
                    audioPlayer.load();
                    audioPlayer.play();
                    alert('Dialogue generated and is now playing.');
                }
            } else {
                throw new Error(data.error || 'An unknown error occurred during dialogue generation.');
            }
        })
        .catch(err => {
            handleError(errorId, err.message);
        })
        .finally(() => toggleLoading(buttonId, false));
}
