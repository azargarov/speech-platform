package gateway

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"speech-platform/internal/transport"
)

func TestRequestIDMiddlewareReturnsAndLogsOneServerOwnedID(t *testing.T) {
	var logs strings.Builder
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	handler := WithRequestID(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := transport.RequestID(r.Context())
		if id == "" || id == "caller-controlled" {
			t.Errorf("context contains missing or caller-controlled ID %q", id)
		}
		w.Header().Set("X-Speech-Provider", "local")
		transport.JSON(w, http.StatusUnauthorized, transport.Error{Code: "unauthorized", Message: "safe error"})
	}), logger)

	request := httptest.NewRequest(http.MethodGet, "/v1/test", nil)
	request.Header.Set(RequestIDHeader, "caller-controlled")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	id := response.Header().Get(RequestIDHeader)
	if id == "" || id == "caller-controlled" || len(id) != 36 {
		t.Fatalf("invalid server request ID: %q", id)
	}
	if response.Code != http.StatusUnauthorized || !strings.Contains(response.Body.String(), `"code":"unauthorized"`) {
		t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
	}
	var events []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(logs.String()), "\n") {
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatal(err)
		}
		events = append(events, event)
	}
	if len(events) != 2 || events[0]["msg"] != "request started" || events[1]["msg"] != "request failed" {
		t.Fatalf("unexpected request events: %#v", events)
	}
	for _, event := range events {
		if event["request_id"] != id {
			t.Fatalf("event does not contain response request ID: %#v", event)
		}
	}
	if events[1]["api_code"] != "unauthorized" || events[1]["provider"] != "local" {
		t.Fatalf("failure metadata missing: %#v", events[1])
	}
	if strings.Contains(logs.String(), "safe error") {
		t.Fatal("response message leaked into request logs")
	}
}

func TestRequestIDMiddlewareAssignsDistinctConcurrentIDs(t *testing.T) {
	handler := WithRequestID(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}), slog.New(slog.NewTextHandler(io.Discard, nil)))
	const requests = 64
	ids := make(chan string, requests)
	var group sync.WaitGroup
	for i := 0; i < requests; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/readyz", nil))
			ids <- response.Header().Get(RequestIDHeader)
		}()
	}
	group.Wait()
	close(ids)
	seen := map[string]bool{}
	for id := range ids {
		if len(id) != 36 || seen[id] {
			t.Fatalf("missing or duplicate request ID %q", id)
		}
		seen[id] = true
	}
	if len(seen) != requests {
		t.Fatalf("got %d distinct IDs, want %d", len(seen), requests)
	}
}
