
function formatPriceInfo(priceData) {
    if (priceData.length === 0) {
        return "Prisdata ikke tilgjengelig";
    }
    var formattedData = '<ul>';
    priceData.forEach(entry => {
        var [date, price] = entry
        var dateObj = new Date(date);
        var day = String(dateObj.getDate()).padStart(2, '0'); // Legger til '0' foran hvis det trengs
        var month = String(dateObj.getMonth() + 1).padStart(2, '0'); // Månedene starter på 0 i JavaScript
        var year = dateObj.getFullYear();

        var formattedDate = `${day}.${month}.${year}`; // Formatere datoen til dd.MM.yyyy
        if (price == 9.0)
            formattedData += `<li>${formattedDate}: Solgt </li>`;
        else
            formattedData += `<li>${formattedDate}: ${price} kr</li>`; // Formatere prisen
    });
    formattedData += '</ul>';
    return formattedData;
}

// Funksjon for å hente prishistorikk
function fetchPriceHistory(carId) {
    fetch('http://127.0.0.1:8000/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ car_id: carId })
    })
    .then(response => response.json())
    .then(data => {
        console.log("data.price_data ");
        console.log(data.price_data);
        insertPriceInfo(data.price_data);  // Kall `insertPriceInfo` med prisdataen
    })
    .catch(error => console.error('Error:', error));
}

function insertPriceInfo(priceData) {
    // Finn elementet du vil sette inn informasjonen før
    var targetElement = document.querySelector('.panel.panel--bleed.summary-icons');

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
    targetElement.parentNode.insertBefore(priceElement, targetElement);
}
function getCarIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    const carId = urlParams.get('finnkode');
    return carId;
}

// Bruk funksjonen og gjør noe med car_id
const carId = getCarIdFromUrl();
if (carId) {
    console.log('Car ID:', carId);
    fetchPriceHistory(carId);
}

