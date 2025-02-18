#!/bin/sh

set -e

for req_app in wget python3 virtualenv java javac jar; do
    if ! which "$req_app" 2> /dev/null >&2; then
        echo "This script requires $req_app to be available via \$PATH." >&2
        echo 'Please contact your system administrator to install it.' >&2
        exit 1
    fi
done

skr_ver='SKR_Web_API_V2_3'
jar="$skr_ver.jar"

echo 'Downloading MetaMap Web API...'
while ! wget "https://ii.nlm.nih.gov/Web_API/$jar"; do
    echo 'Retrying in 3 seconds...'
    sleep 3
done

echo 'Extracting API files...'
jar xf "$jar"

(
    cd "$skr_ver/classes"

    for jar in ../lib/*.jar; do
        jar xf "$jar"
    done
)

echo 'Compiling metamap worker...'
javac metamap_worker/MetaMapWorker.java \
    -d "$skr_ver/classes" \
    -cp "$skr_ver/classes"

echo 'Creating metamap_worker uber jar...'

(
    cd "$skr_ver/classes"

    jar cfm ../../metamap_worker/metamap_worker.jar \
        ../../metamap_worker/manifest.txt .
)
