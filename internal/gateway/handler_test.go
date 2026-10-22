package gateway

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestFoundation(t *testing.T) {
	h := Handler(Foundation{}, 1024)
	for _, tc := range []struct {
		method, path string
		status       int
	}{{"GET", "/metrics", 200}, {"GET", "/healthz", 200}, {"GET", "/readyz", 503}, {"POST", "/v1/stt/transcriptions", 503}, {"POST", "/v1/tts/speech", 503}, {"GET", "/v1/stt/models", 404}, {"GET", "/v1/tts/voices", 503}} {
		r := httptest.NewRequest(tc.method, tc.path, nil)
		if tc.path == "/v1/stt/transcriptions" {
			r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
		} else if tc.path == "/v1/tts/speech" {
			r.Header.Set("Content-Type", "application/json")
			r.Body = io.NopCloser(strings.NewReader(`{"text":"hello"}`))
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.status {
			t.Fatalf("%s: %d", tc.path, w.Code)
		}
	}
}

func TestRequestSizeLimit(t *testing.T) {
	h := Handler(Foundation{}, 4)
	for _, tc := range []struct {
		name string
		body string
		want int
	}{{"at_limit", "1234", 503}, {"over_limit", "12345", 413}, {"unknown_length_over_limit", "12345", 413}} {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/v1/stt/transcriptions", strings.NewReader(tc.body))
			r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
			if tc.name == "unknown_length_over_limit" {
				r.ContentLength = -1
			}
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code != tc.want {
				t.Fatalf("status=%d want=%d body=%s", w.Code, tc.want, w.Body.String())
			}
			if tc.want == 413 {
				var response map[string]string
				if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil || response["code"] != "request_too_large" {
					t.Fatalf("response=%q error=%v", w.Body.String(), err)
				}
			}
		})
	}
}

func TestSTTProxyForwardsBoundedRequestAndRequiresConfiguredToken(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.URL.Path != "/internal/v1/transcriptions" || r.Header.Get("X-Request-Timeout-Ms") != "180000" || r.ContentLength <= 0 {
			t.Errorf("bad forwarded request: %#v", r)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"text":"ok","transcription":"ok","language":"en","detected_language":"en","source_language":"en","output_language":"en","translated":false}`))
	}))
	defer worker.Close()
	proxy := NewSTTProxy(worker.URL, "12345678901234567890123456789012", 180*time.Second)
	h := HandlerWithSTT(proxy, 1024, proxy)
	unauthorized := httptest.NewRequest("POST", "/v1/stt/transcriptions", strings.NewReader("payload"))
	unauthorized.Header.Set("Content-Type", "multipart/form-data; boundary=x")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, unauthorized)
	if w.Code != http.StatusUnauthorized {
		t.Fatalf("unauthorized status=%d", w.Code)
	}
	r := httptest.NewRequest("POST", "/v1/stt/transcriptions", strings.NewReader("--x--\r\n"))
	r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
	r.Header.Set("Authorization", "Bearer 12345678901234567890123456789012")
	w = httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), `"transcription":"ok"`) {
		t.Fatalf("status=%d response=%s", w.Code, w.Body.String())
	}
	ready := httptest.NewRecorder()
	h.ServeHTTP(ready, httptest.NewRequest("GET", "/readyz", nil))
	if ready.Code != http.StatusOK {
		t.Fatalf("readiness=%d", ready.Code)
	}
}

func TestTTSProxyValidationForwardingAndAudioResponse(t *testing.T) {
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.URL.Path != "/internal/v1/speech" || r.Header.Get("X-Request-Timeout-Ms") != "600000" {
			t.Errorf("bad forwarded request: path=%s timeout=%s", r.URL.Path, r.Header.Get("X-Request-Timeout-Ms"))
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode request: %v", err)
		}
		if body["language"] != "auto" || body["voice"] != "default" {
			t.Errorf("unexpected defaults: %#v", body)
		}
		if body["input_format"] == nil {
			t.Errorf("input_format default was not forwarded: %#v", body)
		}
		if body["text"] == "hello" && body["mode"] != "quality" {
			t.Errorf("mode default=%v, want quality", body["mode"])
		}
		if body["text"] == "hello" && body["input_format"] != "text" {
			t.Errorf("input_format default=%v, want text", body["input_format"])
		}
		if body["text"] == "hello ssml" && body["input_format"] != "ssml" {
			t.Errorf("input_format=%v, want ssml", body["input_format"])
		}
		if body["text"] == "hello fast" && body["mode"] != "fast" {
			t.Errorf("forwarded mode=%v, want fast", body["mode"])
		}
		if body["text"] == "hello high quality" && body["mode"] != "high_quality" {
			t.Errorf("forwarded mode=%v, want high_quality", body["mode"])
		}
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write([]byte("RIFF-test"))
	}))
	defer worker.Close()
	proxy := NewTTSProxy(worker.URL, "12345678901234567890123456789012", 600*time.Second)
	stt := NewSTTProxy(worker.URL, "", time.Second)
	h := HandlerWithWorkers(NewWorkersReadiness(stt, proxy), 1024, stt, proxy)
	for _, tc := range []struct {
		name, body string
		status     int
		code       string
	}{
		{"valid", `{"text":"hello"}`, 200, ""},
		{"explicit_ssml", `{"text":"hello ssml","input_format":"ssml"}`, 200, ""},
		{"fast_mode", `{"text":"hello fast","mode":"fast"}`, 200, ""},
		{"high_quality_mode", `{"text":"hello high quality","mode":"high_quality"}`, 200, ""},
		{"invalid_language", `{"text":"hello","language":"zh"}`, 400, "invalid_language"},
		{"invalid_mode", `{"text":"hello","mode":"turbo"}`, 400, "invalid_mode"},
		{"invalid_input_format", `{"text":"hello","input_format":"guess"}`, 400, "invalid_input_format"},
		{"null_input_format", `{"text":"hello","input_format":null}`, 400, "invalid_input_format"},
		{"ssml_language_field", `{"text":"hello","input_format":"ssml","language":"en"}`, 400, "invalid_language"},
		{"unknown_field", `{"text":"hello","extra":true}`, 400, "invalid_request"},
		{"empty_text", `{"text":"   "}`, 400, "invalid_text"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodPost, "/v1/tts/speech", strings.NewReader(tc.body))
			r.Header.Set("Content-Type", "application/json")
			r.Header.Set("Authorization", "Bearer 12345678901234567890123456789012")
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code != tc.status {
				t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
			}
			if tc.status == 200 && (w.Header().Get("Content-Type") != "audio/wav" || w.Body.String() != "RIFF-test") {
				t.Fatalf("unexpected audio response: %#v %q", w.Header(), w.Body.String())
			}
			if tc.code != "" {
				var got map[string]string
				_ = json.Unmarshal(w.Body.Bytes(), &got)
				if got["code"] != tc.code {
					t.Fatalf("error=%v", got)
				}
			}
		})
	}
}
