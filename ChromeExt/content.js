function injectStyles() {
    var styles = `
        .price-grid {
            display: grid;
            grid-template-columns: repeat(6, 1fr); /* Seks kolonner nå */
            gap: 5px;
            margin-top: 10px;
            font-size: 0.8em; /* Mindre font */
        }
        .grid-header {
            font-weight: bold;
            background-color: #f0f0f0;
            padding: 5px;
            text-align: right; /* Justerer overskrifter til høyre */
        }
        .grid-item {
            padding: 5px;
            border-bottom: 1px solid #ddd;
            text-align: right; /* Høyrejuster alle grid-celler */
        }
    `;
    
    var styleSheet = document.createElement("style");
    styleSheet.textContent = styles;
    document.head.appendChild(styleSheet);
}

function formatPriceInfo(priceData) {
    if (priceData.length === 0) {
        return "Prisdata ikke tilgjengelig";
    }

    // Legg til overskrift utenfor grid
    var formattedData = `
        <div class="price-grid">
            <div class="grid-header">ID</div>
            <div class="grid-header">Pris (Kr)</div>
            <div class="grid-header">Pris Dato</div>
            <div class="grid-header">Km stand</div>
            <div class="grid-header">Startdato</div>
            <div class="grid-header">Solgt/Inaktivert</div>
    `;

    priceData.forEach(entry => {
        var [carId, vin, price, km, priceDate, startDate, soldDate, listedDays] = entry;

        // Formatering av datoer
        var formattedStartDate = formatDate(new Date(startDate));
        var formattedSoldDate = soldDate ? formatDate(new Date(soldDate)) : '';
        var formattedPriceDate = priceDate ? formatDate(new Date(priceDate)) : '';

        // Legg til rader i grid
        formattedData += `
            <div class="grid-item">${carId}</div>
            <div class="grid-item">${price}</div>
            <div class="grid-item">${formattedPriceDate}</div>
            <div class="grid-item">${km}</div>
            <div class="grid-item">${formattedStartDate}</div>
            <div class="grid-item">${formattedSoldDate}</div>
        `;
    });

    formattedData += `</div>
        <canvas id="priceChart" width="600" height="200" style="margin-top:20px;display:block;"></canvas>
    `;
    return formattedData;
}

function formatDate(dateObj) {
    var day = String(dateObj.getDate()).padStart(2, '0');
    var month = String(dateObj.getMonth() + 1).padStart(2, '0');
    var year = dateObj.getFullYear(); // Bruk hele året (yyyy)
    return `${day}.${month}.${year}`; // dd.MM.yyyy
}

// Funksjon for å hente prishistorikk
function fetchPriceHistory(carId) {
    fetch('http://127.0.0.1:8001/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ car_id: carId })
    })
    .then(response => response.json())
    .then(data => {
        insertPriceInfo(data.price_data);  // Kall `insertPriceInfo` med prisdataen
    })
    .catch(error => console.error('Error:', error));
}

function drawPriceChart(priceData) {
    if (!priceData || priceData.length === 0) return;
    var canvas = document.getElementById('priceChart');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');

    // Hent og sorter data etter pricedate
    var points = priceData
        .map(entry => {
            var price = Number(entry[2]);
            var date = entry[4] ? new Date(entry[4]) : null;
            return (date && !isNaN(price)) ? { price, date } : null;
        })
        .filter(Boolean)
        .sort((a, b) => a.date - b.date);

    if (points.length < 2) return;

    // Finn min/max for skalering
    var minPrice = Math.min(...points.map(p => p.price));
    var maxPrice = Math.max(...points.map(p => p.price));
    var minDate = points[0].date;
    var maxDate = points[points.length - 1].date;

    // Gi litt ekstra plass på y-aksen (5%)
    var priceRange = maxPrice - minPrice || 1;
    var pad = priceRange * 0.05;
    minPrice -= pad;
    maxPrice += pad;

    // Padding
    var leftPad = 50, rightPad = 20, topPad = 20, bottomPad = 40;
    var w = canvas.width, h = canvas.height;

    // Akser
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = "#888";
    ctx.beginPath();
    ctx.moveTo(leftPad, topPad);
    ctx.lineTo(leftPad, h - bottomPad);
    ctx.lineTo(w - rightPad, h - bottomPad);
    ctx.stroke();

    // Grid-linjer for hver 50k
    ctx.strokeStyle = "#e0e0e0";
    ctx.lineWidth = 1;
    ctx.beginPath();
    var gridStep = 50000;
    var firstGrid = Math.ceil(minPrice / gridStep) * gridStep;
    for (var gridVal = firstGrid; gridVal < maxPrice; gridVal += gridStep) {
        var y = topPad + (1 - (gridVal - minPrice) / (maxPrice - minPrice || 1)) * (h - topPad - bottomPad);
        ctx.moveTo(leftPad, y);
        ctx.lineTo(w - rightPad, y);
    }
    ctx.stroke();
    ctx.lineWidth = 1;

    // Y-akse etiketter
    ctx.fillStyle = "#333";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(Math.round(maxPrice), leftPad - 5, topPad + 5);
    ctx.fillText(Math.round(minPrice), leftPad - 5, h - bottomPad);

    // X-akse etiketter for alle punkter, rotert
    ctx.save();
    ctx.textAlign = "right";
    ctx.font = "9.6px sans-serif"; // 80% av 12px
    points.forEach((pt, i) => {
        var x = leftPad + ((pt.date - minDate) / (maxDate - minDate || 1)) * (w - leftPad - rightPad);
        var y = h - bottomPad + 18;
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(-Math.PI / 4);
        ctx.fillText(formatDate(pt.date), 0, 0);
        ctx.restore();
    });
    ctx.restore();

    // Tegn linje
    ctx.strokeStyle = "#1976d2";
    ctx.beginPath();
    points.forEach((pt, i) => {
        var x = leftPad + ((pt.date - minDate) / (maxDate - minDate || 1)) * (w - leftPad - rightPad);
        var y = topPad + (1 - (pt.price - minPrice) / (maxPrice - minPrice || 1)) * (h - topPad - bottomPad);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // Tegn punkter
    ctx.fillStyle = "#1976d2";
    points.forEach(pt => {
        var x = leftPad + ((pt.date - minDate) / (maxDate - minDate || 1)) * (w - leftPad - rightPad);
        var y = topPad + (1 - (pt.price - minPrice) / (maxPrice - minPrice || 1)) * (h - topPad - bottomPad);
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, 2 * Math.PI);
        ctx.fill();
    });
}

function insertPriceInfo(priceData) {
    // Finn elementet du vil sette inn informasjonen
    //var targetElement = document.querySelector('.panel.panel--bleed.summary-icons');
    //var targetElement = document.querySelector('.md\\:col-span-2');
    var beforeElement = document.querySelector('.grid.mt-16.gap-24.md\\:gap-8.mt-40.md\\:mt-24.pb-40.border-b.grid-cols-2.md\\:grid-cols-\\[auto_auto_auto_auto\\]');

    console.log('Target element found:', beforeElement);
    // Opprett et nytt element for prisinformasjonen
    var priceElement = document.createElement('div');
    priceElement.className = 'grid__unit u-pa8';
    priceElement.innerHTML = `
        <div class="media">
            <div class="media__img">
                <div class="icon icon--price"></div>
            </div>
            <div class="media__body">
                <div>Prishistorie</div>
                <div class="u-strong">${formatPriceInfo(priceData)}</div>
            </div>
        </div>
    `;

    // Sett inn det nye elementet før målelementet
    if (beforeElement) {
            beforeElement.parentNode.insertBefore(priceElement, beforeElement);
            // Tegn grafen etter at DOM er oppdatert
            setTimeout(() => drawPriceChart(priceData), 0);
        } else {
            console.error('Before element not found');
    }

}

function getCarIdFromUrl() {
    const pathSegments = window.location.pathname.split('/'); // Deler opp stien i segmenter
    const carId = pathSegments[pathSegments.length - 1]; // Henter det siste segmentet av stien
    return carId; // Returnerer carId
}

// Bruk funksjonen og gjør noe med car_id
const carId = getCarIdFromUrl();
console.log('Starter extension');
if (carId) {
    injectStyles();
    console.log('Car ID:', carId);
    fetchPriceHistory(carId);
}

