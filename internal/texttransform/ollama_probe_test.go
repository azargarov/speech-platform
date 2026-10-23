package texttransform

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"speech-platform/internal/config"
)

func TestCheckLocalOllamaUsesReadOnlyVersionEndpoint(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.Method != http.MethodGet || r.URL.Path != "/api/version" {
			t.Errorf("request = %s %s", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"version":"0.33.1"}`))
	}))
	defer server.Close()

	endpoint := ollamaTestEndpoint(t, server)
	settings := ollamaTestSettings(endpoint)
	if err := checkLocalOllama(context.Background(), &settings, ollamaTestLookup); err != nil {
		t.Fatalf("checkLocalOllama() error = %v", err)
	}
	if requests != 1 {
		t.Fatalf("requests = %d, want 1", requests)
	}
}

func TestCheckLocalOllamaReportsDNSFailure(t *testing.T) {
	settings := ollamaTestSettings("http://ollama:11434/api/generate")
	lookup := func(context.Context, string) ([]net.IPAddr, error) {
		return nil, fmt.Errorf("lookup failed")
	}
	err := checkLocalOllama(context.Background(), &settings, lookup)
	if err == nil || !strings.Contains(err.Error(), "DNS lookup failed") {
		t.Fatalf("error = %v, want DNS failure", err)
	}
}

func TestCheckLocalOllamaReportsTCPFailure(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := listener.Addr().String()
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	_, port, err := net.SplitHostPort(address)
	if err != nil {
		t.Fatal(err)
	}
	settings := ollamaTestSettings("http://ollama:" + port + "/api/generate")
	err = checkLocalOllama(context.Background(), &settings, ollamaTestLookup)
	if err == nil || !strings.Contains(err.Error(), "TCP connection failed") {
		t.Fatalf("error = %v, want TCP failure", err)
	}
}

func TestCheckLocalOllamaRejectsProviderFailureAndMalformedVersion(t *testing.T) {
	for _, test := range []struct {
		name string
		body string
		code int
	}{
		{name: "http error", body: `{"error":"unavailable"}`, code: http.StatusServiceUnavailable},
		{name: "invalid version", body: `{"version":""}`, code: http.StatusOK},
		{name: "malformed JSON", body: `{`, code: http.StatusOK},
	} {
		t.Run(test.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(test.code)
				_, _ = w.Write([]byte(test.body))
			}))
			defer server.Close()
			settings := ollamaTestSettings(ollamaTestEndpoint(t, server))
			err := checkLocalOllama(context.Background(), &settings, ollamaTestLookup)
			if err == nil {
				t.Fatal("checkLocalOllama() succeeded")
			}
		})
	}
}

func TestCheckLocalOllamaRequiresNetworkAlias(t *testing.T) {
	settings := ollamaTestSettings("http://host.docker.internal:11434/api/generate")
	err := checkLocalOllama(context.Background(), &settings, ollamaTestLookup)
	if err == nil || !strings.Contains(err.Error(), "ollama network alias") {
		t.Fatalf("error = %v, want alias validation error", err)
	}
}

func TestCheckLocalOllamaRequiresEnabledLocalModel(t *testing.T) {
	settings := ollamaTestSettings("http://ollama:11434/api/generate")
	settings.Models[0].Enabled = boolPointer(false)
	err := checkLocalOllama(context.Background(), &settings, ollamaTestLookup)
	if err == nil || !strings.Contains(err.Error(), "no enabled local Ollama model") {
		t.Fatalf("error = %v, want no-model error", err)
	}
}

func ollamaTestSettings(endpoint string) config.TextTransform {
	enabled := true
	return config.TextTransform{
		Enabled: &enabled,
		Providers: []config.TextProvider{{
			ID: "local-provider", Type: "ollama", Locality: "local", Endpoint: endpoint,
		}},
		Models: []config.TextModel{{
			ID: "local-model", Provider: "local-provider", Enabled: &enabled,
		}},
	}
}

func ollamaTestEndpoint(t *testing.T, server *httptest.Server) string {
	t.Helper()
	parsed, err := url.Parse(server.URL)
	if err != nil {
		t.Fatal(err)
	}
	return fmt.Sprintf("http://ollama:%s/api/generate", parsed.Port())
}

func ollamaTestLookup(context.Context, string) ([]net.IPAddr, error) {
	return []net.IPAddr{{IP: net.ParseIP("127.0.0.1")}}, nil
}

func boolPointer(value bool) *bool { return &value }
