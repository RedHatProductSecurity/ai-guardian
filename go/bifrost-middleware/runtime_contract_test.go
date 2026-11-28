package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/maximhq/bifrost/core/schemas"
)

// TestRuntimeContractReachesMockDaemonAndProvider keeps the canonical runtime
// lane honest: an allowed request must cross both middleware boundaries, while
// the daemon sees only normalized content.
func TestRuntimeContractReachesMockDaemonAndProvider(t *testing.T) {
	var daemonRequests atomic.Int32
	daemon := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		daemonRequests.Add(1)
		body, err := io.ReadAll(request.Body)
		if err != nil {
			t.Fatal(err)
		}
		payload := string(body)
		if !strings.Contains(payload, "runtime contract prompt") {
			t.Fatalf("normalized prompt missing from daemon request: %s", payload)
		}
		if strings.Contains(payload, "provider-secret") {
			t.Fatal("provider credential leaked into daemon request")
		}
		_, _ = writer.Write([]byte(`{"clean":true,"blocked":false}`))
	}))
	defer daemon.Close()

	var providerRequests atomic.Int32
	provider := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		providerRequests.Add(1)
		_, _ = writer.Write([]byte(`{"id":"mock-response","object":"chat.completion"}`))
	}))
	defer provider.Close()

	activeClient = &daemonClient{url: daemon.URL, maxPayload: 4096, httpClient: daemon.Client()}
	defer func() { activeClient = nil }()
	prompt := "runtime contract prompt"
	request := &schemas.BifrostRequest{ChatRequest: &schemas.BifrostChatRequest{
		Model:  "mock-model",
		Input:  []schemas.ChatMessage{{Content: &schemas.ChatMessageContent{ContentStr: &prompt}}},
		Params: &schemas.ChatParameters{MCPServers: []schemas.ChatMCPServer{{AuthorizationToken: stringPtr("provider-secret")}}},
	}}
	if _, shortCircuit, err := PreLLMHook(nil, request); err != nil || shortCircuit != nil {
		t.Fatalf("PreLLMHook() = shortCircuit %v, err %v", shortCircuit, err)
	}
	response, err := http.Get(provider.URL)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if daemonRequests.Load() != 1 || providerRequests.Load() != 1 {
		t.Fatalf("boundary requests = daemon %d, provider %d; want one each", daemonRequests.Load(), providerRequests.Load())
	}
}
