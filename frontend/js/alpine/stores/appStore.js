window.ResearchAgent = window.ResearchAgent || {};

window.ResearchAgent.routes = {
    landing: '/',
    workspace: '/workspace',
    search: '/workspace/search',
    explore: '/workspace/explore',
    share: '/synthesis/share',
};

window.ResearchAgent.exploreDefaults = Object.freeze({
    pageSize: 20,
});

window.ResearchAgent.buildExploreSeed = function buildExploreSeed(values = {}) {
    const normalized = window.ResearchAgent.normalizeSearchValues(values);
    return {
        topic: normalized.topic,
        year: normalized.year,
        venue: normalized.venue,
        strictVenue: normalized.strictVenue,
    };
};

window.ResearchAgent.exploreParamsFromSeed = function exploreParamsFromSeed(seed = {}) {
    const params = new URLSearchParams();
    if (seed.topic) params.set('topic', seed.topic);
    if (seed.year) params.set('year', seed.year);
    if (seed.venue) params.set('venue', seed.venue);
    if (seed.venue && seed.strictVenue) params.set('strictVenue', 'true');
    return params;
};

window.ResearchAgent.exploreSeedFromParams = function exploreSeedFromParams(searchParams) {
    return window.ResearchAgent.buildExploreSeed({
        topic: searchParams.get('topic') || '',
        year: searchParams.get('year') || '',
        venue: searchParams.get('venue') || '',
        strictVenue: searchParams.get('strictVenue') === 'true',
    });
};

window.ResearchAgent.defaults = Object.freeze({
    topic: '',
    year: '',
    venue: '',
    strictVenue: false,
    maxResults: 10,
});

window.ResearchAgent.searchHistoryKey = 'research-agent-search-history-v2';
window.ResearchAgent.sidebarStateKey = 'research-agent-sidebar-collapsed-v2';

window.ResearchAgent.cloneSearchValues = function cloneSearchValues(values = {}) {
    const maxResults = Number.parseInt(values.maxResults, 10);
    return {
        topic: typeof values.topic === 'string' ? values.topic : '',
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
        const normalized = window.ResearchAgent.normalizeSearchValues({ topic, maxResults: 10 });
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
        mode: 'landing',
        currentView: 'form',
        theme: localStorage.getItem('theme') || 'light',
        sidebarCollapsed: storedSidebarState === null ? false : storedSidebarState === 'true',
        techPanelOpen: false,
        isLoading: false,
        error: '',
        progressEvents: [],
        form: window.ResearchAgent.cloneSearchValues(window.ResearchAgent.defaults),
        history: window.ResearchAgent.loadSearchHistory(),
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
            seed: { topic: '', year: '', venue: '', strictVenue: false },
            papers: [],
            seenIds: {},
            nextCursor: 0,
            hasMore: true,
            isLoadingPage: false,
            error: '',
            pageRequestId: 0,
        },

        init() {
            if (this.initialized) {
                return;
            }

            this.initialized = true;
            this.applyTheme(this.theme);
            window.addEventListener('popstate', () => {
                this.syncFromLocation();
            });
            this.syncFromLocation();
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
                seed: { topic: '', year: '', venue: '', strictVenue: false },
                papers: [],
                seenIds: {},
                nextCursor: 0,
                hasMore: true,
                isLoadingPage: false,
                error: '',
                pageRequestId: 0,
            };
        },

        buildExploreRoute(seed) {
            const params = window.ResearchAgent.exploreParamsFromSeed(seed);
            const search = params.toString();
            return {
                pathname: window.ResearchAgent.routes.explore,
                search: search ? `?${search}` : '',
            };
        },

        async openExplore({ replace = false, fromForm = false } = {}) {
            const sourceValues = fromForm ? this.form : {};
            const seed = window.ResearchAgent.buildExploreSeed(sourceValues);

            this.resetExplore();
            this.explore.seed = seed;

            this.setMode('workspace');
            this.currentView = 'explore';
            this.error = '';
            this.closeSidebar();

            const route = this.buildExploreRoute(seed);
            this.goToPath(route.pathname, { search: route.search, replace });

            return await this.loadMoreExplore();
        },

        async loadMoreExplore() {
            if (this.explore.isLoadingPage || !this.explore.hasMore) {
                return false;
            }
            const seed = this.explore.seed || {};

            const requestId = ++this.explore.pageRequestId;
            this.explore.isLoadingPage = true;
            this.explore.error = '';

            try {
                const payload = window.searchAPI.buildExplorePayload({
                    topic: seed.topic,
                    year: seed.year,
                    venue: seed.venue,
                    strictVenue: seed.strictVenue,
                    cursor: this.explore.nextCursor,
                    pageSize: window.ResearchAgent.exploreDefaults.pageSize,
                });
                const data = await window.searchAPI.exploreArxiv(payload);
                if (requestId !== this.explore.pageRequestId) {
                    return false;
                }

                const incoming = Array.isArray(data?.papers) ? data.papers : [];
                const seen = this.explore.seenIds;
                const newPapers = [];
                for (const paper of incoming) {
                    const key = paper.external_id || paper.url || paper.title;
                    if (!key || seen[key]) continue;
                    seen[key] = true;
                    newPapers.push(paper);
                }

                this.explore.papers = [...this.explore.papers, ...newPapers];
                this.explore.nextCursor = Number.isFinite(data?.next_cursor)
                    ? data.next_cursor
                    : this.explore.nextCursor;
                this.explore.hasMore = data?.has_more === true;
                return true;
            } catch (error) {
                if (requestId === this.explore.pageRequestId) {
                    this.explore.error = error?.message || 'Could not load more papers';
                }
                return false;
            } finally {
                if (requestId === this.explore.pageRequestId) {
                    this.explore.isLoadingPage = false;
                }
            }
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

        logout() {
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
            // Run a new search instead of pulling from localStorage. 
            // Our server-side cache will instantly serve the result.
            await this.runSearch(values, { replaceRoute: replace, pushRoute: true, saveHistory: false });
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

        removeFromHistory(id) {
            this.history = this.history.filter(item => item.id !== id);
            window.ResearchAgent.saveSearchHistory(this.history);
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
            this.error = '';
            this.isLoading = false;
            this.progressEvents = [];
            this.result = null;
            this.activeSearchKey = '';
            this.resetExplorer();
            this.resetExplore();
            this.closeSidebar();
            this.openWorkspace({ showForm: true });
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
            this.closeSidebar();

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
                    this.persistHistory(normalized, result);
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
                const seed = window.ResearchAgent.exploreSeedFromParams(searchParams);

                if (seed.topic) {
                    this.form = window.ResearchAgent.cloneSearchValues({
                        ...this.form,
                        topic: seed.topic,
                        year: seed.year,
                        venue: seed.venue,
                        strictVenue: seed.strictVenue,
                    });
                }
                this.setMode('workspace');
                this.currentView = 'explore';
                this.error = '';
                this.resetExplore();
                this.explore.seed = seed;
                await this.loadMoreExplore();
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
            this.closeSidebar();

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
