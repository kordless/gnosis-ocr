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

// State
let currentSession = null;
let ocrResults = null;
let statusCheckInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
});

// Event Listeners
function setupEventListeners() {
    // File upload
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });
    fileInput.addEventListener('change', handleFileSelect);
    
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

// Upload File
async function uploadFile(file) {
    // Validate file
    if (file.type !== 'application/pdf') {
        showError('Please upload a PDF file');
        return;
    }
    
    if (file.size > 52428800) { // 50MB
        showError('File size exceeds 50MB limit');
        return;
    }
    
    // Show progress section
    showSection('progress');
    updateProgress(0, 'Uploading document...');
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Upload failed');
        }
        
        const data = await response.json();
        currentSession = data.session_hash;
        
        // Start status checking
        startStatusChecking();
        
    } catch (error) {
        showError(error.message);
    }
}

// Status Checking
function startStatusChecking() {
    statusCheckInterval = setInterval(checkStatus, 1000);
}

async function checkStatus() {
    if (!currentSession) return;
    
    try {
        const response = await fetch(`/status/${currentSession}`);
        if (!response.ok) throw new Error('Status check failed');
        
        const status = await response.json();
        
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
            clearInterval(statusCheckInterval);
            showError(status.message || 'Processing failed');
        }
        
    } catch (error) {
        clearInterval(statusCheckInterval);
        showError(error.message);
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
    imageOutput.innerHTML = `<img src="/images/${currentSession}/${pageNumber}" alt="Page ${pageNumber}">`;
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
function updateProgress(percent, message, currentPage = null, totalPages = null) {
    progressFill.style.width = `${percent}%`;
    progressPercent.textContent = `${Math.round(percent)}%`;
    progressMessage.textContent = message;
    
    if (currentPage && totalPages) {
        progressPages.textContent = `Page ${currentPage} of ${totalPages}`;
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
    if (statusCheckInterval) {
        clearInterval(statusCheckInterval);
    }
    
    // Reset file input
    fileInput.value = '';
    
    // Show upload section
    showSection('upload');
}