// DOM Elements
const uploadSection = document.getElementById('upload-section');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const errorMessage = document.getElementById('error-message');

const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const browseBtn = document.getElementById('browse-btn');

const progressFill = document.getElementById('progress-fill');
const progressPercent = document.getElementById('progress-percent');
const progressMessage = document.getElementById('progress-message');
const progressDetails = document.getElementById('progress-details');
const progressPages = document.getElementById('progress-pages');

const pageSelect = document.getElementById('page-select');
const imagePageSelect = document.getElementById('image-page-select');
const textOutput = document.getElementById('text-output');
const imageOutput = document.getElementById('image-output');
const metadataOutput = document.getElementById('metadata-output');

const downloadMarkdown = document.getElementById('download-markdown');
const downloadAll = document.getElementById('download-all');
const newUpload = document.getElementById('new-upload');
const copyText = document.getElementById('copy-text');
const errorRetry = document.getElementById('error-retry');

// Model status tracking
let modelReady = false;
let checkingModel = false;

// Check model status
async function checkModelStatus() {
    if (checkingModel) return;
    checkingModel = true;
    
    try {
        const response = await fetch('/health');
        const health = await response.json();
        
        if (health.status === 'healthy' && health.model_loaded) {
            modelReady = true;
            updateUploadArea('ready');
        } else if (health.status === 'starting' || !health.model_loaded) {
            modelReady = false;
            updateUploadArea('loading');
            // Check again in 2 seconds
            setTimeout(checkModelStatus, 2000);
        } else {
            modelReady = false;
            updateUploadArea('failed');
        }
    } catch (error) {
        modelReady = false;
        updateUploadArea('error');
    } finally {
        checkingModel = false;
    }
}

// Update upload area based on model status
function updateUploadArea(status) {
    const uploadArea = document.getElementById('upload-area');
    const h2 = uploadArea.querySelector('h2');
    const p = uploadArea.querySelector('p');
    const button = uploadArea.querySelector('button');
    
    switch (status) {
        case 'loading':
            h2.textContent = 'Loading OCR Model...';
            p.textContent = 'You can upload files - they will be queued until ready';
            button.disabled = false;
            button.textContent = 'Upload (Will Queue)';
            uploadArea.style.opacity = '0.8';
            break;
        case 'ready':
            h2.textContent = 'Drop PDF file here or click to browse';
            p.textContent = 'Maximum file size: 500MB';
            button.disabled = false;
            button.textContent = 'Browse Files';
            uploadArea.style.opacity = '1';
            break;
        case 'failed':
            h2.textContent = 'OCR Model Failed to Load';
            p.textContent = 'Please refresh the page to try again';
            button.disabled = true;
            button.textContent = 'Model Failed';
            uploadArea.style.opacity = '0.6';
            break;
        case 'error':
            h2.textContent = 'Connection Error';
            p.textContent = 'Unable to check model status';
            button.disabled = true;
            button.textContent = 'Connection Error';
            uploadArea.style.opacity = '0.6';
            break;
    }
}


// State
let currentSession = null;
let ocrResults = null;
let statusCheckInterval = null;
// WebSocket removed - using polling only
let uploadPaused = false;
let currentUploadSession = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
});

// Event Listeners
function setupEventListeners() {
    // Model loading is automatic in background
    // No manual load model button needed
    
    // File upload
    if (browseBtn) {
        browseBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            console.log('Browse button clicked');
            fileInput.click();
        });
    } else {
        console.error('Browse button not found');
    }
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect);
    }

    
    // Drag and drop
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);
    uploadArea.addEventListener('click', (e) => {
        // Only trigger if not clicking the browse button
        if (!e.target.closest('#browse-btn')) {
            fileInput.click();
        }
    });
    
    // Results actions
    newUpload.addEventListener('click', resetToUpload);
    downloadMarkdown.addEventListener('click', () => downloadFile('markdown'));
    downloadAll.addEventListener('click', () => downloadFile('all'));
    copyText.addEventListener('click', copyTextToClipboard);
    errorRetry.addEventListener('click', resetToUpload);
    
    // Tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    
    // Page navigation
    pageSelect.addEventListener('change', () => displayPage(pageSelect.value));
    imagePageSelect.addEventListener('change', () => displayImage(imagePageSelect.value));
}

// File Handling
function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        uploadFile(file);
    }
}

function handleDragOver(e) {
    e.preventDefault();
    uploadArea.classList.add('dragover');
}

function handleDragLeave(e) {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    
    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
        uploadFile(file);
    } else {
        showError('Please upload a PDF file');
    }
}

// Upload File - Always use chunked upload for cloud compatibility
async function uploadFile(file) {
    // Validate file type
    const validTypes = [
        'application/pdf',
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 
        'image/webp', 'image/bmp', 'image/tiff', 'image/tif'
    ];
    
    const fileExt = file.name.toLowerCase().split('.').pop();
    const validExtensions = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'];
    
    if (!validTypes.includes(file.type) && !validExtensions.includes(fileExt)) {
        showError('Please upload a PDF or image file (PDF, JPG, PNG, GIF, WEBP, BMP, TIFF)');
        return;
    }
    
    // Show progress section
    showSection('progress');
    updateProgress(0, 'Preparing upload...');
    
    // Always use chunked upload for Google Cloud Run compatibility
    await uploadFileChunked(file);
}

// Non-chunked upload removed - using only chunked upload for cloud compatibility

// Chunked upload - now used for all files for cloud compatibility
async function uploadFileChunked(file) {
    const CHUNK_SIZE = 1024 * 1024; // 1MB chunks - optimal for Google Cloud Run
    const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
    
    try {
        updateProgress(0, `Preparing chunked upload (${totalChunks} chunks)...`);
        
        // Start upload session
        const startResponse = await fetch('/api/v1/jobs/submit/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                filename: file.name,
                total_size: file.size,
                total_chunks: totalChunks
            })
        });

        
        if (!startResponse.ok) {
            const error = await startResponse.json();
            throw new Error(error.message || 'Failed to start upload');
        }
        
        const sessionData = await startResponse.json();
        
        currentSession = sessionData.upload_id;
        currentUploadSession = sessionData;
        
        
        // WebSocket functionality removed - using polling instead

        
        
        // Upload chunks
        let jobId = null;
        for (let chunkNumber = 0; chunkNumber < totalChunks; chunkNumber++) {
            if (uploadPaused) {
                // Wait for resume
                await waitForResume();
            }
            
            const start = chunkNumber * CHUNK_SIZE;
            const end = Math.min(start + CHUNK_SIZE, file.size);
            const chunk = file.slice(start, end);
            
            const chunkResult = await uploadChunk(currentSession, chunkNumber, chunk);
            
            // Check if upload is complete (last chunk)
            if (chunkResult.upload_complete) {
                jobId = chunkResult.job_id;
                updateProgress(100, 'Upload complete, processing...');
                break;
            }
            
            // Update progress for partial upload
            const progress = ((chunkNumber + 1) / totalChunks) * 100;
            updateProgress(progress, `Uploading chunk ${chunkNumber + 1} of ${totalChunks}...`);
        }
        
        // If we have a job ID, start polling for job status instead of session status
        if (jobId) {
            currentSession = jobId; // Switch to using job ID for status checks
            startJobStatusChecking(jobId);
        }

        
    } catch (error) {
        logError('Chunked upload failed', { session: currentSession, error: error.message });
        showError(error.message);
    }
}

// Upload single chunk
async function uploadChunk(sessionHash, chunkNumber, chunk) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = async function(e) {
            try {
                
                const arrayBuffer = e.target.result;
                // Convert to base64 safely for large chunks
                const uint8Array = new Uint8Array(arrayBuffer);
                let binaryString = '';
                for (let i = 0; i < uint8Array.length; i++) {
                    binaryString += String.fromCharCode(uint8Array[i]);
                }
                const base64 = btoa(binaryString);
                
                // Create form data for file upload (new endpoint expects file upload)
                const formData = new FormData();
                const chunkBlob = new Blob([uint8Array]);
                formData.append('file', chunkBlob, `chunk_${chunkNumber}`);
                
                
                const controller = new AbortController();
                const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
                
                const response = await fetch(`/api/v1/jobs/submit/chunk/${sessionHash}`, {
                    method: 'POST',
                    headers: { 'X-Chunk-Number': chunkNumber.toString() },
                    body: formData,
                    signal: controller.signal
                });
                
                clearTimeout(timeoutId);
                

                
                if (!response.ok) {
                    let errorMessage = `HTTP ${response.status}: Failed to upload chunk ${chunkNumber}`;
                    try {
                        const error = await response.json();
                        errorMessage = error.message || errorMessage;
                    } catch (e) {
                        // If response is not JSON (e.g., HTML error page), use status text
                        errorMessage = `HTTP ${response.status} ${response.statusText}: ${errorMessage}`;
                    }
                    throw new Error(errorMessage);
                }
                
                const result = await response.json();
                resolve(result);
                
            } catch (error) {
                logError('Chunk upload failed', { chunkNumber, sessionHash, error: error.message });
                reject(error);
            }
        };
        
        reader.onerror = () => reject(new Error('Failed to read chunk'));
        reader.readAsArrayBuffer(chunk);
    });
}

// WebSocket functionality removed - using status polling instead

// WebSocket progress updates removed - using status polling instead

// Wait for upload resume (placeholder for pause/resume functionality)
async function waitForResume() {
    return new Promise(resolve => {
        const checkInterval = setInterval(() => {
            if (!uploadPaused) {
                clearInterval(checkInterval);
                resolve();
            }
        }, 100);
    });
}

// Status Checking with retry logic
let statusCheckFailureCount = 0;
const MAX_STATUS_FAILURES = 5; // Allow 5 consecutive failures before giving up

function startStatusChecking() {
    // Clear any existing interval first
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    // Reset failure count
    statusCheckFailureCount = 0;
    statusCheckInterval = setInterval(checkStatus, 10000);
}

// Job status checking for new job system
function startJobStatusChecking(jobId) {
    // Clear any existing interval first
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    // Reset failure count
    statusCheckFailureCount = 0;
    statusCheckInterval = setInterval(() => checkJobStatus(jobId), 10000);
}

async function checkJobStatus(jobId) {
    if (!jobId) return;
    
    try {
        const response = await fetch(`/api/v1/jobs/status/${jobId}`);
        
        if (!response.ok) {
            statusCheckFailureCount++;
            if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
                showError('Unable to check job status. Please refresh the page.');
                clearInterval(statusCheckInterval);
            }
            return;
        }
        
        // Reset failure count on successful response
        statusCheckFailureCount = 0;
        
        const status = await response.json();
        
        if (status.status === 'completed') {
            clearInterval(statusCheckInterval);
            updateProgress(100, 'Processing complete!');
            
            // Show final results
            if (status.result) {
                showResults(jobId, status.result);
            }
        } else if (status.status === 'failed') {
            clearInterval(statusCheckInterval);
            showError(`Processing failed: ${status.error || 'Unknown error'}`);
        } else if (status.status === 'processing' || status.status === 'pending') {
            // Update progress based on job progress
            const progress = status.progress || {};
            const fileRef = status.file_reference || {};
            
            // Enhanced progress message for PDFs
            let progressMessage = progress.message || 'Processing...';
            if (fileRef.file_type === 'pdf' && fileRef.page_count > 1) {
                if (status.status === 'pending') {
                    progressMessage = `PDF detected: ${fileRef.page_count} pages - ${progress.message || 'Waiting to start...'}`;
                } else if (progress.current_page && progress.total_pages) {
                    progressMessage = `Processing page ${progress.current_page} of ${progress.total_pages}`;
                }
            }
            
            updateProgress(
                progress.percent || 0, 
                progressMessage,
                progress.current_page,
                progress.total_pages || fileRef.page_count
            );
            
            // Show incremental results as pages complete
            if (status.partial_results && status.partial_results.length > 0) {
                showIncrementalResults(status);
            }
        }

        
    } catch (error) {
        statusCheckFailureCount++;
        logError('Status check failed', error);
        
        if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
            showError('Unable to check job status. Please refresh the page.');
            clearInterval(statusCheckInterval);
        }
    }
}



async function checkStatus() {
    if (!currentSession) {
        return;
    }
    
    
    try {
        const response = await fetch(`/status/${currentSession}`, {
            timeout: 10000 // 10 second timeout
        });
        

        
        if (!response.ok) {
            const errorText = await response.text();
            logError('Status check failed', {
                session: currentSession,
                status: response.status,
                statusText: response.statusText,
                error: errorText,
                failure_count: statusCheckFailureCount + 1
            });
            throw new Error(`Status check failed: ${response.status} ${response.statusText}`);
        }
        
        const status = await response.json();
        
        // Reset failure count on successful response
        statusCheckFailureCount = 0;
        
        // Update progress
        updateProgress(
            status.progress,
            status.message || 'Processing...',
            status.current_page,
            status.total_pages
        );
        
        // Check if completed
        if (status.status === 'completed') {
            clearInterval(statusCheckInterval);
            await loadResults();
        } else if (status.status === 'failed') {
            logError('Processing failed', { session: currentSession, message: status.message });
            clearInterval(statusCheckInterval);
            showError(status.message || 'Processing failed');
        }

        
    } catch (error) {
        statusCheckFailureCount++;
        
        logError('Status check error', {
            session: currentSession,
            error: error.message,
            failure_count: statusCheckFailureCount,
            max_failures: MAX_STATUS_FAILURES
        });
        
        // Only show error and stop if we've exceeded max failures
        if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
            clearInterval(statusCheckInterval);
            showError(`Connection lost after ${MAX_STATUS_FAILURES} attempts. Please try refreshing the page.`);
        }
    }

}

// Show incremental results as pages complete
function showIncrementalResults(status) {
    // Show results section if not already visible
    if (progressSection.classList.contains('hidden')) {
        return; // Don't show if we're not in progress mode
    }
    
    // Create or update incremental results container
    let incrementalContainer = document.getElementById('incremental-results');
    if (!incrementalContainer) {
        incrementalContainer = document.createElement('div');
        incrementalContainer.id = 'incremental-results';
        incrementalContainer.className = 'incremental-results';
        incrementalContainer.innerHTML = `
            <h3>Extracted Text (Live Preview)</h3>
            <div id="incremental-content" class="incremental-content"></div>
        `;
        
        // Insert after progress section
        const progressInfo = document.querySelector('.progress-info');
        progressInfo.parentNode.insertBefore(incrementalContainer, progressInfo.nextSibling);
    }
    
    const contentDiv = document.getElementById('incremental-content');
    
    // Build combined markdown from all completed pages
    let combinedMarkdown = '';
    const sortedResults = status.partial_results.sort((a, b) => a.page_number - b.page_number);
    
    for (const pageResult of sortedResults) {
        if (pageResult.status === 'completed' && pageResult.text) {
            combinedMarkdown += `\n\n---\n\n${pageResult.text}`;
        }
    }
    
    // Render markdown to HTML
    if (combinedMarkdown.trim()) {
        const html = marked.parse(combinedMarkdown);
        contentDiv.innerHTML = html;
        
        // Highlight code blocks
        contentDiv.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
        
        // Scroll to bottom to show new content
        contentDiv.scrollTop = contentDiv.scrollHeight;
    }
}

// Load Results
async function loadResults() {
    try {
        const response = await fetch(`/results/${currentSession}`);
        if (!response.ok) throw new Error('Failed to load results');
        
        ocrResults = await response.json();
        displayResults();
        
    } catch (error) {
        showError(error.message);
    }
}


// Display Results
function displayResults() {
    // Clean up incremental results when showing final results
    const incrementalContainer = document.getElementById('incremental-results');
    if (incrementalContainer) {
        incrementalContainer.remove();
    }
    
    showSection('results');
    
    // Populate page selectors
    populatePageSelectors();
    
    // Display first page
    displayPage(1);
    displayImage(1);
    
    // Display metadata
    displayMetadata();
}


function populatePageSelectors() {
    pageSelect.innerHTML = '';
    imagePageSelect.innerHTML = '';
    
    for (let i = 1; i <= ocrResults.total_pages; i++) {
        const option = new Option(`Page ${i}`, i);
        pageSelect.add(option.cloneNode(true));
        imagePageSelect.add(option);
    }
}

function displayPage(pageNumber) {
    const page = ocrResults.pages.find(p => p.page_number == pageNumber);
    if (page) {
        // Convert markdown to HTML
        const html = marked.parse(page.text);
        textOutput.innerHTML = html;
        
        // Highlight code blocks
        textOutput.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
    }
}

function displayImage(pageNumber) {
    // Use the actual image_url from the API response instead of hardcoded /images/ path
    const page = ocrResults?.pages?.find(p => p.page_number === pageNumber);
    if (page && page.image_url) {
        imageOutput.innerHTML = `<img src="${page.image_url}" alt="Page ${pageNumber}">`;
    } else {
        imageOutput.innerHTML = `<p>Image not available for page ${pageNumber}</p>`;
    }
}

function displayMetadata() {
    const metadata = {
        filename: ocrResults.filename,
        total_pages: ocrResults.total_pages,
        processing_time: `${ocrResults.processing_time.toFixed(2)}s`,
        created_at: new Date(ocrResults.created_at).toLocaleString(),
        ...ocrResults.metadata
    };
    
    metadataOutput.textContent = JSON.stringify(metadata, null, 2);
}

// Tab Switching
function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    // Update tab content
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tabName}-content`);
    });
}

// Download Functions
function downloadFile(type) {
    if (!currentSession) return;
    
    let url;
    if (type === 'markdown') {
        url = `/results/${currentSession}/combined.md`;
    } else {
        url = `/download/${currentSession}`;
    }
    
    // Create temporary link and click it
    const link = document.createElement('a');
    link.href = url;
    link.download = '';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Copy to Clipboard
async function copyTextToClipboard() {
    const currentPage = pageSelect.value;
    const page = ocrResults.pages.find(p => p.page_number == currentPage);
    
    if (page) {
        try {
            await navigator.clipboard.writeText(page.text);
            
            // Show feedback
            const originalHTML = copyText.innerHTML;
            copyText.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="20 6 9 17 4 12"></polyline></svg>';
            copyText.style.color = 'var(--success-color)';
            
            setTimeout(() => {
                copyText.innerHTML = originalHTML;
                copyText.style.color = '';
            }, 2000);
            
        } catch (error) {
            console.error('Failed to copy:', error);
        }
    }
}

// Progress Updates
function updateProgress(percent, message, currentPage = null, totalPages = null, chunkInfo = null) {
    progressFill.style.width = `${percent}%`;
    progressPercent.textContent = `${Math.round(percent)}%`;
    progressMessage.textContent = message;
    
    if (currentPage && totalPages) {
        progressPages.textContent = `Page ${currentPage} of ${totalPages}`;
        progressDetails.textContent = '';
    } else if (chunkInfo) {
        progressPages.textContent = chunkInfo;
        progressDetails.textContent = '';
    } else {
        progressPages.textContent = '';
        progressDetails.textContent = '';
    }
}

// Section Management
function showSection(section) {
    // Hide all sections
    uploadSection.classList.add('hidden');
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
    errorMessage.classList.add('hidden');
    
    // Show requested section
    switch (section) {
        case 'upload':
            uploadSection.classList.remove('hidden');
            break;
        case 'progress':
            progressSection.classList.remove('hidden');
            break;
        case 'results':
            resultsSection.classList.remove('hidden');
            break;
    }
}

// Error Handling
function showError(message) {
    errorMessage.classList.remove('hidden');
    document.getElementById('error-text').textContent = message;
    
    // Hide other sections
    uploadSection.classList.add('hidden');
    progressSection.classList.add('hidden');
    resultsSection.classList.add('hidden');
}

// Reset
function resetToUpload() {
    // Clear state
    currentSession = null;
    ocrResults = null;
    currentUploadSession = null;
    uploadPaused = false;
    statusCheckFailureCount = 0; // Reset failure count
    
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    
    // Clean up incremental results
    const incrementalContainer = document.getElementById('incremental-results');
    if (incrementalContainer) {
        incrementalContainer.remove();
    }
    
    // WebSocket cleanup removed - using polling only
    
    // Reset file input
    fileInput.value = '';
    
    // Show upload section
    showSection('upload');
}



// Logging Functions - only log errors in client
function logError(message, context = {}) {
    console.error('[ERROR]', message, context);
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Check model status immediately
    checkModelStatus();
    
    // Job system allows uploads even when model is loading
    // Jobs are queued until model is ready
});
