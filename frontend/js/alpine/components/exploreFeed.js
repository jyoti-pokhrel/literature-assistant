window.exploreFeed = function exploreFeed() {
    return {
        diagnostics: null,

        init() {
            const store = this.$store?.app;
            if (!store) return;
            if (store.currentView !== 'explore') return;
            this.refreshProfile();
            // Always try to load a first page on view show.
            this.loadMore();
        },

        async refreshProfile() {
            const store = this.$store.app;
            try {
                const data = await window.searchAPI.fetchExploreProfile();
                store.explore.profileSummary = data?.profile_summary || null;
            } catch (error) {
                store.explore.error = error?.message || 'Could not load explore profile';
            }
        },

        async loadMore() {
            const store = this.$store.app;
            if (store.explore.isLoadingPage || !store.explore.hasMore) return false;

            const requestId = ++store.explore.pageRequestId;
            store.explore.isLoadingPage = true;
            store.explore.error = '';

            const recentTopics = (store.history || [])
                .map((entry) => entry?.topic || entry?.query || "")
                .filter(Boolean);

            try {
                const data = await window.searchAPI.fetchExploreFeed({
                    cursor: store.explore.nextCursor,
                    pageSize: window.ResearchAgent.exploreDefaults.pageSize,
                    recentTopics,
                });
                if (requestId !== store.explore.pageRequestId) return false;

                const incoming = Array.isArray(data?.papers) ? data.papers : [];
                const seen = store.explore.seenIds;
                const newPapers = [];
                for (const paper of incoming) {
                    const key = paper.external_id || paper.url || paper.title;
                    if (!key || seen[key]) continue;
                    seen[key] = true;
                    newPapers.push(paper);
                }

                store.explore.papers = [...store.explore.papers, ...newPapers];
                store.explore.nextCursor = Number.isFinite(data?.next_cursor)
                    ? data.next_cursor
                    : store.explore.nextCursor;
                store.explore.hasMore = data?.has_more === true;
                if (data?.profile_summary) {
                    store.explore.profileSummary = data.profile_summary;
                }
                if (
                    store.explore.papers.length === 0 &&
                    data?.has_more !== true &&
                    !this.diagnostics
                ) {
                    await this.loadDiagnostics();
                }
                return true;
            } catch (error) {
                if (requestId === store.explore.pageRequestId) {
                    store.explore.error = error?.message || 'Could not load more recommendations';
                }
                return false;
            } finally {
                if (requestId === store.explore.pageRequestId) {
                    store.explore.isLoadingPage = false;
                }
            }
        },

        async loadDiagnostics() {
            try {
                this.diagnostics = await window.searchAPI.fetchExploreDiagnostics();
            } catch (e) {
                this.diagnostics = { notes: ['Diagnostics endpoint failed: ' + (e?.message || e)] };
            }
        },

        async recordInteraction(paper, kind) {
            if (!paper?.external_id || !kind) return;
            const store = this.$store.app;
            try {
                await window.searchAPI.recordExploreInteractions([
                    { external_id: paper.external_id, kind },
                ]);
            } catch (e) {
                // Best-effort - UI continues even on failure.
            }
            if (kind === 'hide' || kind === 'dislike') {
                store.explore.papers = store.explore.papers.filter(
                    (p) => p.external_id !== paper.external_id
                );
            }
            if (kind === 'open' && paper.url) {
                window.open(paper.url, '_blank', 'noopener,noreferrer');
            }
        },

        topTopicsList() {
            const summary = this.$store.app.explore.profileSummary;
            if (!summary || !Array.isArray(summary.top_topics)) return '';
            return summary.top_topics.slice(0, 3).join(' · ');
        },
    };
};
