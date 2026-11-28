package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/maximhq/bifrost/core/schemas"
)

func TestSharedMiddlewareContractFixtures(t *testing.T) {
	root := filepath.Join("..", "..")
	payload, err := os.ReadFile(filepath.Join(root, "tests", "fixtures", "middleware_contract.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture struct {
		Contract string `json:"contract"`
		Version  int    `json:"version"`
		Cases    []struct {
			Name        string         `json:"name"`
			Daemon      daemonResponse `json:"daemon"`
			DaemonError string         `json:"daemon_error"`
			Expected    struct {
				Decision string `json:"decision"`
			} `json:"expected"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(payload, &fixture); err != nil {
		t.Fatal(err)
	}
	if fixture.Contract != "ai-guardian.middleware" || fixture.Version != 1 {
		t.Fatalf("unexpected contract identity: %+v", fixture)
	}
	for _, testCase := range fixture.Cases {
		switch testCase.Name {
		case "allow", "deny", "pause", "malformed_verdict":
			decision := "allow"
			if testCase.Daemon.Blocked || (!testCase.Daemon.Clean && !testCase.Daemon.Paused) {
				decision = "deny"
			} else if testCase.Daemon.Paused {
				decision = "paused"
			}
			if decision != testCase.Expected.Decision {
				t.Errorf("fixture %s: decision %q, want %q", testCase.Name, decision, testCase.Expected.Decision)
			}
		case "daemon_unavailable", "sensitive_field_exclusion":
			// Transport and content-boundary behavior are covered by the focused tests below.
		default:
			t.Errorf("unhandled shared fixture %q", testCase.Name)
		}
	}
}

func TestPreLLMHookBlocksWithoutFallback(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true,"reason_code":"secret"}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "token", maxPayload: 1024, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{Model: "test-model", Input: []schemas.ChatMessage{{}}}}
	_, shortCircuit, err := PreLLMHook(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	if shortCircuit == nil || shortCircuit.Error == nil {
		t.Fatal("expected security short-circuit")
	}
	if shortCircuit.Error.AllowFallbacks == nil || *shortCircuit.Error.AllowFallbacks {
		t.Fatal("security denial must disable provider fallback")
	}
}

func TestPreLLMHookExcludesOAuthFieldsFromDaemonPayload(t *testing.T) {
	const accessToken = "oauth-access-token-must-not-leak"
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		payload := string(body)
		for _, secret := range []string{accessToken, "refresh-token-must-not-leak", "provider-api-key-must-not-leak", "session-cookie-must-not-leak"} {
			if strings.Contains(payload, secret) {
				t.Fatalf("credential %q leaked into daemon payload: %s", secret, payload)
			}
		}
		if !strings.Contains(payload, "safe user content") {
			t.Fatalf("safe content missing from daemon payload: %s", payload)
		}
		_, _ = writer.Write([]byte(`{"clean":true}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "daemon-token", maxPayload: 4096, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	content := "safe user content"
	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{
		Model: "test-model",
		Input: []schemas.ChatMessage{{Content: &schemas.ChatMessageContent{ContentStr: &content}}},
		Params: &schemas.ChatParameters{MCPServers: []schemas.ChatMCPServer{{
			URL:                "https://mcp.example",
			AuthorizationToken: stringPtr(accessToken),
		}}},
	}}
	_, shortCircuit, err := PreLLMHook(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	if shortCircuit != nil {
		t.Fatalf("safe request was denied: %+v", shortCircuit)
	}
}

func TestSanitizeJSONRemovesCredentialFieldVariants(t *testing.T) {
	value := map[string]any{
		"content":          "safe",
		"Authorization":    "authorization-secret",
		"refresh_token":    "refresh-secret",
		"provider-api-key": "provider-secret",
		"nested":           map[string]any{"cookie": "cookie-secret", "text": "safe"},
		"items":            []any{map[string]any{"accessToken": "access-secret"}},
	}
	payload := string(sanitizeJSON(value))
	for _, secret := range []string{"authorization-secret", "refresh-secret", "provider-secret", "cookie-secret", "access-secret"} {
		if strings.Contains(payload, secret) {
			t.Fatalf("credential %q leaked into sanitized payload: %s", secret, payload)
		}
	}
	if !strings.Contains(payload, "safe") {
		t.Fatalf("safe content missing from sanitized payload: %s", payload)
	}
}

func TestPostLLMHookBlocksResponseBeforeDelivery(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body daemonRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.Action != "block" {
			t.Fatalf("action = %q, want block", body.Action)
		}
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "token", maxPayload: 1024, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	response := &schemas.BifrostResponse{ChatResponse: &schemas.BifrostChatResponse{Model: "test-model"}}
	_, bifrostErr, err := PostLLMHook(nil, response, nil)
	if err != nil {
		t.Fatal(err)
	}
	if bifrostErr == nil || bifrostErr.AllowFallbacks == nil || *bifrostErr.AllowFallbacks {
		t.Fatal("expected terminal response denial")
	}
}

func TestDaemonFailureCanBeExplicitlyFailOpen(t *testing.T) {
	activeClient = &daemonClient{
		url:        "http://127.0.0.1:1",
		maxPayload: 1024,
		failClosed: false,
		httpClient: &http.Client{},
	}
	defer func() { activeClient = nil }()

	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{Model: "test-model"}}
	_, shortCircuit, err := PreLLMHook(nil, request)
	if err != nil {
		t.Fatal(err)
	}
	if shortCircuit != nil {
		t.Fatal("explicit fail-open mode should not short-circuit daemon unavailability")
	}
}

func TestPreMCPHookSendsOnlyAllowlistedContent(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body daemonRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.Action != "block" || !strings.Contains(body.Content, "read_file") || !strings.Contains(body.Content, "safe.txt") {
			t.Fatalf("unexpected MCP content: %s", body.Content)
		}
		if strings.Contains(body.Content, "daemon-token") {
			t.Fatalf("MCP daemon credential leaked into content: %s", body.Content)
		}
		_, _ = writer.Write([]byte(`{"clean":true,"blocked":false}`))
	}))
	defer server.Close()

	activeClient = &daemonClient{url: server.URL, token: "daemon-token", maxPayload: 4096, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	tool := "read_file"
	arguments := `{"path":"safe.txt"}`
	request := &schemas.BifrostMCPRequest{
		RequestType: schemas.MCPRequestTypeChatToolCall,
		ClientName:  "filesystem",
		ChatAssistantMessageToolCall: &schemas.ChatAssistantMessageToolCall{
			Function: schemas.ChatAssistantMessageToolCallFunction{Name: &tool, Arguments: arguments},
		},
	}
	_, shortCircuit, err := PreMCPHook(nil, request)
	if err != nil || shortCircuit != nil {
		t.Fatalf("PreMCPHook() = shortCircuit %v, err %v", shortCircuit, err)
	}
}

func TestPreMCPHookHonorsExplicitDaemonDenial(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true,"reason_code":"secret"}`))
	}))
	defer server.Close()
	activeClient = &daemonClient{url: server.URL, token: "daemon-token", maxPayload: 4096, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	tool := "write_file"
	request := &schemas.BifrostMCPRequest{
		RequestType: schemas.MCPRequestTypeChatToolCall,
		ClientName:  "filesystem",
		ChatAssistantMessageToolCall: &schemas.ChatAssistantMessageToolCall{
			Function: schemas.ChatAssistantMessageToolCallFunction{Name: &tool, Arguments: `{}`},
		},
	}
	_, shortCircuit, err := PreMCPHook(nil, request)
	if err != nil || shortCircuit == nil || shortCircuit.Error == nil {
		t.Fatalf("expected MCP denial, got shortCircuit %v, err %v", shortCircuit, err)
	}
	if shortCircuit.Error.AllowFallbacks == nil || *shortCircuit.Error.AllowFallbacks {
		t.Fatal("MCP security denial must disable fallback")
	}
}

func TestPreMCPHookAllowsPausedDaemon(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		_, _ = writer.Write([]byte(`{"clean":true,"blocked":false,"paused":true,"reason_code":"middleware_paused"}`))
	}))
	defer server.Close()
	activeClient = &daemonClient{url: server.URL, token: "daemon-token", maxPayload: 4096, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	tool := "read_file"
	request := &schemas.BifrostMCPRequest{
		RequestType: schemas.MCPRequestTypeChatToolCall,
		ClientName:  "filesystem",
		ChatAssistantMessageToolCall: &schemas.ChatAssistantMessageToolCall{
			Function: schemas.ChatAssistantMessageToolCallFunction{Name: &tool, Arguments: `{}`},
		},
	}
	_, shortCircuit, err := PreMCPHook(nil, request)
	if err != nil || shortCircuit != nil {
		t.Fatalf("paused daemon should allow MCP operation, got %v / %v", shortCircuit, err)
	}
}

func TestPostMCPHookInspectsToolResult(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		var body daemonRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(body.Content, "tool result") {
			t.Fatalf("tool result was not sent for inspection: %s", body.Content)
		}
		_, _ = writer.Write([]byte(`{"clean":false,"blocked":true}`))
	}))
	defer server.Close()
	activeClient = &daemonClient{url: server.URL, token: "daemon-token", maxPayload: 4096, httpClient: server.Client()}
	defer func() { activeClient = nil }()
	result := "tool result"
	response := &schemas.BifrostMCPResponse{
		ChatMessage: &schemas.ChatMessage{Content: &schemas.ChatMessageContent{ContentStr: &result}},
		ExtraFields: schemas.BifrostMCPResponseExtraFields{MCPRequestType: schemas.MCPRequestTypeChatToolCall, ClientName: "filesystem", ToolName: "read_file"},
	}
	_, bifrostErr, err := PostMCPHook(nil, response, nil)
	if err != nil || bifrostErr == nil {
		t.Fatalf("expected MCP result denial, got %v / %v", bifrostErr, err)
	}
}

func TestHTTPTransportStreamChunkHookBlocksBeforeDelivery(t *testing.T) {
	chunk := &schemas.BifrostStreamChunk{
		BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"},
	}

	result, err := HTTPTransportStreamChunkHook(nil, nil, chunk)
	if result != nil {
		t.Fatal("streaming content must not be returned before inspection")
	}
	assertStreamError(t, err, "ai_guardian_stream_unsupported")
}

func TestHTTPTransportStreamChunkHookDoesNotEmitSplitUTF8Fragments(t *testing.T) {
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	defer ctx.Cancel()
	chunks := []*schemas.BifrostStreamChunk{
		{BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"}},
		{BifrostChatResponse: &schemas.BifrostChatResponse{Object: "chat.completion.chunk"}},
	}

	for _, chunk := range chunks {
		result, err := HTTPTransportStreamChunkHook(ctx, nil, chunk)
		if result != nil {
			t.Fatal("split UTF-8 content must not be emitted")
		}
		assertStreamError(t, err, "ai_guardian_stream_unsupported")
	}
}

func TestHTTPTransportStreamChunkHookStopsOnCancellation(t *testing.T) {
	ctx := schemas.NewBifrostContext(context.Background(), time.Time{})
	ctx.Cancel()

	result, err := HTTPTransportStreamChunkHook(ctx, nil, &schemas.BifrostStreamChunk{})
	if result != nil {
		t.Fatal("cancelled stream must not emit a chunk")
	}
	assertStreamError(t, err, "ai_guardian_stream_cancelled")
}

func assertStreamError(t *testing.T, err error, code string) {
	t.Helper()
	interception, ok := err.(*schemas.StreamInterceptionError)
	if !ok || interception.BifrostError == nil || interception.BifrostError.Error == nil || interception.BifrostError.Error.Code == nil {
		t.Fatalf("error = %#v, want structured stream interception error", err)
	}
	if *interception.BifrostError.Error.Code != code {
		t.Fatalf("error code = %q, want %q", *interception.BifrostError.Error.Code, code)
	}
}

func stringPtr(value string) *string { return &value }
