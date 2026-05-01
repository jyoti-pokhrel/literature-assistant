async function parseResponse(response, fallbackMessage) {
    const data = await response.json();

    if (!response.ok) {
        const detail = Array.isArray(data.detail)
            ? data.detail.map((item) => item.msg || item.message).join(", ")
            : data.detail || data.message || fallbackMessage;
        throw new Error(detail);
    }

    return data;
}

async function searchPapers(payload) {
    const response = await fetch(`${BASE_URL}/search/papers`, {
        method: "POST",
        headers: getHeaders({ hasBody: true, includeAuth: false }),
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Search failed");
}

async function analyzeGaps(payload) {
    const response = await fetch(`${BASE_URL}/synthesis/gaps`, {
        method: "POST",
        headers: getHeaders({ hasBody: true, includeAuth: false }),
        body: JSON.stringify(payload),
    });

    return await parseResponse(response, "Synthesis failed");
}

async function fetchPublicReport(report_id) {
    const response = await fetch(`${BASE_URL}/synthesis/public/report/${report_id}`, {
        method: "GET",
        headers: getHeaders({ includeAuth: false }),
    });

    return await parseResponse(response, "Failed to load shared report");
}

function buildSearchPayload({ topic, year, venue, maxResults }) {
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
        chips.push(`Venue: ${filters.venue}`);
    }

    return chips;
}

function sourceLabel(source) {
    return source
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

window.searchAPI = {
    searchPapers,
    analyzeGaps,
    fetchPublicReport,
    buildSearchPayload,
    formatFilters,
    sourceLabel,
};
