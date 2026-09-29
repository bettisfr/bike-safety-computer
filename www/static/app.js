const cards = new Map();
const cardContainer = document.querySelector('#ant-cards');

let last = null;
let lastAt = 0;
let online = false;

function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
}

function createCard(device) {
    const card = element('section', 'sensor');
    const heading = element('div', 'sensor-head');
    const title = element('h3', '', device.name);
    const metrics = element('span', 'metrics');
    const signal = element('div', 'signal');
    const status = element('div', 'status', 'Waiting…');
    const table = element('table', 'fields');
    const error = element('div', 'error');

    heading.append(title, metrics);
    card.append(heading, status, signal, table, error);
    return {
        card, title, metrics, signal, status, table, error,
        kind: device.kind,
        visibleFields: device.visible_fields,
        rows: new Map(),
    };
}

function syncCards(devices) {
    const visible = new Set();

    devices.forEach((device, index) => {
        visible.add(device.key);
        let card = cards.get(device.key);
        if (!card) {
            card = createCard(device);
            cards.set(device.key, card);
        }
        card.kind = device.kind;
        card.visibleFields = device.visible_fields;
        card.title.textContent = device.name;

        if (cardContainer.children[index] !== card.card) {
            cardContainer.insertBefore(card.card, cardContainer.children[index] || null);
        }
    });

    for (const [key, card] of cards) {
        if (!visible.has(key)) {
            card.card.remove();
            cards.delete(key);
        }
    }
}

function renderSection(card, section, elapsed, active) {
    if (!section) return;

    card.status.textContent = section.status || 'Waiting…';
    card.error.textContent = section.error || '';
    card.signal.textContent = section.packet_age_s == null
        ? ''
        : `Updated ${Math.floor(section.packet_age_s + elapsed)} s ago`;

    const fields = (section.fields || [])
        .filter(field => card.visibleFields.includes(field.label))
        .sort((a, b) => card.visibleFields.indexOf(a.label) - card.visibleFields.indexOf(b.label));
    const labels = new Set(fields.map(field => field.label));

    for (const [label, row] of card.rows) {
        if (!labels.has(label)) {
            row.value.parentElement.remove();
            card.rows.delete(label);
        }
    }

    for (const field of fields) {
        let row = card.rows.get(field.label);
        if (!row) {
            const tableRow = element('tr');
            const label = element('td', '', field.label);
            const value = element('td');
            const age = element('td');
            tableRow.append(label, value, age);
            row = { value, age };
            card.rows.set(field.label, row);
        }
        row.value.textContent = field.value;
        row.value.className = field.changed && active && elapsed < 2 ? 'changed' : '';
        row.age.textContent = field.age_s == null
            ? '—'
            : `${field.saved ? 'saved · ' : ''}${Math.floor(field.age_s + elapsed)} s`;
        card.table.append(row.value.parentElement);
    }

    card.card.classList.toggle(
        'stale', !active || (section.packet_age_s != null && section.packet_age_s + elapsed > 10),
    );
}

function formatNumber(value) {
    return value == null ? '—' : value.toFixed(1);
}

function renderMetric(card, section, elapsed, active) {
    if (card.kind === 'heart_rate') {
        const rate = section?.fields?.find(field => field.label === 'Heart rate');
        const value = active && section?.status === 'connected' && rate && rate.age_s + elapsed < 10
            ? rate.value.replace(/\s*bpm$/, '')
            : '—';
        card.metrics.textContent = `${value} bpm`;
    } else if (card.kind === 'speed_cadence') {
        const speed = active ? formatNumber(section?.speed_kmh) : '—';
        const cadence = active ? formatNumber(section?.cadence_rpm) : '—';
        card.metrics.textContent = `${speed}\u00a0km/h · ${cadence}\u00a0rpm`;
    } else if (card.kind === 'drivetrain') {
        const gear = section?.fields?.find(field => field.label === 'Gear');
        card.metrics.textContent = active && gear && gear.age_s + elapsed < 10 ? gear.value : '—';
    } else {
        card.metrics.textContent = '';
    }
}

function draw() {
    const elapsed = (performance.now() - lastAt) / 1000;
    const active = online && elapsed < 4;
    const badge = document.querySelector('#connection');
    badge.textContent = active ? '● Live' : 'Disconnected';
    badge.className = `pill ${active ? 'ok' : 'warn'}`;

    const banner = document.querySelector('#banner');
    banner.textContent = online ? '' : 'Connection to Raspberry lost. Reconnecting…';
    banner.style.display = banner.textContent ? 'block' : 'none';

    const devices = last?.devices || [];
    const sections = last?.sections_ant || {};
    syncCards(devices);
    for (const device of devices) {
        const card = cards.get(device.key);
        const section = sections[device.key];
        renderSection(card, section, elapsed, active);
        renderMetric(card, section, elapsed, active);
    }
}

async function poll() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 3000);
    try {
        const response = await fetch('/api/state', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(response.status);
        last = await response.json();
        lastAt = performance.now();
        online = true;
    } catch (error) {
        online = false;
    } finally {
        clearTimeout(timer);
        draw();
        setTimeout(poll, 500);
    }
}

poll();
setInterval(() => { if (last) draw(); }, 1000);
