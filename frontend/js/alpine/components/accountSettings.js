/**
 * accountSettings — Alpine component
 *
 * Handles the "Account settings" modal that lets authenticated users change
 * their username or password.  Mounted on #account-settings-modal in
 * index.html.
 *
 * Opens via a custom window event:
 *   $dispatch('open-account-settings')
 *   // or imperatively:
 *   window.dispatchEvent(new CustomEvent('open-account-settings'))
 *
 * API calls
 *   PATCH /users/me/username  { new_username }
 *   PATCH /users/me/password  { current_password, new_password }
 */
function accountSettings() {
  return {
    // ── state ────────────────────────────────────────────────────────────
    show: false,
    activeTab: 'username',    // 'username' | 'password'
    isGoogleUser: false,

    usernameForm: {
      newUsername: '',
      loading: false,
      error: '',
      success: '',
    },

    passwordForm: {
      currentPassword: '',
      newPassword: '',
      loading: false,
      error: '',
      success: '',
    },

    // ── lifecycle ────────────────────────────────────────────────────────
    init() {
      // Detect auth provider from the Alpine store once it's ready.
      // The store is initialised by appStore.js before this component mounts.
      this.$nextTick(() => {
        this._syncGoogleFlag();
      });
    },

    _syncGoogleFlag() {
      try {
        this.isGoogleUser = Alpine.store('app')?.user?.authProvider === 'google';
      } catch (_) {
        this.isGoogleUser = false;
      }
    },

    // ── public API ───────────────────────────────────────────────────────
    open() {
      this._syncGoogleFlag();
      this.activeTab = 'username';
      this.clearMessages();
      this.usernameForm.newUsername = '';
      this.passwordForm.currentPassword = '';
      this.passwordForm.newPassword = '';
      this.show = true;
      // Focus the first input after the transition
      this.$nextTick(() => {
        document.getElementById('acct-new-username')?.focus();
      });
    },

    close() {
      this.show = false;
      this.clearMessages();
    },

    clearMessages() {
      this.usernameForm.error = '';
      this.usernameForm.success = '';
      this.passwordForm.error = '';
      this.passwordForm.success = '';
    },

    // ── helpers ──────────────────────────────────────────────────────────
    _authHeader() {
      const token = localStorage.getItem('access_token');
      return token ? { Authorization: `Bearer ${token}` } : {};
    },

    async _patch(url, body) {
      const res = await fetch(url, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...this._authHeader(),
        },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data?.detail || `Request failed (${res.status})`;
        throw new Error(Array.isArray(msg) ? msg.map(e => e.msg || e).join('; ') : String(msg));
      }
      return data;
    },

    // ── form handlers ────────────────────────────────────────────────────
    async saveUsername() {
      const username = this.usernameForm.newUsername.trim();
      this.usernameForm.error = '';
      this.usernameForm.success = '';

      if (!username) {
        this.usernameForm.error = 'Please enter a new username.';
        return;
      }
      if (!/^[a-zA-Z0-9_-]{3,20}$/.test(username)) {
        this.usernameForm.error = 'Username must be 3–20 characters: letters, numbers, _ or -.';
        return;
      }

      this.usernameForm.loading = true;
      try {
        const data = await this._patch('/users/me/username', { new_username: username });

        // Update the store so the sidebar reflects the new name immediately.
        try {
          const store = Alpine.store('app');
          if (store?.user) {
            store.user.username = data.username;
          }
          localStorage.setItem('username', data.username);
        } catch (_) { /* store update is best-effort */ }

        this.usernameForm.success = 'Username updated! You will be signed out so your session refreshes.';
        this.usernameForm.newUsername = '';

        // Sign out after a short delay so the user can read the message.
        setTimeout(() => {
          try { Alpine.store('app').signOut(); } catch (_) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('username');
            window.location.href = '/';
          }
        }, 2000);
      } catch (err) {
        this.usernameForm.error = err.message || 'Failed to update username.';
      } finally {
        this.usernameForm.loading = false;
      }
    },

    async savePassword() {
      this.passwordForm.error = '';
      this.passwordForm.success = '';

      if (!this.passwordForm.currentPassword) {
        this.passwordForm.error = 'Please enter your current password.';
        return;
      }
      if (!this.passwordForm.newPassword) {
        this.passwordForm.error = 'Please enter a new password.';
        return;
      }
      if (this.passwordForm.newPassword.length < 8) {
        this.passwordForm.error = 'New password must be at least 8 characters.';
        return;
      }
      if (!/[A-Z]/.test(this.passwordForm.newPassword)) {
        this.passwordForm.error = 'New password must contain at least one uppercase letter.';
        return;
      }
      if (!/\d/.test(this.passwordForm.newPassword)) {
        this.passwordForm.error = 'New password must contain at least one number.';
        return;
      }

      this.passwordForm.loading = true;
      try {
        await this._patch('/users/me/password', {
          current_password: this.passwordForm.currentPassword,
          new_password: this.passwordForm.newPassword,
        });

        this.passwordForm.success = 'Password updated successfully!';
        this.passwordForm.currentPassword = '';
        this.passwordForm.newPassword = '';
      } catch (err) {
        this.passwordForm.error = err.message || 'Failed to update password.';
      } finally {
        this.passwordForm.loading = false;
      }
    },
  };
}
