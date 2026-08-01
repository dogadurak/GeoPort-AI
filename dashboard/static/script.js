// Initialize Leaflet Map centered on Storebaelt, Denmark
const map = L.map('map').setView([55.33, 10.95], 10);

// Use a Dark Mode Base Map (CartoDB Dark Matter)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
}).addTo(map);

// Colors matching UI CSS variables
const COLORS = {
    darkVessel: '#ef4444',
    matched: '#10b981',
    ghost: '#f59e0b'
};

// Helper to create a circle marker style
function getMarkerStyle(color) {
    return {
        radius: 6,
        fillColor: color,
        color: '#ffffff',
        weight: 1,
        opacity: 1,
        fillOpacity: 0.8
    };
}

// Helper to create a popup content string
function createPopupContent(title, properties) {
    let content = `<div class="popup-content">
        <h4 style="border-bottom: 1px solid #4b5563; padding-bottom: 8px; margin-bottom: 12px; font-size: 1.1em;">
            ${title}
        </h4>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.9em;">
    `;
    
    // Gemi Tipi (AIS'ten geliyorsa)
    if (properties.ais_ship_type) {
        content += `<div><strong>Gemi Tipi:</strong></div><div>${properties.ais_ship_type}</div>`;
    }
    
    // İsim / MMSI
    if (properties.ais_name) {
        content += `<div><strong>İsim:</strong></div><div>${properties.ais_name}</div>`;
    } else if (properties.name) {
        content += `<div><strong>İsim:</strong></div><div>${properties.name}</div>`;
    }
    if (properties.ais_mmsi || properties.mmsi) {
        content += `<div><strong>MMSI:</strong></div><div>${properties.ais_mmsi || properties.mmsi}</div>`;
    }

    // Tespit Yöntemi
    if (properties.type) {
        let detType = properties.type === 'YOLO' ? 'Derin Öğrenme (YOLO-OBB)' : 'İstatistiksel (CFAR)';
        content += `<div><strong>Tespit:</strong></div><div>${detType}</div>`;
    }
    
    // Tahmini Boyutlar ve Gemi Sınıfı (YOLO için)
    if (properties.bbox) {
        let w = Math.abs(properties.bbox[2] - properties.bbox[0]);
        let h = Math.abs(properties.bbox[3] - properties.bbox[1]);
        // Sentinel-1 IW GRD piksel çözünürlüğü yaklaşık 10 metre
        let length = Math.round(Math.max(w, h) * 10);
        let width = Math.round(Math.min(w, h) * 10);
        content += `<div><strong>Tahmini Boyut:</strong></div><div>${length}m x ${width}m</div>`;
        
        let shipClass = "Bilinmeyen";
        if (length > 150) shipClass = "Büyük Yük / Tanker Gemisi";
        else if (length > 50) shipClass = "Kargo / Yolcu Gemisi";
        else shipClass = "Küçük Tekne / Balıkçı";
        content += `<div><strong style="color:#60a5fa;">Tahmini Sınıf:</strong></div><div style="color:#60a5fa;">${shipClass}</div>`;
        
    } else if (properties.area_px) {
        let area = properties.area_px * 100;
        content += `<div><strong>Tahmini Alan:</strong></div><div>${area} m²</div>`;
        content += `<div><strong style="color:#60a5fa;">Tahmini Sınıf:</strong></div><div style="color:#60a5fa;">Küçük Tekne (Hedef)</div>`;
    }

    // Güven Skoru
    if (properties.conf !== undefined && properties.conf > 0) {
        let confPct = (properties.conf * 100).toFixed(1);
        content += `<div><strong>Yapay Zeka Güveni:</strong></div><div>%${confPct}</div>`;
    }

    // Real AIS Velocity & Navigational Status if available
    if (properties.ais_sog !== undefined && properties.ais_sog !== null) {
        content += `<div><strong style="color: #6ee7b7;">Hız (SOG):</strong></div><div style="color: #6ee7b7;">${properties.ais_sog} knot</div>`;
    }
    if (properties.ais_nav_status) {
        content += `<div><strong>Navigasyon:</strong></div><div>${properties.ais_nav_status}</div>`;
    }
    
    content += `</div></div>`;
    return content;
}

// State to keep track of counts
const counts = {
    dark: 0,
    matched: 0,
    ghost: 0
};

// Fetch and render GeoJSON
async function loadLayer(url, color, title, counterElementId, countKey) {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        
        const data = await response.json();
        
        if (data.features) {
            counts[countKey] = data.features.length;
            document.getElementById(counterElementId).textContent = counts[countKey];
        }

        L.geoJSON(data, {
            pointToLayer: function (feature, latlng) {
                return L.circleMarker(latlng, getMarkerStyle(color));
            },
            onEachFeature: function (feature, layer) {
                if (feature.properties) {
                    layer.bindPopup(createPopupContent(title, feature.properties));
                }
            }
        }).addTo(map);

    } catch (error) {
        console.error(`Could not load ${url}:`, error);
    }
}

// Load all layers
async function initDashboard() {
    await Promise.all([
        loadLayer('/api/dark_vessels', COLORS.darkVessel, 'Dark Vessel (SAR Only)', 'stat-dark', 'dark'),
        loadLayer('/api/matched_vessels', COLORS.matched, 'Matched Vessel', 'stat-matched', 'matched'),
        loadLayer('/api/ghost_signals', COLORS.ghost, 'Ghost Signal (AIS Only)', 'stat-ghost', 'ghost')
    ]);
}

// Start
initDashboard();
