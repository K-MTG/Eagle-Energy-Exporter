import xml.etree.ElementTree
import traceback
import time
import os
import json
from typing import Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import Response

from opentelemetry import metrics
from opentelemetry.exporter.prometheus_remote_write import PrometheusRemoteWriteMetricsExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes

# FastAPI app initialization
app = FastAPI()

# Initialize Prometheus exporter with the endpoint from environment variables
exporter = PrometheusRemoteWriteMetricsExporter(
    endpoint=os.environ['PROMETHEUS_REMOTE_WRITE_ENDPOINT']
)

# Define the resource that will be associated with metrics (e.g., service name)
resource = Resource(attributes={
    ResourceAttributes.SERVICE_NAME: "eagle_energy_exporter"
})

# Set up the periodic exporting metric reader that sends metrics every 1000ms
reader = PeriodicExportingMetricReader(exporter, 1000)

# Initialize the MeterProvider with the resource and the reader
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)
meter = metrics.get_meter(__name__)

# Define gauges (metrics) to track energy summation and instantaneous demand
summation_delivered_gauge = meter.create_gauge(
    name="summation_delivered",
    description="summation of energy delivered",
    unit="kWh",
)

summation_received_gauge = meter.create_gauge(
    name="summation_received",
    description="summation of energy received",
    unit="kWh",
)

instantaneous_demand_gauge = meter.create_gauge(
    name="instantaneous_demand",
    description="demand of energy",
    unit="kWh",
)


def utc2000_to_epoch(seconds: int) -> int:
    """
    Converts a UTC2000 timestamp (seconds since Jan 1, 2000) to Unix epoch time (seconds since Jan 1, 1970).

    Args:
        seconds (int): The timestamp in UTC2000 seconds.

    Returns:
        int: The corresponding Unix epoch time.
    """
    unix2000_time = 946684800  # Seconds since 1970-01-01 00:00:00 UTC (Unix epoch)
    return seconds + unix2000_time


def convert_hex_to_int(hex_num: str) -> int:
    """
    Converts a hexadecimal string (with "0x" prefix) to a signed integer.

    Args:
        hex_num (str): The hexadecimal string (e.g., "0x1A3").

    Returns:
        int: The corresponding integer value, adjusted for 32-bit two's complement if necessary.
    """
    # Remove the "0x" prefix and convert to an integer
    value = int(hex_num[2:], 16)

    # Check if the value is greater than 2^31 (i.e., it should be interpreted as negative in 32-bit two's complement)
    if value >= 0x80000000:  # 0x80000000 is 2^31
        value -= 0x100000000  # Subtract 2^32 to get the signed value

    return value


class EagleParse:
    """
    A class for parsing Eagle XML data and extracting relevant metrics and labels for Prometheus.
    """

    _global_config: Dict[str, Dict[str, dict]] = dict()  # Global configuration dictionary to store device-specific state and labels

    def __init__(self, raw_xml: bytes, client_host: str) -> None:
        """
        Initialize the parser with raw XML data.

        Args:
            raw_xml (bytes): The raw XML data to be parsed.
            client_host (str): The client host sending the data, used for labels.
        """
        self.raw_xml: str = raw_xml.decode("utf-8")  # Decode the raw XML data for string processing

        # Initialize placeholders for parsed metrics and labels
        self._metric: Dict[str, Dict[str, float]] = dict()
        self._labels: Optional[Dict[str, str]] = None

        # Parse the XML string to get the root element
        self.root = xml.etree.ElementTree.fromstring(self.raw_xml)

        # Extract timestamp, default to current time if not present
        self.timestamp: int = int(self.root.attrib.get("timestamp", '0').rstrip('s')) or int(time.time())

        # Retrieve and store global state based on the DeviceMacId
        device_mac_id: Optional[str] = self.root.findtext(".//DeviceMacId", None)
        if device_mac_id:
            if device_mac_id not in self._global_config:
                # Set initial labels for the device, including client host and any optional labels from environment
                labels = {'device_mac_id': device_mac_id,
                          'client_host': client_host}
                prom_opt_labels = json.loads(os.environ.get('PROMETHEUS_OPT_LABELS', '{}'))   # Optional labels per device
                if prom_opt_labels and device_mac_id in prom_opt_labels:
                    labels.update(prom_opt_labels[device_mac_id])
                self._global_config[device_mac_id] = {'labels': labels,
                                                      'state': {'device_info_received': False,
                                                                'network_info_received': False}}

            # Set instance-level labels and state for the device
            self._labels = self._global_config[device_mac_id]['labels']
            self._state: Dict[str, bool] = self._global_config[device_mac_id]['state']

    async def parse(self) -> None:
        """
        Parse the XML data and extract the relevant metrics and labels.

        This method calls various private parsing methods for different sections of the XML.
        """
        self._parse_instantaneous_demand()
        self._parse_current_summation()
        self._parse_device_info()
        self._parse_network_info()

    def _parse_instantaneous_demand(self) -> None:
        """
        Parse the 'InstantaneousDemand' section of the XML and update metrics.

        This method calculates and stores the instantaneous energy demand in kWh.
        """
        instantaneous_demand = self.root.find(".//InstantaneousDemand")
        if instantaneous_demand is not None:
            # Extract and parse demand, multiplier, and divisor values
            demand: float = convert_hex_to_int(instantaneous_demand.find("Demand").text)
            multiplier: int = convert_hex_to_int(instantaneous_demand.find("Multiplier").text)
            divisor: int = convert_hex_to_int(instantaneous_demand.find("Divisor").text)
            self.timestamp = utc2000_to_epoch(int(instantaneous_demand.find("TimeStamp").text, 16))

            # Default multipliers and divisors to 1 if they are 0
            multiplier = multiplier if multiplier != 0 else 1
            divisor = divisor if divisor != 0 else 1

            # Calculate the demand in kWh
            demand = (demand * multiplier) / divisor  # kWh

            # Assert that the demand is within reasonable bounds
            if (demand > 1000) or (demand < -1000):
                raise Exception(f'Computed demand of "{demand}" exceeds the assertion check of 1000. '
                                f'multiplier={multiplier}, divisor={divisor}, timestamp={self.timestamp}, '
                                f'raw_xml={self.raw_xml}')

            # Store the parsed demand in the metrics dictionary
            self._metric['instantaneous_demand'] = {"demand": demand}

    def _parse_current_summation(self) -> None:
        """
        Parse 'CurrentSummationDelivered' or 'CurrentSummation' section of the XML
        and update metrics for energy delivered and received.
        """
        current_summation = self.root.find("CurrentSummationDelivered") or self.root.find(
            "CurrentSummation")
        if current_summation is not None:
            # Extract and parse summation_delivered, summation_received, multiplier, and divisor values
            summation_delivered: float = convert_hex_to_int(current_summation.find('SummationDelivered').text)
            summation_received: float = convert_hex_to_int(current_summation.find('SummationReceived').text)
            multiplier: int = convert_hex_to_int(current_summation.find("Multiplier").text)
            divisor: int = convert_hex_to_int(current_summation.find("Divisor").text)
            self.timestamp = utc2000_to_epoch(int(current_summation.find("TimeStamp").text, 16))

            # Default multipliers and divisors to 1 if they are 0
            multiplier = multiplier if multiplier != 0 else 1
            divisor = divisor if divisor != 0 else 1

            # Calculate the summation delivered and received in kWh
            summation_delivered = (summation_delivered * multiplier) / divisor  # kWh
            summation_received = (summation_received * multiplier) / divisor  # kWh

            # Store the parsed current summation in the metrics dictionary
            self._metric['current_summation'] = {"summation_delivered": summation_delivered,
                                                 'summation_received': summation_received}

    def _parse_device_info(self) -> None:
        """
        Parse device-related information from the XML and update labels.

        This method extracts firmware version, hardware version, manufacturer, and model ID.
        """
        device_info = self.root.find(".//DeviceInfo")
        if device_info is not None:
            self._state['device_info_received'] = True
            # Extract device details and update the labels
            self._labels['fw_version'] = device_info.findtext("FWVersion", default=None)
            self._labels['hw_version'] = device_info.findtext("HWVersion", default=None)
            self._labels['manufacturer'] = device_info.findtext("Manufacturer", default=None)
            self._labels['model_id'] = device_info.findtext("ModelId", default=None)

    def _parse_network_info(self) -> None:
        """
        Parse network-related information from the XML and update metrics.

        This method extracts the link strength and stores it in the metrics.
        """
        network_info = self.root.find(".//NetworkInfo")
        if network_info is not None:
            self._state['network_info_received'] = True
            # Extract link strength from network information and store it in metrics
            link_strength = network_info.findtext("LinkStrength")
            if link_strength is not None:
                link_strength = int(link_strength, 16)
                self._metric['network_info'] = {"link_strength": link_strength}

    def get_metric_labels(self) -> Dict[str, dict]:
        """
        Return a dictionary containing metrics, labels, and timestamp.

        Returns:
            Dict[str, dict]: A dictionary with 'metric', 'labels', and 'timestamp' for the parsed data.
        """
        # Delay returning metrics until all labels are obtained.
        if self._labels is None or not self._state['device_info_received'] or not self._state['network_info_received']:
            return {}

        # Include meter_mac_id if available
        meter_mac_id: Optional[str] = self.root.findtext(".//MeterMacId", None)
        if meter_mac_id and meter_mac_id != '0x0000000000000000':
            self._labels['meter_mac_id'] = meter_mac_id

        # Return the collected metrics, labels, and timestamp
        return {'metric': self._metric, 'labels': self._labels, 'timestamp': self.timestamp}

    async def publish(self) -> None:
        """
        Publishes the parsed metrics and labels by updating Prometheus metrics.

        This method will call the appropriate gauges to publish the data to Prometheus.
        """
        await self.parse()
        ml = self.get_metric_labels()
        metric_data = ml.get('metric', {})

        if 'current_summation' in metric_data:
            summation_delivered_gauge.set(metric_data['current_summation']['summation_delivered'], ml['labels'])
            summation_received_gauge.set(metric_data['current_summation']['summation_received'], ml['labels'])
        if 'instantaneous_demand' in metric_data:
            instantaneous_demand_gauge.set(metric_data['instantaneous_demand']['demand'], ml['labels'])


@app.post("/")
async def ingest(request: Request) -> Response:
    """
    Ingests raw XML data from an HTTP request, parses it, and publishes the metrics.

    Args:
        request (Request): The HTTP request containing the raw XML data.

    Returns:
        Response: An HTTP response confirming the ingestion process.
    """
    # Read the raw XML body from the incoming HTTP request
    raw_xml = await request.body()
    client_host: str = request.client.host

    try:
        # Create an EagleParse object and publish parsed metrics asynchronously
        eagle_parser = EagleParse(raw_xml, client_host)
        await eagle_parser.publish()
    except Exception:
        # Log error details if parsing fails
        print(f"Error processing the XML: {traceback.format_exc()}")
    finally:
        # Return a 200 OK response after processing
        return Response(status_code=200)
