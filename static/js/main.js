pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.11.338/pdf.worker.min.js';

let currentFileId = null;
let pdfDoc = null;
let pageNum = 1;
let pageRendering = false;
let pageNumPending = null;
const scale = 1.5;
const canvas = document.getElementById('pdf-canvas');
const ctx = canvas.getContext('2d');
const audioPlayer = document.getElementById('audio-player');

// --- PDF Rendering ---
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

    document.getElementById('main-content-title').textContent = filename;
    document.getElementById('myTab').style.display = 'flex';

    document.getElementById('summary-content').innerHTML = '<p>No summary generated yet.</p>';
    document.getElementById('dialogue-content').innerHTML = '<p>No dialogue generated yet.</p>';
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
            if (data.figures && data.figures.length > 0) {
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
                    caption.textContent = data.captions[index] || 'No caption available.';
                    cardBody.appendChild(caption);
                    card.appendChild(img);
                    card.appendChild(cardBody);
                    col.appendChild(card);
                    figuresContainer.appendChild(col);
                });
            } else {
                figuresContainer.innerHTML = '<p>No figures found in this PDF.</p>';
            }
        });

    updateFileContent(fileId);
}

function updateFileContent(fileId) {
    fetch(`/file_content/${fileId}`)
        .then(response => response.json())
        .then(data => {
            if (data.summary) {
                document.getElementById('summary-content').innerHTML = `<pre>${data.summary}</pre>`;
            }
            if (data.dialogue_transcript) {
                document.getElementById('dialogue-content').innerHTML = `<pre>${data.dialogue_transcript}</pre>`;
            }
            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
            }
        });
}

function showLoading(element, message) {
    element.innerHTML = `<div class="d-flex align-items-center"><span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span><span>${message}</span></div>`;
}

// --- Content Generation Functions ---

function summarizeFile(fileId) {
    showLoading(document.getElementById('summary-content'), 'Generating summary...');
    new bootstrap.Tab(document.getElementById('summary-tab')).show();

    fetch(`/summarize_file/${fileId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateFileContent(fileId);
                const fileItem = document.getElementById(`file-item-${fileId}`);
                if (fileItem) {
                    const button = fileItem.querySelector('[data-action="summarizeFile"]');
                    button.textContent = 'Re-summarize';
                    button.classList.remove('btn-outline-secondary');
                    button.classList.add('btn-outline-success');
                }
            } else {
                document.getElementById('summary-content').innerHTML = `<p class="text-danger">Error: ${data.error}</p>`;
            }
        })
        .catch(err => {
            document.getElementById('summary-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
        });
}

function generateDialogue(fileId) {
    showLoading(document.getElementById('dialogue-content'), 'Generating dialogue and audio...');
    new bootstrap.Tab(document.getElementById('dialogue-tab')).show();

    fetch(`/generate_dialogue/${fileId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.audio_url) {
                updateFileContent(fileId);
                const fileItem = document.getElementById(`file-item-${fileId}`);
                if (fileItem) {
                    const button = fileItem.querySelector('[data-action="generateDialogue"]');
                    button.textContent = 'Re-generate';
                    button.classList.remove('btn-outline-primary');
                    button.classList.add('btn-outline-success');
                }
            } else {
                document.getElementById('dialogue-content').innerHTML = `<p class="text-danger">Error: ${data.error}</p>`;
            }
        })
        .catch(err => {
            document.getElementById('dialogue-content').innerHTML = `<p class="text-danger">Error: ${err.message}</p>`;
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

document.addEventListener('DOMContentLoaded', () => {
    const fileList = document.getElementById('file-list');

    fileList.addEventListener('click', (event) => {
        const fileItem = event.target.closest('.file-item');
        const actionButton = event.target.closest('.file-action-button, .folder-action-button');

        if (actionButton) {
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
                case 'generateDialogue':
                    generateDialogue(id);
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
});
