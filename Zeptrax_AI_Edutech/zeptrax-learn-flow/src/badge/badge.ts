/**
 * Standalone Badge Script for Base44
 * Renders the "Edit with Base44" badge on remixable apps
 * No dependencies - pure vanilla JavaScript
 */

// Import badge assets
import logoV3 from './assets/logo_v3.png';
import base44Text from './assets/base44_text.png';
import badgeCover from './assets/badge-cover.png';

// Empty export to make this a module for TypeScript
export {};

(function() {
  'use strict';

  // SVG Icons as strings
  const XIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

  const LoaderIcon = '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="badge-spinner"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>';

  /**
   * Sanitizes a platform URL to prevent XSS attacks
   * Only allows http:// and https:// protocols
   */
  function sanitizePlatformUrl(url: string): string | null {
    if (!url) return null;

    try {
      const parsed = new URL(url);

      // Only allow http and https protocols
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        console.warn('Base44 badge: Invalid protocol in platform URL. Only http and https are allowed.');
        return null;
      }

      // Return the sanitized URL
      return parsed.origin;
    } catch (e) {
      console.warn('Base44 badge: Invalid platform URL provided');
      return null;
    }
  }

  /**
   * Sanitizes an app ID to prevent injection attacks
   * Only allows alphanumeric characters (letters and numbers)
   */
  function sanitizeAppId(appId: string): string | null {
    if (!appId) return null;

    // Only allow alphanumeric characters (letters and numbers only)
    const sanitized = appId.replace(/[^a-zA-Z0-9]/g, '');

    if (sanitized !== appId) {
      console.warn('Base44 badge: App ID contained invalid characters and was sanitized');
    }

    return sanitized || null;
  }

  /**
   * Fires a badge analytics event to the backend (fire-and-forget)
   */
  function trackBadgeEvent(
    platformUrl: string,
    appId: string,
    event: string,
    properties?: Record<string, unknown>,
  ): void {
    fetch(`${platformUrl}/api/apps/public/badge/${appId}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(properties ? { event, properties } : { event }),
    }).catch(() => {
      // Silently fail - analytics must never break the badge
    });
  }

  /**
   * Escapes HTML to prevent XSS when inserting into innerHTML
   */
  function escapeHtml(text: string): string {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function createModal(appId, platformUrl, allowClone) {
    const modalOverlay = document.createElement('div');
    modalOverlay.id = 'base44-modal-overlay';
    modalOverlay.dir = 'ltr';

    Object.assign(modalOverlay.style, {
      position: 'fixed',
      inset: '0',
      zIndex: '1000000',
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '16px',
      backdropFilter: 'blur(4px)',
      animation: 'base44-fade-in 0.2s ease-out',
    });

    const modalContent = document.createElement('div');
    Object.assign(modalContent.style, {
      backgroundColor: '#ffffff',
      borderRadius: '12px',
      maxWidth: '500px',
      width: '100%',
      position: 'relative',
      boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)',
      animation: 'base44-scale-in 0.2s ease-out',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    });

    modalContent.innerHTML = `
      <button
        id="modal-close-btn"
        aria-label="Close modal"
        style="
          position: absolute;
          top: 10px;
          right: 10px;
          padding: 8px;
          border-radius: 6px;
          background: transparent;
          border: none;
          cursor: pointer;
          transition: background-color 0.2s;
          color: #000000;
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 10;
        "
      >
        ${XIcon}
      </button>

      <div style="text-align: center;">
        <div style="position: relative; width: 100%; display: flex; justify-content: center; align-items: center; padding: 1px;">
          <img
            src="${badgeCover}"
            alt="Base44"
            style="width: 100%; height: auto; display: block; border-radius: 12px 12px 0 0;"
          />
          <div style="
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 40px;
            font-weight: 400;
            color: #ffffff;
            white-space: nowrap;
          ">
            Built with Base44
          </div>
        </div>

        <div style="padding: 0 24px 24px 24px;">
          <div style="
            font-size: 18px;
            font-weight: 400;
            color: #000000;
            margin: 24px 0 24px 0;
            line-height: 1.5;
          ">
            <div>Turn ideas into working apps with Base44</div>
            <div>Ready to build your own app?</div>
          </div>

          <div style="display: flex; flex-direction: column; gap: 8px;">
            <button
              id="modal-go-to-base44"
              style="
                height: 36px;
                font-size: 14px;
                font-weight: 500;
                color: #ffffff;
                background-color: #000000;
                border: 1px solid #000000;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.2s;
                font-family: inherit;
                box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.08);
              "
            >
              Go to Base44
            </button>

            ${allowClone ? `<button
              id="modal-clone-app"
              style="
                height: 36px;
                font-size: 14px;
                font-weight: 500;
                color: #09090b;
                background-color: #ffffff;
                border: 1px solid #e4e4e7;
                border-radius: 6px;
                cursor: pointer;
                transition: all 0.2s;
                font-family: inherit;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 8px;
                box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.08);
              "
            >
              <span id="clone-btn-content">Clone This App</span>
            </button>` : ''}
          </div>
        </div>

        <div id="admin-footer" style="display: none;"></div>
      </div>
    `;

    modalContent.addEventListener('click', function(e) {
      e.stopPropagation();
    });

    modalOverlay.appendChild(modalContent);

    // Close button hover
    const closeBtn = modalContent.querySelector('#modal-close-btn') as HTMLButtonElement;
    let buttonActionTaken = false;
    closeBtn.addEventListener('mouseenter', function() {
      this.style.backgroundColor = '#f4f4f5';
    });
    closeBtn.addEventListener('mouseleave', function() {
      this.style.backgroundColor = 'transparent';
    });
    closeBtn.addEventListener('click', function() {
      if (buttonActionTaken) return;
      trackBadgeEvent(platformUrl, appId, 'modal_closed');
      modalOverlay.remove();
    });

    // Go to Base44 button
    const goToBtn = modalContent.querySelector('#modal-go-to-base44') as HTMLButtonElement;
    goToBtn.addEventListener('click', function() {
      if (buttonActionTaken) return;
      buttonActionTaken = true;
      trackBadgeEvent(platformUrl, appId, 'modal_go_to_base44');
      window.open(platformUrl, '_blank');
      modalOverlay.remove();
    });

    // Clone app button (absent when cloning is disallowed)
    const cloneBtn = modalContent.querySelector('#modal-clone-app') as HTMLButtonElement | null;
    if (cloneBtn) {
      cloneBtn.addEventListener('click', function() {
        if (buttonActionTaken) return;
        buttonActionTaken = true;
        trackBadgeEvent(platformUrl, appId, 'modal_clone_app');
        const contentSpan = cloneBtn.querySelector('#clone-btn-content') as HTMLSpanElement;
        contentSpan.innerHTML = `${LoaderIcon}<span style="margin-left: 4px;">Cloning...</span>`;

        window.open(platformUrl + '/remix-app/' + appId, '_blank');

        setTimeout(function() {
          modalOverlay.remove();
        }, 1000);
      });
    }

    // Close on backdrop click
    modalOverlay.addEventListener('click', function() {
      if (buttonActionTaken) return;
      trackBadgeEvent(platformUrl, appId, 'modal_closed');
      modalOverlay.remove();
    });

    // Check if user is admin and show footer if they are
    checkAdminAndShowFooter(appId, platformUrl, modalContent);

    return modalOverlay;
  }

  function checkAdminAndShowFooter(appId, platformUrl, modalContent) {
    const token = localStorage.getItem('token');

    if (!token) {
      return;
    }

    fetch(`${platformUrl}/api/apps/${appId}/entities/User/me`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
      .then(response => {
        if (!response.ok) {
          return null;
        }
        return response.json();
      })
      .then(data => {
        if (data && data.role === 'admin') {
          const footer = modalContent.querySelector('#admin-footer') as HTMLDivElement;
          if (footer) {
            footer.style.display = 'block';
            Object.assign(footer.style, {
              padding: '16px 24px',
              borderTop: '1px solid #e4e4e7',
              backgroundColor: '#f9fafb',
              fontSize: '13px',
              color: '#000000',
              lineHeight: '1.5',
              textAlign: 'center',
              borderRadius: '0 0 12px 12px',
            });
            // Escape values to prevent XSS
            const escapedPlatformUrl = escapeHtml(platformUrl);
            const escapedAppId = escapeHtml(appId);
            footer.innerHTML = `This badge is part of the app experience. Hiding the badge is available on paid plans in the <a href="${escapedPlatformUrl}/apps/${escapedAppId}/editor/workspace/app-settings" target="_blank" rel="noopener noreferrer" style="color: #000000; text-decoration: underline; cursor: pointer;">app settings</a>.`;
          }
        }
      })
      .catch(() => {
        // Silently fail if the request fails
      });
  }

  function createBadgeElement(appId, platformUrl, allowClone) {
    const badge = document.createElement('div');
    badge.id = 'base44-edit-badge';
    badge.dir = 'ltr';

    // Apply styles
    Object.assign(badge.style, {
      position: 'fixed',
      zIndex: '999999',
      bottom: '16px',
      right: '16px',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      backgroundColor: '#000000',
      color: '#ffffff',
      padding: '8px 12px',
      borderRadius: '6px',
      boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
      cursor: 'pointer',
      transition: 'box-shadow 0.2s',
      border: '1px solid #262626',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      fontSize: '14px',
    });

    badge.innerHTML = `
      <img
        src="${logoV3}"
        alt="base44"
        style="width: 20px; height: 20px;"
      />
      <span style="white-space: nowrap; font-size: 12px;">
        <span id="badge-content">
          <div style="display: flex; align-items: center; gap: 6px; justify-content: center; font-size: 14px;">
            <span>${allowClone ? 'Edit with ' : 'Made with '}</span>
            <span style="margin-bottom: 2px;"><img src="${base44Text}" alt="Base44" height="18" width="56" /></span>
          </div>
        </span>
      </span>
      <button
        id="badge-close"
        aria-label="Close badge"
        style="
          padding: 2px;
          margin-left: 2px;
          border-radius: 9999px;
          background: transparent;
          border: none;
          cursor: pointer;
          transition: background-color 0.2s;
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
        "
      >
        ${XIcon}
      </button>
    `;

    // Add hover effect
    badge.addEventListener('mouseenter', function() {
      badge.style.boxShadow = '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)';
    });
    badge.addEventListener('mouseleave', function() {
      badge.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
    });

    // Handle close button
    const closeButton = badge.querySelector('#badge-close') as HTMLButtonElement;
    closeButton.addEventListener('mouseenter', function(e) {
      (e.target as HTMLButtonElement).style.backgroundColor = '#404040';
    });
    closeButton.addEventListener('mouseleave', function(e) {
      (e.target as HTMLButtonElement).style.backgroundColor = 'transparent';
    });
    closeButton.addEventListener('click', function(e) {
      e.stopPropagation();
      trackBadgeEvent(platformUrl, appId, 'badge_dismissed');
      badge.remove();
    });

    // Handle badge click
    badge.addEventListener('click', function() {
      trackBadgeEvent(platformUrl, appId, 'badge_clicked');
      const modal = createModal(appId, platformUrl, allowClone);
      document.body.appendChild(modal);
    });

    return badge;
  }

  // Capture script tag reference at top level (before any callbacks)
  const scriptTag = document.currentScript;

  function renderBadge() {
    // Use the captured script tag reference
    if (!scriptTag) {
      console.warn('Base44 badge: Could not find script tag with data-app-id');
      return;
    }

    const rawAppId = scriptTag.getAttribute('data-app-id');
    const rawPlatformUrl = scriptTag.getAttribute('data-platform-url') || 'https://app.base44.com';
    const allowClone = scriptTag.getAttribute('data-allow-clone') !== 'false';

    // Sanitize inputs
    const appId = sanitizeAppId(rawAppId || '');
    const platformUrl = sanitizePlatformUrl(rawPlatformUrl);

    if (!appId) {
      console.warn('Base44 badge: data-app-id attribute is required and must be valid');
      return;
    }

    if (!platformUrl) {
      console.warn('Base44 badge: data-platform-url must be a valid http or https URL');
      return;
    }

    // Create and append badge
    const badge = createBadgeElement(appId, platformUrl, allowClone);
    document.body.appendChild(badge);
    trackBadgeEvent(platformUrl, appId, 'badge_shown');

    // Add spinner and modal animation styles
    const style = document.createElement('style');
    style.textContent = `
      @keyframes badge-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }
      .badge-spinner {
        animation: badge-spin 1s linear infinite;
      }
      @keyframes base44-fade-in {
        from { opacity: 0; }
        to { opacity: 1; }
      }
      @keyframes base44-scale-in {
        from {
          opacity: 0;
          transform: scale(0.95);
        }
        to {
          opacity: 1;
          transform: scale(1);
        }
      }
    `;
    document.head.appendChild(style);
  }

  // Initialize badge when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderBadge);
  } else {
    // DOM already loaded
    renderBadge();
  }
})();
