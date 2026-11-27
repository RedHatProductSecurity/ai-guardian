package main

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestDaemonClientHTTPCheckUsesBoundedSecurityRequest(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/api/check" {
			t.Fatalf("path = %s, want /api/check", request.URL.Path)
		}
		if request.Header.Get("Authorization") != "Bearer test-token" {
			t.Fatalf("missing daemon authorization")
		}
		var body daemonRequest
		if err := json.NewDecoder(request.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.Action != "block" || body.Content != "safe prompt" || body.ProjectDir != "/srv/project" {
			t.Fatalf("unexpected check body: %+v", body)
		}
		if len(body.Checks) != 4 {
			t.Fatalf("checks = %v, want all MVP checks", body.Checks)
		}
		_, _ = writer.Write([]byte(`{"clean":true,"blocked":false}`))
	}))
	defer server.Close()

	client := &daemonClient{
		url:        server.URL,
		token:      "test-token",
		projectDir: "/srv/project",
		maxPayload: 1024,
		httpClient: server.Client(),
	}
	verdict, err := client.check("safe prompt")
	if err != nil {
		t.Fatal(err)
	}
	if !verdict.Clean || verdict.Blocked {
		t.Fatalf("unexpected verdict: %+v", verdict)
	}
}

func TestDaemonClientRejectsOversizedPayload(t *testing.T) {
	client := &daemonClient{maxPayload: 4}
	if _, err := client.check("too large"); err == nil {
		t.Fatal("oversized payload was accepted")
	}
}

func TestDaemonClientUnixCheckUsesDaemonSDKEnvelope(t *testing.T) {
	socketPath := filepath.Join(t.TempDir(), "daemon.sock")
	listener, err := net.ListenUnix("unix", &net.UnixAddr{Name: socketPath, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()

	go func() {
		connection, acceptErr := listener.AcceptUnix()
		if acceptErr != nil {
			return
		}
		defer connection.Close()
		var length uint32
		if binary.Read(connection, binary.BigEndian, &length) != nil {
			return
		}
		payload := make([]byte, length)
		if _, readErr := io.ReadFull(connection, payload); readErr != nil {
			return
		}
		var envelope struct {
			Type string `json:"type"`
			Data struct {
				CheckType string `json:"check_type"`
				Text      string `json:"text"`
			} `json:"data"`
		}
		if json.Unmarshal(payload, &envelope) != nil || envelope.Type != "sdk_check" || envelope.Data.CheckType != "middleware" || envelope.Data.Text != "safe prompt" {
			return
		}
		response := []byte(`{"type":"response","data":{"data":{"clean":true,"blocked":false}}}`)
		_ = binary.Write(connection, binary.BigEndian, uint32(len(response)))
		_, _ = connection.Write(response)
	}()

	client := &daemonClient{socket: socketPath, maxPayload: 1024}
	verdict, err := client.check("safe prompt")
	if err != nil {
		t.Fatal(err)
	}
	if !verdict.Clean || verdict.Blocked {
		t.Fatalf("unexpected verdict: %+v", verdict)
	}
}

func TestConfiguredScanErrorActionReadsGlobalConfig(t *testing.T) {
	configDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(configDir, "ai-guardian.json"), []byte(`{"on_scan_error":"allow"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AI_GUARDIAN_CONFIG_DIR", configDir)
	t.Setenv("AI_GUARDIAN_CONFIG_INLINE", "")
	t.Setenv("AI_GUARDIAN_CONFIG_OVERLAY", "")
	t.Setenv("AI_GUARDIAN_BIFROST_FAILURE_MODE", "")

	action, ok := configuredScanErrorAction()
	if !ok || action != "allow" {
		t.Fatalf("configured action = %q, %v; want allow, true", action, ok)
	}
}
