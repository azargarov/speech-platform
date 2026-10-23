package gateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"speech-platform/internal/config"
	"speech-platform/internal/texttransform"
)

// This exercises the real public Gateway routes and Ollama adapter against
// deterministic local workers. It intentionally makes no model or provider calls.
func TestM06WarmupAndInferenceIntegrationAcrossAllBackends(t *testing.T) {
	const token = warmupTestToken
	var mu sync.Mutex
	events := []string{}
	failOllamaWarmup := false
	appendEvent := func(value string) {
		mu.Lock()
		events = append(events, value)
		mu.Unlock()
	}

	sttWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/internal/v1/warmup":
			if r.Header.Get("Authorization") != "Bearer "+token {
				t.Errorf("STT warmup auth not forwarded: %q", r.Header.Get("Authorization"))
			}
			if r.ContentLength != 0 || r.Header.Get("X-Request-Timeout-Ms") == "" {
				t.Errorf("invalid STT warmup control request: length=%d timeout=%q", r.ContentLength, r.Header.Get("X-Request-Timeout-Ms"))
			}
			appendEvent("warmup:stt")
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"model_state":"ready"}`)
		case "/internal/v1/transcriptions":
			if r.Header.Get("X-Request-Timeout-Ms") == "" || r.ContentLength <= 0 {
				t.Errorf("invalid STT inference forwarding: %#v", r)
			}
			appendEvent("inference:stt")
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"text":"synthetic transcription","transcription":"synthetic transcription","language":"en","detected_language":"en","source_language":"en","output_language":"en","translated":false}`)
		default:
			t.Errorf("unexpected STT path %q", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer sttWorker.Close()

	ttsWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/internal/v1/warmup":
			if r.Header.Get("Authorization") != "Bearer "+token {
				t.Errorf("TTS warmup auth not forwarded: %q", r.Header.Get("Authorization"))
			}
			if r.ContentLength != 0 || r.Header.Get("X-Request-Timeout-Ms") != "" {
				t.Errorf("invalid TTS warmup control request: length=%d timeout=%q", r.ContentLength, r.Header.Get("X-Request-Timeout-Ms"))
			}
			appendEvent("warmup:tts")
			_, _ = io.WriteString(w, `{"model_state":"ready","inference_active":false}`)
		case "/internal/v1/speech":
			var request map[string]any
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil || request["text"] != "synthetic speech input" {
				t.Errorf("invalid TTS inference payload: %#v err=%v", request, err)
			}
			appendEvent("inference:tts")
			w.Header().Set("Content-Type", "audio/wav")
			_, _ = w.Write([]byte("synthetic-wav"))
		default:
			t.Errorf("unexpected TTS path %q", r.URL.Path)
			http.NotFound(w, r)
		}
	}))
	defer ttsWorker.Close()

	cfg, err := config.Load("../../configs/gateway-text.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/generate" {
			t.Errorf("unexpected Ollama path %q", r.URL.Path)
		}
		var request map[string]any
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Errorf("decode Ollama request: %v", err)
		}
		if request["model"] != "qwen3.5:9b-q4_K_M" || request["stream"] != false || request["think"] != false {
			t.Errorf("unexpected Ollama request options: %#v", request)
		}
		prompt, hasPrompt := request["prompt"]
		if hasPrompt {
			if prompt == "" || request["keep_alive"] != float64(0) {
				t.Errorf("unexpected normal transformation prompt: %#v", prompt)
			}
			appendEvent("inference:text_transform")
			_, _ = io.WriteString(w, `{"response":"synthetic transformed result","done":true}`)
			return
		}
		if _, hasSystem := request["system"]; hasSystem {
			t.Errorf("warmup must not send user/system content: %#v", request)
		}
		if keepAlive, ok := request["keep_alive"].(string); !ok || keepAlive == "0s" || keepAlive == "" {
			t.Errorf("warmup must have finite positive residency: %#v", request["keep_alive"])
		}
		appendEvent("warmup:text_transform")
		mu.Lock()
		fail := failOllamaWarmup
		failOllamaWarmup = false
		mu.Unlock()
		if fail {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = io.WriteString(w, `{"error":"secret provider detail"}`)
			return
		}
		_, _ = io.WriteString(w, `{"response":"","done":true}`)
	}))
	defer ollama.Close()
	cfg.TextTransform.Providers[0].Endpoint = ollama.URL + "/api/generate"
	textService, err := texttransform.New(context.Background(), cfg.TextTransform, token, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer textService.Close()

	stt := NewSTTProxy(sttWorker.URL, token, 2*time.Second)
	tts := NewTTSProxy(ttsWorker.URL, token, 2*time.Second)
	h := HandlerWithWarmupContext(Foundation{}, config.PublicMaxRequestBytes, stt, tts, textService, 4*time.Second, context.Background())

	// Ordinary local transformation works before any predictive warmup.
	if got := servePublic(t, h, http.MethodPost, "/v1/text/transformations", `{"text":"synthetic private input","mode":"written","model":"local-qwen","local_only":true}`, token, "application/json"); got.Code != http.StatusOK {
		t.Fatalf("normal transformation before warmup status=%d body=%s", got.Code, got.Body.String())
	}
	preWarmEvents := snapshotEvents(&mu, events)
	if len(preWarmEvents) != 1 || preWarmEvents[0] != "inference:text_transform" {
		t.Fatalf("unexpected pre-warmup calls: %v", preWarmEvents)
	}

	warmupCases := [][]string{
		{"stt"}, {"tts"}, {"text_transform"},
		{"stt", "text_transform"}, {"stt", "tts"}, {"stt", "tts", "text_transform"},
	}
	wantWarmupEvents := []string{"inference:text_transform"}
	for _, operations := range warmupCases {
		payload, err := json.Marshal(map[string][]string{"operations": operations})
		if err != nil {
			t.Fatal(err)
		}
		warm := servePublic(t, h, http.MethodPost, "/v1/models/warmup", string(payload), token, "application/json")
		response := decodeWarmup(t, warm)
		if warm.Code != http.StatusOK || !response.Complete || len(response.Results) != len(operations) {
			t.Fatalf("operations=%v status=%d response=%+v body=%s", operations, warm.Code, response, warm.Body.String())
		}
		for i, expected := range operations {
			if response.Results[i].Operation != expected || response.Results[i].Status != "ready" {
				t.Fatalf("operations=%v result[%d]=%+v", operations, i, response.Results[i])
			}
			wantWarmupEvents = append(wantWarmupEvents, "warmup:"+expected)
		}
		if strings.Contains(warm.Body.String(), "synthetic transformed result") || strings.Contains(warm.Body.String(), "qwen3.5") {
			t.Fatalf("warmup response exposed provider output/model: %s", warm.Body.String())
		}
	}
	mu.Lock()
	failOllamaWarmup = true
	mu.Unlock()
	partial := servePublic(t, h, http.MethodPost, "/v1/models/warmup", `{"operations":["stt","text_transform"]}`, token, "application/json")
	partialResult := decodeWarmup(t, partial)
	if partial.Code != http.StatusOK || partialResult.Complete || len(partialResult.Results) != 2 || partialResult.Results[0].Status != "ready" || partialResult.Results[1].Status != "resource_unavailable" || strings.Contains(partial.Body.String(), "secret provider detail") {
		t.Fatalf("local Ollama failure did not preserve/sanitize STT result: status=%d response=%+v body=%s", partial.Code, partialResult, partial.Body.String())
	}
	wantWarmupEvents = append(wantWarmupEvents, "warmup:stt", "warmup:text_transform")

	sttRequest := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", strings.NewReader("--b\r\nContent-Disposition: form-data; name=audio; filename=x.wav\r\nContent-Type: audio/wav\r\n\r\nsynthetic-audio\r\n--b--\r\n"))
	sttRequest.Header.Set("Content-Type", "multipart/form-data; boundary=b")
	sttRequest.Header.Set("Authorization", "Bearer "+token)
	sttResponse := httptest.NewRecorder()
	h.ServeHTTP(sttResponse, sttRequest)
	if sttResponse.Code != http.StatusOK || !strings.Contains(sttResponse.Body.String(), "synthetic transcription") {
		t.Fatalf("STT inference after warmup status=%d body=%s", sttResponse.Code, sttResponse.Body.String())
	}
	if got := servePublic(t, h, http.MethodPost, "/v1/tts/speech", `{"text":"synthetic speech input"}`, token, "application/json"); got.Code != http.StatusOK || got.Body.String() != "synthetic-wav" {
		t.Fatalf("TTS inference after warmup status=%d body=%q", got.Code, got.Body.String())
	}
	if got := servePublic(t, h, http.MethodPost, "/v1/text/transformations", `{"text":"synthetic private input","mode":"written","model":"local-qwen","local_only":true}`, token, "application/json"); got.Code != http.StatusOK || !strings.Contains(got.Body.String(), "synthetic transformed result") {
		t.Fatalf("text inference after warmup status=%d body=%s", got.Code, got.Body.String())
	}

	gotEvents := snapshotEvents(&mu, events)
	want := append(wantWarmupEvents, "inference:stt", "inference:tts", "inference:text_transform")
	if strings.Join(gotEvents, ",") != strings.Join(want, ",") {
		t.Fatalf("upstream operation order=%v want=%v", gotEvents, want)
	}
}

func servePublic(t *testing.T, h http.Handler, method, path, body, token, contentType string) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.Header.Set("Content-Type", contentType)
	if token != "" {
		r.Header.Set("Authorization", "Bearer "+token)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func snapshotEvents(mu *sync.Mutex, events []string) []string {
	mu.Lock()
	defer mu.Unlock()
	return append([]string(nil), events...)
}
