export class ModalManager {
    static show(title, content, type = 'info') {
        const modal = document.getElementById('session-modal');
        const modalTitle = document.getElementById('modal-title');
        const modalBody = document.getElementById('modal-body');
        
        modalTitle.textContent = title;
        modalBody.innerHTML = content;
        
        // Add type class for styling
        modal.className = `modal modal-${type}`;
        modal.style.display = 'block';
    }
    
    static showProgress(title, message, progress = 0) {
        const content = `
            <div class="modal-progress">
                <p class="progress-message">${message}</p>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${progress}%"></div>
                </div>
                <p class="progress-percent">${progress}%</p>
            </div>
        `;
        this.show(title, content, 'progress');
    }
    
    static updateProgress(message, progress) {
        const messageEl = document.querySelector('.modal-progress .progress-message');
        const fillEl = document.querySelector('.modal-progress .progress-fill');
        const percentEl = document.querySelector('.modal-progress .progress-percent');
        
        if (messageEl) messageEl.textContent = message;
        if (fillEl) fillEl.style.width = `${progress}%`;
        if (percentEl) percentEl.textContent = `${progress}%`;
    }
    
    static close() {
        document.getElementById('session-modal').style.display = 'none';
    }
    
    static confirm(title, message) {
        return new Promise((resolve) => {
            const content = `
                <div class="modal-confirm">
                    <p>${message}</p>
                    <div class="modal-buttons">
                        <button class="upload-button" onclick="ModalManager._confirmResolve(true)">Yes</button>
                        <button class="cancel-button" onclick="ModalManager._confirmResolve(false)">No</button>
                    </div>
                </div>
            `;
            this.show(title, content, 'confirm');
            ModalManager._confirmResolver = resolve;
        });
    }
    
    static _confirmResolve(value) {
        if (ModalManager._confirmResolver) {
            ModalManager._confirmResolver(value);
            ModalManager._confirmResolver = null;
            ModalManager.close();
        }
    }
}