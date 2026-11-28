package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/maximhq/bifrost/core/schemas"
)

const PluginName = "ai-guardian-bifrost"

var errUnsupported = errors.New("unsupported Bifrost operation")

var activeClient *daemonClient

// Init is the symbol loaded by Bifrost's native plugin loader. Bifrost passes
// its opaque plugin configuration here; daemon connectivity is intentionally
// selected only from the protected process environment.
func Init(_ any) error {
	client, err := newDaemonClientFromEnvironment()
	if err != nil {
		return err
	}
	activeClient = client
	return nil
}

func GetName() string { return PluginName }

func Cleanup() error {
	activeClient = nil
	return nil
}

func PreRequestHook(_ *schemas.BifrostContext, _ *schemas.BifrostRequest) error {
	return nil
}

func PreLLMHook(_ *schemas.BifrostContext, request *schemas.BifrostRequest) (*schemas.BifrostRequest, *schemas.LLMPluginShortCircuit, error) {
	client, err := currentClient()
	if err != nil {
		return request, denyShortCircuit("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	content, err := marshalRequest(request)
	if err != nil {
		return request, denyShortCircuit("ai_guardian_request_error", err.Error()), nil
	}
	verdict, err := client.check(content)
	if err != nil {
		if !client.failClosed {
			return request, nil, nil
		}
		return request, denyShortCircuit("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	if err := validateVerdict(verdict); err != nil {
		if !client.failClosed {
			return request, nil, nil
		}
		return request, denyShortCircuit("ai_guardian_invalid_verdict", err.Error()), nil
	}
	if verdict.Blocked {
		return request, denyShortCircuit("ai_guardian_denied", "AI Guardian denied the request"), nil
	}
	return request, nil, nil
}

func PostLLMHook(_ *schemas.BifrostContext, response *schemas.BifrostResponse, bifrostErr *schemas.BifrostError) (*schemas.BifrostResponse, *schemas.BifrostError, error) {
	if bifrostErr != nil {
		return response, bifrostErr, nil
	}
	client, err := currentClient()
	if err != nil {
		return response, denyError("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	content, err := marshalResponse(response)
	if err != nil {
		return response, denyError("ai_guardian_response_error", err.Error()), nil
	}
	verdict, err := client.check(content)
	if err != nil {
		if !client.failClosed {
			return response, nil, nil
		}
		return response, denyError("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	if err := validateVerdict(verdict); err != nil {
		if !client.failClosed {
			return response, nil, nil
		}
		return response, denyError("ai_guardian_invalid_verdict", err.Error()), nil
	}
	if verdict.Blocked || verdict.Redacted != "" {
		return response, denyError("ai_guardian_denied", "AI Guardian denied the response"), nil
	}
	return response, nil, nil
}

// PreMCPHook is the daemon-authoritative gate for MCP request content. The
// envelope contains only operation metadata and tool/prompt/resource content;
// MCP transport headers and credentials never enter the daemon payload.
func PreMCPHook(_ *schemas.BifrostContext, request *schemas.BifrostMCPRequest) (*schemas.BifrostMCPRequest, *schemas.MCPPluginShortCircuit, error) {
	client, err := currentClient()
	if err != nil {
		return request, denyMCPShortCircuit("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	content, err := marshalMCPRequest(request)
	if err != nil {
		return request, denyMCPShortCircuit("ai_guardian_request_error", err.Error()), nil
	}
	verdict, err := client.check(content)
	if err != nil {
		if !client.failClosed {
			return request, nil, nil
		}
		return request, denyMCPShortCircuit("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	if err := validateVerdict(verdict); err != nil {
		if !client.failClosed {
			return request, nil, nil
		}
		return request, denyMCPShortCircuit("ai_guardian_invalid_verdict", err.Error()), nil
	}
	if verdict.Blocked {
		return request, denyMCPShortCircuit("ai_guardian_denied", "AI Guardian denied the MCP operation"), nil
	}
	return request, nil, nil
}

// PostMCPHook inspects the bounded MCP result before Bifrost returns it to the
// caller. Existing MCP errors are preserved, but only their stable error code
// is sent for inspection, never an error message that may contain credentials.
func PostMCPHook(_ *schemas.BifrostContext, response *schemas.BifrostMCPResponse, bifrostErr *schemas.BifrostError) (*schemas.BifrostMCPResponse, *schemas.BifrostError, error) {
	client, err := currentClient()
	if err != nil {
		return response, denyError("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	content, err := marshalMCPResponse(response, bifrostErr)
	if err != nil {
		return response, denyError("ai_guardian_response_error", err.Error()), nil
	}
	verdict, err := client.check(content)
	if err != nil {
		if !client.failClosed {
			return response, bifrostErr, nil
		}
		return response, denyError("ai_guardian_unavailable", "AI Guardian daemon unavailable"), nil
	}
	if err := validateVerdict(verdict); err != nil {
		if !client.failClosed {
			return response, bifrostErr, nil
		}
		return response, denyError("ai_guardian_invalid_verdict", err.Error()), nil
	}
	if verdict.Blocked || verdict.Redacted != "" {
		return response, denyError("ai_guardian_denied", "AI Guardian denied the MCP result"), nil
	}
	return response, bifrostErr, nil
}

type mcpEnvelope struct {
	Kind      string `json:"kind"`
	Operation string `json:"operation"`
	Client    string `json:"client,omitempty"`
	Tool      string `json:"tool,omitempty"`
	Target    string `json:"target,omitempty"`
	Arguments any    `json:"arguments,omitempty"`
	Result    any    `json:"result,omitempty"`
	ErrorCode string `json:"error_code,omitempty"`
}

func marshalMCPRequest(request *schemas.BifrostMCPRequest) (string, error) {
	if request == nil || request.RequestType == "" {
		return "", errUnsupported
	}
	envelope := mcpEnvelope{Kind: "mcp_request", Operation: string(request.RequestType), Client: request.ClientName}
	switch {
	case request.RequestType.IsExecuteTool():
		envelope.Tool = request.GetToolName()
		envelope.Arguments = request.GetToolArguments()
	case request.BifrostMCPGetPromptRequest != nil:
		envelope.Target = request.BifrostMCPGetPromptRequest.Name
		envelope.Arguments = request.BifrostMCPGetPromptRequest.Arguments
	case request.BifrostMCPReadResourceRequest != nil:
		envelope.Target = request.BifrostMCPReadResourceRequest.URI
	case request.BifrostMCPCompleteRequest != nil:
		envelope.Arguments = request.BifrostMCPCompleteRequest.Params
	case request.RequestType != schemas.MCPRequestTypePing &&
		request.RequestType != schemas.MCPRequestTypeListTools &&
		request.RequestType != schemas.MCPRequestTypeListResources &&
		request.RequestType != schemas.MCPRequestTypeListResourceTemplates &&
		request.RequestType != schemas.MCPRequestTypeListPrompts:
		return "", fmt.Errorf("unsupported MCP operation: %s", request.RequestType)
	}
	return boundedJSON(envelope)
}

func marshalMCPResponse(response *schemas.BifrostMCPResponse, bifrostErr *schemas.BifrostError) (string, error) {
	if response == nil && bifrostErr == nil {
		return "", errUnsupported
	}
	envelope := mcpEnvelope{Kind: "mcp_response"}
	if bifrostErr != nil {
		envelope.Operation = string(bifrostErr.ExtraFields.MCPRequestType)
		envelope.Client = bifrostErr.ExtraFields.MCPClientName
		envelope.Tool = bifrostErr.ExtraFields.MCPToolName
	}
	if response != nil {
		if envelope.Operation == "" {
			envelope.Operation = string(response.ExtraFields.MCPRequestType)
		}
		if envelope.Client == "" {
			envelope.Client = response.ExtraFields.ClientName
		}
		if envelope.Tool == "" {
			envelope.Tool = response.ExtraFields.ToolName
		}
		switch {
		case response.ChatMessage != nil:
			envelope.Result = response.ChatMessage.Content
		case response.ResponsesMessage != nil:
			envelope.Result = response.ResponsesMessage
		case response.BifrostMCPGetPromptResponse != nil:
			envelope.Result = response.BifrostMCPGetPromptResponse.Prompt
		case response.BifrostMCPReadResourceResponse != nil:
			envelope.Result = response.BifrostMCPReadResourceResponse.Resource
		case response.BifrostMCPCompleteResponse != nil:
			envelope.Result = response.BifrostMCPCompleteResponse.Completion
		case response.BifrostMCPListToolsResponse != nil:
			envelope.Result = response.BifrostMCPListToolsResponse.Tools
		case response.BifrostMCPListResourcesResponse != nil:
			envelope.Result = response.BifrostMCPListResourcesResponse.Resources
		case response.BifrostMCPListResourceTemplatesResponse != nil:
			envelope.Result = response.BifrostMCPListResourceTemplatesResponse.ResourceTemplates
		case response.BifrostMCPListPromptsResponse != nil:
			envelope.Result = response.BifrostMCPListPromptsResponse.Prompts
		}
	}
	if bifrostErr != nil {
		envelope.ErrorCode = bifrostErr.ExtraFields.MCPToolName
		if envelope.ErrorCode == "" && bifrostErr.Error != nil && bifrostErr.Error.Code != nil {
			envelope.ErrorCode = *bifrostErr.Error.Code
		}
	}
	if envelope.Operation == "" {
		return "", errUnsupported
	}
	return boundedJSON(envelope)
}

func denyMCPShortCircuit(code, message string) *schemas.MCPPluginShortCircuit {
	return &schemas.MCPPluginShortCircuit{Error: denyError(code, message)}
}

// HTTPTransportStreamChunkHook holds chunks in Bifrost's pause/resume gate and
// evaluates the assembled response only when the stream is complete. This
// avoids releasing a fragment before a finding that spans chunks is known.
func HTTPTransportStreamChunkHook(ctx *schemas.BifrostContext, _ *schemas.HTTPRequest, chunk *schemas.BifrostStreamChunk) (*schemas.BifrostStreamChunk, error) {
	if ctx != nil && ctx.Err() != nil {
		return nil, streamDenyError("ai_guardian_stream_cancelled", "AI Guardian streaming inspection cancelled")
	}
	if chunk == nil {
		return nil, streamDenyError("ai_guardian_stream_error", "AI Guardian received an invalid stream chunk")
	}
	if chunk.BifrostError != nil {
		if ctx != nil {
			ctx.ResumeStream()
		}
		return chunk, nil
	}
	if ctx == nil {
		return nil, streamDenyError("ai_guardian_stream_unsupported", "AI Guardian requires a Bifrost stream gate")
	}
	if _, ok := ctx.Value(schemas.BifrostContextKeyTracer).(schemas.Tracer); !ok {
		return nil, streamDenyError("ai_guardian_stream_unsupported", "AI Guardian requires a Bifrost stream gate")
	}
	if traceID, _ := ctx.Value(schemas.BifrostContextKeyTraceID).(string); traceID == "" {
		return nil, streamDenyError("ai_guardian_stream_unsupported", "AI Guardian requires a Bifrost stream identity")
	}
	if !ctx.IsStreamPaused() {
		ctx.PauseStream()
		if !ctx.IsStreamPaused() {
			return nil, streamDenyError("ai_guardian_stream_unsupported", "AI Guardian requires an active Bifrost stream gate")
		}
	}
	final, _ := ctx.Value(schemas.BifrostContextKeyStreamEndIndicator).(bool)
	if !final {
		return chunk, nil
	}
	client, err := currentClient()
	if err != nil {
		return denyStream(ctx, "ai_guardian_unavailable", "AI Guardian daemon unavailable")
	}
	response := ctx.GetAccumulatedResponse()
	content, err := marshalResponse(response)
	if err != nil {
		return denyStream(ctx, "ai_guardian_response_error", err.Error())
	}
	verdict, err := client.check(content)
	if err != nil {
		if !client.failClosed {
			ctx.ResumeStream()
			return chunk, nil
		}
		return denyStream(ctx, "ai_guardian_unavailable", "AI Guardian daemon unavailable")
	}
	if err := validateVerdict(verdict); err != nil {
		if !client.failClosed {
			ctx.ResumeStream()
			return chunk, nil
		}
		return denyStream(ctx, "ai_guardian_invalid_verdict", err.Error())
	}
	if verdict.Blocked || verdict.Redacted != "" {
		return denyStream(ctx, "ai_guardian_denied", "AI Guardian denied the response")
	}
	ctx.ResumeStream()
	return chunk, nil
}

func currentClient() (*daemonClient, error) {
	if activeClient != nil {
		return activeClient, nil
	}
	client, err := newDaemonClientFromEnvironment()
	if err != nil {
		return nil, err
	}
	activeClient = client
	return client, nil
}

func marshalRequest(request *schemas.BifrostRequest) (string, error) {
	if request == nil {
		return "", errUnsupported
	}
	var provider schemas.ModelProvider
	var model string
	var content any
	switch {
	case request.ChatRequest != nil:
		provider, model, content = request.ChatRequest.Provider, request.ChatRequest.Model, request.ChatRequest.Input
	case request.TextCompletionRequest != nil:
		provider, model, content = request.TextCompletionRequest.Provider, request.TextCompletionRequest.Model, request.TextCompletionRequest.Input
	case request.ResponsesRequest != nil:
		provider, model, content = request.ResponsesRequest.Provider, request.ResponsesRequest.Model, request.ResponsesRequest.Input
	case request.EmbeddingRequest != nil:
		provider, model, content = request.EmbeddingRequest.Provider, request.EmbeddingRequest.Model, request.EmbeddingRequest.Input
	default:
		return "", errUnsupported
	}
	return boundedJSON(safeContentEnvelope{Provider: provider, Model: model, Content: content})
}

func marshalResponse(response *schemas.BifrostResponse) (string, error) {
	if response == nil || response.ResponsesStreamResponse != nil || response.SpeechStreamResponse != nil || response.TranscriptionStreamResponse != nil {
		return "", errUnsupported
	}
	var provider schemas.ModelProvider
	var model string
	var content any
	switch {
	case response.ChatResponse != nil:
		provider, model, content = response.ChatResponse.ExtraFields.Provider, response.ChatResponse.Model, response.ChatResponse.Choices
	case response.TextCompletionResponse != nil:
		provider, model, content = response.TextCompletionResponse.ExtraFields.Provider, response.TextCompletionResponse.Model, response.TextCompletionResponse.Choices
	case response.ResponsesResponse != nil:
		provider, model, content = response.ResponsesResponse.ExtraFields.Provider, response.ResponsesResponse.Model, response.ResponsesResponse.Output
	case response.EmbeddingResponse != nil:
		provider, model, content = response.EmbeddingResponse.ExtraFields.Provider, response.EmbeddingResponse.Model, response.EmbeddingResponse.Data
	default:
		return "", errUnsupported
	}
	return boundedJSON(safeContentEnvelope{Provider: provider, Model: model, Content: content})
}

type safeContentEnvelope struct {
	Provider schemas.ModelProvider `json:"provider,omitempty"`
	Model    string                `json:"model,omitempty"`
	Content  any                   `json:"content,omitempty"`
}

func boundedJSON(value any) (string, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	var decoded any
	if err := json.Unmarshal(payload, &decoded); err != nil {
		return "", err
	}
	return string(sanitizeJSON(decoded)), nil
}

// sanitizeJSON removes credential-bearing fields at the daemon boundary. The
// Bifrost request/response structs intentionally carry content only, but some
// provider-native and OAuth-backed surfaces expose tokens or headers as JSON
// fields. The daemon must never receive those values, even when a future
// schema adds another extension field.
func sanitizeJSON(value any) []byte {
	clean := sanitizeJSONValue(value)
	payload, err := json.Marshal(clean)
	if err != nil {
		return []byte("null")
	}
	return payload
}

func sanitizeJSONValue(value any) any {
	switch typed := value.(type) {
	case []any:
		for index := range typed {
			typed[index] = sanitizeJSONValue(typed[index])
		}
		return typed
	case map[string]any:
		clean := make(map[string]any, len(typed))
		for key, item := range typed {
			if isCredentialField(key) {
				continue
			}
			clean[key] = sanitizeJSONValue(item)
		}
		return clean
	default:
		return value
	}
}

func isCredentialField(key string) bool {
	normalized := strings.ToLower(strings.NewReplacer("_", "", "-", "", " ", "").Replace(key))
	switch normalized {
	case "authorization", "proxyauthorization", "cookie", "setcookie", "headers",
		"access_token", "accesstoken", "refresh_token", "refreshtoken", "idtoken",
		"authorizationtoken", "clientsecret", "apikey", "providerapikey", "apisecret", "secretkey",
		"credential", "credentials", "providerresponseheaders":
		return true
	default:
		return strings.HasSuffix(normalized, "token") || strings.HasSuffix(normalized, "secret")
	}
}

func validateVerdict(verdict daemonResponse) error {
	if verdict.Blocked {
		return nil
	}
	if !verdict.Clean {
		return errors.New("daemon returned neither clean nor blocked")
	}
	return nil
}

func denyShortCircuit(code, message string) *schemas.LLMPluginShortCircuit {
	return &schemas.LLMPluginShortCircuit{Error: denyError(code, message)}
}

func denyError(code, message string) *schemas.BifrostError {
	typeValue := "security_policy"
	codeValue := code
	status := 403
	if code == "ai_guardian_unavailable" || code == "ai_guardian_invalid_verdict" {
		status = 503
	}
	allowFallbacks := false
	return &schemas.BifrostError{
		Type:           &typeValue,
		StatusCode:     &status,
		IsBifrostError: true,
		Error:          &schemas.ErrorField{Type: &typeValue, Code: &codeValue, Message: message},
		AllowFallbacks: &allowFallbacks,
	}
}

func streamDenyError(code, message string) error {
	return &schemas.StreamInterceptionError{BifrostError: denyError(code, message)}
}

func denyStream(ctx *schemas.BifrostContext, code, message string) (*schemas.BifrostStreamChunk, error) {
	if err := ctx.ClearPausedStreamBuffer(); err != nil {
		return nil, streamDenyError("ai_guardian_stream_error", err.Error())
	}
	ctx.EndStream(denyError(code, message))
	return nil, streamDenyError(code, message)
}
