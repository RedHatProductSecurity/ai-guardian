//! Rust OpenShell supervisor middleware service wiring.
//!
//! OpenShell owns the external gRPC boundary. Scanner execution stays in the
//! long-lived AI Guardian daemon and is reached through its permission-
//! protected Unix socket (or explicit authenticated REST for remote
//! deployments). Capability implementations live in sibling modules so this
//! file remains responsible for shared state, protocol wiring, and lifecycle.

use std::env;
use std::net::SocketAddr;
use std::pin::Pin;

use prost_types::Struct;
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

#[path = "compatibility.rs"]
mod compatibility;
#[path = "daemon.rs"]
mod daemon;
#[path = "evaluation.rs"]
mod evaluation;
#[path = "http.rs"]
mod http;
#[path = "policy.rs"]
mod policy;
#[path = "response.rs"]
mod response;
#[path = "websocket.rs"]
mod websocket;

use openshell::extension::v1::PeerMetadata;
use openshell::middleware::v1::http_response_pre_return_server::{
    HttpResponsePreReturn, HttpResponsePreReturnServer,
};
use openshell::middleware::v1::supervisor_middleware_server::{
    SupervisorMiddleware, SupervisorMiddlewareServer,
};
use openshell::middleware::v1 as pb;

const CONTRACT_CAPABILITY: &str = "openshell.supervisor-middleware.contract";
const IMPLEMENTATION_NAME: &str = "ai-guardian/rust-middleware";
const DEFAULT_MAX_PAYLOAD_BYTES: u64 = 256 * 1024;
const MAX_CONFIGURED_PAYLOAD_BYTES: u64 = 4 * 1024 * 1024;
const MAX_PAYLOAD_ENV: &str = "AI_GUARDIAN_MIDDLEWARE_MAX_PAYLOAD_BYTES";
const OPENSHELL_VERSION_ENV: &str = "AI_GUARDIAN_OPENSHELL_VERSION";

type WebSocketStream =
    Pin<Box<dyn Stream<Item = Result<pb::WebSocketSessionEventResult, Status>> + Send>>;
type ResponseStream =
    Pin<Box<dyn Stream<Item = Result<pb::HttpResponseEventResult, Status>> + Send>>;

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
struct MiddlewareService {
    daemon: daemon::DaemonClient,
    registration_name: String,
    max_payload_bytes: u64,
}

impl MiddlewareService {
    fn validate_gateway(gateway: Option<PeerMetadata>) -> Result<(), Status> {
        let compatibility = compatibility::compatibility_policy().map_err(|error| {
            Status::internal(format!("invalid embedded OpenShell compatibility policy: {error}"))
        })?;
        let gateway = gateway.ok_or_else(|| {
            Status::failed_precondition("gateway did not provide protocol metadata")
        })?;
        let version = gateway
            .protocol_version
            .ok_or_else(|| Status::failed_precondition("gateway protocol version is missing"))?;
        let expected = compatibility.supervisor_protocol;
        if version.major != expected.major || version.minor != expected.minor {
            return Err(Status::failed_precondition(format!(
                "unsupported OpenShell protocol {}.{}; expected {}.{}",
                version.major, version.minor, expected.major, expected.minor
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

    fn scan_plan(config: Option<&Struct>) -> Result<policy::ScanPlan, Status> {
        policy::scan_plan(config)
    }

    async fn evaluate(
        &self,
        content: &str,
        request_id: &str,
        plan: &policy::ScanPlan,
        block_all_findings: bool,
    ) -> Result<evaluation::Evaluation, AppError> {
        evaluation::evaluate(
            &self.daemon,
            content,
            request_id,
            plan,
            block_all_findings,
        )
        .await
    }
}

#[tonic::async_trait]
impl SupervisorMiddleware for MiddlewareService {
    type EvaluateWebSocketSessionStream = WebSocketStream;

    async fn describe(
        &self,
        request: Request<pb::MiddlewareDescribeRequest>,
    ) -> Result<Response<pb::MiddlewareManifest>, Status> {
        self.describe_rpc(request).await
    }

    async fn validate_config(
        &self,
        request: Request<pb::ValidateConfigRequest>,
    ) -> Result<Response<pb::ValidateConfigResponse>, Status> {
        self.validate_config_rpc(request).await
    }

    async fn evaluate_http_request(
        &self,
        request: Request<pb::HttpRequestEvaluation>,
    ) -> Result<Response<pb::HttpRequestResult>, Status> {
        self.evaluate_http_request_rpc(request).await
    }

    async fn evaluate_web_socket_session(
        &self,
        request: Request<tonic::Streaming<pb::WebSocketSessionEvent>>,
    ) -> Result<Response<Self::EvaluateWebSocketSessionStream>, Status> {
        self.evaluate_web_socket_session_rpc(request).await
    }
}

#[tonic::async_trait]
impl HttpResponsePreReturn for MiddlewareService {
    type EvaluateStream = ResponseStream;

    async fn evaluate(
        &self,
        request: Request<tonic::Streaming<pb::HttpResponseEvent>>,
    ) -> Result<Response<Self::EvaluateStream>, Status> {
        self.evaluate_response_rpc(request).await
    }
}

fn configured_max_payload_bytes() -> u64 {
    match env::var(MAX_PAYLOAD_ENV) {
        Ok(value) => match value.parse::<u64>() {
            Ok(value) if (1..=MAX_CONFIGURED_PAYLOAD_BYTES).contains(&value) => value,
            _ => {
                warn!(
                    value = %value,
                    default = DEFAULT_MAX_PAYLOAD_BYTES,
                    "invalid Rust middleware payload limit; using default"
                );
                DEFAULT_MAX_PAYLOAD_BYTES
            }
        },
        Err(_) => DEFAULT_MAX_PAYLOAD_BYTES,
    }
}

#[tokio::main]
pub async fn run() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    compatibility::validate_runtime_compatibility()?;
    let bind =
        env::var("AI_GUARDIAN_MIDDLEWARE_BIND").unwrap_or_else(|_| "127.0.0.1:50051".to_string());
    let address: SocketAddr = bind.parse()?;
    let service = MiddlewareService {
        daemon: daemon::DaemonClient::from_environment()?,
        registration_name: env::var("AI_GUARDIAN_MIDDLEWARE_REGISTRATION")
            .unwrap_or_else(|_| "content-guard-test".to_string()),
        max_payload_bytes: configured_max_payload_bytes(),
    };

    info!(%address, "Rust OpenShell middleware listening");
    let result = tonic::transport::Server::builder()
        .add_service(SupervisorMiddlewareServer::new(service.clone()))
        .add_service(HttpResponsePreReturnServer::new(service))
        .serve_with_shutdown(address, shutdown_signal())
        .await;
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

#[cfg(test)]
mod tests {
    use super::*;
    use super::daemon::{
        parse_socket_check_response, paused_check_response, CheckResponse, DaemonClient,
        DaemonFinding, DaemonSocketResponse, DaemonTransport,
    };
    use super::evaluation::{finding_blocks, paused_evaluation, response_has_blocking_findings};
    use super::openshell::extension::v1::ProtocolVersion;
    use prost_types::value::Kind;
    use std::collections::BTreeMap;
    use std::path::PathBuf;

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
    fn gateway_metadata_rejects_unsupported_protocol_minor() {
        let error = MiddlewareService::validate_gateway(Some(PeerMetadata {
            protocol_version: Some(ProtocolVersion { major: 1, minor: 1 }),
            supported_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
            ..Default::default()
        }))
        .expect_err("unsupported protocol minor");
        assert!(error.message().contains("expected 1.0"));
    }

    #[test]
    fn openshell_release_uses_shared_compatibility_policy() {
        assert!(compatibility::validate_openshell_release("0.1.2").is_ok());
        assert!(compatibility::validate_openshell_release("v0.1.9").is_ok());
        assert!(compatibility::validate_openshell_release("0.1.1").is_err());
        assert!(compatibility::validate_openshell_release("0.2.0").is_err());
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

    #[test]
    fn scanner_plan_routes_canary_and_skips_hook_owned_scanners() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([
                            (
                                "canary_detection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "prompt_injection".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("middleware".to_string())),
                                },
                            ),
                            (
                                "scan_pii".to_string(),
                                prost_types::Value {
                                    kind: Some(Kind::StringValue("hooks".to_string())),
                                },
                            ),
                        ]),
                    })),
                },
            )]),
        };

        let plan = MiddlewareService::scan_plan(Some(&config)).expect("valid scan plan");
        assert!(plan.checks.contains(&"injection"));
        assert!(plan.checks.contains(&"canary"));
        assert!(!plan.checks.contains(&"pii"));
    }

    #[test]
    fn scanner_plan_rejects_both_with_actionable_runtime_message() {
        let config = Struct {
            fields: BTreeMap::from([(
                "scanner_ownership".to_string(),
                prost_types::Value {
                    kind: Some(Kind::StructValue(Struct {
                        fields: BTreeMap::from([(
                            "prompt_injection".to_string(),
                            prost_types::Value {
                                kind: Some(Kind::StringValue("both".to_string())),
                            },
                        )]),
                    })),
                },
            )]),
        };

        let error = MiddlewareService::scan_plan(Some(&config)).expect_err("both must fail");
        assert!(error
            .message()
            .contains("scanner ownership 'both' is not supported by Rust middleware"));
        assert!(error.message().contains("prompt_injection"));
    }

    #[test]
    fn daemon_warning_metadata_does_not_block() {
        let finding: DaemonFinding = serde_json::from_value(serde_json::json!({
            "type": "prompt_injection",
            "should_block": false,
            "action_taken": "warn"
        }))
        .expect("warning finding");
        assert!(!finding_blocks(&finding));
        assert!(!response_has_blocking_findings(&CheckResponse {
            clean: false,
            blocked: false,
            findings: vec![finding],
            ..Default::default()
        }));
    }

    #[tokio::test]
    async fn describe_advertises_text_websocket_binding() {
        let service = MiddlewareService {
            daemon: DaemonClient {
                transport: DaemonTransport::unix(PathBuf::from("/unused/daemon.sock")),
                project_dir: None,
            },
            registration_name: "content-guard-test".to_string(),
            max_payload_bytes: DEFAULT_MAX_PAYLOAD_BYTES,
        };
        let response = SupervisorMiddleware::describe(
            &service,
            Request::new(pb::MiddlewareDescribeRequest {
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
            binding.operation == pb::SupervisorMiddlewareOperation::WebsocketMessage as i32
                && binding.phase == pb::SupervisorMiddlewarePhase::PreCredentials as i32
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

    #[test]
    fn parses_paused_daemon_check_response() {
        let envelope: DaemonSocketResponse = serde_json::from_value(serde_json::json!({
            "type": "response",
            "data": {
                "data": {
                    "clean": true,
                    "findings": [],
                    "paused": true,
                    "reason_code": "middleware_paused",
                    "pause_source": "daemon",
                    "pause_scope": "global",
                    "pause_remaining_seconds": 30.0
                }
            }
        }))
        .expect("valid paused daemon response envelope");
        let response = parse_socket_check_response(envelope).expect("paused check result");
        assert!(response.paused);
        assert_eq!(response.reason_code, "middleware_paused");
        assert_eq!(response.pause_source, "daemon");
        assert_eq!(response.pause_remaining_seconds, 30.0);
    }

    #[test]
    fn paused_evaluation_allows_traffic_and_preserves_pause_metadata() {
        let response = CheckResponse {
            clean: true,
            paused: true,
            pause_source: "daemon".to_string(),
            pause_scope: "global".to_string(),
            pause_remaining_seconds: 30.0,
            reason_code: "middleware_paused".to_string(),
            ..Default::default()
        };

        let evaluation = paused_evaluation(response);

        assert!(!evaluation.blocked);
        assert!(evaluation.findings.is_empty());
        assert_eq!(evaluation.reason_code, "");
        assert_eq!(evaluation.metadata.get("pause_source"), Some(&"daemon".to_string()));
        assert_eq!(evaluation.metadata.get("pause_scope"), Some(&"global".to_string()));
    }

    #[test]
    fn pause_status_response_is_clean_pass_through() {
        let response = paused_check_response("daemon", "global", 30.0, "daemon_pause");

        assert!(response.clean);
        assert!(!response.blocked);
        assert!(response.paused);
        assert_eq!(response.reason_code, "middleware_paused");
    }
}
