package main

import (
	"encoding/json"
	"errors"

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
	var value any
	switch {
	case request.ChatRequest != nil:
		value = request.ChatRequest
	case request.TextCompletionRequest != nil:
		value = request.TextCompletionRequest
	case request.ResponsesRequest != nil:
		value = request.ResponsesRequest
	case request.EmbeddingRequest != nil:
		value = request.EmbeddingRequest
	default:
		return "", errUnsupported
	}
	return boundedJSON(value)
}

func marshalResponse(response *schemas.BifrostResponse) (string, error) {
	if response == nil || response.ResponsesStreamResponse != nil || response.SpeechStreamResponse != nil || response.TranscriptionStreamResponse != nil {
		return "", errUnsupported
	}
	var value any
	switch {
	case response.ChatResponse != nil:
		value = response.ChatResponse
	case response.TextCompletionResponse != nil:
		value = response.TextCompletionResponse
	case response.ResponsesResponse != nil:
		value = response.ResponsesResponse
	case response.EmbeddingResponse != nil:
		value = response.EmbeddingResponse
	default:
		return "", errUnsupported
	}
	return boundedJSON(value)
}

func boundedJSON(value any) (string, error) {
	payload, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	return string(payload), nil
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
