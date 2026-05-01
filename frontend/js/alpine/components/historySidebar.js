document.addEventListener('alpine:init', () => {
    Alpine.data('historySidebar', () => ({
        activeMenuId: null,
        open(item) {
            this.$store.app.useHistoryItem(item);
            this.activeMenuId = null;
        },
        toggleMenu(id) {
            this.activeMenuId = this.activeMenuId === id ? null : id;
        }
    }));
});
