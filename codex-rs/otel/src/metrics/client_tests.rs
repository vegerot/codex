use super::*;
use crate::metrics::names::*;
use crate::metrics::runtime_metrics::RuntimeMetricTotals;
use crate::metrics::runtime_metrics::RuntimeMetricsSummary;
use opentelemetry_sdk::metrics::InMemoryMetricExporter;
use pretty_assertions::assert_eq;

#[test]
fn statsig_filter_keeps_runtime_measurements() -> Result<()> {
    let exporter = InMemoryMetricExporter::default();
    let mut config =
        MetricsConfig::otlp("test", "codex", "1.0.0", OtelExporter::Statsig).with_runtime_reader();
    config.exporter = MetricsExporter::InMemory(exporter.clone());
    let metrics = MetricsClient::new(config)?;
    metrics.counter(API_CALL_COUNT_METRIC, /*inc*/ 1, &[])?;
    metrics.record_duration(API_CALL_DURATION_METRIC, Duration::from_millis(100), &[])?;
    metrics.counter(TOOL_CALL_COUNT_METRIC, /*inc*/ 1, &[])?;
    metrics.record_duration(TOOL_CALL_DURATION_METRIC, Duration::from_millis(25), &[])?;
    metrics.record_duration(
        RESPONSES_API_ENGINE_IAPI_TTFT_DURATION_METRIC,
        Duration::from_millis(310),
        &[],
    )?;
    metrics.record_duration(
        RESPONSES_API_ENGINE_SERVICE_TTFT_DURATION_METRIC,
        Duration::from_millis(340),
        &[],
    )?;
    metrics.record_duration_ms_f64(
        RESPONSES_API_ENGINE_SERVICE_TBT_DURATION_METRIC,
        5.267279,
        &[],
    )?;
    metrics.counter("codex.turns", /*inc*/ 1, &[])?;
    assert_eq!(
        RuntimeMetricsSummary::from_snapshot(&metrics.snapshot()?),
        RuntimeMetricsSummary {
            api_calls: RuntimeMetricTotals {
                count: 1,
                duration_ms: 100
            },
            tool_calls: RuntimeMetricTotals {
                count: 1,
                duration_ms: 25
            },
            responses_api_engine_iapi_ttft_ms: 310,
            responses_api_engine_service_ttft_ms: 340,
            responses_api_engine_service_tbt_ms: 5.267279,
            ..Default::default()
        }
    );
    // Runtime reads consume only local deltas and never flush into the exporter.
    assert_eq!(
        RuntimeMetricsSummary::from_snapshot(&metrics.snapshot()?),
        RuntimeMetricsSummary::default()
    );
    metrics.shutdown()?;
    let batches = exporter.get_finished_metrics().expect("exported metrics");
    let mut names: Vec<_> = batches
        .iter()
        .flat_map(ResourceMetrics::scope_metrics)
        .flat_map(opentelemetry_sdk::metrics::data::ScopeMetrics::metrics)
        .map(opentelemetry_sdk::metrics::data::Metric::name)
        .collect();
    names.sort_unstable();
    names.dedup();
    assert_eq!(names, vec!["codex.turns"]);
    Ok(())
}
