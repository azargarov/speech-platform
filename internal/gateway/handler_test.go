package gateway

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"speech-platform/internal/config"
	"speech-platform/internal/texttransform"
)

type gatewayFakeGenerator struct{ calls []string }

func (g *gatewayFakeGenerator) Generate(_ context.Context, _ config.TextProvider, m config.TextModel, _, _, _, _ string) (string, error) {
	g.calls = append(g.calls, m.ID)
	return "synthetic fake response", nil
}

func TestTextTransformationRunsThroughPublicGatewayRouteWithFakeProvider(t *testing.T) {
	cfg, err := config.Load("../../configs/gateway.yaml")
	if err != nil {
		t.Fatal(err)
	}
	cfg.TextTransform.Selection.AllowCloud = false
	const token = "01234567890123456789012345678901"
	generator := &gatewayFakeGenerator{}
	service, err := texttransform.New(context.Background(), cfg.TextTransform, token, generator)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	h := WithRequestID(HandlerWithWorkersAndText(unreadyState{}, config.PublicMaxRequestBytes, nil, nil, service), slog.New(slog.NewTextHandler(io.Discard, nil)))

	unauthorized := httptest.NewRecorder()
	r := httptest.NewRequest(http.MethodPost, "/v1/text/transformations", strings.NewReader(`{"text":"Synthetic note","model":"local-qwen"}`))
	r.Header.Set("Content-Type", "application/json")
	h.ServeHTTP(unauthorized, r)
	if unauthorized.Code != http.StatusUnauthorized || unauthorized.Header().Get(RequestIDHeader) == "" || len(generator.calls) != 0 {
		t.Fatalf("unauthorized status=%d provider calls=%v", unauthorized.Code, generator.calls)
	}

	response := httptest.NewRecorder()
	r = httptest.NewRequest(http.MethodPost, "/v1/text/transformations", strings.NewReader(`{"text":"Synthetic note; keep November 18 unchanged.","mode":"diplomatic","format":"structured","target_language":"sv","model":"local-qwen","local_only":true}`))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Authorization", "Bearer "+token)
	h.ServeHTTP(response, r)
	if response.Code != http.StatusOK || response.Header().Get(RequestIDHeader) == "" || len(generator.calls) != 1 || generator.calls[0] != "local-qwen" {
		t.Fatalf("status=%d provider calls=%v body=%s", response.Code, generator.calls, response.Body.String())
	}
	if !strings.Contains(response.Body.String(), `"provider":"host-ollama"`) || !strings.Contains(response.Body.String(), `"fallback_occurred":false`) {
		t.Fatalf("unexpected response metadata: %s", response.Body.String())
	}

	policyRejected := httptest.NewRecorder()
	r = httptest.NewRequest(http.MethodPost, "/v1/text/transformations", strings.NewReader(`{"text":"Synthetic note","mode":"written","model":"groq-qwen","local_only":false}`))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Authorization", "Bearer "+token)
	r.Header.Set(RequestIDHeader, "caller-controlled")
	h.ServeHTTP(policyRejected, r)
	var policyError map[string]string
	if err := json.Unmarshal(policyRejected.Body.Bytes(), &policyError); err != nil {
		t.Fatal(err)
	}
	if policyRejected.Code != http.StatusForbidden || policyError["code"] != "cloud_not_allowed" || policyRejected.Header().Get(RequestIDHeader) == "" || policyRejected.Header().Get(RequestIDHeader) == "caller-controlled" || len(generator.calls) != 1 {
		t.Fatalf("policy rejection status=%d error=%v request_id=%q provider_calls=%v", policyRejected.Code, policyError, policyRejected.Header().Get(RequestIDHeader), generator.calls)
	}
}

func TestTextTransformationRouteUsesSharedGatewayAndBearerBoundary(t *testing.T) {
	disabled := false
	cfg := &config.TextTransform{Enabled: &disabled}
	service, err := texttransform.New(context.Background(), cfg, "01234567890123456789012345678901", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Close()
	h := HandlerWithWorkersAndText(unreadyState{}, config.PublicMaxRequestBytes, nil, nil, service)
	for _, tc := range []struct {
		method, auth string
		want         int
	}{{http.MethodPost, "", 401}, {http.MethodPost, "Bearer 01234567890123456789012345678901", 503}, {http.MethodGet, "Bearer 01234567890123456789012345678901", 405}} {
		r := httptest.NewRequest(tc.method, "/v1/text/transformations", strings.NewReader(`{"text":"hello"}`))
		r.Header.Set("Content-Type", "application/json")
		if tc.auth != "" {
			r.Header.Set("Authorization", tc.auth)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.want {
			t.Errorf("%s auth=%t status=%d want %d body=%s", tc.method, tc.auth != "", w.Code, tc.want, w.Body.String())
		}
	}
}

func TestHandlerHealthReadinessAndUnavailableRoutes(t *testing.T) {
	h := Handler(unreadyState{}, 1024)
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

func TestOptionalServicesReadinessDisabledRoutesAndAuthentication(t *testing.T) {
	const token = "01234567890123456789012345678901"
	h := HandlerWithOptionalServices(WorkersReadiness{}, 1024, token, false, false, nil, nil, nil, time.Minute, context.Background(), nil, false, 2)
	ready := httptest.NewRecorder()
	h.ServeHTTP(ready, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if ready.Code != http.StatusOK {
		t.Fatalf("Gateway-only readiness=%d body=%s", ready.Code, ready.Body.String())
	}
	for _, tc := range []struct {
		path, contentType, body string
	}{{"/v1/stt/transcriptions", "multipart/form-data; boundary=x", ""}, {"/v1/tts/speech", "application/json", `{}`}} {
		unauthorized := httptest.NewRecorder()
		r := httptest.NewRequest(http.MethodPost, tc.path, strings.NewReader(tc.body))
		r.Header.Set("Content-Type", tc.contentType)
		h.ServeHTTP(unauthorized, r)
		if unauthorized.Code != http.StatusUnauthorized {
			t.Fatalf("disabled unauthenticated %s status=%d body=%s", tc.path, unauthorized.Code, unauthorized.Body.String())
		}
		authorized := httptest.NewRecorder()
		r = httptest.NewRequest(http.MethodPost, tc.path, strings.NewReader(tc.body))
		r.Header.Set("Content-Type", tc.contentType)
		r.Header.Set("Authorization", "Bearer "+token)
		h.ServeHTTP(authorized, r)
		if authorized.Code != http.StatusServiceUnavailable || !strings.Contains(authorized.Body.String(), `"code":"capability_disabled"`) {
			t.Fatalf("disabled authorized %s status=%d body=%s", tc.path, authorized.Code, authorized.Body.String())
		}
	}
}

func TestEnabledGroqWithoutCredentialsIsUnavailableAndCloudConsentStillApplies(t *testing.T) {
	const token = "01234567890123456789012345678901"
	h := HandlerWithOptionalServices(WorkersReadiness{}, 1024, token, false, false, nil, nil, nil, time.Minute, context.Background(), nil, true, 2)
	for _, tc := range []struct {
		consent, code string
		status        int
	}{{"", "cloud_audio_not_authorized", http.StatusForbidden}, {"true", "provider_unavailable", http.StatusServiceUnavailable}} {
		r := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", strings.NewReader(""))
		r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("X-STT-Provider", "groq")
		if tc.consent != "" {
			r.Header.Set("X-Allow-Cloud-Audio", tc.consent)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.status || !strings.Contains(w.Body.String(), `"code":"`+tc.code+`"`) {
			t.Fatalf("consent=%q status=%d body=%s", tc.consent, w.Code, w.Body.String())
		}
	}
}

func TestDisabledGroqStillRequiresExplicitCloudAudioConsent(t *testing.T) {
	const token = "01234567890123456789012345678901"
	h := HandlerWithOptionalServices(WorkersReadiness{}, 1024, token, false, false, nil, nil, nil, time.Minute, context.Background(), nil, false, 2)
	for _, tc := range []struct {
		consent string
		status  int
		code    string
	}{{"", http.StatusForbidden, "cloud_audio_not_authorized"}, {"true", http.StatusServiceUnavailable, "capability_disabled"}} {
		r := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", strings.NewReader(""))
		r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
		r.Header.Set("Authorization", "Bearer "+token)
		r.Header.Set("X-STT-Provider", "groq")
		if tc.consent != "" {
			r.Header.Set("X-Allow-Cloud-Audio", tc.consent)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != tc.status || !strings.Contains(w.Body.String(), `"code":"`+tc.code+`"`) {
			t.Fatalf("consent=%q status=%d body=%s", tc.consent, w.Code, w.Body.String())
		}
	}
}

func TestSelectedDisabledGroqPreservesLegacyErrorWithCapabilityState(t *testing.T) {
	const token = "01234567890123456789012345678901"
	var workerCalls atomic.Int32
	worker := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { workerCalls.Add(1) }))
	defer worker.Close()
	stt := NewSTTProxy(worker.URL, token, time.Second)
	h := HandlerWithOptionalServices(WorkersReadiness{STT: stt}, 1024, token, true, false, stt, nil, nil, time.Minute, context.Background(), nil, false, 2)
	r := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", strings.NewReader(""))
	r.Header.Set("Content-Type", "multipart/form-data; boundary=x")
	r.Header.Set("Authorization", "Bearer "+token)
	r.Header.Set("X-STT-Provider", "groq")
	r.Header.Set("X-Allow-Cloud-Audio", "true")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != http.StatusServiceUnavailable || !strings.Contains(w.Body.String(), `"code":"provider_unavailable"`) || w.Header().Get("X-Speech-Capability-State") != "disabled" || workerCalls.Load() != 0 {
		t.Fatalf("status=%d body=%s state=%q local_calls=%d", w.Code, w.Body.String(), w.Header().Get("X-Speech-Capability-State"), workerCalls.Load())
	}
}

func TestReadinessChecksOnlyConfiguredWorkers(t *testing.T) {
	var calls atomic.Int32
	ttsWorker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/readyz" {
			t.Errorf("unexpected readiness path %q", r.URL.Path)
		}
		calls.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer ttsWorker.Close()
	readiness := NewWorkersReadiness(nil, NewTTSProxy(ttsWorker.URL, "", time.Second))
	if !readiness.Ready() || calls.Load() != 1 {
		t.Fatalf("TTS-only readiness=%t calls=%d", readiness.Ready(), calls.Load())
	}
	if !NewWorkersReadiness(nil, nil).Ready() {
		t.Fatal("Gateway-only readiness must not require a worker")
	}
}

func TestRequestSizeLimit(t *testing.T) {
	h := Handler(unreadyState{}, 4)
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
	var forwardedRequestID string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.URL.Path != "/internal/v1/transcriptions" || !validSpeechTimeoutHeader(r, 180000) || r.ContentLength <= 0 {
			t.Errorf("bad forwarded request: %#v", r)
		}
		forwardedRequestID = r.Header.Get(RequestIDHeader)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"text":"ok","transcription":"ok","language":"en","detected_language":"en","source_language":"en","output_language":"en","translated":false}`))
	}))
	defer worker.Close()
	proxy := NewSTTProxy(worker.URL, "12345678901234567890123456789012", 180*time.Second)
	h := WithRequestID(HandlerWithSTT(proxy, 1024, proxy), slog.New(slog.NewTextHandler(io.Discard, nil)))
	unauthorized := httptest.NewRequest("POST", "/v1/stt/transcriptions", strings.NewReader("payload"))
	unauthorized.Header.Set("Content-Type", "multipart/form-data; boundary=x")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, unauthorized)
	if w.Code != http.StatusUnauthorized || w.Header().Get(RequestIDHeader) == "" {
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
	if forwardedRequestID == "" || forwardedRequestID != w.Header().Get(RequestIDHeader) {
		t.Fatalf("worker request ID %q does not match public response ID %q", forwardedRequestID, w.Header().Get(RequestIDHeader))
	}
	ready := httptest.NewRecorder()
	h.ServeHTTP(ready, httptest.NewRequest("GET", "/readyz", nil))
	if ready.Code != http.StatusOK {
		t.Fatalf("readiness=%d", ready.Code)
	}
}

func TestSTTWorkerFailurePreservesIDAndAPIErrorInGatewayLogs(t *testing.T) {
	var workerRequestID string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		workerRequestID = r.Header.Get(RequestIDHeader)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(`{"code":"resource_exhausted","message":"safe failure"}`))
	}))
	defer worker.Close()
	proxy := NewSTTProxy(worker.URL, "", time.Minute)
	var logs strings.Builder
	logger := slog.New(slog.NewJSONHandler(&logs, nil))
	handler := WithRequestID(HandlerWithSTT(proxy, 1024, proxy), logger)
	request := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", strings.NewReader("--x--\r\n"))
	request.Header.Set("Content-Type", "multipart/form-data; boundary=x")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	requestID := response.Header().Get(RequestIDHeader)
	if response.Code != http.StatusServiceUnavailable || requestID == "" || workerRequestID != requestID {
		t.Fatalf("status=%d public id=%q worker id=%q", response.Code, requestID, workerRequestID)
	}
	var failure map[string]any
	for _, line := range strings.Split(strings.TrimSpace(logs.String()), "\n") {
		var event map[string]any
		if err := json.Unmarshal([]byte(line), &event); err != nil {
			t.Fatal(err)
		}
		if event["msg"] == "request failed" {
			failure = event
		}
	}
	if failure == nil || failure["api_code"] != "resource_exhausted" || failure["request_id"] != requestID || failure["provider"] != "local" {
		t.Fatalf("Gateway failure log lacks correlation metadata: %#v", failure)
	}
}

func TestTTSProxyValidationForwardingAndAudioResponse(t *testing.T) {
	var forwardedRequestID string
	worker := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/readyz" {
			w.WriteHeader(http.StatusOK)
			return
		}
		if r.URL.Path != "/internal/v1/speech" || !validSpeechTimeoutHeader(r, 600000) {
			t.Errorf("bad forwarded request: path=%s timeout=%s", r.URL.Path, r.Header.Get("X-Request-Timeout-Ms"))
		}
		forwardedRequestID = r.Header.Get(RequestIDHeader)
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode request: %v", err)
		}
		if body["language"] != "auto" || body["voice"] != "default" {
			t.Errorf("unexpected defaults: %#v", body)
		}
		if body["text"] == "hello" && body["mode"] != "quality" {
			t.Errorf("mode default=%v, want quality", body["mode"])
		}
		if body["text"] == "hello" && body["input_format"] != nil {
			t.Errorf("default text input_format=%v, want omitted for worker compatibility", body["input_format"])
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
		if body["text"] == "hello extra high quality" && body["mode"] != "extra_high_quality" {
			t.Errorf("forwarded mode=%v, want extra_high_quality", body["mode"])
		}
		if body["text"] == "hello gentle" && body["audio_processing"] != "gentle" {
			t.Errorf("audio_processing=%v, want gentle", body["audio_processing"])
		}
		if (body["text"] == "hello" || body["text"] == "hello none") && body["audio_processing"] != nil {
			t.Errorf("default/none audio_processing=%v, want omitted for worker compatibility", body["audio_processing"])
		}
		w.Header().Set("Content-Type", "audio/wav")
		_, _ = w.Write([]byte("RIFF-test"))
	}))
	defer worker.Close()
	proxy := NewTTSProxy(worker.URL, "12345678901234567890123456789012", 600*time.Second)
	stt := NewSTTProxy(worker.URL, "", time.Second)
	h := WithRequestID(HandlerWithWorkers(NewWorkersReadiness(stt, proxy), 1024, stt, proxy), slog.New(slog.NewTextHandler(io.Discard, nil)))
	for _, tc := range []struct {
		name, body string
		status     int
		code       string
	}{
		{"valid", `{"text":"hello"}`, 200, ""},
		{"explicit_ssml", `{"text":"hello ssml","input_format":"ssml"}`, 200, ""},
		{"fast_mode", `{"text":"hello fast","mode":"fast"}`, 200, ""},
		{"high_quality_mode", `{"text":"hello high quality","mode":"high_quality"}`, 200, ""},
		{"extra_high_quality_mode", `{"text":"hello extra high quality","mode":"extra_high_quality"}`, 200, ""},
		{"gentle_audio_processing", `{"text":"hello gentle","audio_processing":"gentle"}`, 200, ""},
		{"none_audio_processing", `{"text":"hello none","audio_processing":"none"}`, 200, ""},
		{"invalid_language", `{"text":"hello","language":"zh"}`, 400, "invalid_language"},
		{"invalid_mode", `{"text":"hello","mode":"turbo"}`, 400, "invalid_mode"},
		{"invalid_audio_processing", `{"text":"hello","audio_processing":"loud"}`, 400, "invalid_audio_processing"},
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
			if w.Header().Get(RequestIDHeader) == "" {
				t.Fatal("Gateway response omitted X-Request-ID")
			}
			if tc.status == 200 && (w.Header().Get("Content-Type") != "audio/wav" || w.Body.String() != "RIFF-test") {
				t.Fatalf("unexpected audio response: %#v %q", w.Header(), w.Body.String())
			}
			if tc.status == http.StatusOK && w.Header().Get(RequestIDHeader) != forwardedRequestID {
				t.Fatalf("worker request ID %q does not match public response ID %q", forwardedRequestID, w.Header().Get(RequestIDHeader))
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

func validSpeechTimeoutHeader(r *http.Request, maximum int64) bool {
	value, err := strconv.ParseInt(r.Header.Get("X-Request-Timeout-Ms"), 10, 64)
	return err == nil && value > 0 && value <= maximum
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type slowSpeechWriter struct {
	header     http.Header
	status     int
	entered    chan struct{}
	release    chan struct{}
	bodyLength int
	prefix     []byte
}

func (w *slowSpeechWriter) Header() http.Header    { return w.header }
func (w *slowSpeechWriter) WriteHeader(status int) { w.status = status }
func (w *slowSpeechWriter) Write(body []byte) (int, error) {
	close(w.entered)
	<-w.release
	w.bodyLength = len(body)
	w.prefix = append(w.prefix, body[:min(len(body), 16)]...)
	return len(body), nil
}

type zeroAudioReader struct{ remaining int64 }

func (r *zeroAudioReader) Read(buffer []byte) (int, error) {
	if r.remaining == 0 {
		return 0, io.EOF
	}
	n := min(int64(len(buffer)), r.remaining)
	clear(buffer[:n])
	r.remaining -= n
	return int(n), nil
}

type cancelReadCloser struct {
	ctx     context.Context
	entered chan struct{}
	closed  chan struct{}
}

func (b *cancelReadCloser) Read([]byte) (int, error) {
	close(b.entered)
	<-b.ctx.Done()
	return 0, b.ctx.Err()
}

func (b *cancelReadCloser) Close() error {
	close(b.closed)
	return nil
}

func TestSpeechAdmissionBoundsBufferedResponsesAndRecoversAfterSlowClient(t *testing.T) {
	var upstreamCalls atomic.Int32
	proxy := NewTTSProxy("http://worker.invalid", "", time.Minute)
	proxy.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		call := upstreamCalls.Add(1)
		body := io.ReadCloser(io.NopCloser(strings.NewReader("RIFF synthetic audio")))
		contentLength := int64(len("RIFF synthetic audio"))
		if call == 1 {
			body = io.NopCloser(&zeroAudioReader{remaining: maxTTSResponseBytes})
			contentLength = maxTTSResponseBytes
		}
		return &http.Response{
			StatusCode:    http.StatusOK,
			Header:        http.Header{"Content-Type": []string{"audio/wav"}},
			Body:          body,
			ContentLength: contentLength,
			Request:       r,
		}, nil
	})}
	h := HandlerWithWorkers(unreadyState{}, config.PublicMaxRequestBytes, nil, proxy)
	request := func() *http.Request {
		r := httptest.NewRequest(http.MethodPost, "/v1/tts/speech", strings.NewReader(`{"text":"synthetic"}`))
		r.Header.Set("Content-Type", "application/json")
		return r
	}

	writer := &slowSpeechWriter{header: make(http.Header), entered: make(chan struct{}), release: make(chan struct{})}
	releaseWriter := releaseAdmissionSignal(writer.release)
	defer releaseWriter()
	firstDone := make(chan struct{})
	go func() {
		h.ServeHTTP(writer, request())
		close(firstDone)
	}()
	select {
	case <-writer.entered:
	case <-time.After(time.Second):
		releaseWriter()
		t.Fatal("first response did not reach the slow client")
	}

	queuedResults := make(chan *httptest.ResponseRecorder, 2)
	for range 2 {
		go func() {
			response := httptest.NewRecorder()
			h.ServeHTTP(response, request())
			queuedResults <- response
		}()
	}
	var overload *httptest.ResponseRecorder
	select {
	case response := <-queuedResults:
		if response.Code != http.StatusTooManyRequests {
			releaseWriter()
			t.Fatalf("one queued request should fill TTS waiting capacity: status=%d body=%s", response.Code, response.Body.String())
		}
		overload = response
	case <-time.After(time.Second):
		releaseWriter()
		t.Fatal("excess request was not rejected at the bounded queue")
	}
	if upstreamCalls.Load() != 1 {
		releaseWriter()
		t.Fatalf("queued request reached worker before active response delivery: calls=%d", upstreamCalls.Load())
	}
	var failure map[string]string
	if err := json.Unmarshal(overload.Body.Bytes(), &failure); err != nil || failure["code"] != "overloaded" {
		releaseWriter()
		t.Fatalf("capacity error=%v decode=%v", failure, err)
	}

	releaseWriter()
	select {
	case <-firstDone:
	case <-time.After(time.Second):
		t.Fatal("first response did not finish after client resumed")
	}
	select {
	case response := <-queuedResults:
		if response.Code != http.StatusOK {
			t.Fatalf("queued request failed after capacity release: status=%d body=%s", response.Code, response.Body.String())
		}
	case <-time.After(time.Second):
		t.Fatal("queued request did not run after delivery completed")
	}
	if writer.status != http.StatusOK || writer.bodyLength != maxTTSResponseBytes || len(writer.prefix) != 16 {
		t.Fatalf("first response status=%d bytes=%d prefix=%x", writer.status, writer.bodyLength, writer.prefix)
	}

	third := httptest.NewRecorder()
	h.ServeHTTP(third, request())
	if third.Code != http.StatusOK || upstreamCalls.Load() != 3 {
		t.Fatalf("capacity did not recover: response=%d calls=%d", third.Code, upstreamCalls.Load())
	}
}

func TestReadBoundedTTSResponseDoesNotGrowPastLimit(t *testing.T) {
	for _, tc := range []struct {
		name          string
		body          string
		contentLength int64
		want          string
		tooLarge      bool
		wantError     bool
	}{
		{name: "declared_exact", body: "123456", contentLength: 6, want: "123456"},
		{name: "declared_oversized", body: "1234567", contentLength: 7, tooLarge: true},
		{name: "unknown_exact", body: "123456", contentLength: -1, want: "123456"},
		{name: "unknown_oversized", body: "1234567", contentLength: -1, tooLarge: true},
		{name: "declared_truncated", body: "123", contentLength: 6, wantError: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, tooLarge, err := readBoundedTTSResponse(strings.NewReader(tc.body), tc.contentLength, 6)
			if tooLarge != tc.tooLarge || (err != nil) != tc.wantError || string(got) != tc.want {
				t.Fatalf("got=%q tooLarge=%t err=%v", got, tooLarge, err)
			}
		})
	}
}

func TestSpeechClientCancellationClosesResponseAndReleasesCapacity(t *testing.T) {
	var upstreamCalls atomic.Int32
	proxy := NewTTSProxy("http://worker.invalid", "", time.Minute)
	responseRead := make(chan struct{})
	responseClosed := make(chan struct{})
	proxy.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if upstreamCalls.Add(1) == 1 {
			blockedBody := &cancelReadCloser{ctx: r.Context(), entered: responseRead, closed: responseClosed}
			return &http.Response{
				StatusCode: http.StatusOK,
				Header:     http.Header{"Content-Type": []string{"audio/wav"}},
				Body:       blockedBody, ContentLength: 1, Request: r,
			}, nil
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"audio/wav"}},
			Body:       io.NopCloser(strings.NewReader("RIFF")), ContentLength: 4, Request: r,
		}, nil
	})}
	h := HandlerWithWorkers(unreadyState{}, config.PublicMaxRequestBytes, nil, proxy)
	cancelled, cancel := context.WithCancel(context.Background())
	firstRequest := httptest.NewRequest(http.MethodPost, "/v1/tts/speech", strings.NewReader(`{"text":"synthetic"}`)).WithContext(cancelled)
	firstRequest.Header.Set("Content-Type", "application/json")
	firstDone := make(chan struct{})
	go func() {
		h.ServeHTTP(httptest.NewRecorder(), firstRequest)
		close(firstDone)
	}()
	select {
	case <-responseRead:
	case <-time.After(time.Second):
		cancel()
		t.Fatal("worker response read did not start")
	}
	cancel()
	select {
	case <-firstDone:
	case <-time.After(time.Second):
		t.Fatal("cancelled speech request did not return")
	}
	select {
	case <-responseClosed:
	case <-time.After(time.Second):
		t.Fatal("cancelled worker response body was not closed")
	}

	secondRequest := httptest.NewRequest(http.MethodPost, "/v1/tts/speech", strings.NewReader(`{"text":"synthetic"}`))
	secondRequest.Header.Set("Content-Type", "application/json")
	second := httptest.NewRecorder()
	h.ServeHTTP(second, secondRequest)
	if second.Code != http.StatusOK || upstreamCalls.Load() != 2 {
		t.Fatalf("capacity did not recover after cancellation: status=%d calls=%d body=%s", second.Code, upstreamCalls.Load(), second.Body.String())
	}
}
