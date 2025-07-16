# Frontend Update Plan for Processing.json

## Overview
Update the frontend to properly poll processing.json and display comprehensive progress for all stages: upload, extraction, and OCR processing.

## HTML Changes (index.html)

### 1. Replace the progress section with a more comprehensive display:

```html
<!-- Progress Section -->
<section id="progress-section" class="progress-section hidden">
    <!-- Main Progress Card -->
    <div class="progress-card">
        <h2 id="progress-title">Processing Document</h2>
        
        <!-- Stage Indicator -->
        <div class="stage-indicator">
            <div class="stage" data-stage="upload">
                <div class="stage-icon">📤</div>
                <div class="stage-label">Upload</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage" data-stage="extract">
                <div class="stage-icon">📄</div>
                <div class="stage-label">Extract</div>
            </div>
            <div class="stage-connector"></div>
            <div class="stage" data-stage="ocr">
                <div class="stage-icon">🔍</div>
                <div class="stage-label">OCR</div>
            </div>
        </div>
        
        <!-- Main Progress Bar -->
        <div class="progress-container">
            <div class="progress-bar-large">
                <div class="progress-fill-large" id="main-progress-fill"></div>
            </div>
            <div class="progress-stats">
                <span id="progress-percent" class="progress-percent-large">0%</span>
                <span id="progress-message" class="progress-message">Initializing...</span>
            </div>
        </div>
        
        <!-- Page Grid for PDFs -->
        <div id="page-grid-container" class="page-grid-container hidden">
            <h3>Page Processing Status</h3>
            <div id="page-grid" class="page-grid">
                <!-- Page items will be inserted here -->
            </div>
        </div>
        
        <!-- Live Preview -->
        <div id="live-preview" class="live-preview hidden">
            <h3>Current Page Preview</h3>
            <div class="preview-content">
                <img id="current-page-image" class="current-page-image" alt="Current page">
                <div id="current-page-text" class="current-page-text hidden">
                    <h4>Extracted Text</h4>
                    <pre id="page-text-content"></pre>
                </div>
            </div>
        </div>
    </div>
</section>
```

### 2. Update Results Section to show all content:

```html
<!-- Results Section -->
<section id="results-section" class="results-section hidden">
    <div class="results-header">
        <h2>OCR Results</h2>
        <div class="results-actions">
            <button class="btn-secondary" id="download-markdown">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="icon">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Download Markdown
            </button>
            <button class="btn-secondary" id="download-all">Download All Files</button>
            <button class="btn-primary" id="new-upload">New Upload</button>
        </div>
    </div>
    
    <div class="results-tabs">
        <button class="tab-btn active" data-tab="combined">Combined Text</button>
        <button class="tab-btn" data-tab="pages">Individual Pages</button>
        <button class="tab-btn" data-tab="metadata">Processing Details</button>
    </div>

    <div class="results-content">
        <!-- Combined Text Content -->
        <div id="combined-content" class="tab-content active">
            <div class="text-output-large" id="combined-text-output">
                <!-- Combined markdown will be rendered here -->
            </div>
        </div>

        <!-- Individual Pages Content -->
        <div id="pages-content" class="tab-content">
            <div class="page-selector">
                <select id="page-select" class="page-dropdown">
                    <!-- Options will be populated -->
                </select>
                <button class="btn-icon" id="copy-page-text" title="Copy page text">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
            </div>
            <div class="page-display">
                <div class="page-image-container">
                    <img id="page-image" class="page-image" alt="Page image">
                </div>
                <div class="page-text-container">
                    <pre id="page-text-output" class="text-output"></pre>
                </div>
            </div>
        </div>

        <!-- Metadata Content -->
        <div id="metadata-content" class="tab-content">
            <pre id="metadata-output" class="metadata-output"></pre>
        </div>
    </div>
</section>
```

## CSS Updates (style.css additions)

```css
/* Progress Card Styling */
.progress-card {
    background: var(--bg-primary);
    border-radius: 1rem;
    padding: 2.5rem;
    box-shadow: var(--shadow-lg);
}

/* Stage Indicator */
.stage-indicator {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 2rem;
    gap: 0;
}

.stage {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    opacity: 0.3;
    transition: all 0.3s ease;
}

.stage.active {
    opacity: 1;
}

.stage.completed {
    opacity: 1;
}

.stage-icon {
    width: 3rem;
    height: 3rem;
    background: var(--bg-tertiary);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    transition: all 0.3s ease;
}

.stage.active .stage-icon {
    background: var(--primary-color);
    color: white;
    transform: scale(1.1);
}

.stage.completed .stage-icon {
    background: var(--success-color);
    color: white;
}

.stage-label {
    font-size: 0.875rem;
    font-weight: 500;
    color: var(--text-secondary);
}

.stage-connector {
    width: 4rem;
    height: 2px;
    background: var(--border-color);
    margin: 0 0.5rem;
    margin-bottom: 2rem;
}

/* Large Progress Bar */
.progress-container {
    margin-bottom: 2rem;
}

.progress-bar-large {
    height: 1.5rem;
    background: var(--bg-tertiary);
    border-radius: 0.75rem;
    overflow: hidden;
    margin-bottom: 1rem;
}

.progress-fill-large {
    height: 100%;
    background: linear-gradient(90deg, var(--primary-color) 0%, var(--primary-hover) 100%);
    transition: width 0.5s ease;
    position: relative;
    overflow: hidden;
}

.progress-fill-large::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(
        90deg,
        transparent 0%,
        rgba(255, 255, 255, 0.2) 50%,
        transparent 100%
    );
    animation: shimmer 2s infinite;
}

@keyframes shimmer {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

.progress-stats {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.progress-percent-large {
    font-size: 2rem;
    font-weight: 700;
    color: var(--primary-color);
}

.progress-message {
    font-size: 1.125rem;
    color: var(--text-secondary);
}

/* Page Grid */
.page-grid-container {
    margin-top: 2rem;
    padding-top: 2rem;
    border-top: 1px solid var(--border-color);
}

.page-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
    gap: 1rem;
    margin-top: 1rem;
}

.page-item {
    aspect-ratio: 1;
    background: var(--bg-secondary);
    border: 2px solid var(--border-color);
    border-radius: 0.5rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
    transition: all 0.3s ease;
    cursor: pointer;
}

.page-item.processing {
    border-color: var(--primary-color);
    background: var(--bg-primary);
}

.page-item.completed {
    border-color: var(--success-color);
    background: #10b98110;
}

.page-item.failed {
    border-color: var(--error-color);
    background: #ef444410;
}

.page-number {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
}

.page-status-icon {
    position: absolute;
    bottom: 0.25rem;
    right: 0.25rem;
    width: 1.5rem;
    height: 1.5rem;
}

/* Live Preview */
.live-preview {
    margin-top: 2rem;
    padding-top: 2rem;
    border-top: 1px solid var(--border-color);
}

.preview-content {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    margin-top: 1rem;
}

.current-page-image {
    width: 100%;
    height: auto;
    border-radius: 0.5rem;
    box-shadow: var(--shadow-md);
}

.current-page-text {
    background: var(--bg-secondary);
    border-radius: 0.5rem;
    padding: 1rem;
    overflow-y: auto;
    max-height: 400px;
}

/* Results Page Display */
.page-display {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    margin-top: 1rem;
}

.page-image-container {
    background: var(--bg-secondary);
    border-radius: 0.5rem;
    padding: 1rem;
    display: flex;
    align-items: center;
    justify-content: center;
}

.page-image {
    max-width: 100%;
    height: auto;
    border-radius: 0.5rem;
    box-shadow: var(--shadow-md);
}

.text-output-large {
    background: var(--bg-secondary);
    border-radius: 0.5rem;
    padding: 2rem;
    min-height: 400px;
    max-height: 70vh;
    overflow-y: auto;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.8;
}

/* Responsive Updates */
@media (max-width: 768px) {
    .preview-content,
    .page-display {
        grid-template-columns: 1fr;
    }
    
    .stage-connector {
        width: 2rem;
    }
    
    .page-grid {
        grid-template-columns: repeat(auto-fill, minmax(60px, 1fr));
    }
}
```

## JavaScript Updates (script.js)

```javascript
// Global variables
let currentJobId = null;
let currentSessionId = null;
let pollingInterval = null;
let lastProcessingData = null;

// Configuration
const POLLING_INTERVAL = 2000; // 2 seconds for smoother updates
const API_BASE = window.location.origin;

// Initialize the app
document.addEventListener('DOMContentLoaded', function() {
    initializeEventListeners();
});

function initializeEventListeners() {
    // Upload area events
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    
    uploadArea.addEventListener('click', () => fileInput.click());
    uploadArea.addEventListener('dragover', handleDragOver);
    uploadArea.addEventListener('dragleave', handleDragLeave);
    uploadArea.addEventListener('drop', handleDrop);
    fileInput.addEventListener('change', handleFileSelect);
    
    // Results navigation
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => switchTab(e.target.dataset.tab));
    });
    
    // Download buttons
    document.getElementById('download-markdown').addEventListener('click', downloadMarkdown);
    document.getElementById('download-all').addEventListener('click', downloadAll);
    document.getElementById('new-upload').addEventListener('click', resetInterface);
}

// File upload handling
async function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        await uploadFile(file);
    }
}

async function uploadFile(file) {
    // Show progress section
    showSection('progress');
    updateProgress(0, 'Preparing upload...');
    
    // Update stage indicator
    updateStageIndicator('upload');
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        // Upload with progress tracking
        const xhr = new XMLHttpRequest();
        
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) {
                const percentComplete = Math.round((e.loaded / e.total) * 100);
                updateProgress(percentComplete * 0.3, `Uploading... ${percentComplete}%`); // Upload is 30% of total
            }
        });
        
        xhr.addEventListener('load', function() {
            if (xhr.status === 200) {
                const response = JSON.parse(xhr.responseText);
                currentJobId = response.job_id;
                currentSessionId = response.session_id;
                
                updateProgress(30, 'Upload complete, starting processing...');
                
                // Start polling for processing status
                startPolling();
            } else {
                showError('Upload failed: ' + xhr.statusText);
            }
        });
        
        xhr.addEventListener('error', () => showError('Upload failed'));
        
        xhr.open('POST', `${API_BASE}/api/upload`);
        xhr.send(formData);
        
    } catch (error) {
        showError('Upload error: ' + error.message);
    }
}

// Polling for processing status
function startPolling() {
    // Clear any existing polling
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
    
    // Poll immediately
    pollProcessingStatus();
    
    // Then poll at intervals
    pollingInterval = setInterval(pollProcessingStatus, POLLING_INTERVAL);
}

async function pollProcessingStatus() {
    if (!currentSessionId) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/processing`);
        if (!response.ok) throw new Error('Failed to fetch status');
        
        const data = await response.json();
        updateProcessingUI(data);
        
        // Store for reference
        lastProcessingData = data;
        
        // Check if completed
        if (data.status === 'completed' || data.status === 'failed') {
            clearInterval(pollingInterval);
            pollingInterval = null;
            
            if (data.status === 'completed') {
                await loadResults();
            } else {
                showError(data.message || 'Processing failed');
            }
        }
        
    } catch (error) {
        console.error('Polling error:', error);
    }
}

function updateProcessingUI(data) {
    // Update main progress
    const percent = data.percent || 0;
    updateProgress(percent, data.message || 'Processing...');
    
    // Update stage indicator based on current_step
    if (data.current_step === 'queued') {
        updateStageIndicator('upload');
    } else if (data.current_step === 'extracting_images' || data.current_step === 'extraction_complete') {
        updateStageIndicator('extract');
    } else if (data.current_step === 'ocr_processing' || data.current_step === 'processing') {
        updateStageIndicator('ocr');
    }
    
    // Show page grid for PDFs
    if (data.file_info && data.file_info.total_pages > 1) {
        updatePageGrid(data.pages);
        document.getElementById('page-grid-container').classList.remove('hidden');
    }
    
    // Show live preview if processing
    if (data.current_step === 'ocr_processing' && data.pages) {
        updateLivePreview(data);
    }
}

function updateProgress(percent, message) {
    document.getElementById('main-progress-fill').style.width = percent + '%';
    document.getElementById('progress-percent').textContent = percent + '%';
    document.getElementById('progress-message').textContent = message;
}

function updateStageIndicator(activeStage) {
    const stages = document.querySelectorAll('.stage');
    const stageOrder = ['upload', 'extract', 'ocr'];
    const activeIndex = stageOrder.indexOf(activeStage);
    
    stages.forEach((stage, index) => {
        const stageName = stage.dataset.stage;
        const stageIndex = stageOrder.indexOf(stageName);
        
        if (stageIndex < activeIndex) {
            stage.classList.add('completed');
            stage.classList.remove('active');
        } else if (stageIndex === activeIndex) {
            stage.classList.add('active');
            stage.classList.remove('completed');
        } else {
            stage.classList.remove('active', 'completed');
        }
    });
}

function updatePageGrid(pages) {
    const grid = document.getElementById('page-grid');
    grid.innerHTML = '';
    
    Object.entries(pages).forEach(([pageNum, pageData]) => {
        const pageItem = document.createElement('div');
        pageItem.className = 'page-item';
        pageItem.classList.add(pageData.status);
        pageItem.dataset.page = pageNum;
        
        pageItem.innerHTML = `
            <div class="page-number">${pageNum}</div>
            <div class="page-status-icon">
                ${pageData.status === 'completed' ? '✓' : 
                  pageData.status === 'processing' ? '⏳' : 
                  pageData.status === 'failed' ? '✗' : ''}
            </div>
        `;
        
        // Click to preview
        pageItem.addEventListener('click', () => previewPage(pageNum));
        
        grid.appendChild(pageItem);
    });
}

function updateLivePreview(data) {
    // Find the currently processing page
    const processingPage = Object.entries(data.pages).find(([_, pageData]) => 
        pageData.status === 'processing'
    );
    
    if (processingPage) {
        const [pageNum, pageData] = processingPage;
        const preview = document.getElementById('live-preview');
        preview.classList.remove('hidden');
        
        // Show page image
        if (pageData.image) {
            const imageUrl = `${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.image}`;
            document.getElementById('current-page-image').src = imageUrl;
        }
    }
}

async function loadResults() {
    showSection('results');
    
    try {
        // Load combined text
        const combinedResponse = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/results/combined`);
        if (combinedResponse.ok) {
            const combinedText = await combinedResponse.text();
            displayCombinedText(combinedText);
        }
        
        // Populate page selector
        if (lastProcessingData && lastProcessingData.pages) {
            populatePageSelector(lastProcessingData.pages);
        }
        
        // Show metadata
        if (lastProcessingData) {
            document.getElementById('metadata-output').textContent = 
                JSON.stringify(lastProcessingData, null, 2);
        }
        
    } catch (error) {
        showError('Failed to load results: ' + error.message);
    }
}

function displayCombinedText(text) {
    const output = document.getElementById('combined-text-output');
    
    // Render markdown if possible
    if (window.marked) {
        output.innerHTML = marked.parse(text);
    } else {
        output.textContent = text;
    }
}

function populatePageSelector(pages) {
    const select = document.getElementById('page-select');
    select.innerHTML = '';
    
    Object.entries(pages).forEach(([pageNum, pageData]) => {
        const option = document.createElement('option');
        option.value = pageNum;
        option.textContent = `Page ${pageNum}`;
        select.appendChild(option);
    });
    
    // Load first page
    if (select.options.length > 0) {
        select.selectedIndex = 0;
        loadPageContent(select.value);
    }
    
    // Add change listener
    select.addEventListener('change', (e) => loadPageContent(e.target.value));
}

async function loadPageContent(pageNum) {
    const pageData = lastProcessingData.pages[pageNum];
    if (!pageData) return;
    
    // Show page image
    if (pageData.image) {
        const imageUrl = `${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.image}`;
        document.getElementById('page-image').src = imageUrl;
    }
    
    // Load page text
    if (pageData.result_file) {
        try {
            const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.result_file}`);
            if (response.ok) {
                const text = await response.text();
                document.getElementById('page-text-output').textContent = text;
            }
        } catch (error) {
            console.error('Failed to load page text:', error);
        }
    }
}

// Utility functions
function showSection(sectionName) {
    document.querySelectorAll('section').forEach(section => {
        section.classList.add('hidden');
    });
    
    const targetSection = document.getElementById(`${sectionName}-section`);
    if (targetSection) {
        targetSection.classList.remove('hidden');
    }
}

function showError(message) {
    const errorDiv = document.getElementById('error-message');
    document.getElementById('error-text').textContent = message;
    errorDiv.classList.remove('hidden');
}

function resetInterface() {
    currentJobId = null;
    currentSessionId = null;
    lastProcessingData = null;
    
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
    
    showSection('upload');
    document.getElementById('file-input').value = '';
}

// Tab switching
function switchTab(tabName) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.toggle('active', content.id === `${tabName}-content`);
    });
}

// Download functions
async function downloadMarkdown() {
    if (!currentSessionId) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/download/markdown`);
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ocr_results_${currentSessionId}.md`;
            a.click();
            window.URL.revokeObjectURL(url);
        }
    } catch (error) {
        showError('Download failed: ' + error.message);
    }
}

async function downloadAll() {
    if (!currentSessionId) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/download/all`);
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `ocr_results_${currentSessionId}.zip`;
            a.click();
            window.URL.revokeObjectURL(url);
        }
    } catch (error) {
        showError('Download failed: ' + error.message);
    }
}

// Drag and drop handlers
function handleDragOver(e) {
    e.preventDefault();
    e.currentTarget.classList.add('dragover');
}

function handleDragLeave(e) {
    e.currentTarget.classList.remove('dragover');
}

function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('dragover');
    
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        uploadFile(files[0]);
    }
}
```

## Key Features Implemented

1. **Full-width progress display** with large progress bar and percentage
2. **Stage indicators** showing Upload → Extract → OCR progress
3. **Page grid** for PDFs showing individual page status with visual indicators
4. **Live preview** during processing showing current page image
5. **Comprehensive results** with combined text, individual pages, and metadata
6. **Smooth polling** every 2 seconds with proper status updates
7. **Beautiful animations** including shimmer effect on progress bar
8. **Responsive design** that works on mobile and desktop

## API Endpoints Needed

The frontend expects these endpoints from the backend:

1. `POST /api/upload` - Returns `{job_id, session_id}`
2. `GET /api/sessions/{session_id}/processing` - Returns processing.json
3. `GET /api/sessions/{session_id}/files/{filename}` - Returns file content
4. `GET /api/sessions/{session_id}/results/combined` - Returns combined markdown
5. `GET /api/sessions/{session_id}/download/markdown` - Downloads markdown
6. `GET /api/sessions/{session_id}/download/all` - Downloads zip of all files

The UI will now properly show:
- Upload progress with percentage
- Image extraction progress for PDFs
- Individual page processing status
- Live preview of current page being processed
- Complete results with both combined and individual page views
