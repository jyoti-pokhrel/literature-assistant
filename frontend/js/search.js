async function parseResponse(response, fallbackMessage) {
    const data = await response.json();

    if (!response.ok) {
        const detail = data.detail;
        let message = fallbackMessage;
        let code = null;
        if (Array.isArray(detail)) {
            message = detail.map((item) => item.msg || item.message).join(", ");
        } else if (detail && typeof detail === 'object') {
            code = detail.error || null;
            message = detail.message || code || fallbackMessage;
        } else if (typeof detail === 'string') {
            message = detail;
        } else if (data.message) {
            message = data.message;
        }
        const error = new Error(message);
        error.status = response.status;
        error.code = code;
        error.detail = detail;
        throw error;
    }

    return data;
}

async function searchPapers(payload) {
    const response = await authenticatedFetch(`${BASE_URL}/search/papers`, {
        method: "POST",
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Search failed");
}

async function analyzeGaps(payload) {
    const response = await authenticatedFetch(`${BASE_URL}/synthesis/gaps`, {
        method: "POST",
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Synthesis failed");
}

async function analyzeGapsStream(payload, onEvent) {
    const response = await authenticatedFetch(`${BASE_URL}/synthesis/gaps/stream`, {
        method: "POST",
        body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
        return await parseResponse(response, "Synthesis failed");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResult = null;

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
            if (!line.trim()) continue;
            const event = JSON.parse(line);
            if (event.type === "error") {
                throw new Error(event.detail || "Synthesis failed");
            }
            if (event.type === "result") {
                finalResult = event.data;
            }
            if (typeof onEvent === "function") {
                onEvent(event);
            }
        }
    }

    if (buffer.trim()) {
        const event = JSON.parse(buffer);
        if (event.type === "error") {
            throw new Error(event.detail || "Synthesis failed");
        }
        if (event.type === "result") {
            finalResult = event.data;
        }
        if (typeof onEvent === "function") {
            onEvent(event);
        }
    }

    if (!finalResult) {
        throw new Error("Synthesis finished without a result");
    }
    return finalResult;
}

async function fetchExploreFeed({ cursor = 0, pageSize = 20 } = {}) {
    const payload = {
        cursor: Math.max(0, Number.parseInt(cursor, 10) || 0),
        page_size: Math.min(50, Math.max(1, Number.parseInt(pageSize, 10) || 20)),
    };
    const response = await authenticatedFetch(`${BASE_URL}/explore/feed`, {
        method: "POST",
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Could not load recommendations");
}

async function saveExploreSeeds(topics) {
    const payload = { topics: (topics || []).slice(0, 3) };
    const response = await authenticatedFetch(`${BASE_URL}/explore/seed`, {
        method: "POST",
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Could not save your topics");
}

async function fetchExploreProfile() {
    const response = await authenticatedFetch(`${BASE_URL}/explore/profile`, {
        method: "GET",
    });

    return await parseResponse(response, "Could not load explore profile");
}

async function fetchExploreDiagnostics() {
    const response = await authenticatedFetch(`${BASE_URL}/explore/diagnostics`, {
        method: "GET",
    });
    return await parseResponse(response, "Could not load explore diagnostics");
}

async function fetchPublicReport(report_id) {
    const response = await fetch(`${BASE_URL}/synthesis/public/report/${report_id}`, {
        method: "GET",
        headers: getHeaders({ includeAuth: false }),
    });

    return await parseResponse(response, "Failed to load shared report");
}

function buildSearchPayload({ topic, year, venue, strictVenue, maxResults }) {
    const payload = {
        topic: topic.trim(),
        max_results: maxResults,
    };

    const normalizedYear = typeof year === 'string' ? year.trim() : '';
    if (normalizedYear) {
        payload.year = normalizedYear.replace(/\s*-\s*/g, '-');
    }

    if (venue && venue.trim()) {
        payload.venue = venue.trim();
        payload.strict_venue = strictVenue === true;
    }

    return payload;
}

function formatFilters(filters) {
    const chips = [];

    if (filters.year) {
        const label = String(filters.year).includes('-') ? 'Year range' : 'Year';
        chips.push(`${label}: ${filters.year}`);
    }

    if (filters.venue) {
        const label = filters.strict_venue ? 'Venue (strict)' : 'Venue';
        chips.push(`${label}: ${filters.venue}`);
    }

    return chips;
}

function sourceLabel(source) {
    return source
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

async function fetchCurrentUser() {
    const response = await authenticatedFetch(`${BASE_URL}/users/me`);
    if (response.status === 401) return null;
    return await parseResponse(response, "Could not load profile");
}

window.searchAPI = {
    searchPapers,
    analyzeGaps,
    analyzeGapsStream,
    fetchExploreFeed,
    saveExploreSeeds,
    fetchExploreProfile,
    fetchExploreDiagnostics,
    fetchPublicReport,
    buildSearchPayload,
    formatFilters,
    sourceLabel,
    authenticatedFetch,
    fetchCurrentUser,
};
