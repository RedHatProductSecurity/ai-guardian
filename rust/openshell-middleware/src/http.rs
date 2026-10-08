//! HTTP request capability and supervisor handshake RPCs.

use tonic::{Request, Response, Status};
use tracing::{info, warn};

use super::compatibility;
use super::openshell::extension::v1::{PeerMetadata, ProtocolVersion};
use super::openshell::middleware::v1::{self as pb, Decision};
use super::{MiddlewareService, CONTRACT_CAPABILITY, IMPLEMENTATION_NAME};

impl MiddlewareService {
    pub(super) async fn describe_rpc(
        &self,
        request: Request<pb::MiddlewareDescribeRequest>,
    ) -> Result<Response<pb::MiddlewareManifest>, Status> {
        Self::validate_gateway(request.into_inner().gateway)?;
        let compatibility = compatibility::compatibility_policy().map_err(|error| {
            Status::internal(format!("invalid embedded OpenShell compatibility policy: {error}"))
        })?;
        let supported_capabilities = vec![
            CONTRACT_CAPABILITY.to_string(),
            "openshell.middleware.request-scanning".to_string(),
            "openshell.middleware.response-redaction".to_string(),
            "openshell.middleware.semantic-scanning".to_string(),
            "openshell.middleware.websocket-text".to_string(),
        ];
        Ok(Response::new(pb::MiddlewareManifest {
            name: IMPLEMENTATION_NAME.to_string(),
            service_version: env!("CARGO_PKG_VERSION").to_string(),
            bindings: vec![
                pb::MiddlewareBinding {
                    operation: pb::SupervisorMiddlewareOperation::HttpRequest as i32,
                    phase: pb::SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
                pb::MiddlewareBinding {
                    operation: pb::SupervisorMiddlewareOperation::HttpResponse as i32,
                    phase: pb::SupervisorMiddlewarePhase::PreReturn as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
                pb::MiddlewareBinding {
                    operation: pb::SupervisorMiddlewareOperation::WebsocketMessage as i32,
                    phase: pb::SupervisorMiddlewarePhase::PreCredentials as i32,
                    max_payload_bytes: self.max_payload_bytes,
                    request_timeout: None,
                },
            ],
            expected_audience: String::new(),
            extension: Some(PeerMetadata {
                protocol_version: Some(ProtocolVersion {
                    major: compatibility.supervisor_protocol.major,
                    minor: compatibility.supervisor_protocol.minor,
                }),
                implementation_name: IMPLEMENTATION_NAME.to_string(),
                implementation_version: env!("CARGO_PKG_VERSION").to_string(),
                supported_capabilities,
                required_capabilities: vec![CONTRACT_CAPABILITY.to_string()],
            }),
        }))
    }

    pub(super) async fn validate_config_rpc(
        &self,
        request: Request<pb::ValidateConfigRequest>,
    ) -> Result<Response<pb::ValidateConfigResponse>, Status> {
        let request = request.into_inner();
        if !request.middleware_name.is_empty() && request.middleware_name != self.registration_name
        {
            return Ok(Response::new(pb::ValidateConfigResponse {
                valid: false,
                reason: "middleware registration name does not match".to_string(),
            }));
        }
        if let Err(error) = Self::scan_plan(request.config.as_ref()) {
            return Ok(Response::new(pb::ValidateConfigResponse {
                valid: false,
                reason: error.message().to_string(),
            }));
        }
        Ok(Response::new(pb::ValidateConfigResponse {
            valid: true,
            reason: String::new(),
        }))
    }

    pub(super) async fn evaluate_http_request_rpc(
        &self,
        request: Request<pb::HttpRequestEvaluation>,
    ) -> Result<Response<pb::HttpRequestResult>, Status> {
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
        if request.phase != pb::SupervisorMiddlewarePhase::PreCredentials as i32 {
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
        if body_bytes > self.max_payload_bytes as usize {
            return Ok(Response::new(pb::HttpRequestResult {
                decision: Decision::Deny as i32,
                reason: "AI Guardian middleware payload limit exceeded".to_string(),
                reason_code: "payload_limit_exceeded".to_string(),
                ..Default::default()
            }));
        }
        let content = String::from_utf8(request.body)
            .map_err(|_| Status::invalid_argument("request body must be UTF-8"))?;
        let request_id = request_id.to_string();
        let plan = if content.is_empty() {
            super::policy::ScanPlan {
                checks: Vec::new(),
                response_redaction: false,
            }
        } else {
            Self::scan_plan(request.config.as_ref())?
        };
        let result = match self
            .evaluate(&content, &request_id, &plan, true)
            .await
        {
            Ok(result) => result,
            Err(error) => {
                warn!(
                    request_id = %request_id,
                    host,
                    method,
                    "Rust middleware control plane unavailable; denying request: {error}"
                );
                return Ok(Response::new(pb::HttpRequestResult {
                    decision: Decision::Deny as i32,
                    reason: "AI Guardian middleware control plane unavailable".to_string(),
                    reason_code: "middleware_control_plane_unavailable".to_string(),
                    ..Default::default()
                }));
            }
        };
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
        Ok(Response::new(pb::HttpRequestResult {
            decision: if result.blocked {
                Decision::Deny as i32
            } else {
                Decision::Allow as i32
            },
            reason: result.reason,
            reason_code: result.reason_code,
            findings: result.findings,
            metadata: result.metadata,
            ..Default::default()
        }))
    }
}
