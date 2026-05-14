document.addEventListener('alpine:init', () => {
    Alpine.data('historySidebar', () => ({
        open(item) {
            this.$store.app.useHistoryItem(item);
        },
        openChat(chat) {
            this.$store.app.openChat(chat);
        },
    }));
});
