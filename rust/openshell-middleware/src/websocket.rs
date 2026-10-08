//! Text WebSocket session inspection capability.

use std::collections::HashMap;

use async_stream::try_stream;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

use super::daemon::pause_metadata;
use super::openshell::middleware::v1::{
    self as pb, web_socket_message, web_socket_session_event,
    web_socket_session_event_result, Decision, WebSocketMessageResult,
    WebSocketPreflightAction, WebSocketPreflightDecision,
};
use super::MiddlewareService;

impl MiddlewareService {
    pub(super) async fn evaluate_web_socket_session_rpc(
        &self,
        request: Request<tonic::Streaming<pb::WebSocketSessionEvent>>,
    ) -> Result<Response<super::WebSocketStream>, Status> {
        let mut events = request.into_inner();
        let service = self.clone();
        let stream = try_stream! {
            let mut preflight_seen = false;
            let mut started = false;
            let mut skipped = false;
            let mut sequence = 0_u64;
            let mut request_id = String::new();
            let mut target_host = String::new();
            let mut middleware_name = String::new();
            let mut plan = super::policy::ScanPlan {
                checks: Vec::new(),
                response_redaction: false,
            };

            while let Some(event) = events.message().await? {
                match event.event {
                    Some(web_socket_session_event::Event::Preflight(preflight)) => {
                        if preflight_seen || started {
                            Err(Status::failed_precondition(
                                "duplicate WebSocket preflight",
                            ))?;
                        }
                        if preflight.phase
                            != pb::SupervisorMiddlewarePhase::PreCredentials as i32
                        {
                            Err(Status::invalid_argument("unsupported WebSocket phase"))?;
                        }
                        let context = preflight.context.as_ref().ok_or_else(|| {
                            Status::failed_precondition(
                                "WebSocket preflight context is required",
                            )
                        })?;
                        let target = preflight.target.as_ref().ok_or_else(|| {
                            Status::failed_precondition(
                                "WebSocket preflight target is required",
                            )
                        })?;
                        request_id = context.request_id.clone();
                        target_host = target.host.clone();
                        middleware_name = preflight.middleware_name.clone();
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        preflight_seen = true;
                        match service.daemon.pause_status().await {
                            Ok(Some(response)) => {
                                let metadata = pause_metadata(&response);
                                yield pb::WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::PreflightDecision(
                                            WebSocketPreflightDecision {
                                                action: WebSocketPreflightAction::Deny as i32,
                                                reason: response.message,
                                                reason_code: response.reason_code,
                                                metadata,
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                            Ok(None) => {}
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    "Rust middleware control plane unavailable; denying WebSocket upgrade: {error}"
                                );
                                yield pb::WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::PreflightDecision(
                                            WebSocketPreflightDecision {
                                                action: WebSocketPreflightAction::Deny as i32,
                                                reason: "AI Guardian middleware control plane unavailable".to_string(),
                                                reason_code: "middleware_control_plane_unavailable".to_string(),
                                                metadata: HashMap::new(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        }
                        if plan.checks.is_empty() {
                            skipped = true;
                            yield pb::WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::PreflightDecision(
                                        WebSocketPreflightDecision {
                                            action: WebSocketPreflightAction::Skip as i32,
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                        } else {
                            yield pb::WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::PreflightDecision(
                                        WebSocketPreflightDecision {
                                            action: WebSocketPreflightAction::Inspect as i32,
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                        }
                    }
                    Some(web_socket_session_event::Event::SessionStart(_)) => {
                        if !preflight_seen || skipped || started {
                            Err(Status::failed_precondition(
                                "invalid WebSocket session lifecycle",
                            ))?;
                        }
                        started = true;
                    }
                    Some(web_socket_session_event::Event::Message(message)) => {
                        if !preflight_seen || skipped || !started {
                            Err(Status::failed_precondition(
                                "WebSocket message before session start",
                            ))?;
                        }
                        if message.sequence == 0 || message.sequence <= sequence {
                            Err(Status::invalid_argument(
                                "WebSocket message sequence must increase",
                            ))?;
                        }
                        sequence = message.sequence;
                        let payload = message.payload.ok_or_else(|| {
                            Status::invalid_argument("WebSocket payload is required")
                        })?;
                        let text = match payload {
                            web_socket_message::Payload::Text(text) => text,
                            web_socket_message::Payload::Binary(_) => {
                                info!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    middleware = %middleware_name,
                                    sequence,
                                    "Rust middleware denied binary WebSocket message"
                                );
                                yield pb::WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::MessageResult(
                                            WebSocketMessageResult {
                                                sequence,
                                                decision: Decision::Deny as i32,
                                                reason: "binary WebSocket payloads are unsupported"
                                                    .to_string(),
                                                reason_code: "unsupported_websocket_payload"
                                                    .to_string(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        };
                        if text.len() > service.max_payload_bytes as usize {
                            info!(
                                request_id = %request_id,
                                host = %target_host,
                                middleware = %middleware_name,
                                sequence,
                                body_bytes = text.len(),
                                "Rust middleware denied oversized WebSocket message"
                            );
                            yield pb::WebSocketSessionEventResult {
                                result: Some(
                                    web_socket_session_event_result::Result::MessageResult(
                                        WebSocketMessageResult {
                                            sequence,
                                            decision: Decision::Deny as i32,
                                            reason: "WebSocket payload exceeds configured limit"
                                                .to_string(),
                                            reason_code: "payload_limit_exceeded".to_string(),
                                            ..Default::default()
                                        },
                                    ),
                                ),
                            };
                            return;
                        }
                        let result = match service
                            .evaluate(&text, &request_id, &plan, true)
                            .await
                        {
                            Ok(result) => result,
                            Err(error) => {
                                warn!(
                                    request_id = %request_id,
                                    host = %target_host,
                                    middleware = %middleware_name,
                                    sequence,
                                    "Rust middleware control plane unavailable; denying WebSocket message: {error}"
                                );
                                yield pb::WebSocketSessionEventResult {
                                    result: Some(
                                        web_socket_session_event_result::Result::MessageResult(
                                            WebSocketMessageResult {
                                                sequence,
                                                decision: Decision::Deny as i32,
                                                reason: "AI Guardian middleware control plane unavailable".to_string(),
                                                reason_code: "middleware_control_plane_unavailable".to_string(),
                                                ..Default::default()
                                            },
                                        ),
                                    ),
                                };
                                return;
                            }
                        };
                        let blocked = result.blocked;
                        let reason_code = if blocked {
                            result.reason_code.clone()
                        } else {
                            String::new()
                        };
                        info!(
                            request_id = %request_id,
                            host = %target_host,
                            middleware = %middleware_name,
                            sequence,
                            blocked,
                            reason_code = %reason_code,
                            finding_count = result.findings.len(),
                            "Rust middleware WebSocket message decision"
                        );
                        yield pb::WebSocketSessionEventResult {
                            result: Some(
                                web_socket_session_event_result::Result::MessageResult(
                                    WebSocketMessageResult {
                                        sequence,
                                        decision: if blocked {
                                            Decision::Deny as i32
                                        } else {
                                            Decision::Allow as i32
                                        },
                                        reason: result.reason,
                                        reason_code,
                                        findings: result.findings,
                                        metadata: result.metadata,
                                        ..Default::default()
                                    },
                                ),
                            ),
                        };
                        if blocked {
                            return;
                        }
                    }
                    Some(web_socket_session_event::Event::SessionEnd(_)) => return,
                    None => Err(Status::invalid_argument("WebSocket event is required"))?,
                }
            }
        };
        Ok(Response::new(Box::pin(stream)))
    }
}
