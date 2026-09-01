/**
 * ===========================================================================
 * APP DIALOG & TOAST SYSTEM (VNPT SNOC2 MODERN UI)
 * Thay thế hoàn toàn alert() và confirm() mặc định của trình duyệt/Windows.
 * 100% Offline-safe, thuần vanilla JS, hỗ trợ phím tắt Enter/Esc.
 * ===========================================================================
 */

(function(window) {
    // 1. Tạo HTML DOM nếu chưa có
    function initDialogDOM() {
        if (document.getElementById('appModalOverlay')) return;

        // Modal Overlay DOM
        var overlay = document.createElement('div');
        overlay.id = 'appModalOverlay';
        overlay.className = 'app-modal-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="app-modal-card" id="appModalCard">
                <div class="app-modal-head" id="appModalHead">
                    <span class="app-modal-icon" id="appModalIcon">ℹ️</span>
                    <span class="app-modal-title" id="appModalTitle">Thông báo</span>
                    <button type="button" class="app-modal-close" onclick="AppDialog.close()">&times;</button>
                </div>
                <div class="app-modal-body" id="appModalBody"></div>
                <div class="app-modal-foot" id="appModalFoot"></div>
            </div>
        `;
        document.body.appendChild(overlay);

        // Toast Container DOM
        var toastContainer = document.createElement('div');
        toastContainer.id = 'appToastContainer';
        toastContainer.className = 'app-toast-container';
        document.body.appendChild(toastContainer);

        // Bắt phím Enter / Escape cho Modal
        document.addEventListener('keydown', function(e) {
            var m = document.getElementById('appModalOverlay');
            if (m && m.style.display !== 'none') {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    if (AppDialog._onCancel) AppDialog._onCancel();
                    AppDialog.close();
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    var btnOk = document.getElementById('appModalBtnOk');
                    if (btnOk) btnOk.click();
                }
            }
        });
    }

    var AppDialog = {
        _onOk: null,
        _onCancel: null,

        close: function() {
            var overlay = document.getElementById('appModalOverlay');
            if (overlay) overlay.style.display = 'none';
            AppDialog._onOk = null;
            AppDialog._onCancel = null;
        },

        alert: function(msg, options) {
            initDialogDOM();
            options = options || {};
            var title = options.title || 'Thông báo hệ thống';
            var type = options.type || 'info'; // info, success, warning, error
            var btnText = options.btnText || 'Đã hiểu';

            var iconMap = {
                'info': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
                'success': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><polyline points="16 9 10 15 7 12"></polyline></svg>',
                'warning': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
                'error': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>'
            };

            document.getElementById('appModalIcon').innerHTML = iconMap[type] || iconMap['info'];
            document.getElementById('appModalTitle').textContent = title;
            document.getElementById('appModalBody').textContent = msg;

            var foot = document.getElementById('appModalFoot');
            foot.innerHTML = `
                <button type="button" id="appModalBtnOk" class="btn btn-primary px-4 fw-bold" style="font-size:13px;">${btnText}</button>
            `;

            document.getElementById('appModalBtnOk').onclick = function() {
                AppDialog.close();
                if (typeof options.onOk === 'function') options.onOk();
            };

            var overlay = document.getElementById('appModalOverlay');
            overlay.style.display = 'flex';
            document.getElementById('appModalBtnOk').focus();
        },

        confirm: function(msg, options) {
            initDialogDOM();
            options = options || {};
            var title = options.title || 'Xác nhận yêu cầu';
            var type = options.type || 'warning';
            var okText = options.okText || 'Xác nhận';
            var cancelText = options.cancelText || 'Hủy bỏ';
            var isDanger = options.isDanger || false;

            var iconMap = {
                'info': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
                'success': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><polyline points="16 9 10 15 7 12"></polyline></svg>',
                'warning': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
                'error': '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>'
            };

            document.getElementById('appModalIcon').innerHTML = iconMap[type] || iconMap['warning'];
            document.getElementById('appModalTitle').textContent = title;
            document.getElementById('appModalBody').textContent = msg;

            AppDialog._onCancel = options.onCancel;
            AppDialog._onOk = options.onOk;

            var btnClass = isDanger ? 'btn btn-danger' : 'btn btn-primary';

            var foot = document.getElementById('appModalFoot');
            foot.innerHTML = `
                <button type="button" id="appModalBtnCancel" class="btn btn-outline-secondary px-3" style="font-size:13px;">${cancelText}</button>
                <button type="button" id="appModalBtnOk" class="${btnClass} px-3 fw-bold" style="font-size:13px;">${okText}</button>
            `;

            document.getElementById('appModalBtnCancel').onclick = function() {
                AppDialog.close();
                if (typeof options.onCancel === 'function') options.onCancel();
            };

            document.getElementById('appModalBtnOk').onclick = function() {
                AppDialog.close();
                if (typeof options.onOk === 'function') options.onOk();
            };

            var overlay = document.getElementById('appModalOverlay');
            overlay.style.display = 'flex';
            document.getElementById('appModalBtnOk').focus();
        },

        toast: function(msg, type) {
            initDialogDOM();
            type = type || 'info';
            var container = document.getElementById('appToastContainer');

            var toast = document.createElement('div');
            toast.className = `app-toast-item toast-${type}`;
            
            var iconMap = {
                'info': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#2563eb" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
                'success': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><polyline points="16 9 10 15 7 12"></polyline></svg>',
                'warning': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#d97706" stroke-width="2.5"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
                'error': '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#dc2626" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>'
            };

            toast.innerHTML = `
                <span class="app-toast-icon">${iconMap[type] || iconMap['info']}</span>
                <span class="app-toast-text">${msg}</span>
            `;

            container.appendChild(toast);

            setTimeout(function() {
                toast.classList.add('show');
            }, 10);

            setTimeout(function() {
                toast.classList.remove('show');
                setTimeout(function() {
                    if (toast.parentElement) toast.parentElement.removeChild(toast);
                }, 300);
            }, 3200);
        }
    };

    // Public functions
    window.AppDialog = AppDialog;
    window.showAlert = AppDialog.alert;
    window.showConfirm = AppDialog.confirm;
    window.showToast = AppDialog.toast;

    // Tự động khởi tạo khi DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDialogDOM);
    } else {
        initDialogDOM();
    }
})(window);
