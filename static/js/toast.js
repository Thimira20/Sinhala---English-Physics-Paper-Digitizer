/**
 * Toast notification module for user feedback and rate-wait countdowns.
 */

class ToastManager {
    constructor() {
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.className = 'toast-container';
        document.body.appendChild(this.container);
        this._activeRateToast = null;
        this._countdownInterval = null;
    }

    show(message, type = 'info', duration = 4000, options = {}) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        const iconMap = {
            info: 'ℹ',
            success: '✔',
            warning: '⚠',
            error: '✖'
        };

        toast.innerHTML = `
            <span class="toast-icon">${iconMap[type] || '•'}</span>
            <span class="toast-msg">${message}</span>
            <button class="toast-close" title="Dismiss">&times;</button>
        `;

        if (options.actionLabel && typeof options.onAction === 'function') {
            const actionBtn = document.createElement('button');
            actionBtn.className = 'toast-action-btn';
            actionBtn.textContent = options.actionLabel;
            actionBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                try {
                    options.onAction();
                } catch (err) {
                    console.error('Toast action failed:', err);
                }
                this._removeToast(toast);
            });
            const closeBtn = toast.querySelector('.toast-close');
            toast.insertBefore(actionBtn, closeBtn);
        }

        toast.querySelector('.toast-close').addEventListener('click', () => {
            this._removeToast(toast);
        });

        this.container.appendChild(toast);

        // Auto remove
        if (duration > 0) {
            setTimeout(() => {
                this._removeToast(toast);
            }, duration);
        }

        return toast;
    }

    success(message, duration = 3500, options = {}) {
        return this.show(message, 'success', duration, options);
    }

    warning(message, duration = 5000, options = {}) {
        return this.show(message, 'warning', duration, options);
    }

    error(message, duration = 6000, options = {}) {
        return this.show(message, 'error', duration, options);
    }

    info(message, duration = 4000, options = {}) {
        return this.show(message, 'info', duration, options);
    }

    showRateWait(seconds) {
        if (this._countdownInterval) {
            clearInterval(this._countdownInterval);
        }
        if (this._activeRateToast) {
            this._removeToast(this._activeRateToast);
        }

        let remaining = Math.round(seconds);
        const toast = document.createElement('div');
        toast.className = 'toast toast-warning toast-countdown';
        toast.innerHTML = `
            <span class="toast-icon">⏳</span>
            <span class="toast-msg">Rate limit encountered. Resuming in <strong id="rate-seconds">${remaining}s</strong>...</span>
        `;
        this.container.appendChild(toast);
        this._activeRateToast = toast;

        this._countdownInterval = setInterval(() => {
            remaining -= 1;
            const secSpan = toast.querySelector('#rate-seconds');
            if (secSpan) secSpan.textContent = `${remaining}s`;

            if (remaining <= 0) {
                clearInterval(this._countdownInterval);
                this._removeToast(toast);
                this._activeRateToast = null;
            }
        }, 1000);
    }

    _removeToast(toast) {
        toast.classList.add('toast-fade-out');
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 200);
    }
}

export const toast = new ToastManager();
