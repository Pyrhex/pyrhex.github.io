const today = () => new Date().toISOString().slice(0, 10);
const basePath = (document.body && document.body.dataset.basePath) || '';

const normalizeUrl = (path) => {
    if (!path) return '';
    if (/^(https?:)?\/\//i.test(path)) {
        return path;
    }
    if (basePath && path.startsWith(basePath)) {
        return path;
    }
    if (path.startsWith('/')) {
        return `${basePath}${path}`;
    }
    const separator = basePath.endsWith('/') ? '' : '/';
    return `${basePath}${separator}${path}`;
};

function setDefaultDates() {
    document.querySelectorAll('input[type="date"]').forEach((input) => {
        if (!input.value) {
            input.value = today();
        }
    });
}

async function fetchJSON(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        credentials: 'same-origin',
        ...options,
    });
    const payload = await response.text();
    if (!response.ok) {
        throw new Error(payload || 'Request failed');
    }
    if (!payload) {
        return null;
    }
    try {
        return JSON.parse(payload);
    } catch (error) {
        throw new Error('Invalid server response');
    }
}

function renderRecords(records) {
    const body = document.getElementById('activity-body');
    body.innerHTML = '';
    if (!records.length) {
        body.innerHTML = '<tr><td colspan="6">No activity recorded.</td></tr>';
        return;
    }

    for (const record of records) {
        const row = document.createElement('tr');
        const signedAmount = Number(record.amount);
        const formattedAmount = `${signedAmount >= 0 ? '+' : '-'}$${Math.abs(signedAmount).toFixed(2)}`;
        row.innerHTML = `
            <td>${record.date}</td>
            <td>${record.type === 'payment' ? 'Payment' : 'Transaction'}</td>
            <td>${record.description || ''}</td>
            <td class="${signedAmount >= 0 ? 'positive' : 'negative'}">${formattedAmount}</td>
            <td>${record.payment_method}</td>
            <td>
                <button class="link-button delete-record" data-type="${record.type}" data-id="${record.id}">
                    Delete
                </button>
            </td>
        `;
        body.appendChild(row);
    }
}

async function loadLedger() {
    try {
        const data = await fetchJSON(normalizeUrl('/api/records'));
        renderRecords(data.records);
        document.getElementById('person-balance').textContent = `$${Number(data.balance).toFixed(2)}`;
    } catch (error) {
        alert(error.message);
    }
}

async function refreshSummary() {
    try {
        const { balance } = await fetchJSON(normalizeUrl('/api/summary'));
        const totalEl = document.getElementById('current-balance');
        if (totalEl) {
            totalEl.textContent = `$${Number(balance).toFixed(2)}`;
        }
    } catch (error) {
        console.error('Unable to refresh summary', error);
    }
}

function attachFormHandlers() {
    document.querySelectorAll('form[data-endpoint]').forEach((form) => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const endpoint = normalizeUrl(form.dataset.endpoint || '');
            const formData = new FormData(form);
            const payload = Object.fromEntries(formData.entries());
            const status = form.querySelector('.form-status');
            const submitButton = form.querySelector('button[type="submit"]');
            status.hidden = true;
            status.textContent = '';
            submitButton.disabled = true;
            try {
                await fetchJSON(endpoint, {
                    method: 'POST',
                    body: JSON.stringify(payload),
                });
                status.textContent = 'Saved!';
                status.className = 'form-status success';
                status.hidden = false;
                form.reset();
                setDefaultDates();
                refreshSummary();
                loadLedger();
            } catch (error) {
                status.textContent = error.message;
                status.className = 'form-status error';
                status.hidden = false;
            } finally {
                submitButton.disabled = false;
            }
        });
    });
}

function attachDeleteHandler() {
    const body = document.getElementById('activity-body');
    if (!body) return;
    body.addEventListener('click', async (event) => {
        const button = event.target.closest('.delete-record');
        if (!button) return;
        const recordType = button.dataset.type;
        const recordId = button.dataset.id;
        if (!recordType || !recordId) return;
        const confirmed = window.confirm('Delete this entry?');
        if (!confirmed) return;
        try {
            await fetchJSON(normalizeUrl(`/api/records/${recordType}/${recordId}`), {
                method: 'DELETE',
            });
            await loadLedger();
            await refreshSummary();
        } catch (error) {
            alert(error.message);
        }
    });
}

window.addEventListener('DOMContentLoaded', () => {
    setDefaultDates();
    attachFormHandlers();
    attachDeleteHandler();
    loadLedger();
    refreshSummary();
});
