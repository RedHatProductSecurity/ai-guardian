//! Rust OpenShell supervisor middleware.
//!
//! OpenShell owns the external gRPC boundary. Scanner execution stays in the
//! long-lived AI Guardian daemon and is reached through its authenticated,
//! loopback-only REST API.

use std::env;
use std::fs;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::pin::Pin;

use async_stream::try_stream;
use prost_types::{value::Kind, Struct};
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use tokio_stream::Stream;
use tonic::{Request, Response, Status};
use tracing::info;

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
    http_response_event_result, http_response_preflight_result, Decision, Finding,
    HttpRequestEvaluation, HttpRequestResult, HttpResponseBlockDelivery, HttpResponseBodyResult,
    HttpResponseBodyTransform, HttpResponseEvent, HttpResponseEventResult,
    HttpResponsePreflightInspect, HttpResponsePreflightResult, HttpResponseTrailersResult,
    MiddlewareBinding, MiddlewareDescribeRequest, MiddlewareManifest,
    SupervisorMiddlewareOperation, SupervisorMiddlewarePhase, ValidateConfigRequest,
    ValidateConfigResponse,
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
    http: reqwest::Client,
    base_url: String,
    token: String,
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
struct DaemonPidState {
    rest_port: Option<u16>,
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

impl DaemonClient {
    fn from_environment() -> Result<Self, AppError> {
        let base_url = match env::var("AI_GUARDIAN_DAEMON_URL") {
            Ok(value) if !value.trim().is_empty() => value,
            _ => {
                let pid_path = env::var("AI_GUARDIAN_DAEMON_PID_FILE")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| default_state_dir().join("daemon.pid"));
                daemon_url_from_pid_file(&pid_path)?
            }
        }
        .trim_end_matches('/')
        .to_string();
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
        let http = reqwest::Client::builder()
            .connect_timeout(std::time::Duration::from_secs(2))
            .timeout(std::time::Duration::from_secs(10))
            .build()?;
        Ok(Self {
            http,
            base_url,
            token,
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
        let response = self
            .http
            .post(format!("{}/api/check", self.base_url))
            .header(AUTHORIZATION, format!("Bearer {}", self.token))
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

fn daemon_url_from_pid_file(path: &Path) -> Result<String, AppError> {
    let pid_state: DaemonPidState =
        serde_json::from_str(&fs::read_to_string(path).map_err(|error| {
            AppError::Message(format!(
                "cannot read AI Guardian daemon PID file {}: {error}",
                path.display()
            ))
        })?)
        .map_err(|error| {
            AppError::Message(format!(
                "invalid AI Guardian daemon PID file {}: {error}",
                path.display()
            ))
        })?;
    let rest_port = pid_state.rest_port.ok_or_else(|| {
        AppError::Message(format!(
            "AI Guardian daemon PID file {} has no rest_port",
            path.display()
        ))
    })?;
    Ok(format!("http://127.0.0.1:{rest_port}"))
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
        let semantic = self
            .daemon
            .check(content, request_id, semantic_checks)
            .await?;
        let semantic_blocking = semantic.findings.iter().any(|finding| {
            matches!(
                finding.finding_type.as_str(),
                "prompt_injection" | "context_poisoning" | "jailbreak"
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
            .filter(|check| matches!(*check, "secrets" | "pii"))
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
        Ok(Evaluation {
            blocked: !sensitive.clean
                && (block_all_findings || blocking || !plan.response_redaction),
            redacted: if plan.response_redaction {
                sensitive.redacted
            } else {
                None
            },
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
        if request.phase != SupervisorMiddlewarePhase::PreCredentials as i32 {
            return Err(Status::invalid_argument("unsupported HTTP request phase"));
        }
        if request.body.is_empty() {
            return Ok(Response::new(HttpRequestResult {
                decision: Decision::Allow as i32,
                ..Default::default()
            }));
        }
        let content = String::from_utf8(request.body)
            .map_err(|_| Status::invalid_argument("request body must be UTF-8"))?;
        let request_id = request
            .context
            .map(|value| value.request_id)
            .unwrap_or_default();
        let plan = Self::scan_plan(request.config.as_ref())?;
        let result = self
            .evaluate(&content, &request_id, &plan, true)
            .await
            .map_err(|error| Status::unavailable(error.to_string()))?;
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
        _request: Request<tonic::Streaming<pb::WebSocketSessionEvent>>,
    ) -> Result<Response<Self::EvaluateWebSocketSessionStream>, Status> {
        Err(Status::unimplemented(
            "Rust middleware does not advertise WebSocket bindings",
        ))
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
            env::var_os("HOME").map(|path| PathBuf::from(path).join(".local/state/ai-guardian"))
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
    use std::io::Write;

    #[test]
    fn daemon_url_comes_from_pid_rest_port() {
        let mut file = tempfile::NamedTempFile::new().expect("temp PID file");
        write!(file, r#"{{"pid":123,"rest_port":63200}}"#).expect("write PID");
        assert_eq!(
            daemon_url_from_pid_file(file.path()).expect("daemon URL"),
            "http://127.0.0.1:63200"
        );
    }

    #[test]
    fn daemon_pid_without_rest_port_fails_closed() {
        let mut file = tempfile::NamedTempFile::new().expect("temp PID file");
        write!(file, r#"{{"pid":123}}"#).expect("write PID");
        let error = daemon_url_from_pid_file(file.path()).expect_err("missing port");
        assert!(error.to_string().contains("has no rest_port"));
    }

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
}
