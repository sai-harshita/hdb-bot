import logging
import os

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "hdb-chatbot-api")
ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

_resource = Resource.create({"service.name": SERVICE_NAME})


def setup_telemetry() -> None:
    # Traces
    tp = TracerProvider(resource=_resource)
    tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT, insecure=True)))
    trace.set_tracer_provider(tp)

    # Metrics
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=ENDPOINT, insecure=True))
    mp = MeterProvider(resource=_resource, metric_readers=[reader])
    metrics.set_meter_provider(mp)

    # Logs
    lp = LoggerProvider(resource=_resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=ENDPOINT, insecure=True)))
    handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


tracer = trace.get_tracer(SERVICE_NAME)
meter = metrics.get_meter(SERVICE_NAME)

# Custom metrics for guardrail observability
rail_block_counter = meter.create_counter(
    "guardrail_blocks_total", description="Count of requests blocked, by rail"
)
chat_latency = meter.create_histogram(
    "chat_latency_ms", unit="ms", description="End to end chat latency"
)
