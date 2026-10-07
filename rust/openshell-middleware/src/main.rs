//! Rust OpenShell supervisor middleware.
//!
//! OpenShell owns the external gRPC boundary. Scanner execution stays in the
//! long-lived AI Guardian daemon and is reached through its permission-protected
//! Unix socket (or explicit authenticated REST for remote deployments).

use std::env;
use std::fs;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::pin::Pin;

use async_stream::try_stream;
use prost_types::{value::Kind, Struct};
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::UnixStream;
use tokio_stream::Stream;
use tonic::{Request, Response, Status};
use tracing::{info, warn};

pub mod openshell {
    pub mod extension {
        pub mod v1 {
            tonic::include_proto!("openshell.extension.v1");
        }
    }

    pub mod middleware {
        pub mod v1 {
            tonic::include_proto!("openshell.middleware.v1");
        }
    }
}

use openshell::extension::v1::{PeerMetadata, ProtocolVersion};
use openshell::middleware::v1::http_response_pre_return_server::{
    HttpResponsePreReturn, HttpResponsePreReturnServer,
};
use openshell::middleware::v1::supervisor_middleware_server::{
    SupervisorMiddleware, SupervisorMiddlewareServer,
};
use openshell::middleware::v1::{
    self as pb, http_response_body_result, http_response_body_unit, http_response_event,
    http_response_event_result, http_response_preflight_result, web_socket_message,
    web_socket_session_event, web_socket_session_event_result, Decision, Finding,
    HttpRequestEvaluation, HttpRequestResult, HttpResponseBlockDelivery, HttpResponseBodyResult,
    HttpResponseBodyTransform, HttpResponseEvent, HttpResponseEventResult,
    HttpResponsePreflightInspect, HttpResponsePreflightResult, HttpResponseTrailersResult,
    MiddlewareBinding, MiddlewareDescribeRequest, MiddlewareManifest,
    SupervisorMiddlewareOperation, SupervisorMiddlewarePhase, ValidateConfigRequest,
    ValidateConfigResponse, WebSocketMessageResult, WebSocketPreflightAction,
    WebSocketPreflightDecision, WebSocketSessionEventResult,
};

const CONTRACT_CAPABILITY: &str = "openshell.supervisor-middleware.contract";
const IMPLEMENTATION_NAME: &str = "ai-guardian/rust-middleware";
const MAX_PAYLOAD_BYTES: u64 = 262_144;

#[derive(Debug, thiserror::Error)]
enum AppError {
    #[error("{0}")]
    Message(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Http(#[from] reqwest::Error),
}

#[derive(Clone)]
struct DaemonClient {
    transport: DaemonTransport,
}

#[derive(Clone)]
enum DaemonTransport {
    Unix {
        path: PathBuf,
    },
    Http {
        http: reqwest::Client,
        base_url: String,
        token: String,
    },
}

#[derive(Debug, Serialize)]
struct CheckRequest<'a> {
    content: &'a str,
    checks: Vec<&'static str>,
    action: &'static str,
    correlation_id: String,
}

#[derive(Debug, Deserialize, Default)]
struct CheckResponse {
    #[serde(default)]
    clean: bool,
    #[serde(default)]
    findings: Vec<DaemonFinding>,
    redacted: Option<String>,
}

#[derive(Debug, Deserialize)]
struct DaemonSocketResponse {
    #[serde(rename = "type")]
    message_type: String,
    data: Option<serde_json::Value>,
    error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct DaemonFinding {
    #[serde(rename = "type")]
    finding_type: String,
}

#[derive(Debug)]
struct Evaluation {
    blocked: bool,
    redacted: Option<String>,
    findings: Vec<Finding>,
    reason: String,
    reason_code: String,
}

#[derive(Clone, Debug)]
struct ScanPlan {
    checks: Vec<&'static str>,
    response_redaction: bool,
}

fn parse_socket_check_response(envelope: DaemonSocketResponse) -> Result<CheckResponse, AppError> {
    if envelope.message_type != "response" {
        return Err(AppError::Message(
            "unexpected daemon IPC response".to_string(),
        ));
    }
    if let Some(error) = envelope.error {
        return Err(AppError::Message(error));
    }
    let data = envelope
        .data
        .ok_or_else(|| AppError::Message("daemon IPC response has no data".to_string()))?;
    if let Some(error) = data.get("error").and_then(serde_json::Value::as_str) {
        return Err(AppError::Message(error.to_string()));
    }
    let check_data = data.get("data").unwrap_or(&data).clone();
    Ok(serde_json::from_value(check_data)?)
}

impl DaemonClient {
    fn from_environment() -> Result<Self, AppError> {
        if let Ok(value) = env::var("AI_GUARDIAN_DAEMON_URL") {
            if !value.trim().is_empty() {
                let token = daemon_token_from_environment()?;
                let http = reqwest::Client::builder()
                    .connect_timeout(std::time::Duration::from_secs(2))
                    .timeout(std::time::Duration::from_secs(10))
                    .build()?;
                return Ok(Self {
                    transport: DaemonTransport::Http {
                        http,
                        base_url: value.trim_end_matches('/').to_string(),
                        token,
                    },
                });
            }
        }
        Ok(Self {
            transport: DaemonTransport::Unix {
                path: env::var("AI_GUARDIAN_DAEMON_SOCKET")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| default_state_dir().join("daemon.sock")),
            },
        })
    }

    async fn check(
        &self,
        content: &str,
        request_id: &str,
        checks: Vec<&'static str>,
    ) -> Result<CheckResponse, AppError> {
        let body = CheckRequest {
            content,
            checks,
            action: "block",
            correlation_id: request_id.to_string(),
        };
        match &self.transport {
            DaemonTransport::Unix { path } => self.check_unix(path, &body).await,
            DaemonTransport::Http {
                http,
                base_url,
                token,
            } => {
                let response = http
                    .post(format!("{base_url}/api/check"))
                    .header(AUTHORIZATION, format!("Bearer {token}"))
                    .header(CONTENT_TYPE, "application/json")
                    .json(&body)
                    .send()
                    .await?;
                if !response.status().is_success() {
                    return Err(AppError::Message(format!(
                        "AI Guardian daemon /api/check returned {}",
                        response.status()
                    )));
                }
                Ok(response.json().await?)
            }
        }
    }

    async fn check_unix(
        &self,
        path: &Path,
        body: &CheckRequest<'_>,
    ) -> Result<CheckResponse, AppError> {
        tokio::time::timeout(
            std::time::Duration::from_secs(10),
            self.check_unix_inner(path, body),
        )
        .await
        .map_err(|_| AppError::Message("daemon IPC request timed out".to_string()))?
    }

    async fn check_unix_inner(
        &self,
        path: &Path,
        body: &CheckRequest<'_>,
    ) -> Result<CheckResponse, AppError> {
        let mut stream = UnixStream::connect(path).await.map_err(|error| {
            AppError::Message(format!(
                "cannot connect to daemon socket {}: {error}",
                path.display()
            ))
        })?;
        let envelope = serde_json::json!({
            "version": 1,
            "type": "sdk_check",
            "data": {
                "check_type": "middleware",
                "text": body.content,
                "checks": body.checks,
                "action": body.action,
                "correlation_id": body.correlation_id,
            }
        });
        let payload = serde_json::to_vec(&envelope)?;
        let length = u32::try_from(payload.len())
            .map_err(|_| AppError::Message("daemon IPC request is too large".to_string()))?;
        stream.write_u32(length).await?;
        stream.write_all(&payload).await?;
        stream.flush().await?;
        let response_length = stream.read_u32().await?;
        if response_length > 10 * 1024 * 1024 {
            return Err(AppError::Message(
                "daemon IPC response is too large".to_string(),
            ));
        }
        let mut response = vec![0_u8; response_length as usize];
        stream.read_exact(&mut response).await?;
        let envelope: DaemonSocketResponse = serde_json::from_slice(&response)?;
        parse_socket_check_response(envelope)
    }
}

fn daemon_token_from_environment() -> Result<String, AppError> {
    let token = match env::var("AI_GUARDIAN_DAEMON_TOKEN") {
        Ok(value) if !value.is_empty() => value,
        _ => {
            let token_path = env::var("AI_GUARDIAN_DAEMON_TOKEN_FILE")
                .map(PathBuf::from)
                .unwrap_or_else(|_| default_state_dir().join("daemon.token"));
            fs::read_to_string(token_path)?.trim().to_string()
        }
    };
    if token.is_empty() {
        return Err(AppError::Message(
            "AI Guardian daemon REST token is empty".to_string(),
        ));
    }
    Ok(token)
}

#[derive(Clone)]
struct MiddlewareService {
    daemon: DaemonClient,
    registration_name: String,
}

impl MiddlewareService {
    fn findings(findings: &[DaemonFinding]) -> Vec<Finding> {
        findings
            .iter()
            .map(|finding| Finding {
                r#type: finding.finding_type.clone(),
                label: "AI Guardian finding".to_string(),
                count: 1,
                confidence: "high".to_string(),
                severity: "high".to_string(),
            })
            .collect()
    }

    async fn evaluate(
        &self,
        content: &str,
        request_id: &str,
        plan: &ScanPlan,
        block_all_findings: bool,
    ) -> Result<Evaluation, AppError> {
        if plan.checks.is_empty() {
            return Ok(Evaluation {
                blocked: false,
                redacted: None,
                findings: Vec::new(),
                reason: String::new(),
                reason_code: String::new(),
            });
        }
        // Run blocking semantic checks first.  The daemon's legacy combined
        // secrets/PII path can fail independently; it must not hide a valid
        // prompt-injection denial behind a generic middleware failure.
        let semantic_checks: Vec<_> = plan
            .checks
            .iter()
            .copied()
            .filter(|check| matches!(*check, "injection" | "context_poisoning"))
            .collect();
        let semantic = if semantic_checks.is_empty() {
            CheckResponse::default()
        } else {
            self.daemon
                .check(content, request_id, semantic_checks)
                .await?
        };
        let semantic_blocking = semantic.findings.iter().any(|finding| {
            matches!(
                finding.finding_type.as_str(),
                "prompt_injection" | "context_poisoning" | "jailbreak" | "canary_detected"
            )
        });
        if semantic_blocking {
            return Ok(Evaluation {
                blocked: true,
                redacted: None,
                findings: Self::findings(&semantic.findings),
                reason: "AI Guardian finding".to_string(),
                reason_code: "semantic_content_blocked".to_string(),
            });
        }

        let sensitive_checks: Vec<_> = plan
            .checks
            .iter()
            .copied()
            .filter(|check| matches!(*check, "secrets" | "pii" | "offensive"))
            .collect();
        let sensitive = if sensitive_checks.is_empty() {
            CheckResponse::default()
        } else {
            self.daemon
                .check(content, request_id, sensitive_checks)
                .await?
        };
        let combined_findings: Vec<_> = semantic
            .findings
            .iter()
            .chain(sensitive.findings.iter())
            .cloned()
            .collect();
        let findings = Self::findings(&combined_findings);
        let blocking = sensitive
            .findings
            .iter()
            .any(|finding| matches!(finding.finding_type.as_str(), "jailbreak"));
        let redacted = if plan.response_redaction {
            sensitive.redacted.clone()
        } else {
            None
        };
        Ok(Evaluation {
            blocked: !sensitive.clean && (block_all_findings || blocking || redacted.is_none()),
            redacted,
            findings,
            reason: if sensitive.clean {
                String::new()
            } else {
                "AI Guardian finding".to_string()
            },
            reason_code: if sensitive.clean {
                String::new()
            } else if blocking {
                "semantic_content_blocked".to_string()
            } else {
                "sensitive_content_detected".to_string()
            },
        })
    }

    fn validate_gateway(gateway: Option<PeerMetadata>) -> Result<(), Status> {
        let gateway = gateway.ok_or_else(|| {
            Status::failed_precondition("gateway did not provide protocol metadata")
        })?;
        let version = gateway
            .protocol_version
            .ok_or_else(|| Status::failed_precondition("gateway protocol version is missing"))?;
        if version.major != 1 {
            return Err(Status::failed_precondition(format!(
                "unsupported OpenShell protocol {}.{}",
                version.major, version.minor
            )));
        }
        if !gateway
            .supported_capabilities
            .iter()
            .any(|value| value == CONTRACT_CAPABILITY)
        {
            return Err(Status::failed_precondition(
                "gateway does not support supervisor-middleware contract",
            ));
        }
        Ok(())
    }

    fn scan_plan(config: Option<&Struct>) -> Result<ScanPlan, Status> {
        let Some(config) = config else {
            return Ok(ScanPlan {
                checks: vec!["injection", "context_poisoning", "secrets", "pii"],
                response_redaction: true,
            });
        };
        let response_redaction = config
            .fields
            .get("response_redaction")
            .and_then(|value| match value.kind.as_ref() {
                Some(Kind::BoolValue(value)) => Some(*value),
                _ => None,
            })
            .unwrap_or(true);
        let ownership =
            config
                .fields
                .get("scanner_ownership")
                .and_then(|value| match value.kind.as_ref() {
                    Some(Kind::StructValue(value)) => Some(&value.fields),
                    _ => None,
                });
        let mut checks = Vec::new();
        let mut redaction_owned = ownership.is_none();
        if let Some(values) = ownership {
            for (scanner, value) in values {
                let mode = match value.kind.as_ref() {
                    Some(Kind::StringValue(value)) => value.as_str(),
                    _ => {
                        return Err(Status::invalid_argument(format!(
                            "scanner ownership for {scanner} must be a string"
                        )))
                    }
                };
                if mode == "hooks" {
                    continue;
                }
                if mode == "both" {
                    return Err(Status::failed_precondition(format!(
                        "scanner ownership 'both' is not supported by Rust middleware for {scanner}"
                    )));
                }
                if mode != "middleware" && mode != "auto" {
                    return Err(Status::invalid_argument(format!(
                        "unsupported scanner ownership mode for {scanner}: {mode}"
                    )));
                }
                match scanner.as_str() {
                    "prompt_injection" => checks.push("injection"),
                    "context_poisoning" => checks.push("context_poisoning"),
                    "secret_scanning" => checks.push("secrets"),
                    "scan_pii" => checks.push("pii"),
                    "scan_offensive" => checks.push("offensive"),
                    "canary_detection" => checks.push("canary"),
                    "secret_redaction" => redaction_owned = true,
                    "supply_chain" | "config_file_scanning" => {
                        return Err(Status::failed_precondition(format!(
                            "scanner {scanner} is not available through daemon REST middleware"
                        )));
                    }
                    _ => {
                        return Err(Status::invalid_argument(format!(
                            "unknown scanner ownership entry: {scanner}"
                        )));
                    }
                }
            }
        } else {
            checks.extend(["injection", "context_poisoning", "secrets", "pii"]);
        }
        Ok(ScanPlan {
            checks,
            response_redaction: response_redaction && redaction_owned,
        })
    }
}

#[tonic::async_trait]
impl SupervisorMiddleware for MiddlewareService {
    type EvaluateWebSocketSessionStream =
        Pin<Box<dyn Stream<Item = Result<pb::WebSocketSessionEventResult, Status>> + Send>>;

    async fn describe(
        &self,
        request: Request<MiddlewareDescribeRequest>,
    ) -> Result<Response<MiddlewareManifest>, Status> {
        Self::validate_gateway(request.into_inner().gateway)?;
        let supported_capabilities = vec![
            CONTRACT_CAPABILITY.to_string(),
            "openshell.middleware.request-scanning".to_string(),
            "openshell.middleware.response-redaction".to_string(),
            "openshell.middleware.semantic-scanning".to_string(),
            "openshell.middleware.websocket-text".to_string(),
        ];
        Ok(Response::new(MiddlewareManifest {
            name: IMPLEMENTATION_NAME.to_string(),
            service_version: env!("CARGO_PKG_VERSION").to_string(),
            bindings: vec![
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::HttpRequest as i32,
                    phase: SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: MAX_PAYLOAD_BYTES,
                    request_timeout: None,
                },
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::HttpResponse as i32,
                    phase: SupervisorMiddlewarePhase::PreReturn as i32,
                    max_payload_bytes: MAX_PAYLOAD_BYTES,
                    request_timeout: None,
                },
                MiddlewareBinding {
                    operation: SupervisorMiddlewareOperation::WebsocketMessage as i32,
                    phase: SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: MAX_PAYLOAD_BYTES,
                    request_timeout: None,
                },
            ],
            expected_audience: String::new(),
            extension: Some(PeerMetadata {
                protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
                implementation_name: IMPLEMENTATION_NAME.to_string(),
                implementation_version: env!("CARGO_PKG_VERSION").to_string(),
                supported_capabilities,
                required_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
            }),
        }))
    }

    async fn validate_config(
        &self,
        request: Request<ValidateConfigRequest>,
    ) -> Result<Response<ValidateConfigResponse>, Status> {
        let request = request.into_inner();
        if !request.middleware_name.is_empty() && request.middleware_name != self.registration_name
        {
            return Ok(Response::new(ValidateConfigResponse {
                valid: false,
                reason: "middleware registration name does not match".to_string(),
            }));
        }
        if let Err(error) = Self::scan_plan(request.config.as_ref()) {
            return Ok(Response::new(ValidateConfigResponse {
                valid: false,
                reason: error.message().to_string(),
            }));
        }
        Ok(Response::new(ValidateConfigResponse {
            valid: true,
            reason: String::new(),
        }))
    }

    async fn evaluate_http_request(
        &self,
        request: Request<HttpRequestEvaluation>,
    ) -> Result<Response<HttpRequestResult>, Status> {
        let request = request.into_inner();
        let request_id = request
            .context
            .as_ref()
            .map(|value| value.request_id.as_str())
            .unwrap_or("");
        let host = request
            .target
            .as_ref()
            .map(|target| target.host.as_str())
            .unwrap_or("");
        let method = request
            .target
            .as_ref()
            .map(|target| target.method.as_str())
            .unwrap_or("");
        let body_bytes = request.body.len();
        if request.phase != SupervisorMiddlewarePhase::PreCredentials as i32 {
            warn!(
                request_id,
                host,
                method,
                phase = request.phase,
                body_bytes,
                "Rust middleware rejected unsupported request phase"
            );
            return Err(Status::invalid_argument("unsupported HTTP request phase"));
        }
        if request.body.is_empty() {
            info!(
                request_id,
                host, method, body_bytes, "Rust middleware allowed empty request body"
            );
            return Ok(Response::new(HttpRequestResult {
                decision: Decision::Allow as i32,
                ..Default::default()
            }));
        }
        let content = String::from_utf8(request.body)
            .map_err(|_| Status::invalid_argument("request body must be UTF-8"))?;
        let request_id = request_id.to_string();
        let plan = Self::scan_plan(request.config.as_ref())?;
        let result = self
            .evaluate(&content, &request_id, &plan, true)
            .await
            .map_err(|error| Status::unavailable(error.to_string()))?;
        info!(
            request_id = %request_id,
            host,
            method,
            body_bytes,
            blocked = result.blocked,
            reason_code = %result.reason_code,
            finding_count = result.findings.len(),
            "Rust middleware request decision"
        );
        Ok(Response::new(HttpRequestResult {
            decision: if result.blocked {
                Decision::Deny as i32
            } else {
                Decision::Allow as i32
            },
            reason: result.reason,
            reason_code: result.reason_code,
            findings: result.findings,
            ..Default::default()
        }))
    }

    async fn evaluate_web_socket_session(
        &self,
        request: Request<tonic::Streaming<pb::WebSocketSessionEvent>>,
    ) -> Result<Response<Self::EvaluateWebSocketSessionStream>, Status> {
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
            let mut plan = ScanPlan {
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
                            != SupervisorMiddlewarePhase::PreCredentials as i32
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
                        if plan.checks.is_empty() {
                            skipped = true;
                            yield WebSocketSessionEventResult {
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
                            yield WebSocketSessionEventResult {
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
                                yield WebSocketSessionEventResult {
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
                        if text.len() > MAX_PAYLOAD_BYTES as usize {
                            info!(
                                request_id = %request_id,
                                host = %target_host,
                                middleware = %middleware_name,
                                sequence,
                                body_bytes = text.len(),
                                "Rust middleware denied oversized WebSocket message"
                            );
                            yield WebSocketSessionEventResult {
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
                        let result = service
                            .evaluate(&text, &request_id, &plan, true)
                            .await
                            .map_err(|error| Status::unavailable(error.to_string()))?;
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
                        yield WebSocketSessionEventResult {
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

#[tonic::async_trait]
impl HttpResponsePreReturn for MiddlewareService {
    type EvaluateStream =
        Pin<Box<dyn Stream<Item = Result<HttpResponseEventResult, Status>> + Send>>;

    async fn evaluate(
        &self,
        request: Request<tonic::Streaming<HttpResponseEvent>>,
    ) -> Result<Response<Self::EvaluateStream>, Status> {
        let mut events = request.into_inner();
        let service = self.clone();
        let stream = try_stream! {
            let mut request_id = String::new();
            let mut body = Vec::new();
            let mut plan = ScanPlan {
                checks: vec!["injection", "context_poisoning", "secrets", "pii"],
                response_redaction: true,
            };
            while let Some(event) = events.message().await? {
                match event.event {
                    Some(http_response_event::Event::Preflight(preflight)) => {
                        request_id = preflight.context.as_ref().map(|value| value.request_id.clone()).unwrap_or_default();
                        plan = MiddlewareService::scan_plan(preflight.config.as_ref())?;
                        if !preflight.permitted_body_modes.iter().any(|mode| *mode == pb::HttpResponseBodyMode::WholeBodyBytes as i32) {
                            Err(Status::failed_precondition("whole-body response inspection is required"))?;
                        }
                        yield HttpResponseEventResult {
                            result: Some(http_response_event_result::Result::PreflightResult(
                                HttpResponsePreflightResult {
                                    action: Some(http_response_preflight_result::Action::Inspect(
                                        HttpResponsePreflightInspect {
                                            body_mode: pb::HttpResponseBodyMode::WholeBodyBytes as i32,
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
                        if let Some(http_response_body_unit::Payload::Data(data)) = unit.payload {
                            body.extend(data);
                        }
                        if unit.end_of_stream {
                            let content = String::from_utf8(body.clone())
                                .map_err(|_| Status::invalid_argument("response body must be UTF-8"))?;
                            let result = service.evaluate(&content, &request_id, &plan, false).await
                                .map_err(|error| Status::unavailable(error.to_string()))?;
                            info!(
                                request_id = %request_id,
                                blocked = result.blocked,
                                reason_code = %result.reason_code,
                                finding_count = result.findings.len(),
                                "Rust middleware response decision"
                            );
                            let action = if result.blocked {
                                http_response_body_result::Action::BlockDelivery(HttpResponseBlockDelivery {})
                            } else if let Some(redacted) = result.redacted {
                                http_response_body_result::Action::Transform(HttpResponseBodyTransform {
                                    replacement: Some(
                                        pb::http_response_body_transform::Replacement::Data(
                                            redacted.into_bytes(),
                                        ),
                                    ),
                                })
                            } else {
                                http_response_body_result::Action::PassThrough(
                                    pb::HttpResponseBodyPassThrough {},
                                )
                            };
                            yield HttpResponseEventResult {
                                result: Some(http_response_event_result::Result::BodyResult(
                                    HttpResponseBodyResult {
                                        sequence: body_sequence,
                                        action: Some(action),
                                        reason: result.reason,
                                        reason_code: result.reason_code,
                                        findings: result.findings,
                                        ..Default::default()
                                    },
                                )),
                            };
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

fn default_state_dir() -> PathBuf {
    env::var_os("AI_GUARDIAN_STATE_DIR")
        .map(PathBuf::from)
        .or_else(|| {
            env::var_os("XDG_STATE_HOME").map(|path| PathBuf::from(path).join("ai-guardian"))
        })
        .or_else(|| {
            if cfg!(windows) {
                env::var_os("LOCALAPPDATA")
                    .map(|path| PathBuf::from(path).join("ai-guardian/state"))
                    .or_else(|| {
                        env::var_os("USERPROFILE")
                            .map(|path| PathBuf::from(path).join("AppData/Local/ai-guardian/state"))
                    })
            } else {
                env::var_os("HOME").map(|path| PathBuf::from(path).join(".local/state/ai-guardian"))
            }
        })
        .unwrap_or_else(|| PathBuf::from(".ai-guardian"))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let bind =
        env::var("AI_GUARDIAN_MIDDLEWARE_BIND").unwrap_or_else(|_| "127.0.0.1:50051".to_string());
    let address: SocketAddr = bind.parse()?;
    let service = MiddlewareService {
        daemon: DaemonClient::from_environment()?,
        registration_name: env::var("AI_GUARDIAN_MIDDLEWARE_REGISTRATION")
            .unwrap_or_else(|_| "content-guard-test".to_string()),
    };

    info!(%address, "Rust OpenShell middleware listening");
    let result = tonic::transport::Server::builder()
        .add_service(SupervisorMiddlewareServer::new(service.clone()))
        .add_service(HttpResponsePreReturnServer::new(service))
        .serve_with_shutdown(address, shutdown_signal())
        .await;
    remove_pid_file_if_owned();
    result?;
    Ok(())
}

async fn shutdown_signal() {
    #[cfg(unix)]
    {
        let mut terminate =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("install SIGTERM handler");
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {}
            _ = terminate.recv() => {}
        }
    }
    #[cfg(not(unix))]
    {
        let _ = tokio::signal::ctrl_c().await;
    }
}

fn remove_pid_file_if_owned() {
    let Some(path) = env::var_os("AI_GUARDIAN_MIDDLEWARE_PID_FILE") else {
        return;
    };
    let path = PathBuf::from(path);
    let Ok(raw) = fs::read_to_string(&path) else {
        return;
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&raw) else {
        return;
    };
    if value.get("pid").and_then(|pid| pid.as_u64()) == Some(std::process::id() as u64) {
        let _ = fs::remove_file(path);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;

    #[test]
    fn gateway_metadata_requires_contract_capability() {
        let error = MiddlewareService::validate_gateway(Some(PeerMetadata {
            protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
            supported_capabilities: Vec::new(),
            ..Default::default()
        }))
        .expect_err("missing contract capability");
        assert!(error.message().contains("supervisor-middleware contract"));
    }

    #[test]
    fn scanner_plan_routes_supported_keys_and_rejects_local_only_scanners() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([
                            (
                                "prompt_injection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "supply_chain".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                        ]),
                    })),
                },
            )]),
        };
        let error = MiddlewareService::scan_plan(Some(&config)).expect_err("local-only scanner");
        assert!(error.message().contains("supply_chain"));
    }

    #[tokio::test]
    async fn describe_advertises_text_websocket_binding() {
        let service = MiddlewareService {
            daemon: DaemonClient {
                transport: DaemonTransport::Unix {
                    path: PathBuf::from("/unused/daemon.sock"),
                },
            },
            registration_name: "content-guard-test".to_string(),
        };
        let response = SupervisorMiddleware::describe(
            &service,
            Request::new(MiddlewareDescribeRequest {
                gateway: Some(PeerMetadata {
                    protocol_version: Some(ProtocolVersion { major: 1, minor: 0 }),
                    supported_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
                    ..Default::default()
                }),
            }),
        )
        .await
        .expect("compatible gateway metadata")
        .into_inner();

        assert!(response
            .extension
            .expect("extension metadata")
            .supported_capabilities
            .iter()
            .any(|capability| capability == "openshell.middleware.websocket-text"));
        assert!(response.bindings.iter().any(|binding| {
            binding.operation == SupervisorMiddlewareOperation::WebsocketMessage as i32
                && binding.phase == SupervisorMiddlewarePhase::PreCredentials as i32
        }));
    }

    #[test]
    fn parses_nested_daemon_socket_check_response() {
        let envelope: DaemonSocketResponse = serde_json::from_value(serde_json::json!({
            "type": "response",
            "data": {
                "data": {
                    "clean": true,
                    "findings": []
                }
            }
        }))
        .expect("valid daemon response envelope");
        let response = parse_socket_check_response(envelope).expect("nested check result");
        assert!(response.clean);
        assert!(response.findings.is_empty());
    }
}
