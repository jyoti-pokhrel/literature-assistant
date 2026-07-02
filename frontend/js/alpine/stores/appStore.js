window.ResearchAgent = window.ResearchAgent || {};

window.ResearchAgent.routes = {
    landing: '/',
    workspace: '/workspace',
    search: '/workspace/search',
    explore: '/workspace/explore',
    citations: '/workspace/citations',
    share: '/synthesis/share',
};

window.ResearchAgent.exploreDefaults = Object.freeze({
    pageSize: 20,
});

window.ResearchAgent.defaults = Object.freeze({
    topic: '',
    year: '',
    venue: '',
    strictVenue: false,
    maxResults: 20,
});

window.ResearchAgent.searchHistoryKey = 'research-agent-search-history-v2';
window.ResearchAgent.sidebarStateKey = 'research-agent-sidebar-collapsed-v3';

window.ResearchAgent.cloneSearchValues = function cloneSearchValues(values = {}) {
    const maxResults = Number.parseInt(values.maxResults, 10);
    return {
        topic: typeof values.topic === 'string' ? values.topic : (typeof values.query === 'string' ? values.query : ''),
        year: typeof values.year === 'string' ? values.year : '',
        venue: typeof values.venue === 'string' ? values.venue : '',
        strictVenue: values.strictVenue === true || values.strictVenue === 'true',
        maxResults: Number.isFinite(maxResults) ? maxResults : window.ResearchAgent.defaults.maxResults,
    };
};

window.ResearchAgent.normalizeSearchValues = function normalizeSearchValues(values = {}) {
    const normalized = window.ResearchAgent.cloneSearchValues(values);
    normalized.topic = normalized.topic.trim();
    normalized.year = normalized.year.trim().replace(/\s*-\s*/g, '-');
    normalized.venue = normalized.venue.trim();
    if (!normalized.venue) {
        normalized.strictVenue = false;
    }

    if (!Number.isFinite(normalized.maxResults)) {
        normalized.maxResults = window.ResearchAgent.defaults.maxResults;
    }
    normalized.maxResults = Math.min(Math.max(normalized.maxResults, 1), 50);

    return normalized;
};

window.ResearchAgent.searchKey = function searchKey(values = {}) {
    const normalized = window.ResearchAgent.normalizeSearchValues(values);
    return JSON.stringify(normalized);
};

window.ResearchAgent.valuesFromSearchParams = function valuesFromSearchParams(searchParams) {
    return window.ResearchAgent.normalizeSearchValues({
        topic: searchParams.get('topic') || searchParams.get('q') || '',
        year: searchParams.get('year') || '',
        venue: searchParams.get('venue') || '',
        strictVenue: searchParams.get('strictVenue') === 'true',
        maxResults: searchParams.get('maxResults') || window.ResearchAgent.defaults.maxResults,
    });
};

window.ResearchAgent.searchParamsFromValues = function searchParamsFromValues(values = {}) {
    const normalized = window.ResearchAgent.normalizeSearchValues(values);
    const params = new URLSearchParams();

    if (normalized.topic) params.set('topic', normalized.topic);
    if (normalized.year) params.set('year', normalized.year);
    if (normalized.venue) params.set('venue', normalized.venue);
    if (normalized.venue && normalized.strictVenue) params.set('strictVenue', 'true');
    params.set('maxResults', String(normalized.maxResults));

    return params;
};

window.ResearchAgent.validateSearchValues = function validateSearchValues(values = {}) {
    const normalized = window.ResearchAgent.normalizeSearchValues(values);

    if (!normalized.topic) {
        throw new Error('Topic is required');
    }

    if (normalized.year) {
        const exactYear = /^\d{4}$/;
        const yearRange = /^(\d{4})-(\d{4})$/;

        if (exactYear.test(normalized.year)) {
            if (Number(normalized.year) < 1) {
                throw new Error('Year must be a positive integer');
            }
        } else {
            const match = normalized.year.match(yearRange);
            if (!match) {
                throw new Error('Year must be a 4 digit year or a range like 2023-2026');
            }

            const startYear = Number(match[1]);
            const endYear = Number(match[2]);
            if (startYear < 1 || endYear < 1) {
                throw new Error('Year range must contain positive integers');
            }
            if (startYear > endYear) {
                throw new Error('Year range start must be less than or equal to end');
            }
        }
    }

    if (normalized.maxResults < 1 || normalized.maxResults > 50) {
        throw new Error('Max results must be between 1 and 50');
    }

    return normalized;
};

window.ResearchAgent.coerceStoredResult = function coerceStoredResult(result) {
    if (!result) {
        return null;
    }

    if (result.searchData && Object.prototype.hasOwnProperty.call(result, 'gapData')) {
        return result;
    }

    if (result.topic && Array.isArray(result.papers)) {
        return {
            searchData: result,
            gapData: result.gapData || null,
        };
    }

    return null;
};

window.ResearchAgent.buildHistorySummary = function buildHistorySummary(values, result) {
    const searchData = result?.searchData || result;
    const filters = searchData?.filters ? window.searchAPI.formatFilters(searchData.filters) : [];
    const count = searchData?.count ?? searchData?.papers?.length ?? 0;
    return filters.length ? `${filters.join(' · ')} · ${count} results` : `${count} results`;
};

window.ResearchAgent.loadSearchHistory = function loadSearchHistory() {
    try {
        const raw = JSON.parse(localStorage.getItem(window.ResearchAgent.searchHistoryKey) || '[]');
        if (!Array.isArray(raw)) {
            return [];
        }

        return raw
            .map((item) => {
                if (!item) return null;
                // Note: We no longer strictly require `result` here because we use server-side cache
                const result = window.ResearchAgent.coerceStoredResult(item?.result);

                const values = window.ResearchAgent.normalizeSearchValues({
                    topic: item.topic,
                    year: item.year,
                    venue: item.venue,
                    strictVenue: item.strictVenue,
                    maxResults: item.maxResults,
                });

                return {
                    id: item.id || `${Date.now()}`,
                    topic: values.topic,
                    year: values.year,
                    venue: values.venue,
                    strictVenue: values.strictVenue,
                    maxResults: values.maxResults,
                    summary: item.summary || window.ResearchAgent.buildHistorySummary(values, result),
                    // Intentionally omitting result to save localStorage space; use API cache instead.
                };
            })
            .filter(Boolean)
            .slice(0, 8);
    } catch (_error) {
        return [];
    }
};

window.ResearchAgent.saveSearchHistory = function saveSearchHistory(history) {
    localStorage.setItem(window.ResearchAgent.searchHistoryKey, JSON.stringify(history.slice(0, 8)));
};

window.ResearchAgent.buildExploreSuggestions = function buildExploreSuggestions(history = []) {
    const suggestions = [];
    const seen = new Set();
    const pushSuggestion = (topic, reason) => {
        const normalized = window.ResearchAgent.normalizeSearchValues({ topic, maxResults: window.ResearchAgent.defaults.maxResults });
        if (!normalized.topic || seen.has(normalized.topic.toLowerCase())) {
            return;
        }
        seen.add(normalized.topic.toLowerCase());
        suggestions.push({ ...normalized, reason });
    };

    history.slice(0, 5).forEach((item) => {
        const topic = item.topic || '';
        if (!topic) return;
        pushSuggestion(`${topic} evaluation gaps`, 'Based on your recent search');
        pushSuggestion(`${topic} robustness limitations`, 'Explore recurring limitations');
    });

    if (!suggestions.length) {
        pushSuggestion('multi agent reinforcement learning robustness', 'Starter research direction');
        pushSuggestion('large language model evaluation gaps', 'Starter research direction');
        pushSuggestion('privacy preserving machine learning limitations', 'Starter research direction');
    }

    return suggestions.slice(0, 4);
};

document.addEventListener('alpine:init', () => {
    const storedSidebarState = localStorage.getItem(window.ResearchAgent.sidebarStateKey);
    Alpine.store('app', {
        initialized: false,
        get isLoggedIn() {
            const token = localStorage.getItem('access_token');
            return !!(token && token !== 'undefined' && token !== 'null');
        },
        user: {
            username: '',
            email: '',
            role: '',
            authProvider: '',
            get displayName() { return this.username || ''; },
            get initial() { return (this.username || '?').trim().charAt(0).toUpperCase() || '?'; },
            get subtitle() {
                if (this.role === 'admin') return 'Admin';
                return this.authProvider === 'google' ? 'Google account' : 'Researcher';
            },
            get isAdmin() { return this.role === 'admin'; },
        },
        mode: 'landing',
        currentView: 'form',
        theme: localStorage.getItem('theme') || 'light',
        sidebarCollapsed: storedSidebarState === null ? false : storedSidebarState === 'true',
        techPanelOpen: false,
        isLoading: false,
        activeHistoryMenuId: null,
        error: '',
        progressEvents: [],
        form: window.ResearchAgent.cloneSearchValues(window.ResearchAgent.defaults),
        history: [],
        chatHistory: [],
        currentChatSession: null,
        chatInput: '',
        result: null,
        activeSearchKey: '',
        explorer: {
            selectedGapId: null,
            selectedPaperId: null,
            selectedClusterId: null,
            panelOpen: false,
            panelType: null,
            filters: {
                minConfidence: 0,
                maxConfidence: 1,
                clusterId: '',
                searchText: '',
                sortBy: 'confidence_desc',
            },
        },
        explore: {
            papers: [],
            seenIds: {},
            nextCursor: 0,
            hasMore: true,
            isLoadingPage: false,
            error: '',
            pageRequestId: 0,
            profileSummary: null,
        },

        async init() {
            if (this.initialized) {
                return;
            }

            this.initialized = true;
            this.applyTheme(this.theme);
            if (this.requireAuthForCurrentRoute()) return;
            this.hydrateUser();

            if (this.isLoggedIn) {
                await this.refreshHistory();
            }

            window.addEventListener('popstate', () => {
                if (this.requireAuthForCurrentRoute()) return;
                this.syncFromLocation();
            });
            this.syncFromLocation();
        },

        // True iff the current route requires login. If it does and the user
        // is not logged in, redirect to /html/login.html?next=<path> and
        // return true (caller should bail out of further init).
        requireAuthForCurrentRoute() {
            const path = window.location.pathname || '/';
            const workspaceRoutes = window.ResearchAgent.routes;
            const needsAuth =
                path === workspaceRoutes.workspace ||
                path.startsWith(workspaceRoutes.workspace + '/') ||
                path === workspaceRoutes.search ||
                path === workspaceRoutes.explore;
            if (!needsAuth) return false;
            if (this.isLoggedIn) return false;
            const next = path + window.location.search;
            const safeNext = next.startsWith('/') && !next.startsWith('//') ? next : '/workspace';
            window.location.replace(`/html/login.html?next=${encodeURIComponent(safeNext)}`);
            return true;
        },

        hydrateUser() {
            const cachedName = localStorage.getItem('username') || '';
            if (cachedName) this.user.username = cachedName;
            if (!this.isLoggedIn) return;
            // Refresh from server in the background — corrects role/email drift.
            window.searchAPI?.fetchCurrentUser?.()
                .then((me) => {
                    if (!me || !me.username) return;
                    this.user.username = me.username;
                    this.user.email = me.email || '';
                    this.user.role = me.role || '';
                    this.user.authProvider = me.auth_provider || '';
                    localStorage.setItem('username', me.username);
                })
                .catch(() => { /* 401 is handled by the fetch interceptor */ });
        },

        async refreshHistory() {
            if (!this.isLoggedIn) return;
            try {
                const [searchHistory, chatHistory] = await Promise.all([
                    window.searchAPI.fetchSearchHistory(),
                    window.chatAPI.fetchChatHistory()
                ]);
                this.history = searchHistory.map(item => ({
                    ...item,
                    topic: item.topic || item.query || '',
                    summary: item.summary || `${item.result_count || item.results_count || 0} results`
                }));
                this.chatHistory = chatHistory;
                
                // Update current chat session if it's open
                if (this.currentView === 'chat' && this.currentChatSession) {
                    const updatedSession = this.chatHistory.find(s => s.session_id === this.currentChatSession.session_id);
                    if (updatedSession) {
                        this.currentChatSession = updatedSession;
                    }
                }
            } catch (err) {
                console.error("Failed to refresh history:", err);
            }
        },

        applyTheme(theme) {
            this.theme = theme === 'dark' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', this.theme);
            localStorage.setItem('theme', this.theme);
            window.dispatchEvent(new CustomEvent('theme:change', { detail: { theme: this.theme } }));
        },

        toggleTheme() {
            this.applyTheme(this.theme === 'dark' ? 'light' : 'dark');
        },

        openSidebar() {
            this.sidebarCollapsed = false;
            localStorage.setItem(window.ResearchAgent.sidebarStateKey, 'false');
        },

        closeSidebar() {
            this.sidebarCollapsed = true;
            localStorage.setItem(window.ResearchAgent.sidebarStateKey, 'true');
        },

        toggleSidebar() {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            localStorage.setItem(window.ResearchAgent.sidebarStateKey, String(this.sidebarCollapsed));
        },

        setMode(mode) {
            this.mode = mode === 'workspace' ? 'workspace' : 'landing';
            document.documentElement.setAttribute('data-route-mode', this.mode);
        },

        resetExplorer() {
            this.explorer = {
                selectedGapId: null,
                selectedPaperId: null,
                selectedClusterId: null,
                panelOpen: false,
                panelType: null,
                filters: {
                    minConfidence: 0,
                    maxConfidence: 1,
                    clusterId: '',
                    searchText: '',
                    sortBy: 'confidence_desc',
                },
            };
        },

        resetExplore() {
            this.explore = {
                papers: [],
                seenIds: {},
                nextCursor: 0,
                hasMore: true,
                isLoadingPage: false,
                error: '',
                pageRequestId: 0,
                profileSummary: null,
            };
        },

        resetExplorePapers() {
            this.explore.papers = [];
            this.explore.seenIds = {};
            this.explore.nextCursor = 0;
            this.explore.hasMore = true;
            this.explore.error = '';
        },

        async openExplore({ replace = false } = {}) {
            this.resetExplore();
            this.setMode('workspace');
            this.currentView = 'explore';
            this.error = '';

            this.goToPath(window.ResearchAgent.routes.explore, { replace });
            // exploreFeed component's init() handles profile load + first page
            return true;
        },

        openCitations({ replace = false } = {}) {
            this.setMode('workspace');
            this.currentView = 'citations';
            this.error = '';
            this.goToPath(window.ResearchAgent.routes.citations, { replace });
        },

        async loadMoreExplore() {
            // Delegates to the active exploreFeed Alpine component, which holds
            // the cold-start state and the seed-onboarding form.
            const root = document.getElementById('explore-view');
            if (!root) return false;
            const component = window.Alpine?.$data?.(root);
            if (component && typeof component.loadMore === 'function') {
                return await component.loadMore();
            }
            return false;
        },

        focusMainPrompt() {
            window.setTimeout(() => {
                document.getElementById('main-prompt')?.focus();
            }, 50);
        },

        goToPath(pathname, { search = '', replace = false } = {}) {
            const currentSearch = window.location.search || '';
            if (window.location.pathname === pathname && currentSearch === search) {
                return;
            }

            const method = replace ? 'replaceState' : 'pushState';
            window.history[method]({}, '', `${pathname}${search}`);
        },

        openLanding({ replace = false } = {}) {
            this.setMode('landing');
            this.currentView = 'form';
            this.goToPath(window.ResearchAgent.routes.landing, { replace });
        },

        signOut() {
            localStorage.removeItem('access_token');
            localStorage.removeItem('username');
            window.location.href = window.ResearchAgent.routes.landing;
        },

        openWorkspace({ replace = false, showForm = true } = {}) {
            this.setMode('workspace');
            if (showForm) {
                this.currentView = 'form';
            }
            this.goToPath(window.ResearchAgent.routes.workspace, { replace });
            if (showForm) {
                this.focusMainPrompt();
            }
        },

        buildSearchRoute(values) {
            const params = window.ResearchAgent.searchParamsFromValues(values);
            return {
                pathname: window.ResearchAgent.routes.search,
                search: `?${params.toString()}`,
            };
        },

        findHistoryMatch(values) {
            const targetKey = window.ResearchAgent.searchKey(values);
            return this.history.find((item) => window.ResearchAgent.searchKey(item) === targetKey) || null;
        },

        async useHistoryItem(item, { replace = false } = {}) {
            const values = window.ResearchAgent.normalizeSearchValues(item);
            this.form = window.ResearchAgent.cloneSearchValues(values);
            this.error = '';
            this.isLoading = true;
            this.progressEvents = [];
            this.resetExplorer();
            this.setMode('workspace');
            this.closeSidebar();

            try {
                let result = null;
                if (item.report_id) {
                    result = await window.searchAPI.fetchReport(item.report_id);
                } else if (item.result) {
                    result = window.ResearchAgent.coerceStoredResult(item.result);
                }

                if (!result) {
                    // If no result found in history, rerun the search
                    // Our server-side cache will instantly serve the result.
                    await this.runSearch(values, { replaceRoute: replace, pushRoute: true, saveHistory: false });
                    return;
                }

                this.result = { searchData: result, gapData: result };
                this.currentView = 'results';
                this.activeSearchKey = window.ResearchAgent.searchKey(values);
                
                const route = this.buildSearchRoute(values);
                this.goToPath(route.pathname, { search: route.search, replace });
            } catch (err) {
                console.error("Failed to load history item:", err);
                this.error = "Failed to load results. They may have been deleted.";
                // Rerun search as fallback
                await this.runSearch(values, { replaceRoute: replace });
            } finally {
                this.isLoading = false;
            }
        },

        persistHistory(values, result) {
            const normalized = window.ResearchAgent.normalizeSearchValues(values);
            const item = {
                id: `${Date.now()}`,
                topic: normalized.topic,
                year: normalized.year,
                venue: normalized.venue,
                strictVenue: normalized.strictVenue,
                maxResults: normalized.maxResults,
                summary: window.ResearchAgent.buildHistorySummary(normalized, result),
                // We no longer save the massive result payload to avoid QuotaExceededError
            };

            const key = window.ResearchAgent.searchKey(normalized);
            this.history = [item, ...this.history.filter((entry) => window.ResearchAgent.searchKey(entry) !== key)].slice(0, 8);
            window.ResearchAgent.saveSearchHistory(this.history);
        },

        async removeFromHistory(id) {
            try {
                await window.searchAPI.deleteSearchHistory(id);
                this.history = this.history.filter(item => item.id !== id);
            } catch (err) {
                this.error = "Failed to remove history item";
            }
        },

        async clearAllSearchHistory() {
            try {
                await window.searchAPI.clearSearchHistory();
                this.history = [];
                window.ResearchAgent.saveSearchHistory(this.history);
            } catch (err) {
                this.error = "Failed to clear search history";
            }
        },

        async removeFromChatHistory(sessionId) {
            try {
                await window.chatAPI.deleteChatSession(sessionId);
                this.chatHistory = this.chatHistory.filter(item => item.session_id !== sessionId);
            } catch (err) {
                this.error = "Failed to remove chat session";
            }
        },

        async clearAllChatHistory() {
            try {
                await window.chatAPI.clearChatHistory();
                this.chatHistory = [];
                if (this.currentChatSession && this.currentView === 'chat') {
                    this.startNewSearch();
                }
            } catch (err) {
                this.error = "Failed to clear chat history";
            }
        },

        exploreSuggestions() {
            return window.ResearchAgent.buildExploreSuggestions(this.history);
        },

        async runExploreSuggestion(item) {
            this.form = window.ResearchAgent.cloneSearchValues(item);
            await this.runSearch(this.form);
        },

        startNewSearch() {
            this.form = window.ResearchAgent.cloneSearchValues(window.ResearchAgent.defaults);
            this.result = null;
            this.error = '';
            this.activeSearchKey = '';
            this.resetExplorer();
            this.resetExplore();
            this.currentView = 'form';
            this.closeSidebar();
            if (window.innerWidth < 768) {
                this.sidebarCollapsed = true;
            }
            this.openWorkspace({ showForm: true });
        },

        openChat(chat) {
            this.currentChatSession = chat;
            this.currentView = 'chat';
            this.closeSidebar();
        },

        async sendChatMessage() {
            if (!this.chatInput.trim() || this.isLoading) return;
            
            const message = this.chatInput.trim();
            this.chatInput = '';
            this.isLoading = true;
            
            // Create a temporary session if none exists
            if (!this.currentChatSession) {
                this.currentChatSession = {
                    session_id: 'temp-' + Date.now(),
                    title: message.substring(0, 50) + '...',
                    messages: []
                };
            }
            
            // Optimistically add user message
            this.currentChatSession.messages.push({
                role: 'user',
                content: message,
                timestamp: new Date().toISOString()
            });

            try {
                // Mock AI response logic for now, as no LLM endpoint is specified
                // In a full implementation, this would call an LLM API endpoint first
                const aiResponse = `I received your message: "${message}". I am a research assistant ready to help you analyze papers. How can I assist you further?`;
                
                this.currentChatSession.messages.push({
                    role: 'assistant',
                    content: aiResponse,
                    timestamp: new Date().toISOString()
                });

                const payload = {
                    session_id: this.currentChatSession.session_id.startsWith('temp-') ? null : this.currentChatSession.session_id,
                    title: this.currentChatSession.title,
                    message: message,
                    response: aiResponse
                };

                const res = await window.chatAPI.saveChatMessage(payload);
                if (res.success && res.session_id) {
                    this.currentChatSession.session_id = res.session_id;
                }
                
                await this.refreshHistory();
            } catch (err) {
                console.error("Failed to send/save chat message:", err);
                this.error = "Failed to send message.";
            } finally {
                this.isLoading = false;
            }
        },

        async runSearch(values = this.form, options = {}) {
            const {
                pushRoute = true,
                replaceRoute = false,
                saveHistory = true,
                allowCached = false,
                regenerate = false,
            } = options;

            let normalized;
            try {
                normalized = window.ResearchAgent.validateSearchValues(values);
            } catch (error) {
                this.error = error.message || 'Search failed';
                this.currentView = 'form';
                return false;
            }

            if (allowCached) {
                const cached = this.findHistoryMatch(normalized);
                if (cached) {
                    this.useHistoryItem(cached, { replace: replaceRoute });
                    return true;
                }
            }

            this.form = window.ResearchAgent.cloneSearchValues(normalized);
            this.setMode('workspace');
            this.currentView = 'results';
            this.error = '';
            this.isLoading = true;
            this.progressEvents = [];
            this.resetExplorer();

            if (pushRoute) {
                const route = this.buildSearchRoute(normalized);
                this.goToPath(route.pathname, { search: route.search, replace: replaceRoute });
            }

            try {
                const paperPayload = window.searchAPI.buildSearchPayload(normalized);
                const gapPayload = {
                    ...paperPayload,
                    top_k_gaps: 5,
                    regenerate: regenerate,
                };

                const onProgress = (event) => {
                    if (event.type === 'progress') {
                        this.progressEvents = [...this.progressEvents, event].slice(-10);
                    }
                };
                const synthesisData = window.searchAPI.analyzeGapsStream
                    ? await window.searchAPI.analyzeGapsStream(gapPayload, onProgress)
                    : await window.searchAPI.analyzeGaps(gapPayload);

                const result = { searchData: synthesisData, gapData: synthesisData };
                this.result = result;
                this.resetExplorer();
                this.activeSearchKey = window.ResearchAgent.searchKey(normalized);

                if (saveHistory) {
                    await this.refreshHistory();
                }

                return true;
            } catch (error) {
                this.error = error.message || 'Search failed';
                if (!this.result) {
                    this.currentView = 'form';
                }
                return false;
            } finally {
                this.isLoading = false;
            }
        },

        async syncFromLocation() {
            const pathname = window.location.pathname;
            const searchParams = new URLSearchParams(window.location.search);

            if (pathname === window.ResearchAgent.routes.landing || pathname === '/index.html') {
                this.setMode('landing');
                this.currentView = 'form';
                return;
            }

            if (pathname === window.ResearchAgent.routes.workspace) {
                this.setMode('workspace');
                this.currentView = 'form';
                this.error = '';
                return;
            }

            if (pathname === window.ResearchAgent.routes.explore) {
                this.setMode('workspace');
                this.currentView = 'explore';
                this.error = '';
                this.resetExplore();
                // exploreFeed's init() handles profile + first page on view show
                return;
            }

            if (pathname === window.ResearchAgent.routes.citations) {
                this.setMode('workspace');
                this.currentView = 'citations';
                this.error = '';
                return;
            }

            if (pathname === window.ResearchAgent.routes.search) {
                const values = window.ResearchAgent.valuesFromSearchParams(searchParams);
                this.form = window.ResearchAgent.cloneSearchValues(values);
                this.setMode('workspace');
                this.currentView = 'results';

                if (!values.topic) {
                    this.currentView = 'form';
                    this.error = 'Topic is required';
                    return;
                }

                await this.runSearch(values, {
                    pushRoute: false,
                    replaceRoute: true,
                    saveHistory: false,
                    allowCached: true,
                });
                return;
            }

            if (pathname.startsWith(window.ResearchAgent.routes.share)) {
                const parts = pathname.split('/').filter(Boolean);
                const reportId = parts[parts.length - 1];
                if (reportId && reportId !== 'share') {
                    await this.loadSharedReport(reportId);
                    return;
                }
            }

            this.openLanding({ replace: true });
        },

        async loadSharedReport(reportId) {
            this.setMode('workspace');
            this.currentView = 'results';
            this.isLoading = true;
            this.error = '';

            try {
                const data = await window.searchAPI.fetchPublicReport(reportId);
                
                // SynthesisResponse from API
                const result = { searchData: data, gapData: data };
                this.result = result;
                this.resetExplorer();
                this.form.topic = data.topic || '';
                
                return true;
            } catch (error) {
                console.error('Failed to load shared report:', error);
                this.error = error.message || 'Failed to load report';
                this.currentView = 'form';
                return false;
            } finally {
                this.isLoading = false;
            }
        },
    });
});
