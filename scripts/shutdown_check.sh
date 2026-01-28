#!/bin/sh

# Define the URL to check for shutdown readiness
URL='http://localhost:8000/shutdownz'

# Start an infinite loop to periodically check the shutdown status
while true; do
    # Send a GET request to the URL and capture the HTTP response code
    response_code=$(curl -s -o /dev/null -w "%{http_code}" "$URL")
    # Capture the exit status of the curl command
    curl_exit_status=$?

    # Print the response code for logging purposes
    echo "Response code: $response_code"

    # Check if the curl command was successful
    if [ $curl_exit_status -ne 0 ]; then
        # If curl failed, log a message and continue the loop
        echo "Curl command failed with exit status $curl_exit_status. Continuing the check."
    elif [ "$response_code" -eq 200 ]; then
        # If the response is 200, log a message and break the loop
        echo "Received acceptable response code ($response_code). Stopping the check."
        break
    else
        # If the response is not 200, log a message and continue the loop
        echo "Received unacceptable response code ($response_code). Continuing the check."
    fi

    # Wait for 10 seconds before the next check
    sleep 10
done
