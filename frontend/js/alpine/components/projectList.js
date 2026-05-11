function projectList() {
    return {
        nameInput: '',
        descriptionInput: '',
        creating: false,
        createError: '',

        async init() {
            await this.$store.app.loadProjects();
        },

        async create() {
            const name = (this.nameInput || '').trim();
            if (!name) {
                this.createError = 'Project needs a name';
                return;
            }
            this.creating = true;
            this.createError = '';
            try {
                await this.$store.app.createProject({
                    name,
                    description: (this.descriptionInput || '').trim(),
                });
                this.nameInput = '';
                this.descriptionInput = '';
                // Drop into the omnibar with the new project active.
                this.$store.app.currentView = 'form';
                this.$store.app.focusMainPrompt();
            } catch (error) {
                this.createError = error?.message || 'Could not create project';
            } finally {
                this.creating = false;
            }
        },

        async open(project) {
            this.$store.app.selectProject(project.id);
            this.$store.app.currentView = 'form';
            this.$store.app.focusMainPrompt();
        },

        async archive(project) {
            if (!confirm(`Archive "${project.name}"? Its data is kept; it just disappears from this list.`)) {
                return;
            }
            try {
                await this.$store.app.archiveProject(project.id);
            } catch (error) {
                alert(error?.message || 'Could not archive project');
            }
        },

        formatDate(value) {
            if (!value) return '';
            const d = new Date(value);
            if (Number.isNaN(d.getTime())) return '';
            return d.toLocaleDateString();
        },
    };
}
