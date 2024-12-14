#!/bin/sh
# entrypoint.sh

# Sørg for at skriptet stopper ved feil
set -e

# Her kan du legge til eventuelle forberedende kommandoer
# som databasemigrasjoner, vente på avhengigheter, etc.

# Kjør PrisHistorie.py script
# echo "Kjører PrisHistorie.py..."
# python /app/PrisHistorie.py

# Start cron-tjenesten
echo "Starter cron jobb for PrisHistorie.py..."
# cron
service cron start

# Kjør en kommando som holder containeren kjørende
# Dette kan være en server, en while-løkke, eller noe som holder prosessen aktiv
# tail -f /var/log/cron.log
tail -f /dev/null

# Du kan legge til kommandoer her for å håndtere når skriptet er ferdig kjørt
# For eksempel, logging eller opprydding

# Skriptet vil avslutte, og containeren vil stoppe med mindre det er andre prosesser som kjører
