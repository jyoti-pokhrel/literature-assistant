// Project, library, and gap-feedback API client.
// Companion to /js/search.js — uses the same BASE_URL and getHeaders helpers
// already defined in /js/api.js.

(function () {
    async function parseResponse(response, fallback) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = Array.isArray(data.detail)
                ? data.detail.map((item) => item.msg || item.message).join(", ")
                : data.detail || data.message || fallback;
            throw new Error(detail);
        }
        return data;
    }

    function paperKey(paper) {
        if (!paper) return "";
        const source = paper.source || "";
        const externalId = paper.external_id || "";
        if (!externalId) return "";
        return `${source}:${externalId}`;
    }

    // Projects ----------------------------------------------------------------

    async function listProjects({ includeArchived = false } = {}) {
        const url = `${BASE_URL}/projects${includeArchived ? "?include_archived=true" : ""}`;
        const response = await fetch(url, { headers: getHeaders() });
        return await parseResponse(response, "Failed to load projects");
    }

    async function createProject({ name, description = "" }) {
        const response = await fetch(`${BASE_URL}/projects`, {
            method: "POST",
            headers: getHeaders({ hasBody: true }),
            body: JSON.stringify({ name, description }),
        });
        return await parseResponse(response, "Failed to create project");
    }

    async function updateProject(projectId, patch) {
        const response = await fetch(`${BASE_URL}/projects/${projectId}`, {
            method: "PATCH",
            headers: getHeaders({ hasBody: true }),
            body: JSON.stringify(patch),
        });
        return await parseResponse(response, "Failed to update project");
    }

    async function archiveProject(projectId) {
        const response = await fetch(`${BASE_URL}/projects/${projectId}`, {
            method: "DELETE",
            headers: getHeaders(),
        });
        return await parseResponse(response, "Failed to archive project");
    }

    // Library -----------------------------------------------------------------

    async function listLibrary(projectId, { status = null, tag = null } = {}) {
        const params = new URLSearchParams();
        if (status) params.set("status_filter", status);
        if (tag) params.set("tag", tag);
        const qs = params.toString();
        const url = `${BASE_URL}/projects/${projectId}/library${qs ? `?${qs}` : ""}`;
        const response = await fetch(url, { headers: getHeaders() });
        return await parseResponse(response, "Failed to load library");
    }

    async function saveToLibrary(projectId, paper, { notes = "", status = "to_read", tags = [] } = {}) {
        if (!paper?.external_id) {
            throw new Error("Cannot save: paper has no external id");
        }
        const response = await fetch(`${BASE_URL}/projects/${projectId}/library`, {
            method: "POST",
            headers: getHeaders({ hasBody: true }),
            body: JSON.stringify({ paper, notes, status, tags }),
        });
        return await parseResponse(response, "Failed to save paper");
    }

    async function updateLibraryItem(projectId, paperKeyValue, patch) {
        const response = await fetch(
            `${BASE_URL}/projects/${projectId}/library/${encodeURIComponent(paperKeyValue)}`,
            {
                method: "PATCH",
                headers: getHeaders({ hasBody: true }),
                body: JSON.stringify(patch),
            },
        );
        return await parseResponse(response, "Failed to update library entry");
    }

    async function removeFromLibrary(projectId, paperKeyValue) {
        const response = await fetch(
            `${BASE_URL}/projects/${projectId}/library/${encodeURIComponent(paperKeyValue)}`,
            { method: "DELETE", headers: getHeaders() },
        );
        return await parseResponse(response, "Failed to remove paper");
    }

    // Gap feedback ------------------------------------------------------------

    async function submitGapFeedback(reportId, gapId, patch) {
        const response = await fetch(
            `${BASE_URL}/synthesis/report/${encodeURIComponent(reportId)}/gaps/${encodeURIComponent(gapId)}/feedback`,
            {
                method: "POST",
                headers: getHeaders({ hasBody: true }),
                body: JSON.stringify(patch),
            },
        );
        return await parseResponse(response, "Failed to save feedback");
    }

    window.projectsAPI = {
        paperKey,
        listProjects,
        createProject,
        updateProject,
        archiveProject,
        listLibrary,
        saveToLibrary,
        updateLibraryItem,
        removeFromLibrary,
        submitGapFeedback,
    };
})();
