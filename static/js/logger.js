/**
 * Frontend Logger - Budget-friendly debugging utility
 * Sends logs to backend for centralized debugging
 * Inspired by Loggly approach with local console fallback
 */
class FrontendLogger {
    constructor(options = {}) {
        this.endpoint = options.endpoint || '/api/log';
        this.enableConsole = options.enableConsole !== false;
        this.enableRemote = options.enableRemote !== false;
        this.sessionId = options.sessionId || this.generateSessionId();
        this.context = options.context || {};
        this.logLevel = options.logLevel || 'DEBUG';
        
        // Buffer for batch sending (budget optimization)
        this.logBuffer = [];
        this.bufferSize = options.bufferSize || 10;
        this.flushInterval = options.flushInterval || 5000; // 5 seconds
        
        this.startAutoFlush();
        
        // Color styles for console output
        this.styles = {
            ERROR: 'color: #ff4444; font-weight: bold;',
            WARN: 'color: #ffaa00; font-weight: bold;',
            INFO: 'color: #4CAF50; font-weight: bold;',
            DEBUG: 'color: #2196F3;',
            STATUS: 'color: #9C27B0; font-weight: bold;'
        };
    }
    
    generateSessionId() {
        return 'frontend_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
    }
    
    log(level, message, context = {}) {
        const timestamp = new Date().toISOString();
        const logEntry = {
            level: level.toUpperCase(),
            message,
            context: { ...this.context, ...context },
            session_id: this.sessionId,
            timestamp,
            url: window.location.href,
            user_agent: navigator.userAgent
        };
        
        // Console output (immediate feedback)
        if (this.enableConsole) {
            const style = this.styles[level.toUpperCase()] || '';
            const prefix = `[${level.toUpperCase()}] ${timestamp} ${this.sessionId}:`;
            
            if (style) {
                console.log(`%c${prefix}`, style, message, context);
            } else {
                console.log(prefix, message, context);
            }
        }
        
        // Remote logging (buffered for efficiency)
        if (this.enableRemote) {
            this.logBuffer.push(logEntry);
            
            // Immediate flush for errors
            if (level.toUpperCase() === 'ERROR') {
                this.flush();
            } else if (this.logBuffer.length >= this.bufferSize) {
                this.flush();
            }
        }
    }
    
    // Convenience methods
    error(message, context = {}) {
        this.log('ERROR', message, context);
    }
    
    warn(message, context = {}) {
        this.log('WARN', message, context);
    }
    
    info(message, context = {}) {
        this.log('INFO', message, context);
    }
    
    debug(message, context = {}) {
        this.log('DEBUG', message, context);
    }
    
    // Special method for status debugging
    status(sessionHash, action, result = null, error = null) {
        const context = {
            session_hash: sessionHash,
            action,
            result: result ? JSON.stringify(result) : null,
            error: error ? error.toString() : null,
            timestamp: new Date().toISOString()
        };
        
        if (error) {
            this.error(`Status action failed: ${action}`, context);
        } else {
            this.log('STATUS', `Status action: ${action}`, context);
        }
    }
    
    // Flush logs to backend
    async flush() {
        if (this.logBuffer.length === 0) return;
        
        const logsToSend = [...this.logBuffer];
        this.logBuffer = [];
        
        try {
            // Send each log individually for now (could batch optimize later)
            for (const logEntry of logsToSend) {
                await fetch(this.endpoint, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(logEntry)
                });
            }
        } catch (error) {
            // Fallback to console if remote logging fails
            console.error('Failed to send logs to backend:', error);
            // Put logs back in buffer for retry
            this.logBuffer.unshift(...logsToSend);
        }
    }
    
    startAutoFlush() {
        setInterval(() => {
            this.flush();
        }, this.flushInterval);
        
        // Flush on page unload
        window.addEventListener('beforeunload', () => {
            // Use sendBeacon for reliable delivery on page unload
            if (this.logBuffer.length > 0 && navigator.sendBeacon) {
                const payload = JSON.stringify({
                    logs: this.logBuffer,
                    final_flush: true
                });
                navigator.sendBeacon(this.endpoint + '/batch', payload);
            }
        });
    }
    
    // Method to track session lifecycle
    trackSession(sessionHash, event, data = {}) {
        this.status(sessionHash, `session_${event}`, data);
    }
    
    // Method to track API calls
    trackApiCall(url, method, responseStatus, duration, error = null) {
        // Don't log calls to the logging endpoint itself (prevents infinite recursion)
        if (url === this.endpoint || url.includes('/api/log')) {
            return;
        }
        
        const context = {

            api_url: url,
            method,
            status: responseStatus,
            duration_ms: duration,
            error: error ? error.toString() : null
        };
        
        if (error || responseStatus >= 400) {
            this.error(`API call failed: ${method} ${url}`, context);
        } else {
            this.debug(`API call: ${method} ${url}`, context);
        }
    }
}

// Global logger instance
window.Logger = new FrontendLogger({
    context: {
        page: 'gnosis-ocr',
        version: '2.0'
    }
});

// Convenience global methods
window.logError = (msg, ctx) => window.Logger.error(msg, ctx);
window.logWarn = (msg, ctx) => window.Logger.warn(msg, ctx);
window.logInfo = (msg, ctx) => window.Logger.info(msg, ctx);
window.logDebug = (msg, ctx) => window.Logger.debug(msg, ctx);
window.logStatus = (hash, action, result, error) => window.Logger.status(hash, action, result, error);

// Override fetch to automatically track API calls
const originalFetch = window.fetch;
window.fetch = async function(...args) {
    const startTime = Date.now();
    const [url, options = {}] = args;
    const method = options.method || 'GET';
    
    try {
        const response = await originalFetch.apply(this, args);
        const duration = Date.now() - startTime;
        
        window.Logger.trackApiCall(url, method, response.status, duration);
        return response;
    } catch (error) {
        const duration = Date.now() - startTime;
        window.Logger.trackApiCall(url, method, 0, duration, error);
        throw error;
    }
};

// Log page load
window.Logger.info('Page loaded', {
    url: window.location.href,
    referrer: document.referrer,
    timestamp: new Date().toISOString()
});

console.log('%c🔍 Frontend Logger Initialized', 'color: #4CAF50; font-weight: bold; font-size: 14px;');
console.log('Available methods: logError(), logWarn(), logInfo(), logDebug(), logStatus()');
console.log('Session ID:', window.Logger.sessionId);
