const BASE_URL = (() => {
    const configuredBase =
        window.__RA_API_BASE_URL__
        || document.querySelector('meta[name="ra-api-base"]')?.content?.trim();

    if (configuredBase) {
        return configuredBase.replace(/\/+$/, "");
    }

    const currentOrigin = window.location?.origin;
    
    if (currentOrigin && /^https?:/.test(currentOrigin)) {
        return currentOrigin;
    }

    return "";
})();

function getHeaders({ hasBody = false, includeAuth = true } = {}) {
    const token = localStorage.getItem("token");
    const headers = {};

    if (hasBody) {
        headers["Content-Type"] = "application/json";
    }

    if (includeAuth && token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    return headers;
}

async function authenticatedFetch(url, options = {}) {
    options.headers = {
        ...options.headers,
        ...getHeaders({ hasBody: !!options.body })
    };
    return await fetch(url, options);
}

async function signup(username, email, password, role) {
    const response = await fetch(`${BASE_URL}/signup`, {
        method: "POST",
        headers: getHeaders({ hasBody: true, includeAuth: false }),
        body: JSON.stringify({ username, email, password, role })
    })
    return await response.json()
}

async function login(username, password) {
    const response = await fetch(`${BASE_URL}/login`, {
        method: "POST",
        headers: {
            "Content-Type": "application/x-www-form-urlencoded"
        },
        body: `username=${username}&password=${password}`
    })
    const data = await response.json()
    if (data.access_token) {
        localStorage.setItem("token", data.access_token)
    }
    return data
}

function logout() {
    localStorage.removeItem("token")
    window.location.href = window.location.protocol.startsWith("http") ? "/" : "index.html"
}

function isLoggedIn() {
    return localStorage.getItem("token") !== null
}

async function fetchPapers() {
    const response = await fetch(`${BASE_URL}/papers`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchPaper(paper_id) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function addPaper(paperData) {
    const response = await fetch(`${BASE_URL}/papers`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(paperData)
    })
    return await response.json()
}

async function updatePaper(paper_id, paperData) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "PUT",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(paperData)
    })
    return await response.json()
}

async function deletePaper(paper_id) {
    const response = await fetch(`${BASE_URL}/papers/${paper_id}`, {
        method: "DELETE",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchReports() {
    const response = await fetch(`${BASE_URL}/reports`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function fetchReport(report_id) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "GET",
        headers: getHeaders()
    })
    return await response.json()
}

async function addReport(reportData) {
    const response = await fetch(`${BASE_URL}/reports`, {
        method: "POST",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(reportData)
    })
    return await response.json()
}

async function updateReport(report_id, reportData) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "PUT",
        headers: getHeaders({ hasBody: true }),
        body: JSON.stringify(reportData)
    })
    return await response.json()
}

async function deleteReport(report_id) {
    const response = await fetch(`${BASE_URL}/reports/${report_id}`, {
        method: "DELETE",
        headers: getHeaders()
    })
    return await response.json()
}