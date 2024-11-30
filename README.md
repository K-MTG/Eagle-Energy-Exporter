# Eagle Energy Exporter

**Eagle Energy Exporter** is a service that ingests raw XML data from Rainforest Eagle devices, 
parses it, and **remote-writes energy-related metrics** to Prometheus for monitoring. The service parses Eagle XML data
to extract energy summation, instantaneous demand, and network/device information, and sends the parsed metrics to 
Prometheus using the **Prometheus Remote Write Exporter**.

## Features

- **Ingests XML data** from Eagle Energy devices.
- **Parses energy metrics** such as `summation_delivered`, `summation_received`, and `instantaneous_demand`.
- **Remote writes metrics** to Prometheus using the **Prometheus Remote Write Exporter**.
- Supports ingesting data from multiple eagle devices
- No polling! Message is received vs constant polling  

## Requirements

- Docker (for containerized deployment)
- Prometheus (for monitoring and metrics collection)

## Installation Using Docker Compose

1. **Clone the repository**:

   ```bash
   git clone https://github.com/your-repo/eagle-energy-exporter.git
   cd eagle-energy-exporter
   ```

2. **Docker Compose Configuration**:

   The project comes with a `docker-compose.yml` file, which simplifies the process of running the service in a containerized environment.

3. **Set up environment variables**:

   You need to configure the environment variables for the Prometheus remote write endpoint and any optional labels for your devices.

   - Open the `docker-compose.yml` file in a text editor.
   - Locate the `environment` section.
   - Update the `PROMETHEUS_REMOTE_WRITE_ENDPOINT` with your Prometheus remote write endpoint (e.g., `http://your-prometheus-server:9090/api/v1/write`).
   - Optionally, update or remove the `PROMETHEUS_OPT_LABELS` with any custom labels you'd like to associate with specific devices in the JSON format. 

   Example:

   ```yaml
   environment:
     - PROMETHEUS_REMOTE_WRITE_ENDPOINT=http://your-prometheus-server:9090/api/v1/write
     - PROMETHEUS_OPT_LABELS={"0xabc123": {"location": "Home"}}
   ```

4. **Build and start the container**:

   Run the following command to build and start the Docker container using Docker Compose:

   ```bash
   docker compose up --build -d
   ```

   This will start the FastAPI application and make it available on port `39501`.

5. **Verify the application is running**:

   You should be able to access the FastAPI app at `http://localhost:39501`, which will be receiving raw XML data from Eagle devices.

6. **Shut down the containers**:

   When you want to stop the container, run the following:

   ```bash
   docker-compose down
   ```

## Configuring the Eagle Energy Gateway

To configure your Eagle Energy Gateway to send data to your **Eagle Energy Exporter** service, follow the steps below:

### For Eagle 2 (Older Version):

1. Go to **Settings > Cloud** in the Eagle web UI.
2. Add a new cloud provider and paste in the following URL:  
   `<http://<server_ip>:39501>`.
3. Click **Add Cloud**.
4. Select the newly added provider and click **Set Cloud**.

### For Eagle 3 (Newer Version):

For Eagle 3, configuration is done through the cloud portal. Follow these steps:

1. Navigate to **Settings** > **Cloud** in the Eagle 3 portal.
2. Configure the provider with the following details:
   - **Provider**: `eagle-energy-exporter`
   - **Protocol**: `http`
   - **HostName**: `<server_ip>`
   - **Port**: `39501`
   - **Url**: `/`
   - **Format**: `XML: RAW`

3. Save the configuration, and the Eagle device will start sending raw XML data to your Eagle Energy Exporter.

## How It Works

1. **Eagle devices** send XML data to the FastAPI service.
2. The service **parses the XML** to extract energy metrics such as:
   - `summation_delivered`: The total energy delivered (in kWh).
   - `summation_received`: The total energy received (in kWh).
   - `instantaneous_demand`: The current energy demand (in kWh).
   - `network_info`: Link strength (optional, depending on the device).
3. The **parsed metrics** are then **remote-written to Prometheus** using the **Prometheus Remote Write Exporter**. These metrics are not exposed via HTTP for scraping directly.

## Changelog

### v1.0.0 - 2024-11-29
- Initial release of Eagle Energy Exporter.


### Credits
- Inspired by the work of @augoisms on the Rainforest Eagle integration for Hubitat Hub. You can find the original work [here](https://github.com/augoisms/hubitat/blob/master/rainforest-eagle/rainforest-eagle.driver.groovy).