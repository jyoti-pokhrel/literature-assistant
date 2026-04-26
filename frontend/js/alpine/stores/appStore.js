window.ResearchAgent = window.ResearchAgent || {};

window.ResearchAgent.routes = {
    landing: '/',
    workspace: '/workspace',
    search: '/workspace/search',
};

window.ResearchAgent.defaults = Object.freeze({
    topic: '',
    year: '',
    venue: '',
    maxResults: 10,
});

window.ResearchAgent.searchHistoryKey = 'research-agent-search-history-v2';
window.ResearchAgent.sidebarStateKey = 'research-agent-sidebar-collapsed-v1';

window.ResearchAgent.cloneSearchValues = function cloneSearchValues(values = {}) {
    const maxResults = Number.parseInt(values.maxResults, 10);
    return {
        topic: typeof values.topic === 'string' ? values.topic : '',
        year: typeof values.year === 'string' ? values.year : '',
        venue: typeof values.venue === 'string' ? values.venue : '',
        maxResults: Number.isFinite(maxResults) ? maxResults : window.ResearchAgent.defaults.maxResults,
    };
};

window.ResearchAgent.normalizeSearchValues = function normalizeSearchValues(values = {}) {
    const normalized = window.ResearchAgent.cloneSearchValues(values);
    normalized.topic = normalized.topic.trim();
    normalized.year = normalized.year.trim().replace(/\s*-\s*/g, '-');
    normalized.venue = normalized.venue.trim();

    if (!Number.isFinite(normalized.maxResults)) {
        normalized.maxResults = window.ResearchAgent.defaults.maxResults;
    }
    normalized.maxResults = Math.min(Math.max(normalized.maxResults, 1), 20);

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
        maxResults: searchParams.get('maxResults') || window.ResearchAgent.defaults.maxResults,
    });
};

window.ResearchAgent.searchParamsFromValues = function searchParamsFromValues(values = {}) {
    const normalized = window.ResearchAgent.normalizeSearchValues(values);
    const params = new URLSearchParams();

    if (normalized.topic) params.set('topic', normalized.topic);
    if (normalized.year) params.set('year', normalized.year);
    if (normalized.venue) params.set('venue', normalized.venue);
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

    if (normalized.maxResults < 1 || normalized.maxResults > 20) {
        throw new Error('Max results must be between 1 and 20');
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
                const result = window.ResearchAgent.coerceStoredResult(item?.result);
                if (!item || !result) {
                    return null;
                }

                const values = window.ResearchAgent.normalizeSearchValues({
                    topic: item.topic,
                    year: item.year,
                    venue: item.venue,
                    maxResults: item.maxResults,
                });

                return {
                    id: item.id || `${Date.now()}`,
                    topic: values.topic,
                    year: values.year,
                    venue: values.venue,
                    maxResults: values.maxResults,
                    summary: item.summary || window.ResearchAgent.buildHistorySummary(values, result),
                    result,
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

document.addEventListener('alpine:init', () => {
    const storedSidebarState = localStorage.getItem(window.ResearchAgent.sidebarStateKey);
    Alpine.store('app', {
        initialized: false,
        mode: 'landing',
        currentView: 'form',
        theme: localStorage.getItem('theme') || 'dark',
        sidebarCollapsed: storedSidebarState === null ? window.innerWidth <= 768 : storedSidebarState === 'true',
        isLoading: false,
        error: '',
        form: window.ResearchAgent.cloneSearchValues(window.ResearchAgent.defaults),
        history: window.ResearchAgent.loadSearchHistory(),
        result: null,
        activeSearchKey: '',

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
            this.theme = theme === 'light' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', this.theme);
            localStorage.setItem('theme', this.theme);
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

        useHistoryItem(item, { replace = false } = {}) {
            const values = window.ResearchAgent.normalizeSearchValues(item);
            const result = window.ResearchAgent.coerceStoredResult(item.result);
            if (!result) {
                return;
            }

            this.form = window.ResearchAgent.cloneSearchValues(values);
            this.result = result;
            this.error = '';
            this.isLoading = false;
            this.currentView = 'results';
            this.activeSearchKey = window.ResearchAgent.searchKey(values);
            this.setMode('workspace');
            this.closeSidebar();

            const route = this.buildSearchRoute(values);
            this.goToPath(route.pathname, { search: route.search, replace });
        },

        persistHistory(values, result) {
            const normalized = window.ResearchAgent.normalizeSearchValues(values);
            const item = {
                id: `${Date.now()}`,
                topic: normalized.topic,
                year: normalized.year,
                venue: normalized.venue,
                maxResults: normalized.maxResults,
                summary: window.ResearchAgent.buildHistorySummary(normalized, result),
                result,
            };

            const key = window.ResearchAgent.searchKey(normalized);
            this.history = [item, ...this.history.filter((entry) => window.ResearchAgent.searchKey(entry) !== key)].slice(0, 8);
            window.ResearchAgent.saveSearchHistory(this.history);
        },

        startNewSearch() {
            this.form = window.ResearchAgent.cloneSearchValues(window.ResearchAgent.defaults);
            this.error = '';
            this.isLoading = false;
            this.result = null;
            this.activeSearchKey = '';
            this.closeSidebar();
            this.openWorkspace({ showForm: true });
        },

        async runSearch(values = this.form, options = {}) {
            const {
                pushRoute = true,
                replaceRoute = false,
                saveHistory = true,
                allowCached = false,
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
                };

                const [searchData, gapData] = await Promise.all([
                    window.searchAPI.searchPapers(paperPayload),
                    window.searchAPI.analyzeGaps(gapPayload),
                ]);

                const result = { searchData, gapData };
                this.result = result;
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

            this.openLanding({ replace: true });
        },
    });
});
