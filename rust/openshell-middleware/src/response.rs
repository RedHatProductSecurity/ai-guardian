//! HTTP response inspection and redaction capability.

use async_stream::try_stream;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use super::daemon::pause_metadata;
use super::openshell::middleware::v1::{
    self as pb, http_response_body_result, http_response_body_unit, http_response_event,
    http_response_event_result, http_response_preflight_result, HttpResponseBlockDelivery,
    HttpResponseBodyResult,
    HttpResponseBodyTransform, HttpResponseEventResult,
    HttpResponsePreflightInspect, HttpResponsePreflightResult, HttpResponseTrailersResult,
};
use super::MiddlewareService;

impl MiddlewareService {
    pub(super) async fn evaluate_response_rpc(
        &self,
        request: Request<tonic::Streaming<pb::HttpResponseEvent>>,
    ) -> Result<Response<super::ResponseStream>, Status> {
        let mut events = request.into_inner();
        let service = self.clone();
        let stream = try_stream! {
            let mut request_id = String::new();
            let mut body = Vec::new();
            let mut plan = super::policy::ScanPlan {
                checks: vec!["injection", "context_poisoning", "secrets", "pii"],
                response_redaction: true,
            };
            let mut body_mode = pb::HttpResponseBodyMode::WholeBodyBytes as i32;
            while let Some(event) = events.message().await? {
                match event.event {
                    Some(http_response_event::Event::Preflight(preflight)) => {
                        request_id = preflight
                            .context
                            .as_ref()
                            .map(|value| value.request_id.clone())
                            .unwrap_or_default();
                        let pause_response = match service.daemon.pause_status().await {
                            Ok(response) => response,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    "Rust middleware control plane unavailable; blocking response: {error}"
                                );
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::PreflightResult(
                                        HttpResponsePreflightResult {
                                            action: Some(http_response_preflight_result::Action::BlockDelivery(
                                                HttpResponseBlockDelivery {},
                                            )),
                                            reason: "AI Guardian middleware control plane unavailable".to_string(),
                                            reason_code: "middleware_control_plane_unavailable".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                        };
                        if let Some(response) = pause_response {
                            let metadata = pause_metadata(&response);
                            yield HttpResponseEventResult {
                                result: Some(http_response_event_result::Result::PreflightResult(
                                    HttpResponsePreflightResult {
                                        action: Some(http_response_preflight_result::Action::BlockDelivery(
                                            HttpResponseBlockDelivery {},
                                        )),
                                        reason: response.message,
                                        reason_code: response.reason_code,
                                        metadata,
                                        ..Default::default()
                                    },
                                )),
                            };
                            return;
                        }
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        body_mode = if preflight
                            .permitted_body_modes
                            .iter()
                            .any(|mode| *mode == pb::HttpResponseBodyMode::WholeBodyBytes as i32)
                        {
                            pb::HttpResponseBodyMode::WholeBodyBytes as i32
                        } else if preflight
                            .permitted_body_modes
                            .iter()
                            .any(|mode| *mode == pb::HttpResponseBodyMode::StreamBytes as i32)
                        {
                            pb::HttpResponseBodyMode::StreamBytes as i32
                        } else {
                            Err(Status::failed_precondition(
                                "stream or whole-body response inspection is required",
                            ))?
                        };
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::PreflightResult(
                                HttpResponsePreflightResult {
                                    action: Some(http_response_preflight_result::Action::Inspect(
                                        HttpResponsePreflightInspect {
                                            body_mode,
                                            header_mutations: Vec::new(),
                                        },
                                    )),
                                    ..Default::default()
                                },
                            )),
                        };
                    }
                    Some(http_response_event::Event::Body(unit)) => {
                        let body_sequence = unit.sequence;
                        let data = match unit.payload {
                            Some(http_response_body_unit::Payload::Data(data)) => data,
                            None => Vec::new(),
                        };
                        let content_bytes = if body_mode
                            == pb::HttpResponseBodyMode::StreamBytes as i32
                        {
                            if data.len() > service.max_payload_bytes as usize {
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware payload limit exceeded"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                            data
                        } else {
                            body.extend(data);
                            if body.len() > service.max_payload_bytes as usize {
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware payload limit exceeded"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                            if !unit.end_of_stream {
                                continue;
                            }
                            body.clone()
                        };
                        let content = String::from_utf8(content_bytes)
                            .map_err(|_| Status::invalid_argument("response body must be UTF-8"))?;
                        let result = match service
                            .evaluate(&content, &request_id, &plan, false)
                            .await
                        {
                            Ok(result) => result,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    "Rust middleware control plane unavailable; blocking response: {error}"
                                );
                                yield HttpResponseEventResult {
                                    result: Some(http_response_event_result::Result::BodyResult(
                                        HttpResponseBodyResult {
                                            sequence: body_sequence,
                                            action: Some(
                                                http_response_body_result::Action::BlockDelivery(
                                                    HttpResponseBlockDelivery {},
                                                ),
                                            ),
                                            reason: "AI Guardian middleware control plane unavailable".to_string(),
                                            reason_code: "middleware_control_plane_unavailable".to_string(),
                                            ..Default::default()
                                        },
                                    )),
                                };
                                return;
                            }
                        };
                        info!(
                            request_id = %request_id,
                            blocked = result.blocked,
                            reason_code = %result.reason_code,
                            finding_count = result.findings.len(),
                            "Rust middleware response decision"
                        );
                        let action = if result.blocked {
                            http_response_body_result::Action::BlockDelivery(
                                HttpResponseBlockDelivery {},
                            )
                        } else if let Some(redacted) = result.redacted {
                            http_response_body_result::Action::Transform(
                                HttpResponseBodyTransform {
                                    replacement: Some(
                                        pb::http_response_body_transform::Replacement::Data(
                                            redacted.into_bytes(),
                                        ),
                                    ),
                                },
                            )
                        } else {
                            http_response_body_result::Action::PassThrough(
                                pb::HttpResponseBodyPassThrough {},
                            )
                        };
                        let blocked = result.blocked;
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::BodyResult(
                                HttpResponseBodyResult {
                                    sequence: body_sequence,
                                    action: Some(action),
                                    reason: result.reason,
                                    reason_code: result.reason_code,
                                    findings: result.findings,
                                    metadata: result.metadata,
                                    ..Default::default()
                                },
                            )),
                        };
                        if blocked {
                            return;
                        }
                    }
                    Some(http_response_event::Event::Trailers(_)) => {
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::TrailersResult(
                                HttpResponseTrailersResult::default(),
                            )),
                        };
                    }
                    Some(http_response_event::Event::SessionEnd(_)) => break,
                    None => Err(Status::invalid_argument("response event is required"))?,
                }
            }
        };
        Ok(Response::new(Box::pin(stream)))
    }
}
