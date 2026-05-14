window.exploreFeed = function exploreFeed() {
    return {
        seedDraft: ['', '', ''],
        savingSeeds: false,
        seedError: '',

        init() {
            const store = this.$store?.app;
            if (!store) return;
            if (store.currentView !== 'explore') {
                return;
            }
            this.refreshProfile();
        },

        async refreshProfile() {
            const store = this.$store.app;
            try {
                const data = await window.searchAPI.fetchExploreProfile();
                store.explore.profileSummary = data?.profile_summary || null;
                store.explore.coldStart = !!data?.is_cold_start;
                if (!store.explore.coldStart && !store.explore.papers.length) {
                    await this.loadMore();
                }
            } catch (error) {
                const code = error?.code || error?.detail?.error;
                if (code === 'cold_start_required' || error?.status === 409) {
                    store.explore.coldStart = true;
                    return;
                }
                store.explore.error = error?.message || 'Could not load explore profile';
            }
        },

        async saveSeeds() {
            const store = this.$store.app;
            const topics = this.seedDraft
                .map((value) => (typeof value === 'string' ? value.trim() : ''))
                .filter(Boolean);
            if (topics.length < 1) {
                this.seedError = 'Add at least one topic to get started';
                return;
            }
            this.seedError = '';
            this.savingSeeds = true;
            try {
                const data = await window.searchAPI.saveExploreSeeds(topics);
                store.explore.profileSummary = data?.profile_summary || null;
                store.explore.coldStart = false;
                store.resetExplorePapers();
                await this.loadMore();
            } catch (error) {
                this.seedError = error?.message || 'Could not save your topics';
            } finally {
                this.savingSeeds = false;
            }
        },

        async loadMore() {
            const store = this.$store.app;
            if (store.explore.isLoadingPage || !store.explore.hasMore || store.explore.coldStart) {
                return false;
            }

            const requestId = ++store.explore.pageRequestId;
            store.explore.isLoadingPage = true;
            store.explore.error = '';

            try {
                const data = await window.searchAPI.fetchExploreFeed({
                    cursor: store.explore.nextCursor,
                    pageSize: window.ResearchAgent.exploreDefaults.pageSize,
                });
                if (requestId !== store.explore.pageRequestId) {
                    return false;
                }

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
                return true;
            } catch (error) {
                const code = error?.code || error?.detail?.error;
                if (code === 'cold_start_required' || error?.status === 409) {
                    store.explore.coldStart = true;
                    store.explore.hasMore = false;
                    return false;
                }
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

        topTopicsList() {
            const summary = this.$store.app.explore.profileSummary;
            if (!summary || !Array.isArray(summary.top_topics)) return '';
            return summary.top_topics.slice(0, 3).join(' · ');
        },
    };
};
