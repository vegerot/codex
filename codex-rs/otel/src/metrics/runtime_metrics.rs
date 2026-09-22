use crate::metrics::names::API_CALL_COUNT_METRIC;
use crate::metrics::names::API_CALL_DURATION_METRIC;
use crate::metrics::names::HOOK_RUN_DURATION_METRIC;
use crate::metrics::names::HOOK_RUN_METRIC;
use crate::metrics::names::RESPONSES_API_ENGINE_IAPI_TBT_DURATION_METRIC;
use crate::metrics::names::RESPONSES_API_ENGINE_IAPI_TTFT_DURATION_METRIC;
use crate::metrics::names::RESPONSES_API_ENGINE_SERVICE_TBT_DURATION_METRIC;
use crate::metrics::names::RESPONSES_API_ENGINE_SERVICE_TTFT_DURATION_METRIC;
use crate::metrics::names::RESPONSES_API_INFERENCE_TIME_DURATION_METRIC;
use crate::metrics::names::RESPONSES_API_OVERHEAD_DURATION_METRIC;
use crate::metrics::names::SSE_EVENT_COUNT_METRIC;
use crate::metrics::names::SSE_EVENT_DURATION_METRIC;
use crate::metrics::names::TOOL_CALL_COUNT_METRIC;
use crate::metrics::names::TOOL_CALL_DURATION_METRIC;
use crate::metrics::names::TOOL_CALL_UNIFIED_EXEC_DURATION_METRIC;
use crate::metrics::names::TOOL_CALL_UNIFIED_EXEC_METRIC;
use crate::metrics::names::TURN_TTFM_DURATION_METRIC;
use crate::metrics::names::TURN_TTFT_DURATION_METRIC;
use crate::metrics::names::WEBSOCKET_EVENT_COUNT_METRIC;
use crate::metrics::names::WEBSOCKET_EVENT_DURATION_METRIC;
use crate::metrics::names::WEBSOCKET_REQUEST_COUNT_METRIC;
use crate::metrics::names::WEBSOCKET_REQUEST_DURATION_METRIC;
use opentelemetry_sdk::metrics::data::AggregatedMetrics;
use opentelemetry_sdk::metrics::data::Metric;
use opentelemetry_sdk::metrics::data::MetricData;
use opentelemetry_sdk::metrics::data::ResourceMetrics;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct RuntimeMetricTotals {
    pub count: u64,
    pub duration_ms: u64,
}

impl RuntimeMetricTotals {
    pub fn is_empty(self) -> bool {
        self.count == 0 && self.duration_ms == 0
    }

    pub fn merge(&mut self, other: Self) {
        self.count = self.count.saturating_add(other.count);
        self.duration_ms = self.duration_ms.saturating_add(other.duration_ms);
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct RuntimeMetricsSummary {
    pub hook_calls: RuntimeMetricTotals,
    pub local_commands: RuntimeMetricTotals,
    pub tool_calls: RuntimeMetricTotals,
    pub api_calls: RuntimeMetricTotals,
    pub streaming_events: RuntimeMetricTotals,
    pub websocket_calls: RuntimeMetricTotals,
    pub websocket_events: RuntimeMetricTotals,
    pub responses_api_overhead_ms: u64,
    pub responses_api_inference_time_ms: u64,
    pub responses_api_engine_iapi_ttft_ms: u64,
    pub responses_api_engine_service_ttft_ms: u64,
    pub responses_api_engine_iapi_tbt_ms: f64,
    pub responses_api_engine_service_tbt_ms: f64,
    pub turn_ttft_ms: u64,
    pub turn_ttfm_ms: u64,
}

impl RuntimeMetricsSummary {
    pub fn is_empty(self) -> bool {
        self.hook_calls.is_empty()
            && self.local_commands.is_empty()
            && self.tool_calls.is_empty()
            && self.api_calls.is_empty()
            && self.streaming_events.is_empty()
            && self.websocket_calls.is_empty()
            && self.websocket_events.is_empty()
            && self.responses_api_overhead_ms == 0
            && self.responses_api_inference_time_ms == 0
            && self.responses_api_engine_iapi_ttft_ms == 0
            && self.responses_api_engine_service_ttft_ms == 0
            && self.responses_api_engine_iapi_tbt_ms == 0.0
            && self.responses_api_engine_service_tbt_ms == 0.0
            && self.turn_ttft_ms == 0
            && self.turn_ttfm_ms == 0
    }

    pub fn merge(&mut self, other: Self) {
        self.hook_calls.merge(other.hook_calls);
        self.local_commands.merge(other.local_commands);
        self.tool_calls.merge(other.tool_calls);
        self.api_calls.merge(other.api_calls);
        self.streaming_events.merge(other.streaming_events);
        self.websocket_calls.merge(other.websocket_calls);
        self.websocket_events.merge(other.websocket_events);
        if other.responses_api_overhead_ms > 0 {
            self.responses_api_overhead_ms = other.responses_api_overhead_ms;
        }
        if other.responses_api_inference_time_ms > 0 {
            self.responses_api_inference_time_ms = other.responses_api_inference_time_ms;
        }
        if other.responses_api_engine_iapi_ttft_ms > 0 {
            self.responses_api_engine_iapi_ttft_ms = other.responses_api_engine_iapi_ttft_ms;
        }
        if other.responses_api_engine_service_ttft_ms > 0 {
            self.responses_api_engine_service_ttft_ms = other.responses_api_engine_service_ttft_ms;
        }
        if other.responses_api_engine_iapi_tbt_ms > 0.0 {
            self.responses_api_engine_iapi_tbt_ms = other.responses_api_engine_iapi_tbt_ms;
        }
        if other.responses_api_engine_service_tbt_ms > 0.0 {
            self.responses_api_engine_service_tbt_ms = other.responses_api_engine_service_tbt_ms;
        }
        if other.turn_ttft_ms > 0 {
            self.turn_ttft_ms = other.turn_ttft_ms;
        }
        if other.turn_ttfm_ms > 0 {
            self.turn_ttfm_ms = other.turn_ttfm_ms;
        }
    }

    pub fn responses_api_summary(&self) -> RuntimeMetricsSummary {
        Self {
            responses_api_overhead_ms: self.responses_api_overhead_ms,
            responses_api_inference_time_ms: self.responses_api_inference_time_ms,
            responses_api_engine_iapi_ttft_ms: self.responses_api_engine_iapi_ttft_ms,
            responses_api_engine_service_ttft_ms: self.responses_api_engine_service_ttft_ms,
            responses_api_engine_iapi_tbt_ms: self.responses_api_engine_iapi_tbt_ms,
            responses_api_engine_service_tbt_ms: self.responses_api_engine_service_tbt_ms,
            ..RuntimeMetricsSummary::default()
        }
    }

    pub(crate) fn from_snapshot(snapshot: &ResourceMetrics) -> Self {
        let hook_calls = RuntimeMetricTotals {
            count: sum_counter_with_attribute(snapshot, HOOK_RUN_METRIC, "execution_mode", "sync"),
            duration_ms: sum_histogram_ms_with_attribute(
                snapshot,
                HOOK_RUN_DURATION_METRIC,
                "execution_mode",
                "sync",
            ),
        };
        let local_commands = RuntimeMetricTotals {
            count: sum_counter(snapshot, TOOL_CALL_UNIFIED_EXEC_METRIC),
            duration_ms: sum_histogram_ms(snapshot, TOOL_CALL_UNIFIED_EXEC_DURATION_METRIC),
        };
        let tool_calls = RuntimeMetricTotals {
            count: sum_counter(snapshot, TOOL_CALL_COUNT_METRIC),
            duration_ms: sum_histogram_ms(snapshot, TOOL_CALL_DURATION_METRIC),
        };
        let api_calls = RuntimeMetricTotals {
            count: sum_counter(snapshot, API_CALL_COUNT_METRIC),
            duration_ms: sum_histogram_ms(snapshot, API_CALL_DURATION_METRIC),
        };
        let streaming_events = RuntimeMetricTotals {
            count: sum_counter(snapshot, SSE_EVENT_COUNT_METRIC),
            duration_ms: sum_histogram_ms(snapshot, SSE_EVENT_DURATION_METRIC),
        };
        let websocket_calls = RuntimeMetricTotals {
            count: sum_counter(snapshot, WEBSOCKET_REQUEST_COUNT_METRIC),
            duration_ms: sum_histogram_ms(snapshot, WEBSOCKET_REQUEST_DURATION_METRIC),
        };
        let websocket_events = RuntimeMetricTotals {
            count: sum_counter(snapshot, WEBSOCKET_EVENT_COUNT_METRIC),
            duration_ms: sum_histogram_ms(snapshot, WEBSOCKET_EVENT_DURATION_METRIC),
        };
        let responses_api_overhead_ms =
            sum_histogram_ms(snapshot, RESPONSES_API_OVERHEAD_DURATION_METRIC);
        let responses_api_inference_time_ms =
            sum_histogram_ms(snapshot, RESPONSES_API_INFERENCE_TIME_DURATION_METRIC);
        let responses_api_engine_iapi_ttft_ms =
            sum_histogram_ms(snapshot, RESPONSES_API_ENGINE_IAPI_TTFT_DURATION_METRIC);
        let responses_api_engine_service_ttft_ms =
            sum_histogram_ms(snapshot, RESPONSES_API_ENGINE_SERVICE_TTFT_DURATION_METRIC);
        let responses_api_engine_iapi_tbt_ms =
            sum_histogram_f64(snapshot, RESPONSES_API_ENGINE_IAPI_TBT_DURATION_METRIC);
        let responses_api_engine_service_tbt_ms =
            sum_histogram_f64(snapshot, RESPONSES_API_ENGINE_SERVICE_TBT_DURATION_METRIC);
        let turn_ttft_ms = sum_histogram_ms(snapshot, TURN_TTFT_DURATION_METRIC);
        let turn_ttfm_ms = sum_histogram_ms(snapshot, TURN_TTFM_DURATION_METRIC);
        Self {
            hook_calls,
            local_commands,
            tool_calls,
            api_calls,
            streaming_events,
            websocket_calls,
            websocket_events,
            responses_api_overhead_ms,
            responses_api_inference_time_ms,
            responses_api_engine_iapi_ttft_ms,
            responses_api_engine_service_ttft_ms,
            responses_api_engine_iapi_tbt_ms,
            responses_api_engine_service_tbt_ms,
            turn_ttft_ms,
            turn_ttfm_ms,
        }
    }
}

fn sum_counter(snapshot: &ResourceMetrics, name: &str) -> u64 {
    snapshot
        .scope_metrics()
        .flat_map(opentelemetry_sdk::metrics::data::ScopeMetrics::metrics)
        .filter(|metric| metric.name() == name)
        .map(sum_counter_metric)
        .sum()
}

fn sum_counter_metric(metric: &Metric) -> u64 {
    match metric.data() {
        AggregatedMetrics::U64(MetricData::Sum(sum)) => sum
            .data_points()
            .map(opentelemetry_sdk::metrics::data::SumDataPoint::value)
            .sum(),
        _ => 0,
    }
}

fn sum_counter_with_attribute(
    snapshot: &ResourceMetrics,
    name: &str,
    attribute_key: &str,
    attribute_value: &str,
) -> u64 {
    snapshot
        .scope_metrics()
        .flat_map(opentelemetry_sdk::metrics::data::ScopeMetrics::metrics)
        .filter(|metric| metric.name() == name)
        .map(|metric| match metric.data() {
            AggregatedMetrics::U64(MetricData::Sum(sum)) => sum
                .data_points()
                .filter(|point| {
                    point.attributes().any(|attribute| {
                        attribute.key.as_str() == attribute_key
                            && attribute.value.as_str().as_ref() == attribute_value
                    })
                })
                .map(opentelemetry_sdk::metrics::data::SumDataPoint::value)
                .sum(),
            _ => 0,
        })
        .sum()
}

fn sum_histogram_ms(snapshot: &ResourceMetrics, name: &str) -> u64 {
    f64_to_u64(sum_histogram_f64(snapshot, name))
}

fn sum_histogram_ms_with_attribute(
    snapshot: &ResourceMetrics,
    name: &str,
    attribute_key: &str,
    attribute_value: &str,
) -> u64 {
    f64_to_u64(
        snapshot
            .scope_metrics()
            .flat_map(opentelemetry_sdk::metrics::data::ScopeMetrics::metrics)
            .filter(|metric| metric.name() == name)
            .map(|metric| match metric.data() {
                AggregatedMetrics::F64(MetricData::Histogram(histogram)) => histogram
                    .data_points()
                    .filter(|point| {
                        point.attributes().any(|attribute| {
                            attribute.key.as_str() == attribute_key
                                && attribute.value.as_str().as_ref() == attribute_value
                        })
                    })
                    .map(opentelemetry_sdk::metrics::data::HistogramDataPoint::sum)
                    .sum(),
                _ => 0.0,
            })
            .sum(),
    )
}

fn sum_histogram_f64(snapshot: &ResourceMetrics, name: &str) -> f64 {
    snapshot
        .scope_metrics()
        .flat_map(opentelemetry_sdk::metrics::data::ScopeMetrics::metrics)
        .filter(|metric| metric.name() == name)
        .map(sum_histogram_metric)
        .sum()
}

fn sum_histogram_metric(metric: &Metric) -> f64 {
    match metric.data() {
        AggregatedMetrics::F64(MetricData::Histogram(histogram)) => histogram
            .data_points()
            .map(opentelemetry_sdk::metrics::data::HistogramDataPoint::sum)
            .sum(),
        _ => 0.0,
    }
}

fn f64_to_u64(value: f64) -> u64 {
    if !value.is_finite() || value <= 0.0 {
        return 0;
    }
    let clamped = value.min(u64::MAX as f64);
    clamped.round() as u64
}
