function libraryPage() {
    return {
        statusFilter: '',
        tagFilter: '',
        noteDrafts: {}, // { paper_key: text }
        savePendingFor: null,
        saveTimers: {}, // debounce timers per paper_key

        async init() {
            await this.$store.app.loadLibrary();
            this.syncDrafts();
            // Re-sync drafts when the library list changes (e.g. after adds).
            this.$watch('$store.app.library.length', () => this.syncDrafts());
        },

        syncDrafts() {
            const drafts = {};
            for (const item of this.$store.app.library) {
                drafts[item.paper_key] = item.notes || '';
            }
            this.noteDrafts = drafts;
        },

        async refresh() {
            await this.$store.app.loadLibrary({
                status: this.statusFilter || null,
                tag: this.tagFilter || null,
            });
            this.syncDrafts();
        },

        items() {
            const status = this.statusFilter;
            const tag = (this.tagFilter || '').trim().toLowerCase();
            return this.$store.app.library.filter((it) => {
                if (status && it.status !== status) return false;
                if (tag && !(it.tags || []).some((t) => t.toLowerCase().includes(tag))) {
                    return false;
                }
                return true;
            });
        },

        onNoteInput(paperKey) {
            // debounce 600ms per paper
            if (this.saveTimers[paperKey]) {
                clearTimeout(this.saveTimers[paperKey]);
            }
            this.saveTimers[paperKey] = setTimeout(async () => {
                this.savePendingFor = paperKey;
                try {
                    await this.$store.app.updateLibraryNotes(paperKey, this.noteDrafts[paperKey] || '');
                } catch (error) {
                    console.error('note save failed', error);
                } finally {
                    if (this.savePendingFor === paperKey) {
                        this.savePendingFor = null;
                    }
                }
            }, 600);
        },

        async remove(item) {
            if (!confirm(`Remove "${item.paper?.title || 'this paper'}" from the library?`)) {
                return;
            }
            try {
                await this.$store.app.removeFromCurrentProject(item.paper_key);
                delete this.noteDrafts[item.paper_key];
            } catch (error) {
                alert(error?.message || 'Could not remove paper');
            }
        },

        sourceLabel(item) {
            return item.paper?.source || item.source || '';
        },

        sourceUrl(item) {
            return item.paper?.url || item.paper?.pdf_url || '#';
        },
    };
}
