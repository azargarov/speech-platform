package gateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"net/textproto"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func groqMultipart(t *testing.T, fields map[string]string) ([]byte, string) {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	header := make(textproto.MIMEHeader)
	header.Set("Content-Disposition", `form-data; name="audio"; filename="synthetic.wav"`)
	header.Set("Content-Type", "audio/wav")
	part, err := writer.CreatePart(header)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := io.WriteString(part, "synthetic-audio"); err != nil {
		t.Fatal(err)
	}
	for key, value := range fields {
		if err := writer.WriteField(key, value); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return body.Bytes(), writer.FormDataContentType()
}

func groqTestAdapter(t *testing.T, handler http.Handler) *GroqSTTAdapter {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	adapter, err := NewGroqSTTAdapter("fixture-value", "whisper-large-v3-turbo", time.Second)
	if err != nil {
		t.Fatal(err)
	}
	adapter.endpoint = server.URL
	return adapter
}

func groqTestHandler(t *testing.T, adapter *GroqSTTAdapter, local http.RoundTripper) http.Handler {
	t.Helper()
	stt := NewSTTProxy("http://local.invalid", "", 2*time.Second)
	stt.Client = &http.Client{Transport: local}
	return HandlerWithWarmupContextAndGroqSTT(Foundation{}, 25*1024*1024, stt, nil, nil, 2*time.Second, context.Background(), adapter, true, 2)
}

func groqRequest(t *testing.T, fields map[string]string, provider string, consent bool) *http.Request {
	t.Helper()
	body, contentType := groqMultipart(t, fields)
	request := httptest.NewRequest(http.MethodPost, "/v1/stt/transcriptions", bytes.NewReader(body))
	request.Header.Set("Content-Type", contentType)
	if provider != "" {
		request.Header.Set("X-STT-Provider", provider)
	}
	if consent {
		request.Header.Set("X-Allow-Cloud-Audio", "true")
	}
	return request
}

func TestGroqSTTRequiresIndependentCloudAudioConsent(t *testing.T) {
	var groqCalls atomic.Int32
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		groqCalls.Add(1)
		_, _ = io.WriteString(w, `{"text":"ok","language":"en"}`)
	}))
	var localCalls atomic.Int32
	local := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		localCalls.Add(1)
		return admissionWorkerResponse("stt", r), nil
	})
	h := groqTestHandler(t, adapter, local)

	defaultResponse := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "", false))
	if defaultResponse.Code != http.StatusOK || defaultResponse.Header().Get("X-Speech-Provider") != "local" {
		t.Fatalf("default request status=%d provider=%q body=%s", defaultResponse.Code, defaultResponse.Header().Get("X-Speech-Provider"), defaultResponse.Body.String())
	}
	denied := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "groq", false))
	if denied.Code != http.StatusForbidden || !strings.Contains(denied.Body.String(), "cloud_audio_not_authorized") {
		t.Fatalf("unauthorized Groq request status=%d body=%s", denied.Code, denied.Body.String())
	}
	if groqCalls.Load() != 0 || localCalls.Load() != 1 {
		t.Fatalf("unauthorized request caused upstream work: local=%d groq=%d", localCalls.Load(), groqCalls.Load())
	}
	consentedLocalFirst := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "", true))
	if consentedLocalFirst.Code != http.StatusOK || consentedLocalFirst.Header().Get("X-Speech-Provider") != "local" || localCalls.Load() != 2 || groqCalls.Load() != 0 {
		t.Fatalf("local-first request status=%d provider=%q local=%d groq=%d", consentedLocalFirst.Code, consentedLocalFirst.Header().Get("X-Speech-Provider"), localCalls.Load(), groqCalls.Load())
	}
}

func TestSTTProviderSelectionRules(t *testing.T) {
	for _, tc := range []struct {
		name       string
		headers    http.Header
		available  bool
		want       []speechProviderID
		wantStatus int
	}{
		{"default local only", http.Header{}, true, []speechProviderID{localWhisperProvider}, 0},
		{"consented local first", http.Header{"X-Allow-Cloud-Audio": []string{"true"}}, true, []speechProviderID{localWhisperProvider, groqWhisperProvider}, 0},
		{"consent does not enable disabled provider", http.Header{"X-Allow-Cloud-Audio": []string{"true"}}, false, []speechProviderID{localWhisperProvider}, 0},
		{"pinned local", http.Header{"X-Allow-Cloud-Audio": []string{"true"}, "X-Stt-Provider": []string{"local"}}, true, []speechProviderID{localWhisperProvider}, 0},
		{"pinned Groq needs consent", http.Header{"X-Stt-Provider": []string{"groq"}}, true, nil, http.StatusForbidden},
		{"pinned Groq disabled", http.Header{"X-Allow-Cloud-Audio": []string{"true"}, "X-Stt-Provider": []string{"groq"}}, false, nil, http.StatusServiceUnavailable},
		{"bad consent", http.Header{"X-Allow-Cloud-Audio": []string{"yes"}}, true, nil, http.StatusBadRequest},
		{"bad provider", http.Header{"X-Stt-Provider": []string{"other"}}, true, nil, http.StatusBadRequest},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, failure := selectSTTProviders(tc.headers, tc.available)
			if tc.wantStatus != 0 {
				if failure == nil || failure.Status != tc.wantStatus {
					t.Fatalf("failure=%+v want status %d", failure, tc.wantStatus)
				}
				return
			}
			if failure != nil || len(got) != len(tc.want) {
				t.Fatalf("providers=%v failure=%+v want=%v", got, failure, tc.want)
			}
			for i := range got {
				if got[i] != tc.want[i] {
					t.Fatalf("providers=%v want=%v", got, tc.want)
				}
			}
		})
	}
}

func TestDisabledGroqCannotReceiveAudio(t *testing.T) {
	var calls atomic.Int32
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		calls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"text":"unexpected","language":"en"}`)
	}))
	stt := NewSTTProxy("http://local.invalid", "", time.Second)
	stt.Client = &http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return admissionWorkerResponse("stt", r), nil
	})}
	h := HandlerWithWarmupContextAndGroqSTT(Foundation{}, 25*1024*1024, stt, nil, nil, time.Second, context.Background(), adapter, false, 2)
	response := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "groq", true))
	if response.Code != http.StatusServiceUnavailable || calls.Load() != 0 {
		t.Fatalf("disabled Groq status=%d calls=%d body=%s", response.Code, calls.Load(), response.Body.String())
	}
}

func TestGroqSTTMapsRequestAndResponseWithoutLeakingProviderErrors(t *testing.T) {
	type received struct{ auth, model, format, language, audio string }
	got := make(chan received, 1)
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/" {
			t.Errorf("unexpected fake endpoint path %q", r.URL.Path)
		}
		item := received{auth: r.Header.Get("Authorization")}
		reader, err := r.MultipartReader()
		if err != nil {
			t.Errorf("multipart: %v", err)
			return
		}
		for {
			part, err := reader.NextPart()
			if errors.Is(err, io.EOF) {
				break
			}
			if err != nil {
				t.Errorf("part: %v", err)
				return
			}
			b, _ := io.ReadAll(part)
			switch part.FormName() {
			case "file":
				item.audio = string(b)
			case "model":
				item.model = string(b)
			case "response_format":
				item.format = string(b)
			case "language":
				item.language = string(b)
			}
		}
		got <- item
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"text":"synthetic transcript","language":"english","segments":[{"start":0,"end":1.25,"text":"synthetic transcript"}]}`)
	}))
	h := groqTestHandler(t, adapter, roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return admissionWorkerResponse("stt", r), nil
	}))
	request := groqRequest(t, map[string]string{"source_language": "en", "output_language": "en", "timestamps": "true"}, "groq", true)
	response := serveAdmissionRequest(h, "stt", request)
	if response.Code != http.StatusOK || response.Header().Get("X-Speech-Provider") != "groq" {
		t.Fatalf("status=%d provider=%q body=%s", response.Code, response.Header().Get("X-Speech-Provider"), response.Body.String())
	}
	upstream := <-got
	if upstream.auth != "Bearer fixture-value" || upstream.model != "whisper-large-v3-turbo" || upstream.format != "verbose_json" || upstream.language != "en" || upstream.audio != "synthetic-audio" {
		t.Fatalf("upstream mapping=%+v", upstream)
	}
	var result map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if result["text"] != "synthetic transcript" || result["translated"] != false || result["output_language"] != "en" {
		t.Fatalf("public response mapping=%#v", result)
	}
}

func TestGroqSTTSelectionAndValidationDoNotContactProvider(t *testing.T) {
	var calls atomic.Int32
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		calls.Add(1)
		_, _ = io.WriteString(w, `{"text":"ok","language":"en"}`)
	}))
	for _, tc := range []struct {
		name, provider string
		consent        bool
		fields         map[string]string
		status         int
	}{
		{"no consent", "groq", false, nil, http.StatusForbidden},
		{"unsupported translation", "groq", true, map[string]string{"source_language": "auto", "output_language": "en"}, http.StatusBadRequest},
		{"explicit model not sent to Groq", "groq", true, map[string]string{"model": "large-v3-turbo"}, http.StatusBadRequest},
		{"explicit local", "local", true, map[string]string{"model": "custom-model"}, http.StatusOK},
	} {
		t.Run(tc.name, func(t *testing.T) {
			localCalls := roundTripFunc(func(r *http.Request) (*http.Response, error) {
				return admissionWorkerResponse("stt", r), nil
			})
			localHandler := groqTestHandler(t, adapter, localCalls)
			response := serveAdmissionRequest(localHandler, "stt", groqRequest(t, tc.fields, tc.provider, tc.consent))
			if response.Code != tc.status {
				t.Fatalf("status=%d want=%d body=%s", response.Code, tc.status, response.Body.String())
			}
		})
	}
	if calls.Load() != 0 {
		t.Fatalf("invalid or local-only requests contacted Groq %d times", calls.Load())
	}
}

func TestGroqSTTRateLimitAndMalformedResponseAreSanitized(t *testing.T) {
	for _, tc := range []struct {
		name   string
		status int
		body   string
		want   int
		code   string
	}{
		{"rate limit", 429, `{"error":"secret provider detail"}`, 429, "overloaded"},
		{"authentication failure", 401, `{"error":"secret credential detail"}`, 503, "provider_unavailable"},
		{"provider outage", 503, `{"error":"secret outage detail"}`, 503, "provider_unavailable"},
		{"malformed success", 200, `{`, 502, "invalid_provider_response"},
		{"missing transcript", 200, `{"language":"en"}`, 502, "invalid_provider_response"},
		{"provider error", 200, `{"text":"ok","language":"en","error":{"message":"secret"}}`, 502, "invalid_provider_response"},
		{"oversized response", 200, strings.Repeat("x", int(maxSTTResponseBytes+1)), 502, "invalid_provider_response"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.Header().Set("Retry-After", "5")
				w.WriteHeader(tc.status)
				_, _ = io.WriteString(w, tc.body)
			}))
			h := groqTestHandler(t, adapter, nil)
			response := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "groq", true))
			if response.Code != tc.want || !strings.Contains(response.Body.String(), tc.code) || strings.Contains(response.Body.String(), "secret") {
				t.Fatalf("status=%d body=%s", response.Code, response.Body.String())
			}
			if tc.name == "rate limit" && response.Header().Get("Retry-After") != "5" {
				t.Fatalf("sanitized Retry-After=%q", response.Header().Get("Retry-After"))
			}
		})
	}
}

func TestGroqSTTBoundedUploadAndAdapterCancellation(t *testing.T) {
	if _, err := NewGroqSTTAdapter("", "whisper-large-v3-turbo", time.Second); err == nil {
		t.Fatal("empty credential was accepted")
	}
	if _, err := readBoundedSTTRequest(strings.NewReader("12345"), -1, 4); !errors.Is(err, errSTTRequestTooLarge) {
		t.Fatalf("oversized unknown upload error=%v", err)
	}
	if _, err := readBoundedSTTRequest(strings.NewReader("12345"), 5, 4); !errors.Is(err, errSTTRequestTooLarge) {
		t.Fatalf("oversized declared upload error=%v", err)
	}
	if got, err := readBoundedSTTRequest(strings.NewReader("1234"), -1, 4); err != nil || string(got) != "1234" {
		t.Fatalf("boundary upload=%q err=%v", got, err)
	}
	badMediaBody, badMediaType := groqMultipart(t, nil)
	badMediaBody = []byte(strings.Replace(string(badMediaBody), "Content-Type: audio/wav", "Content-Type: application/pdf", 1))
	if _, err := parseGroqSTTRequest(badMediaBody, badMediaType); err != nil {
		var failure *groqSTTFailure
		if !errors.As(err, &failure) || failure.Status != http.StatusUnsupportedMediaType {
			t.Fatalf("unsupported audio media type error=%v", err)
		}
	} else {
		t.Fatal("unsupported audio media type was accepted")
	}
	entered, release := make(chan struct{}), make(chan struct{})
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		<-release
		_, _ = io.WriteString(w, `{"text":"ok","language":"en"}`)
	}))
	body, contentType := groqMultipart(t, nil)
	input, err := parseGroqSTTRequest(body, contentType)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { _, _, err := adapter.Transcribe(ctx, input); done <- err }()
	waitAdmissionSignal(t, entered, "fake Groq request")
	cancel()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("cancelled request unexpectedly succeeded")
		}
	case <-time.After(2 * time.Second):
		t.Fatal("adapter did not observe cancellation")
	}
	close(release)

	enteredDeadline, releaseDeadline := make(chan struct{}), make(chan struct{})
	deadlineAdapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		close(enteredDeadline)
		<-releaseDeadline
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"text":"late","language":"en"}`)
	}))
	ctx, cancel = context.WithTimeout(context.Background(), 30*time.Millisecond)
	done = make(chan error, 1)
	go func() { _, _, err := deadlineAdapter.Transcribe(ctx, input); done <- err }()
	waitAdmissionSignal(t, enteredDeadline, "deadline Groq request")
	select {
	case err := <-done:
		var failure *groqSTTFailure
		if !errors.As(err, &failure) || failure.Status != http.StatusGatewayTimeout {
			t.Fatalf("deadline error=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("adapter did not stop waiting by caller deadline")
	}
	cancel()
	close(releaseDeadline)
}

func TestGroqProviderFailureReleasesAdmissionForLaterRequest(t *testing.T) {
	var calls atomic.Int32
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if calls.Add(1) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = io.WriteString(w, "private provider detail")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"text":"recovered","language":"en"}`)
	}))
	h := groqTestHandler(t, adapter, nil)
	first := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "groq", true))
	if first.Code != http.StatusServiceUnavailable || strings.Contains(first.Body.String(), "private") {
		t.Fatalf("first status=%d body=%s", first.Code, first.Body.String())
	}
	second := serveAdmissionRequest(h, "stt", groqRequest(t, nil, "groq", true))
	if second.Code != http.StatusOK || calls.Load() != 2 {
		t.Fatalf("second status=%d calls=%d body=%s", second.Code, calls.Load(), second.Body.String())
	}
}

func TestLocalAndGroqSTTExecuteConcurrentlyWithinGlobalCapacity(t *testing.T) {
	localEntered, groqEntered := make(chan struct{}), make(chan struct{})
	localRelease, groqRelease := make(chan struct{}), make(chan struct{})
	adapter := groqTestAdapter(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		close(groqEntered)
		<-groqRelease
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"text":"cloud","language":"en"}`)
	}))
	local := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		close(localEntered)
		<-localRelease
		return admissionWorkerResponse("stt", r), nil
	})
	h := groqTestHandler(t, adapter, local)
	localDone := make(chan *httptest.ResponseRecorder, 1)
	go func() { localDone <- serveAdmissionRequest(h, "stt", groqRequest(t, nil, "local", false)) }()
	waitAdmissionSignal(t, localEntered, "local request")
	cloudDone := make(chan *httptest.ResponseRecorder, 1)
	go func() { cloudDone <- serveAdmissionRequest(h, "stt", groqRequest(t, nil, "", true)) }()
	waitAdmissionSignal(t, groqEntered, "Groq request while local is busy")
	close(localRelease)
	close(groqRelease)
	for name, result := range map[string]<-chan *httptest.ResponseRecorder{"local": localDone, "Groq": cloudDone} {
		select {
		case response := <-result:
			if response.Code != http.StatusOK {
				t.Fatalf("%s response status=%d body=%s", name, response.Code, response.Body.String())
			}
		case <-time.After(2 * time.Second):
			t.Fatalf("%s response did not complete", name)
		}
	}
}

func TestSTTAdmissionGlobalActiveLimitIsTwo(t *testing.T) {
	a := newSTTAdmissionWithGroq(3, 2, true)
	local, full, err := a.acquire(context.Background(), localWhisperProvider)
	if err != nil || full || local == nil {
		t.Fatalf("local acquire lease=%v full=%t err=%v", local, full, err)
	}
	groq, full, err := a.acquire(context.Background(), groqWhisperProvider)
	if err != nil || full || groq == nil {
		t.Fatalf("Groq acquire lease=%v full=%t err=%v", groq, full, err)
	}
	if a.activeTotal != 2 {
		t.Fatalf("active count=%d want 2", a.activeTotal)
	}
	waitCtx, stopWaiting := context.WithCancel(context.Background())
	waiterDone := make(chan error, 1)
	go func() { _, _, err := a.acquire(waitCtx, localWhisperProvider, groqWhisperProvider); waiterDone <- err }()
	waitForAdmissionQueue(t, a, 1)
	stopWaiting()
	if err := <-waiterDone; !errors.Is(err, context.Canceled) {
		t.Fatalf("third concurrent STT error=%v", err)
	}
	local.Release()
	groq.Release()
	if a.activeTotal != 0 {
		t.Fatalf("capacity leaked after release: %d", a.activeTotal)
	}
}
